import hashlib
import json
import re

from django.db import transaction
from django.db.models import Case, IntegerField, Sum, Value, When
from django.utils import timezone

from apps.congress.models import Representative
from apps.congress.names import normalize_person_name
from apps.research.models import ResearchRun
from apps.research.tasks import continue_work, fenced_work, is_latest_run

from .fec_client import get_page, receipt_parameters
from .identity import (
    candidate_search_name,
    excluded_candidates,
    resolve_candidate,
    review_choices,
    surname_query,
    verified_match,
)
from .models import (
    CampaignCommittee,
    CandidateCommittee,
    CandidateIdentity,
    Contributor,
    ContributorIdentity,
    FinanceResearchCheckpoint,
    FinanceSnapshot,
    FinanceTransaction,
    RepresentativeCandidate,
)
from .normalization import normalize_receipt, normalize_refund
from .outside import (
    ENDPOINTS,
    ensure_outside_scans,
    outside_complete,
    persist_outside_page,
)
from .snapshots import reconciliation

FILTERED_SCHEDULES = ("totals", "a_11b", "a_11c", "b_20b", "b_20c", "a_11ai", "b_20a")


@transaction.atomic
def persist_page(checkpoint, page):
    """Caller owns the work lease transaction; commit page and cursor together."""
    digest = hashlib.sha256(
        json.dumps(page["results"], sort_keys=True).encode()
    ).hexdigest()
    if digest in checkpoint.page_hashes:
        raise ValueError("repeated_page")
    rows = []
    for raw in page["results"]:
        row = (
            normalize_refund
            if checkpoint.schedule.startswith("b")
            else normalize_receipt
        )(raw)
        if row["committee_id"] != checkpoint.committee_id:
            raise ValueError("recipient_mismatch")
        rows.append(row)
    by_identity = {row["identity_key"]: row for row in rows}
    identities = {
        identity.provider_key: identity
        for identity in ContributorIdentity.objects.filter(provider_key__in=by_identity)
    }
    missing = [key for key in by_identity if key not in identities]
    if missing:
        donors = Contributor.objects.bulk_create(
            [
                Contributor(
                    name=by_identity[key]["name"],
                    kind=by_identity[key]["contributor_kind"],
                )
                for key in missing
            ]
        )
        ContributorIdentity.objects.bulk_create(
            [
                ContributorIdentity(
                    provider_key=key,
                    contributor=donor,
                    verified=by_identity[key]["verified"],
                )
                for key, donor in zip(missing, donors, strict=False)
            ],
            ignore_conflicts=True,
        )
        identities.update(
            {
                identity.provider_key: identity
                for identity in ContributorIdentity.objects.filter(
                    provider_key__in=missing
                )
            }
        )
        # A concurrent snapshot may win the identity insert. Only discard the
        # unused contributor rows this transaction just created, never donors
        # referenced by another snapshot.
        used = {identity.contributor_id for identity in identities.values()}
        unused = [donor.pk for donor in donors if donor.pk not in used]
        if unused:
            Contributor.objects.filter(pk__in=unused).delete()
    desired = {}
    for row in rows:
        identity = identities[row["identity_key"]]
        fields = {
            key: row[key]
            for key in (
                "amount",
                "date",
                "kind",
                "source_url",
                "effective",
                "exclusion_reason",
                "filing_id",
                "source_metadata",
            )
        }
        fields.update(
            committee_id=checkpoint.committee_id, contributor_id=identity.contributor_id
        )
        if row["source_key"] in desired and desired[row["source_key"]] != fields:
            raise ValueError("source_record_changed")
        desired[row["source_key"]] = fields
    existing = set(
        FinanceTransaction.objects.filter(
            snapshot_id=checkpoint.snapshot_id, source_key__in=desired
        ).values_list("source_key", flat=True)
    )
    FinanceTransaction.objects.bulk_create(
        [
            FinanceTransaction(
                snapshot_id=checkpoint.snapshot_id, source_key=key, **fields
            )
            for key, fields in desired.items()
            if key not in existing
        ],
        ignore_conflicts=True,
    )
    # Check both existing rows and conflicting concurrent inserts; no amended
    # row may silently replace an already-counted record in this snapshot.
    saved_rows = list(
        FinanceTransaction.objects.filter(
            snapshot_id=checkpoint.snapshot_id, source_key__in=desired
        )
    )
    if len(saved_rows) != len(desired):
        raise ValueError("source_record_not_saved")
    for saved in saved_rows:
        if any(
            getattr(saved, key) != value
            for key, value in desired[saved.source_key].items()
        ):
            raise ValueError("source_record_changed")
    cursor = page["pagination"].get("last_indexes") or {}
    cursor = {key: value for key, value in cursor.items() if value is not None}
    receipt_parameters(
        checkpoint.committee_id, checkpoint.snapshot.period, cursor, checkpoint.schedule
    )
    if page["results"] and (not cursor or cursor == checkpoint.cursor):
        raise ValueError("missing_or_unchanged_cursor")
    checkpoint.cursor = cursor
    checkpoint.complete = not page["results"]
    checkpoint.page_hashes = [*checkpoint.page_hashes, digest]
    checkpoint.save(update_fields=["cursor", "complete", "page_hashes"])


