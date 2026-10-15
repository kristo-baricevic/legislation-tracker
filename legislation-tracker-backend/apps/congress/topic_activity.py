"""Observed legislative topic activity, with explicit uncertainty and provenance.

No ideological inference, behavioral data or vote-position ranking. January-3
year-derived terms never produce exact service-day rates.
"""

import calendar
import hashlib
import json
import math
import re
import secrets
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from apps.accounts.recommendation_support import (
    USABLE_TOPIC,
    RecommendationError,
    bounded_json,
    cache_call,
    read_snapshot,
)
from apps.legislation.models import Bill, BillDocument, BillTopic

from .models import BillCosponsor, Representative, RepresentativeTerm, Vote, VoteRecord

SCHEMA = "representative-topic-activity-v1"
PASSAGE_QUESTIONS = {
    "on passage",
    "on passage of the bill",
    "on the passage of the bill",
}


@dataclass(frozen=True)
class ActivityPolicy:
    window_months: int = 24
    topic_share: str = "0.20"
    minimum_observations: int = 20
    minimum_topic_observations: int = 5
    minimum_tag_coverage: str = "0.80"

    def __post_init__(self):
        for value in (
            self.window_months,
            self.minimum_observations,
            self.minimum_topic_observations,
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(
                    "Activity evidence/window policy must be positive integers"
                )
        if not 6 <= self.window_months <= 48:
            raise ValueError("Activity window must be 6..48 months")
        for value in (self.topic_share, self.minimum_tag_coverage):
            if not isinstance(value, str):
                raise ValueError("Activity thresholds must be finite decimal strings")
            try:
                number = Decimal(value)
            except Exception as exc:
                raise ValueError("Invalid activity threshold") from exc
            if not number.is_finite() or not 0 < number <= 1:
                raise ValueError("Activity thresholds must be finite and in (0,1]")

    @property
    def version(self):
        digest = hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True).encode()
        ).hexdigest()[:12]
        return f"observed-topic-policy-v1-{digest}"


DEFAULT_POLICY = ActivityPolicy(
    **getattr(settings, "REPRESENTATIVE_TOPIC_ACTIVITY_POLICY", {})
)


def quantize_fraction(value):
    scaled = value * 1_000_000
    integer, remainder = divmod(scaled.numerator, scaled.denominator)
    twice = remainder * 2
    if twice > scaled.denominator or (twice == scaled.denominator and integer % 2):
        integer += 1
    return Fraction(integer, 1_000_000)


def cosine(left, right):
    keys = sorted(left.keys() | right.keys())
    dot = math.fsum(float(left.get(key, 0)) * float(right.get(key, 0)) for key in keys)
    left_norm = math.sqrt(math.fsum(float(left.get(key, 0)) ** 2 for key in keys))
    right_norm = math.sqrt(math.fsum(float(right.get(key, 0)) ** 2 for key in keys))
    value = (
        min(1.0, max(0.0, dot / (left_norm * right_norm)))
        if left_norm and right_norm
        else 0.0
    )
    return Fraction(
        Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)
    )


def fraction_json(value):
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def window_for(captured_at, policy):
    end = captured_at.astimezone(ZoneInfo("America/New_York")).date()
    month = end.year * 12 + end.month - 1 - policy.window_months
    year, zero_month = divmod(month, 12)
    start = end.replace(
        year=year,
        month=zero_month + 1,
        day=min(end.day, calendar.monthrange(year, zero_month + 1)[1]),
    )
    return start, end + timedelta(days=1)


def _repeat_units(rows, bills, weights):
    groups = {}
    for bill_id, event_date in rows.items():
        item = bills[bill_id]
        title = " ".join(
            unicodedata.normalize("NFKC", item["title"]).casefold().split()
        )
        key = (
            ("title", item["sponsor_id"], title)
            if title and item["sponsor_id"] is not None
            else ("bill", bill_id)
        )
        groups.setdefault(key, []).append((bill_id, event_date))
    result = []
    for members in groups.values():
        common = dict(weights[members[0][0]])
        for bill_id, _ in members[1:]:
            common = {
                key: min(value, weights[bill_id].get(key, Fraction(0)))
                for key, value in common.items()
                if weights[bill_id].get(key, 0) > 0
            }
        result.append((common, members))
    return result


