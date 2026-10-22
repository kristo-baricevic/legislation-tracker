"""Conservative classification of processed FEC Schedule A receipts.

Unknown receipts remain excluded, never guessed into donor totals. The processed
feed handles amendments; immutable snapshots prevent combining different scans.
"""
from datetime import date
from decimal import Decimal, InvalidOperation
import re


def memo_flag(value):
    if value is None or value is False or value == 0 or value in ("", "false", "False", "0"):
        return False
    if value is True or value == 1 or value in ("true", "True", "1"):
        return True
    raise ValueError("invalid_memo_flag")


def source_metadata(row):
    # Evidence identifiers only. No addresses, employers, contact details, or
    # unconstrained provider payloads are retained.
    fields = ("transaction_id", "original_sub_id", "file_number", "image_number",
              "back_reference_transaction_id", "back_reference_schedule_name",
              "amendment_indicator", "receipt_type", "line_number", "filing_form",
              "conduit_committee_id", "memo_code", "memoed_subtotal")
    return {key: str(row[key])[:128] for key in fields if row.get(key) is not None}


def normalize_receipt(row):
    committee = str(row.get("committee_id", ""))
    sub_id = str(row.get("sub_id", ""))
    if not re.fullmatch(r"C\d{8}", committee) or not sub_id.isdigit():
        raise ValueError("invalid_source_identity")
    try:
        amount = Decimal(str(row["contribution_receipt_amount"]))
        if not amount.is_finite() or abs(amount) >= Decimal("1e18") or amount != amount.quantize(Decimal(".01")):
            raise ValueError("invalid_amount")
    except (KeyError, InvalidOperation):
        raise ValueError("invalid_amount") from None
    line = str(row.get("line_number") or "").upper().replace("(", "").replace(")", "")
    entity = row.get("entity_type")
    donor_id = str(row.get("contributor_id") or "")
    verified = entity in {"PAC", "COM", "CCM", "PTY"} and bool(re.fullmatch(r"C\d{8}", donor_id))
    reason = ""
    kind = {"11D": "candidate_contribution", "12": "transfer", "13A": "candidate_loan", "13B": "loan"}.get(line, "contribution" if line in {"11AI", "11A1", "11B", "11C"} else "other_receipt")
    if row.get("memo_code") or memo_flag(row.get("memoed_subtotal")):
        reason = "memo_record"
    elif amount < 0:
        kind, reason = "adjustment", "negative_receipt_requires_reconciliation"
    elif kind != "contribution":
        reason = "not_classified_as_contribution"
    elif row.get("conduit_committee_id") or row.get("conduit_committee_name"):
        reason = "earmarked_requires_reconciliation"
    when = row.get("contribution_receipt_date")
    try:
        when = date.fromisoformat(when[:10]) if when else None
    except (TypeError, ValueError):
        raise ValueError("invalid_receipt_date") from None
    return dict(source_key=f"{committee}:{sub_id}", committee_id=committee, name=str(row.get("contributor_name") or "Unidentified contributor")[:255], identity_key=f"fec:{donor_id}" if verified else f"fec-record:{committee}:{sub_id}", verified=verified, contributor_kind="committee" if verified else "individual" if entity == "IND" else "unresolved", amount=amount, date=when, kind=kind, effective=not reason, exclusion_reason=reason, filing_id=str(row.get("file_number") or ""), source_metadata=source_metadata(row), source_url=f"https://www.fec.gov/data/receipts/?data_type=processed&committee_id={committee}&sub_id={sub_id}")


def normalize_refund(row):
    line = str(row.get("line_number", "")).upper()
    adapted = {**row, "contributor_name": row.get("recipient_name"), "contributor_id": row.get("recipient_committee_id"), "contribution_receipt_amount": row.get("disbursement_amount"), "contribution_receipt_date": row.get("disbursement_date"), "line_number": {"20A": "11AI", "20B": "11B", "20C": "11C"}.get(line, "other")}
    result = normalize_receipt(adapted)
    result["source_metadata"] = source_metadata(row)
    result["source_key"] = "B:" + result["source_key"]
    if not result["verified"]:
        result["identity_key"] = "refund:" + result["identity_key"]
    result["kind"] = "refund" if result["effective"] else "other_disbursement"
    result["source_url"] = result["source_url"].replace("/receipts/", "/disbursements/")
    return result