def process_finance(work):
    run = ResearchRun.objects.select_related("representative").get(
        pk=work.payload_json["run_id"]
    )
    identity = resolve_candidate(run.representative_id, run.period)
    if identity.status == "verified" and work.payload_json.get("include_history", True):
        from .history import queue_history

        queue_history(run)
    snapshot = FinanceSnapshot.objects.filter(run=run).first()
    priority = Case(
        *[
            When(schedule=name, then=Value(i))
            for i, name in enumerate(FILTERED_SCHEDULES)
        ],
        default=Value(10),
        output_field=IntegerField(),
    )
    checkpoint = (
        snapshot.checkpoints.filter(complete=False)
        .select_related("committee", "snapshot")
        .order_by(priority, "pk")
        .first()
        if snapshot
        else None
    )
    phase = work.payload_json.get("finance_phase", "committees")
    if phase == "receipts" and snapshot and not outside_complete(snapshot):
        phase = "outside_setup"
    if (
        phase == "outside"
        and snapshot
        and snapshot.outside_scans.count()
        < len(identity.candidate_ids) * len(ENDPOINTS)
    ):
        phase = "outside_setup"
    candidates = identity.candidate_ids
    index = work.payload_json.get("candidate_index", 0)
    outside_scan = (
        snapshot.outside_scans.filter(complete=False)
        .order_by("candidate_id", "category")
        .first()
        if snapshot
        else None
    )
    outside_page_number = outside_scan.page if outside_scan else None
    if identity.status != "verified":
        # Recheck blocked discoveries using fresh provider evidence, not saved names.
        rep = run.representative
        filters = {
            "state": rep.state,
            "office": "S" if rep.chamber == "senate" else "H",
            "cycle": run.period,
            "per_page": 100,
        }
        page = get_page(
            "candidates/search/", {**filters, "q": candidate_search_name(rep)}
        )
        rows = page["results"]
        year = timezone.now().year
        matched = (
            verified_match(rep, rows, run.period, year + year % 2)
            if page["pagination"].get("pages", 1) <= 1
            else None
        )
        # A later staff correction takes precedence over fresh search results.
        from .models import ConfirmedCandidate

        reviewed = (
            ConfirmedCandidate.objects.filter(representative=rep, period=run.period)
            .values_list("candidate_id", flat=True)
            .first()
        )
        excluded = excluded_candidates(rep.pk, run.period)
        if reviewed:
            excluded.add(reviewed)
        if matched in excluded:
            matched = None
        choices = []
        if not matched:
            surname = surname_query(rep)
            if surname and surname.casefold() != candidate_search_name(rep).casefold():
                if rep.chamber == "house" and str(rep.district).isdigit():
                    filters["district"] = str(rep.district).zfill(2)
                fallback = get_page("candidates/search/", {**filters, "q": surname})
                rows = [*rows, *fallback["results"]]
            choices = [
                choice
                for choice in review_choices(rep, rows)
                if choice["candidate_id"] not in excluded
            ]
    elif phase == "committees" and index < len(candidates):
        page = get_page(
            f"candidate/{candidates[index]}/committees/",
            {
                "cycle": run.period,
                "per_page": 100,
                "page": work.payload_json.get("committee_page", 1),
            },
        )
    elif phase == "outside" and outside_scan:
        page = get_page(
            ENDPOINTS[outside_scan.category],
            {
                "candidate_id": outside_scan.candidate_id,
                "cycle": run.period,
                "per_page": 100,
                "page": outside_scan.page,
                "sort": "committee_id",
            },
        )
    elif phase in {"outside", "outside_setup"}:
        page = None
    elif checkpoint:
        page = (
            get_page(
                f"committee/{checkpoint.committee_id}/totals/",
                {"cycle": run.period, "per_page": 100},
            )
            if checkpoint.schedule == "totals"
            else get_page(
                f"schedules/schedule_{checkpoint.schedule[0]}/",
                receipt_parameters(
                    checkpoint.committee_id,
                    run.period,
                    checkpoint.cursor,
                    checkpoint.schedule,
                ),
            )
        )
    else:
        page = None
    with transaction.atomic():
        current = fenced_work(work)
        if current is None:
            return {"status": "superseded"}
        Representative.objects.select_for_update().get(pk=run.representative_id)
        if not is_latest_run(run):
            return {"status": "superseded"}
        if resolve_candidate(run.representative_id, run.period) != identity:
            continue_work(current, "finance")
            return {"status": "identity_changed"}
        if run.status == "queued":
            run.status = "running"
            run.sections = {**run.sections, "finance": {"status": "running"}}
            run.save(update_fields=["status", "sections"])
        if identity.status != "verified":
            for item in page["results"] if matched else []:
                fec_id = item.get("candidate_id", "")
                if not re.fullmatch(r"[HS]\d[A-Z]{2}\d{5}", fec_id):
                    continue
                if matched and fec_id != matched:
                    continue
                candidate, _ = CandidateIdentity.objects.update_or_create(
                    fec_id=fec_id,
                    defaults={
                        "name": normalize_person_name(item.get("name", ""))[:255],
                        "office": item.get("office", ""),
                        "state": item.get("state", ""),
                    },
                )
                mapping, created = RepresentativeCandidate.objects.get_or_create(
                    representative=run.representative,
                    candidate=candidate,
                    defaults={
                        "periods": [run.period],
                        "verified": fec_id == matched,
                        "evidence_url": f"https://www.fec.gov/data/candidate/{fec_id}/?cycle={run.period}",
                    },
                )
                if mapping.revoked or run.period in mapping.rejected_periods:
                    continue
                if (
                    not created
                    and fec_id == matched
                    and (not mapping.verified or not mapping.evidence_url)
                ):
                    # Fresh current-period proof does not verify historical periods.
                    mapping.periods = [run.period]
                    mapping.verified = True
                    mapping.evidence_url = f"https://www.fec.gov/data/candidate/{fec_id}/?cycle={run.period}"
                    mapping.save(update_fields=["periods", "verified", "evidence_url"])
                # Only fresh current-period proof extends a verified mapping.
                # Never promote unverified historical periods as a side effect.
                if (
                    not created
                    and fec_id == matched
                    and mapping.verified
                    and mapping.evidence_url
                    and run.period not in mapping.periods
                ):
                    mapping.periods = sorted({*mapping.periods, run.period})
                    mapping.save(update_fields=["periods"])
            if (
                matched
                and resolve_candidate(run.representative_id, run.period).status
                == "verified"
            ):
                run.sections["finance"] = {"status": "running", "reason": ""}
                run.status = "running"
                run.save(update_fields=["sections", "status"])
                continue_work(current, "finance")
                return {"status": "running"}
            run.sections["finance"] = {
                "status": "needs_review",
                "reason": "candidate_identity_requires_verification",
            }
            run.status, run.finished_at = "needs_review", timezone.now()
            if choices:
                run.sections["finance"].update(
                    candidates=choices, representative_name=rep.name
                )
            elif not page["results"]:
                run.sections["finance"] = {
                    "status": "not_available",
                    "reason": "candidate_not_found",
                }
                run.status = "partial"
            run.save(update_fields=["sections", "status", "finished_at"])
            return {"status": run.status}
        if snapshot is None:
            snapshot, _ = FinanceSnapshot.objects.get_or_create(
                run=run,
                defaults=dict(
                    representative=run.representative,
                    period=run.period,
                    candidate_ids=candidates,
                    normalization_version="fec-2-filtered",
                ),
            )
        snapshot.refresh_from_db()
        if snapshot.invalidated or snapshot.candidate_ids != candidates:
            raise ValueError("identity_changed_during_research")
        if phase == "committees" and index < len(candidates):
            for item in page["results"]:
                committee_id = item.get("committee_id", "")
                if item.get("designation") not in {"P", "A"} or not re.fullmatch(
                    r"C\d{8}", committee_id
                ):
                    continue
                committee, _ = CampaignCommittee.objects.update_or_create(
                    fec_id=committee_id,
                    defaults={"name": str(item.get("name", committee_id))[:255]},
                )
                CandidateCommittee.objects.update_or_create(
                    candidate_id=candidates[index],
                    committee=committee,
                    period=run.period,
                    defaults={
                        "designation": item["designation"],
                        "source_url": f"https://www.fec.gov/data/committee/{committee_id}/",
                    },
                )
                link = {
                    "candidate_id": candidates[index],
                    "committee_id": committee_id,
                    "designation": item["designation"],
                    "source_url": f"https://www.fec.gov/data/candidate/{candidates[index]}/?cycle={run.period}",
                }
                if link not in snapshot.committee_links:
                    snapshot.committee_links = [*snapshot.committee_links, link]
                    snapshot.save(update_fields=["committee_links"])
                # Never change the query underneath a previously saved cursor.
                for schedule in (
                    FILTERED_SCHEDULES
                    if snapshot.normalization_version == "fec-2-filtered"
                    else ("a", "b", "totals")
                ):
                    FinanceResearchCheckpoint.objects.get_or_create(
                        snapshot=snapshot, committee=committee, schedule=schedule
                    )
            page_number = current.payload_json.get("committee_page", 1)
            if page_number < page["pagination"].get("pages", 1):
                current.payload_json["committee_page"] = page_number + 1
            else:
                current.payload_json.update(candidate_index=index + 1, committee_page=1)
                if index + 1 == len(candidates):
                    current.payload_json["finance_phase"] = "outside"
                    ensure_outside_scans(snapshot)
            continue_work(current, "finance")
        elif phase == "outside_setup":
            ensure_outside_scans(snapshot)
            current.payload_json["finance_phase"] = "outside"
            continue_work(current, "finance")
        elif phase == "outside":
            if outside_scan:
                outside_scan.refresh_from_db()
                if (
                    not outside_scan.complete
                    and outside_scan.page == outside_page_number
                ):
                    persist_outside_page(outside_scan, page)
            else:
                current.payload_json["finance_phase"] = "totals"
            continue_work(current, "finance")
        elif checkpoint:
            if checkpoint.schedule == "totals":
                # Whitelist aggregate fields; never persist contributor contact
                # information or raw provider payloads.
                fields = (
                    "coverage_start_date",
                    "coverage_end_date",
                    "receipts",
                    "disbursements",
                    "individual_itemized_contributions",
                    "individual_unitemized_contributions",
                    "political_party_committee_contributions",
                    "other_political_committee_contributions",
                    "contribution_refunds",
                )
                checkpoint.source_totals = {
                    "committee": checkpoint.committee.name,
                    "records": [
                        {key: row.get(key) for key in fields} for row in page["results"]
                    ],
                    "source_url": f"https://www.fec.gov/data/committee/{checkpoint.committee_id}/?cycle={run.period}",
                }
                checkpoint.complete = page["pagination"].get("pages", 1) <= 1
                if not checkpoint.complete:
                    raise ValueError("ambiguous_committee_totals")
                checkpoint.save(update_fields=["source_totals", "complete"])
                if not snapshot.checkpoints.filter(
                    schedule="totals", complete=False
                ).exists():
                    current.payload_json["finance_phase"] = "receipts"
            else:
                persist_page(checkpoint, page)
            continue_work(current, "finance")
        else:
            # Source scans are not atomic and totals/refund reconciliation is
            # not implied by exhaustion. Never label this as complete funding.
            total = (
                snapshot.transactions.filter(
                    effective=True, kind="contribution"
                ).aggregate(value=Sum("amount"))["value"]
                or 0
            )
            refunds = (
                snapshot.transactions.filter(effective=True, kind="refund").aggregate(
                    value=Sum("amount")
                )["value"]
                or 0
            )
            snapshot.totals = {
                "observed_itemized_contributions": str(total),
                "observed_itemized_refunds": str(refunds),
                "net": None,
                "scope": "Processed itemized records; not total campaign funding",
                "reconciliation": "not_reconciled",
                "official_totals": [
                    cp.source_totals
                    for cp in snapshot.checkpoints.filter(schedule="totals")
                ],
            }
            snapshot.coverage = "partial"
            snapshot.totals["reconciliation"] = reconciliation(snapshot)
            FinanceSnapshot.objects.filter(
                representative=run.representative, period=run.period, active=True
            ).update(active=False)
            snapshot.active, snapshot.published_at = True, timezone.now()
            snapshot.save(
                update_fields=["active", "published_at", "coverage", "totals"]
            )
            run.sections["finance"] = {
                "status": "partial",
                "reason": "itemized_receipts_only",
                "snapshot": str(snapshot.pk),
            }
            run.status, run.finished_at = "partial", timezone.now()
            run.save(update_fields=["sections", "status", "finished_at"])
    return {"status": run.status}