def _totals(units):
    masses, counts = {}, {}
    for weights, _ in units:
        for topic_id, weight in weights.items():
            masses[topic_id] = masses.get(topic_id, Fraction(0)) + weight
            counts[topic_id] = counts.get(topic_id, 0) + 1
    return {
        "n": len(units),
        "tagged": sum(bool(weights) for weights, _ in units),
        "masses": masses,
        "counts": counts,
    }


def _channel(
    rows, bills, weights, topics, policy, missing, unknown_session, withdrawn=0
):
    raw_units = [
        (weights[bill_id], [(bill_id, event_date)])
        for bill_id, event_date in rows.items()
    ]
    grouped_units = _repeat_units(rows, bills, weights)
    raw, grouped = _totals(raw_units), _totals(grouped_units)
    metrics = []
    for topic_id in sorted(raw["masses"]):
        values = {}
        for name, totals in (("raw", raw), ("grouped", grouped)):
            mass = totals["masses"].get(topic_id, Fraction(0))
            values[name] = {
                "topic_observation_count": totals["counts"].get(topic_id, 0),
                "mass": fraction_json(mass),
                "share": (
                    float(quantize_fraction(mass / totals["n"]))
                    if totals["n"]
                    else None
                ),
            }
        recurring = all(
            totals["n"] >= policy.minimum_observations
            and totals["counts"].get(topic_id, 0) >= policy.minimum_topic_observations
            and totals["masses"].get(topic_id, 0) / totals["n"]
            >= Fraction(policy.topic_share)
            and Fraction(totals["tagged"], totals["n"])
            >= Fraction(policy.minimum_tag_coverage)
            for totals in (raw, grouped)
        )
        examples = sorted(
            (
                (bill_id, event_date)
                for bill_id, event_date in rows.items()
                if topic_id in weights[bill_id]
            ),
            key=lambda item: (item[1], item[0]),
            reverse=True,
        )[:3]
        metrics.append(
            {
                "topic": topics[topic_id],
                **values,
                "recurring": recurring,
                "classification": "recurring_observed_activity" if recurring else None,
                "examples": [
                    {
                        "bill_id": bill_id,
                        "bill_number": bills[bill_id]["bill_number"],
                        "session": bills[bill_id]["session"],
                        "event_date": event_date.isoformat(),
                        "source_kind": "recorded_activity",
                        "source_url": None,
                    }
                    for bill_id, event_date in examples
                ],
            }
        )
    metrics.sort(
        key=lambda item: (
            -grouped["masses"].get(item["topic"]["id"], 0) / (grouped["n"] or 1),
            -item["grouped"]["topic_observation_count"],
            item["topic"]["id"],
        )
    )
    status = (
        "no_dated_observations"
        if not raw["n"]
        else (
            "insufficient_history"
            if min(raw["n"], grouped["n"]) < policy.minimum_observations
            else "observed_subset"
        )
    )
    result = {
        "status": status,
        "missing_date_count": missing,
        "unknown_session_count": unknown_session,
        "withdrawn_count": withdrawn,
        "raw_observation_count": raw["n"],
        "grouped_observation_count": grouped["n"],
        "raw_tagged_count": raw["tagged"],
        "grouped_tagged_count": grouped["tagged"],
        "topics": metrics,
        "recurring_topic_ids": [
            item["topic"]["id"] for item in metrics if item["recurring"]
        ][:5],
    }
    for name, totals in (("raw", raw), ("grouped", grouped)):
        coverage = Fraction(totals["tagged"], totals["n"]) if totals["n"] else None
        result[f"{name}_tag_coverage"] = (
            {
                "fraction": fraction_json(coverage),
                "display": float(quantize_fraction(coverage)),
            }
            if coverage is not None
            else None
        )
    vector = (
        {key: value / grouped["n"] for key, value in grouped["masses"].items()}
        if grouped["n"]
        else {}
    )
    return result, vector, grouped["n"]


def _checkpoint(deadline, *, database=False):
    if time.monotonic() >= deadline:
        raise RecommendationError()
    if database and connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "SET LOCAL statement_timeout = %s",
                [max(1, min(15_000, int((deadline - time.monotonic()) * 1000)))],
            )


