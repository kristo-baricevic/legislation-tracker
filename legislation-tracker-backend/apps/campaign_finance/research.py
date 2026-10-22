import hashlib
import json
import re
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from apps.congress.models import Representative
from apps.research.models import ResearchRun
from apps.research.tasks import fenced_work, continue_work
from .identity import resolve_candidate
from .models import CandidateIdentity, RepresentativeCandidate, CampaignCommittee, CandidateCommittee, Contributor, ContributorIdentity, FinanceSnapshot, FinanceResearchCheckpoint, FinanceTransaction
from .normalization import normalize_receipt, normalize_refund
from .fec_client import get_page, receipt_parameters
from .snapshots import reconciliation


def persist_page(checkpoint, page):
    """Caller owns the work lease transaction; commit page and cursor together."""
    digest = hashlib.sha256(json.dumps(page["results"], sort_keys=True).encode()).hexdigest()
    if digest in checkpoint.page_hashes:
        raise ValueError("repeated_page")
    for raw in page["results"]:
        row = (normalize_refund if checkpoint.schedule == "b" else normalize_receipt)(raw)
        if row["committee_id"] != checkpoint.committee_id:
            raise ValueError("recipient_mismatch")
        identity = ContributorIdentity.objects.filter(provider_key=row["identity_key"]).first()
        if identity is None:
            donor = Contributor.objects.create(name=row["name"], kind=row["contributor_kind"])
            identity = ContributorIdentity.objects.create(provider_key=row["identity_key"], contributor=donor, verified=row["verified"])
        fields = {key: row[key] for key in ("amount", "date", "kind", "source_url", "effective", "exclusion_reason", "filing_id", "source_metadata")}
        saved, created = FinanceTransaction.objects.get_or_create(snapshot=checkpoint.snapshot, source_key=row["source_key"], defaults={"committee": checkpoint.committee, "contributor": identity.contributor, **fields})
        if not created and (saved.contributor_id != identity.contributor_id or any(getattr(saved, key) != value for key, value in fields.items())):
            # An upstream revision during a scan cannot silently change an
            # already-counted record. Keep the previous published snapshot.
            raise ValueError("source_record_changed")
    cursor = page["pagination"].get("last_indexes") or {}
    cursor = {key: value for key, value in cursor.items() if value is not None}
    receipt_parameters(checkpoint.committee_id, checkpoint.snapshot.period, cursor, checkpoint.schedule)
    if page["results"] and (not cursor or cursor == checkpoint.cursor):
        raise ValueError("missing_or_unchanged_cursor")
    checkpoint.cursor = cursor
    checkpoint.complete = not page["results"]
    checkpoint.page_hashes = [*checkpoint.page_hashes, digest]
    checkpoint.save(update_fields=["cursor", "complete", "page_hashes"])


