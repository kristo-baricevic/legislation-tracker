"""Temporary dashboard scope; never mutates the user's followed interests."""
import hashlib
import json
import re
from django.db.models import Q
from apps.legislation.bill_stage import stage_for
from .recommendation_support import RecommendationError

FILTER_NAMES = {"q", "topic_id", "sponsor", "state", "status", "sort"}


def read_filters(params):
    values = {key: params[key].strip() for key in sorted(FILTER_NAMES) if params.get(key, "").strip()}
    # Raw statuses are exact captions from Bill.status, an unbounded text field.
    if any(len(value) > 300 for key, value in values.items()
           if key != "status" or not value.startswith("raw:")):
        raise RecommendationError("invalid_recommendation_filter", 400)
    if "topic_id" in values and not re.fullmatch(r"[1-9][0-9]{0,9}", values["topic_id"]):
        raise RecommendationError("invalid_recommendation_filter", 400)
    if "sponsor" in values and not (re.fullmatch(r"id:[1-9][0-9]{0,9}", values["sponsor"]) or values["sponsor"].startswith("unidentified:")):
        raise RecommendationError("invalid_recommendation_filter", 400)
    if "state" in values and not re.fullmatch(r"[A-Z]{2}", values["state"]):
        raise RecommendationError("invalid_recommendation_filter", 400)
    if "status" in values and values["status"] not in {"introduced", "committee", "first_chamber", "both_chambers", "law"} and not values["status"].startswith("raw:"):
        raise RecommendationError("invalid_recommendation_filter", 400)
    if "sort" in values and values["sort"] not in {"recent", "oldest", "title", "number"}:
        raise RecommendationError("invalid_recommendation_filter", 400)
    return values


def filter_key(filters):
    return hashlib.sha256(json.dumps(filters, sort_keys=True).encode()).hexdigest() if filters else ""


def filter_bills(query, filters):
    if filters.get("q"):
        query = query.filter(Q(title__icontains=filters["q"]) | Q(bill_number__icontains=filters["q"]))
    if filters.get("topic_id"):
        query = query.filter(bill_topics__topic_id=int(filters["topic_id"]))
    if filters.get("sponsor"):
        sponsor = filters["sponsor"]
        query = query.filter(sponsor_id=int(sponsor[3:])) if sponsor.startswith("id:") else query.none()
    if filters.get("state"):
        query = query.filter(sponsor__state__iexact=filters["state"])
    if filters.get("status"):
        status = filters["status"]
        if status.startswith("raw:"):
            query = query.filter(status=status[4:])
        else:
            statuses = query.order_by().values_list("status", flat=True).distinct()
            query = query.filter(status__in=[value for value in statuses if stage_for(value) == status])
    return query


def sort_results(results, sort):
    if sort == "title":
        results.sort(key=lambda item: (item["bill"]["title"].casefold(), item["bill"]["id"]))
    elif sort == "number":
        def number(item):
            bill = item["bill"]
            parts = re.split(r"(\d+)", bill["bill_number"])
            return (tuple((1, int(p)) if p.isdigit() else (0, p.casefold()) for p in parts), -bill["session"], bill["id"])
        results.sort(key=number)
    elif sort in {"recent", "oldest"}:
        dated = [item for item in results if item["bill"]["last_action_at"]]
        undated = [item for item in results if not item["bill"]["last_action_at"]]
        dated.sort(key=lambda item: item["bill"]["id"])
        dated.sort(key=lambda item: item["bill"]["last_action_at"], reverse=sort == "recent")
        results[:] = dated + sorted(undated, key=lambda item: item["bill"]["id"])