def _build_catalog(captured_at, policy, deadline):
    start, end = window_for(captured_at, policy)
    start_instant = datetime.combine(
        start, datetime.min.time(), ZoneInfo("America/New_York")
    )
    end_instant = datetime.combine(
        end, datetime.min.time(), ZoneInfo("America/New_York")
    )
    # Congress starts January 3; use intervals only for undated-record attribution.
    sessions = [
        number
        for number in range(1, (end.year - 1789) // 2 + 2)
        if date(1789 + 2 * (number - 1), 1, 3) < end
        and date(1789 + 2 * number, 1, 3) > start
    ]
    cos_in_window = BillCosponsor.objects.filter(
        bill_id=OuterRef("pk"), sponsorship_date__gte=start, sponsorship_date__lt=end
    )
    vote_in_window = Vote.objects.filter(
        bill_id=OuterRef("pk"),
        vote_date__gte=start_instant,
        vote_date__lt=end_instant,
        vote_date__lte=captured_at,
    )
    scoped = Bill.objects.filter(jurisdiction="federal").filter(
        Q(session__in=sessions)
        | Q(introduced_at__gte=start, introduced_at__lt=end)
        | Exists(cos_in_window)
        | Exists(vote_in_window)
    )
    _checkpoint(deadline, database=True)
    bill_rows = {}
    resolution_rows = {}
    resolution_observations = {}
    for row in scoped.values(
        "id", "session", "bill_number", "title", "sponsor_id", "introduced_at"
    ).iterator(chunk_size=1000):
        prefix = re.fullmatch(
            r"(hr|s|hjres|sjres|hres|sres|hconres|sconres)\s*\.?\s*(\d+)",
            row["bill_number"].strip(),
            re.I,
        )
        if prefix and prefix[1].lower() in {"hr", "s"}:
            bill_rows[row["id"]] = row
        elif prefix:
            kind = (
                "joint_count"
                if "jres" in prefix[1].lower()
                else (
                    "concurrent_count"
                    if "conres" in prefix[1].lower()
                    else "simple_count"
                )
            )
            resolution_rows[row["id"]] = (row, kind)
            if (
                row["sponsor_id"] is not None
                and row["introduced_at"]
                and start <= row["introduced_at"] < end
            ):
                resolution_observations.setdefault(row["sponsor_id"], {}).setdefault(
                    kind, set()
                ).add(row["id"])
        if len(bill_rows) % 1000 == 0:
            _checkpoint(deadline)
    _checkpoint(deadline, database=True)
    topics, tag_ids = {}, {key: set() for key in bill_rows}
    for edge_index, edge in enumerate(
        BillTopic.objects.filter(USABLE_TOPIC, bill_id__in=scoped.values("id"))
        .values("bill_id", "topic_id", "topic__name", "topic__slug")
        .iterator(chunk_size=1000)
    ):
        if edge_index % 1000 == 0:
            _checkpoint(deadline)
        if edge["bill_id"] in bill_rows:
            tag_ids[edge["bill_id"]].add(edge["topic_id"])
            topics[edge["topic_id"]] = {
                "id": edge["topic_id"],
                "name": edge["topic__name"],
                "slug": edge["topic__slug"],
            }
    weights = {
        key: {topic_id: Fraction(1, len(ids)) for topic_id in ids}
        for key, ids in tag_ids.items()
    }
    _checkpoint(deadline, database=True)
    roster = list(
        Representative.objects.values(
            "id", "bioguide_id", "name", "is_current", "chamber", "state"
        )
    )
    _checkpoint(deadline, database=True)
    members_with_terms = set(
        RepresentativeTerm.objects.values_list(
            "representative_id", flat=True
        ).distinct()
    )
    sponsor_rows, cosponsor_rows, missing_sponsor, missing_cosponsor, withdrawn = (
        {},
        {},
        {},
        {},
        {},
    )
    unknown_sponsor, unknown_cosponsor = {}, {}
    for row in bill_rows.values():
        rep_id, event_date = row["sponsor_id"], row["introduced_at"]
        if rep_id is None:
            continue
        if not row["session"] or row["session"] <= 0:
            unknown_sponsor[rep_id] = unknown_sponsor.get(rep_id, 0) + 1
        elif event_date is None and row["session"] in sessions:
            missing_sponsor[rep_id] = missing_sponsor.get(rep_id, 0) + 1
        if (
            event_date is not None
            and start <= event_date < end
            and row["session"]
            and row["session"] > 0
        ):
            sponsor_rows.setdefault(rep_id, {})[row["id"]] = event_date
    _checkpoint(deadline, database=True)
    for relation_index, relation in enumerate(
        BillCosponsor.objects.filter(bill_id__in=scoped.values("id"))
        .filter(
            Q(sponsorship_date__gte=start, sponsorship_date__lt=end)
            | Q(sponsorship_date__isnull=True)
        )
        .values("bill_id", "representative_id", "sponsorship_date", "withdrawn_at")
        .iterator(chunk_size=1000)
    ):
        if relation_index % 1000 == 0:
            _checkpoint(deadline)
        if relation["bill_id"] in resolution_rows:
            if (
                relation["withdrawn_at"] is None
                and relation["sponsorship_date"] is not None
            ):
                kind = resolution_rows[relation["bill_id"]][1]
                resolution_observations.setdefault(
                    relation["representative_id"], {}
                ).setdefault(kind, set()).add(relation["bill_id"])
            continue
        if relation["bill_id"] not in bill_rows:
            continue
        rep_id = relation["representative_id"]
        congress = bill_rows[relation["bill_id"]]["session"]
        if not congress or congress <= 0:
            unknown_cosponsor[rep_id] = unknown_cosponsor.get(rep_id, 0) + 1
            continue
        if relation["withdrawn_at"] is not None:
            withdrawn[rep_id] = withdrawn.get(rep_id, 0) + 1
        elif relation["sponsorship_date"] is None and congress in sessions:
            missing_cosponsor[rep_id] = missing_cosponsor.get(rep_id, 0) + 1
        elif relation["sponsorship_date"] is not None:
            cosponsor_rows.setdefault(rep_id, {})[relation["bill_id"]] = relation[
                "sponsorship_date"
            ]
    _checkpoint(deadline, database=True)
    votes = Vote.objects.filter(
        bill_id__in=scoped.values("id"),
        vote_date__gte=start_instant,
        vote_date__lt=end_instant,
        vote_date__lte=captured_at,
    )
    selected = {}
    passage_rolls = {}
    for vote_index, row in enumerate(
        votes.order_by("vote_date", "id")
        .values(
            "id",
            "bill_id",
            "chamber",
            "question",
            "vote_date",
            "session_number",
            "source_url",
        )
        .iterator(chunk_size=1000)
    ):
        if vote_index % 1000 == 0:
            _checkpoint(deadline)
        if (
            row["bill_id"] not in bill_rows
            or " ".join(row["question"].casefold().split()) not in PASSAGE_QUESTIONS
        ):
            continue
        passage_rolls[row["id"]] = row
        selected[(row["bill_id"], row["chamber"])] = row
    selected_ids = {row["id"] for row in selected.values()}
    selected_by_id = {row["id"]: row for row in selected.values()}
    chamber_positions = {}
    observed_members, uncertain = set(), {}
    _checkpoint(deadline, database=True)
    for record_index, row in enumerate(
        VoteRecord.objects.filter(vote__in=votes)
        .values("vote_id", "representative_id", "position")
        .iterator(chunk_size=1000)
    ):
        if record_index % 1000 == 0:
            _checkpoint(deadline)
        if row["vote_id"] in passage_rolls:
            observed = passage_rolls[row["vote_id"]]
            observed_members.add(
                (row["representative_id"], observed["bill_id"], observed["chamber"])
            )
        if row["vote_id"] not in selected_ids:
            continue
        vote = selected_by_id[row["vote_id"]]
        key = (row["representative_id"], vote["bill_id"], vote["chamber"])
        if not vote["session_number"] or not _http_url(vote["source_url"]):
            uncertain.setdefault(row["representative_id"], set()).add(vote["bill_id"])
        else:
            chamber_positions[key] = (vote, row["position"])
    for rep_id, bill_id, chamber in observed_members:
        value = chamber_positions.get((rep_id, bill_id, chamber))
        if value is None or value[0]["id"] != selected[(bill_id, chamber)]["id"]:
            uncertain.setdefault(rep_id, set()).add(bill_id)
    positions_by_rep, cross_chamber = {}, {}
    for (rep_id, bill_id, _chamber), value in chamber_positions.items():
        own = positions_by_rep.setdefault(rep_id, {})
        if bill_id in own:
            cross_chamber.setdefault(rep_id, set()).add(bill_id)
        if bill_id not in own or (value[0]["vote_date"], value[0]["id"]) > (
            own[bill_id][0]["vote_date"],
            own[bill_id][0]["id"],
        ):
            own[bill_id] = value
    catalog = {}
    for member in roster:
        _checkpoint(deadline)
        rep_id = member["id"]
        sponsor = sponsor_rows.get(rep_id, {})
        cosponsor = cosponsor_rows.get(rep_id, {})
        sponsor_data, sponsor_vector, sponsor_n = _channel(
            sponsor,
            bill_rows,
            weights,
            topics,
            policy,
            missing_sponsor.get(rep_id, 0),
            unknown_sponsor.get(rep_id, 0),
        )
        cosponsor_data, cosponsor_vector, cosponsor_n = _channel(
            cosponsor,
            bill_rows,
            weights,
            topics,
            policy,
            missing_cosponsor.get(rep_id, 0),
            unknown_cosponsor.get(rep_id, 0),
            withdrawn.get(rep_id, 0),
        )
        union_rows = dict(sponsor)
        for bill_id, event_date in cosponsor.items():
            union_rows[bill_id] = max(event_date, union_rows.get(bill_id, event_date))
        units = _repeat_units(union_rows, bill_rows, weights)
        union = _totals(units)
        denominator = 3 * bool(sponsor_n) + 2 * bool(cosponsor_n)
        vector = (
            {
                topic_id: (
                    3 * sponsor_vector.get(topic_id, 0)
                    + 2 * cosponsor_vector.get(topic_id, 0)
                )
                / denominator
                for topic_id in sponsor_vector.keys() | cosponsor_vector.keys()
            }
            if denominator
            else {}
        )
        passage = _passage_evidence(
            positions_by_rep.get(rep_id, {}),
            bill_rows,
            topics,
            tag_ids,
            uncertain.get(rep_id, set()),
            cross_chamber.get(rep_id, set()),
        )
        resolution_counts = {
            kind: (
                len(resolution_observations.get(rep_id, {}).get(kind, set()))
                if resolution_rows
                else None
            )
            for kind in ("joint_count", "simple_count", "concurrent_count")
        }
        for source_kind, channel in (
            ("sponsor_fk", sponsor_data),
            ("active_cosponsor", cosponsor_data),
        ):
            for metric in channel["topics"]:
                for example in metric["examples"]:
                    example["source_kind"] = source_kind
        data = {
            "schema_version": SCHEMA,
            "policy_version": policy.version,
            "representative": member,
            "captured_at": captured_at.isoformat(),
            "window": {
                "start_date": start.isoformat(),
                "end_date_exclusive": end.isoformat(),
                "timezone": "America/New_York",
                "months": policy.window_months,
            },
            "policy": {
                "topic_share": policy.topic_share,
                "minimum_observations": policy.minimum_observations,
                "minimum_topic_observations": policy.minimum_topic_observations,
                "minimum_tag_coverage": policy.minimum_tag_coverage,
            },
            "exposure": {
                "status": "unknown",
                "term_precision": (
                    "year_derived" if rep_id in members_with_terms else "unknown"
                ),
                "service_days": None,
                "monthly_rate": None,
                "reason": "term_precision_unknown",
            },
            "channels": {"sponsor": sponsor_data, "active_cosponsor": cosponsor_data},
            "passage_evidence": passage,
            "resolutions": {
                "coverage": "observed_subset" if resolution_rows else "unsupported",
                **resolution_counts,
            },
            "caveats": [
                "ingested_subset",
                "term_precision_unknown",
                "official_bill_families_unavailable",
                "vote_coverage_unknown",
            ],
        }
        catalog[str(rep_id)] = {
            "activity": data,
            "vector": {str(key): fraction_json(value) for key, value in vector.items()},
            "union_count": union["n"],
            "union_tagged_count": union["tagged"],
            "union_topic_sets": [sorted(unit_weights) for unit_weights, _ in units],
        }
    _checkpoint(deadline, database=True)
    examples = [
        example
        for item in catalog.values()
        for channel in item["activity"]["channels"].values()
        for metric in channel["topics"]
        for example in metric["examples"]
    ]
    example_ids = {example["bill_id"] for example in examples}
    urls = {}
    for row in (
        BillDocument.objects.filter(bill_id__in=example_ids)
        .exclude(source_url__isnull=True)
        .order_by("bill_id", "id")
        .values("bill_id", "source_url")
        .iterator(chunk_size=1000)
    ):
        if _http_url(row["source_url"]):
            urls.setdefault(row["bill_id"], row["source_url"])
    for example in examples:
        example["source_url"] = urls.get(example["bill_id"])
    return {
        "schema_version": SCHEMA,
        "policy_version": policy.version,
        "captured_at": captured_at.isoformat(),
        "expires_at": captured_at.timestamp() + 300,
        "topics": {str(key): value for key, value in topics.items()},
        "representatives": catalog,
    }


def _http_url(value):
    try:
        parsed = urlsplit(value or "")
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except ValueError:
        return False


def _passage_evidence(positions, bills, topics, tags, uncertain, cross_chamber):
    counts = {key: 0 for key in ("yes", "no", "present", "not_voting", "other")}
    topic_counts, examples = {}, []
    for bill_id, (vote, position) in positions.items():
        position = position if position in counts else "other"
        counts[position] += 1
        for topic_id in tags[bill_id]:
            topic_counts.setdefault(topic_id, {key: 0 for key in counts})[position] += 1
        examples.append(
            {
                "bill_id": bill_id,
                "bill_number": bills[bill_id]["bill_number"],
                "session": bills[bill_id]["session"],
                "vote_id": vote["id"],
                "event_date": vote["vote_date"].isoformat(),
                "question": vote["question"],
                "position": position,
                "source_kind": "recorded_passage_position",
                "source_url": vote["source_url"],
                "cross_chamber_history": bill_id in cross_chamber,
            }
        )

    def projection(values):
        decisive = values["yes"] + values["no"]
        return {
            **values,
            "selected_bill_count": sum(values.values()),
            "yes_rate": round(values["yes"] / decisive, 6) if decisive else None,
            "missing_or_uncertain": 0,
        }

    return {
        "status": "coverage_unknown",
        **projection(counts),
        "missing_or_uncertain": len(uncertain),
        "missing_eligibility": "unknown",
        "cross_chamber_history_count": len(cross_chamber),
        "topics": [
            {
                "topic": topics[key],
                **projection(values),
                "missing_or_uncertain": sum(
                    key in tags[bill_id] for bill_id in uncertain
                ),
            }
            for key in sorted(
                set(topic_counts)
                | {topic_id for bill_id in uncertain for topic_id in tags[bill_id]}
            )
            for values in [topic_counts.get(key, {key: 0 for key in counts})]
        ],
        "examples": sorted(
            examples,
            key=lambda item: (item["event_date"], item["vote_id"]),
            reverse=True,
        )[:3],
    }


def representative_activity_catalog(*, captured_at=None, policy=None):
    policy = policy or DEFAULT_POLICY
    now = timezone.now()
    capture = captured_at or now
    if capture > now or now.timestamp() - capture.timestamp() >= 300:
        raise RecommendationError()
    day = capture.astimezone(ZoneInfo("America/New_York")).date()
    key = f"representative-topic-activity:v1:{policy.version}:{day}"
    cached = cache_call("get", key)
    if (
        cached
        and now.timestamp() < cached["expires_at"]
        and cached["captured_at"] <= now.isoformat()
    ):
        return cached
    token = secrets.token_hex(16)
    if not cache_call("add", key + ":gate", token, timeout=30):
        raise RecommendationError()
    deadline = time.monotonic() + 20
    try:
        with read_snapshot():
            result = _build_catalog(capture, policy, deadline)
        result = bounded_json(result, 16 * 1024 * 1024)
        if time.monotonic() >= deadline or cache_call("get", key + ":gate") != token:
            raise RecommendationError()
        remaining = int(result["expires_at"] - timezone.now().timestamp())
        if remaining <= 0:
            raise RecommendationError()
        cache_call("set", key, result, timeout=remaining)
        return result
    except RecommendationError:
        raise
    except Exception as exc:
        raise RecommendationError() from exc


def representative_topic_activity(representative_id, *, captured_at=None, policy=None):
    catalog = representative_activity_catalog(captured_at=captured_at, policy=policy)
    item = catalog["representatives"].get(str(representative_id))
    if item is None:
        raise Representative.DoesNotExist()
    return item["activity"]