def process_finance(work):
    run = ResearchRun.objects.select_related("representative").get(pk=work.payload_json["run_id"])
    identity = resolve_candidate(run.representative_id, run.period)
    snapshot = FinanceSnapshot.objects.filter(run=run).first()
    checkpoint = snapshot.checkpoints.filter(complete=False).select_related("committee", "snapshot").first() if snapshot else None
    phase = work.payload_json.get("finance_phase", "committees")
    candidates = identity.candidate_ids
    index = work.payload_json.get("candidate_index", 0)
    if identity.status != "verified":
        # Name search supplies review candidates, never automatic links.
        page = get_page("candidates/search/", {"q": run.representative.name, "state": run.representative.state, "office": "S" if run.representative.chamber == "senate" else "H", "cycle": run.period, "per_page": 100}) if identity.status == "not_found" else None
    elif phase == "committees" and index < len(candidates):
        page = get_page(f"candidate/{candidates[index]}/committees/", {"cycle": run.period, "per_page": 100, "page": work.payload_json.get("committee_page", 1)})
    elif checkpoint:
        page = get_page(f"committee/{checkpoint.committee_id}/totals/", {"cycle": run.period, "per_page": 100}) if checkpoint.schedule == "totals" else get_page(f"schedules/schedule_{checkpoint.schedule}/", receipt_parameters(checkpoint.committee_id, run.period, checkpoint.cursor, checkpoint.schedule))
    else:
        page = None
    with transaction.atomic():
        current = fenced_work(work)
        if current is None:
            return {"status": "superseded"}
        Representative.objects.select_for_update().get(pk=run.representative_id)
        if resolve_candidate(run.representative_id, run.period) != identity:
            continue_work(current, "finance")
            return {"status": "identity_changed"}
        if identity.status != "verified":
            for item in (page or {}).get("results", []):
                fec_id = item.get("candidate_id", "")
                if not re.fullmatch(r"[HS]\d[A-Z]{2}\d{5}", fec_id):
                    continue
                candidate, _ = CandidateIdentity.objects.get_or_create(fec_id=fec_id, defaults={"name": str(item.get("name", ""))[:255], "office": item.get("office", ""), "state": item.get("state", "")})
                RepresentativeCandidate.objects.get_or_create(representative=run.representative, candidate=candidate, defaults={"periods": [run.period], "evidence_url": f"https://www.fec.gov/data/candidate/{fec_id}/"})
            run.sections["finance"] = {"status": "needs_review", "reason": "candidate_identity_requires_verification"}
            run.status, run.finished_at = "needs_review", timezone.now()
            run.save(update_fields=["sections", "status", "finished_at"])
            return {"status": run.status}
        if snapshot is None:
            snapshot = FinanceSnapshot.objects.create(run=run, representative=run.representative, period=run.period, candidate_ids=candidates)
        if snapshot.candidate_ids != candidates:
            raise ValueError("identity_changed_during_research")
        if phase == "committees" and index < len(candidates):
            for item in page["results"]:
                committee_id = item.get("committee_id", "")
                if item.get("designation") not in {"P", "A"} or not re.fullmatch(r"C\d{8}", committee_id):
                    continue
                committee, _ = CampaignCommittee.objects.update_or_create(fec_id=committee_id, defaults={"name": str(item.get("name", committee_id))[:255]})
                CandidateCommittee.objects.update_or_create(candidate_id=candidates[index], committee=committee, period=run.period, defaults={"designation": item["designation"], "source_url": f"https://www.fec.gov/data/committee/{committee_id}/"})
                for schedule in ("a", "b", "totals"):
                    FinanceResearchCheckpoint.objects.get_or_create(snapshot=snapshot, committee=committee, schedule=schedule)
            page_number = current.payload_json.get("committee_page", 1)
            if page_number < page["pagination"].get("pages", 1):
                current.payload_json["committee_page"] = page_number + 1
            else:
                current.payload_json.update(candidate_index=index + 1, committee_page=1)
                if index + 1 == len(candidates):
                    current.payload_json["finance_phase"] = "receipts"
            continue_work(current, "finance")
        elif checkpoint:
            if checkpoint.schedule == "totals":
                # Whitelist aggregate fields; never persist contributor contact
                # information or raw provider payloads.
                fields = ("coverage_start_date", "coverage_end_date", "individual_itemized_contributions", "individual_unitemized_contributions", "political_party_committee_contributions", "other_political_committee_contributions", "contribution_refunds")
                checkpoint.source_totals = {"records": [{key: row.get(key) for key in fields} for row in page["results"]], "source_url": f"https://www.fec.gov/data/committee/{checkpoint.committee_id}/?cycle={run.period}"}
                checkpoint.complete = page["pagination"].get("pages", 1) <= 1
                if not checkpoint.complete:
                    raise ValueError("ambiguous_committee_totals")
                checkpoint.save(update_fields=["source_totals", "complete"])
            else:
                persist_page(checkpoint, page)
            continue_work(current, "finance")
        else:
            # Source scans are not atomic and totals/refund reconciliation is
            # not implied by exhaustion. Never label this as complete funding.
            total = snapshot.transactions.filter(effective=True, kind="contribution").aggregate(value=Sum("amount"))["value"] or 0
            refunds = snapshot.transactions.filter(effective=True, kind="refund").aggregate(value=Sum("amount"))["value"] or 0
            snapshot.totals = {"observed_itemized_contributions": str(total), "observed_itemized_refunds": str(refunds), "net": None, "scope": "Processed itemized records; not total campaign funding", "reconciliation": "not_reconciled", "official_totals": [cp.source_totals for cp in snapshot.checkpoints.filter(schedule="totals")]}
            snapshot.coverage = "partial"
            snapshot.totals["reconciliation"] = reconciliation(snapshot)
            FinanceSnapshot.objects.filter(representative=run.representative, period=run.period, active=True).update(active=False)
            snapshot.active, snapshot.published_at = True, timezone.now()
            snapshot.save(update_fields=["active", "published_at", "coverage", "totals"])
            run.sections["finance"] = {"status": "partial", "reason": "itemized_receipts_only", "snapshot": str(snapshot.pk)}
            run.status, run.finished_at = "partial", timezone.now()
            run.save(update_fields=["sections", "status", "finished_at"])
    return {"status": run.status}
