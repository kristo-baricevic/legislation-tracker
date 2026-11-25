"""Compact reader previews for both dashboard rows; never start a job here."""

from itertools import batched

from django.db.models import Case, Exists, F, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce
from django.utils.html import strip_tags

from apps.legislation.enhancements.shared import (
    _reader_result_valid,
    _source_first_inputs,
    source_compatible,
    validation_key,
)
from apps.legislation.extraction.reader_language import VERSION, bill_brief
from apps.legislation.models import (
    Bill,
    BillContract,
    BillDocument,
    BillEnhancement,
    BillProcessingCache,
)


def _enhanced_cards(bills):
    if not bills:
        return {}
    docs = BillDocument.objects.filter(bill_id=OuterRef("pk")).order_by(
        "-created_at", "-id"
    )

    def selected(query):
        return Subquery(query.values("id")[:1])

    identities = dict(
        Bill.objects.filter(pk__in=bills)
        .annotate(
            doc_id=Coalesce(
                selected(docs.filter(is_active_version=True)),
                selected(
                    docs.exclude(extracted_text__isnull=True).exclude(extracted_text="")
                ),
                selected(docs.exclude(raw_text__isnull=True).exclude(raw_text="")),
            )
        )
        .values_list("id", "doc_id")
    )
    documents = BillDocument.objects.defer("raw_text", "extracted_text").in_bulk(
        {pk for pk in identities.values() if pk}
    )
    contracts = (
        BillContract.objects.only("document_id", "contract_hash", "schema_version")
        .annotate(json_version=F("contract_json__schema_version"))
        .in_bulk({b.latest_contract_id for b in bills.values() if b.latest_contract_id})
    )
    candidates = (
        BillEnhancement.objects.filter(bill_id__in=bills)
        .filter(
            Q(status__in=["running", "pending"])
            | (
                Q(status="succeeded", result_json__isnull=False)
                & ~Q(result_completeness="partial")
            )
        )
        .only(
            "bill_id",
            "status",
            "source_manifest_json",
            "source_fingerprint",
            "validation_digest",
            "output_schema_version",
        )
        .annotate(
            clauses=F("result_json__summary"),
            overview=F("result_json__overview"),
            synopsis=F("result_json__synopsis__text"),
        )
        .order_by(
            Case(
                When(status="succeeded", then=Value(0)),
                When(status="running", then=Value(1)),
                default=Value(2),
            ),
            "-created_at",
            "-pk",
        )
    )
    chosen = {}
    for batch in batched(candidates.iterator(chunk_size=64), 64):
        rows = [row for row in batch if row.bill_id not in chosen]
        if not rows:
            continue
        validity = dict(
            BillProcessingCache.objects.filter(
                pk__in=[
                    validation_key(row) for row in rows if row.status == "succeeded"
                ]
            ).values_list("pk", "result_json__valid")
        )
        for row in rows:
            if row.bill_id in chosen:
                continue
            bill = bills[row.bill_id]
            document = documents.get(identities[bill.pk])
            contract = contracts.get(bill.latest_contract_id)
            inputs = None
            if row.output_schema_version == "2.0-source-first":
                inputs = _source_first_inputs(row, document)
                if inputs is None:
                    continue
            elif not source_compatible(row, bill, identity=(document, contract)):
                continue
            if row.status == "succeeded":
                valid = validity.get(validation_key(row))
                if valid is None:
                    valid = _reader_result_valid(row, source_first_inputs=inputs)
                if not valid:
                    continue
            chosen[bill.pk] = row
        if len(chosen) == len(bills):
            break
    return chosen


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
    enhanced = _enhanced_cards({bill.pk: bill for bill in bills if bill.has_candidate})
    for bill in bills:
        card = targets[bill.pk]
        summary = originals.get(bill.latest_contract_id) or strip_tags(
            bill.summary or ""
        )
        saved = enhanced.get(bill.pk)
        if saved and saved.status == "succeeded":
            clauses = saved.clauses or saved.overview or []
            summary = (
                " ".join(
                    c["text"] for c in clauses if isinstance(c, dict) and c.get("text")
                )
                or summary
            )
            if saved.output_schema_version == "2.0-source-first":
                summary = saved.synopsis or summary
        card.update(
            card_summary=" ".join(summary.split())[:800],
            enhancement_status=saved.status if saved else None,
            enhancement_id=saved.pk if saved else None,
        )
    return rows
