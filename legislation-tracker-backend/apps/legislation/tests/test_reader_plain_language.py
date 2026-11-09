from apps.legislation.extraction.reader_language import explain_line
import pytest
from django.core.management import call_command
from io import StringIO
from apps.legislation.models import Bill, BillContract


@pytest.mark.django_db
def test_backfill_is_idempotent_and_keeps_original_identity_and_evidence():
    bill = Bill.objects.create(jurisdiction="federal", session=118, bill_number="HR 99", title="Test", status="Introduced")
    original = {"line_items": [{"id": "one", "kind": "requirement", "actor": "the agency", "action": "report", "display_text": "Requires the agency to report prior to July 1."}]}
    contract = BillContract.objects.create(bill=bill, schema_version="2.1-legal-nlp", contract_hash="immutable", contract_json=original)
    call_command("refresh_reader_copy", stdout=StringIO())
    contract.refresh_from_db()
    assert contract.reader_copy == {}
    call_command("refresh_reader_copy", execute=True, stdout=StringIO())
    contract.refresh_from_db()
    assert contract.reader_copy["lines"]["one"] == "The agency must report before July 1."
    assert contract.contract_json == original
    assert contract.contract_hash == "immutable"
    output = StringIO()
    call_command("refresh_reader_copy", execute=True, stdout=output)
    assert "changed=0 unchanged=1" in output.getvalue()


def test_direct_duty_retains_every_condition_and_number():
    line = {"kind": "requirement", "actor": "the Secretary", "action": "provide assistance",
            "display_text": "Requires the Secretary to provide assistance prior to July 1, 2027, except that payments may not exceed 20% of wages."}
    assert explain_line(line) == "The Secretary must provide assistance before July 1, 2027, except that payments may not exceed 20% of wages."


def test_does_not_rewrite_quoted_amendment_payload():
    text = 'Changes section 2 by replacing “prior to” with “subsequent to”.'
    assert explain_line({"kind": "amendment", "display_text": text}) == text


def test_mismatching_actor_does_not_invent_a_duty():
    assert explain_line({"kind": "requirement", "actor": "the Secretary", "action": "pay", "display_text": "No agency may pay unless authorized."}) == "No agency may pay unless authorized."


def test_plain_language_retains_eligibility_and_authorization_not_appropriation():
    text = "Authorizes such sums as may be necessary for eligible entities in order to carry out the program, subject to section 4."
    assert explain_line({"kind": "financial", "display_text": text}) == "Authorizes whatever funding is needed for eligible entities to carry out the program, subject to section 4."


def test_minimum_maximum_and_quoted_terms_are_preserved():
    text = 'Payments must be not less than $10 and not more than 20% of wages; the term “prior to” remains unchanged.'
    assert explain_line({"kind": "financial", "display_text": text}) == 'Payments must be at least $10 and at most 20% of wages; the term “prior to” remains unchanged.'
