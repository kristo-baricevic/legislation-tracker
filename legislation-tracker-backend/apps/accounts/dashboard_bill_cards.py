"""Compact reader previews for both dashboard rows; never start a job here."""

from django.db.models import Exists, OuterRef
from django.utils.html import strip_tags

from apps.legislation.enhancements.shared import shared_enhancement
from apps.legislation.extraction.reader_language import VERSION, bill_brief
from apps.legislation.models import Bill, BillContract, BillEnhancement


def add_card_summaries(rows):
    if not rows:
        return rows
    targets = {row["bill"]["id"]: row["bill"] for row in rows}
    candidates = BillEnhancement.objects.filter(
        bill_id=OuterRef("pk"), status__in=("pending", "running", "succeeded")
    )
    bills = list(
        Bill.objects.filter(pk__in=targets)
        .annotate(has_candidate=Exists(candidates))
        .only("id", "summary", "latest_contract_id")
    )
    originals = {}
    for contract in BillContract.objects.filter(
        pk__in=[b.latest_contract_id for b in bills if b.latest_contract_id]
    ).values(
        "id",
        "schema_version",
        "contract_hash",
        "reader_copy__version",
        "reader_copy__contract_hash",
        "reader_copy__brief__summary",
        "contract_json__orientation",
        "document__source_purpose",
    ):
        if contract["schema_version"] != "2.1-legal-nlp":
            continue
        summary = (
            contract["reader_copy__brief__summary"]
            if (
                contract["reader_copy__version"] == VERSION
                and contract["reader_copy__contract_hash"] == contract["contract_hash"]
            )
            else None
        )
        if not summary:
            summary = bill_brief(
                {"orientation": contract["contract_json__orientation"]},
                contract["document__source_purpose"] or "",
            )["summary"]
        originals[contract["id"]] = summary
    for bill in bills:
        card = targets[bill.pk]
        summary = originals.get(bill.latest_contract_id) or strip_tags(
            bill.summary or ""
        )
        saved = shared_enhancement(bill) if bill.has_candidate else None
        if saved and saved.status == "succeeded":
            result = saved.result_json or {}
            clauses = result.get("summary") or result.get("overview") or []
            summary = (
                " ".join(
                    c["text"] for c in clauses if isinstance(c, dict) and c.get("text")
                )
                or summary
            )
            if result.get("schema_version") == "2.0-source-first":
                summary = (result.get("synopsis") or {}).get("text") or summary
        card.update(
            card_summary=" ".join(summary.split())[:800],
            enhancement_status=saved.status if saved else None,
            enhancement_id=saved.pk if saved else None,
        )
    return rows
