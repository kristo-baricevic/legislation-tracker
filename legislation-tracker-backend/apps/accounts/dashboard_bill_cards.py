"""Compact reader previews for both dashboard rows; never start a job here."""

from django.db.models import Exists, F, OuterRef, Q, Subquery
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

HISTORY_BATCH_SIZE = 64


def _card_candidate_batches(bill_ids, status, chosen, documents):
    candidates = BillEnhancement.objects.filter(status=status)
    if status == "succeeded":
        candidates = candidates.filter(result_json__isnull=False).exclude(
            result_completeness="partial"
        )
    previews = candidates.only(
        "bill_id",
        "created_at",
        "status",
        "source_manifest_json",
        "source_fingerprint",
        "validation_digest",
        "output_schema_version",
    ).annotate(
        clauses=F("result_json__summary"),
        overview=F("result_json__overview"),
        synopsis=F("result_json__synopsis__text"),
    )

    # The initial probe fetches just one preview per bill, regardless of history.
    newest = candidates.filter(bill_id=OuterRef("pk")).order_by("-created_at", "-pk")
    ids = Bill.objects.filter(pk__in=bill_ids).values_list(
        Subquery(newest.values("pk")[:1]), flat=True
    )
    rows = list(previews.filter(pk__in=[pk for pk in ids if pk is not None]))
    yield rows

    # Only rejected bills enter the historical scan. Each cursor advances past
    # the last preview examined for its bill, including ties on created_at.
    cursors = {row.bill_id: row for row in rows}
    while cursors:
        older = Q()
        for bill_id, cursor in cursors.items():
            doc = documents.get(bill_id)
            if bill_id in chosen or doc is None:
                continue
            older |= (
                Q(bill_id=bill_id, source_manifest_json__document_id=doc.pk)
                & (
                    Q(source_manifest_json__document_content_hash=doc.reader_text_hash)
                    | Q(output_schema_version="2.0-source-first")
                )
                & (
                    Q(created_at__lt=cursor.created_at)
                    | Q(created_at=cursor.created_at, pk__lt=cursor.pk)
                )
            )
        if not older:
            return
        rows = list(
            previews.filter(older).order_by("bill_id", "-created_at", "-pk")[
                :HISTORY_BATCH_SIZE
            ]
        )
        yield rows
        if len(rows) < HISTORY_BATCH_SIZE:
            return
        # The page is grouped by bill, so all bills before the last are exhausted.
        last = rows[-1]
        cursors = {pk: cursor for pk, cursor in cursors.items() if pk > last.bill_id}
        cursors[last.bill_id] = last


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
    documents_by_bill = {
        bill_id: documents.get(pk) for bill_id, pk in identities.items()
    }
    chosen = {}
    for status in ("succeeded", "running", "pending"):
        remaining = bills.keys() - chosen.keys()
        if not remaining:
            break
        for rows in _card_candidate_batches(
            remaining, status, chosen, documents_by_bill
        ):
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
                document = documents_by_bill[bill.pk]
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
    plain_summaries = {}
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
        "contract_json__plain_summary",
        "document__source_purpose",
    ):
        plain = contract["contract_json__plain_summary"]
        if isinstance(plain, str):
            plain_summaries[contract["id"]] = plain
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
        summary = (
            (originals.get(bill.latest_contract_id) or "").strip()
            or strip_tags(bill.summary or "").strip()
            or plain_summaries.get(bill.latest_contract_id, "")
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
