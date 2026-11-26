"""Verbatim pinned passages in controlled layouts with a distant dependency.

The layout and the upstream answers are deterministic. The production planner,
map validator, reconciliation, confirmation, worker, publication and reader
serializer run normally. The separate full-XML test checks the original layout.
"""

import copy
import json
from pathlib import Path
from xml.sax.saxutils import escape

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.legislation.enhancements.reader_citations import citation_passages
from apps.legislation.enhancements.reader_discovery import (
    money_candidates,
    policy_passages,
)
from apps.legislation.tasks import run_bill_enhancement_attempt

from .test_large_bill_staged_flow import (
    RecordedModel,
    _claim,
    _confirmation,
    _cross_section_source,
    _quote,
    _stored_document,
    _valid_credential,
)

FIXTURES = Path(__file__).parent / "fixtures/harness"
AMENDMENT = (
    "Subsection (e) of section 232 of the Carl Levin and Howard P. Buck McKeon National Defense "
    "Authorization Act for Fiscal Year 2015 (Public Law 113–291; 10 U.S.C. note prec. 4091) "
    "is amended by striking September 30, 2025 and inserting September 30, 2030."
)


def fixture(bill):
    evidence = json.loads((FIXTURES / f"{bill}.json").read_text())["evidence"]
    if bill == "119s4387is":
        first = evidence[0]["quote"].split("—")[1]
        second = next(
            line.split("—")[1]
            for line in (FIXTURES / f"{bill}.txt").read_text().splitlines()
            if "shall award grants to eligible entities" in line
        )
        return (
            [
                (
                    first,
                    "authorized to be appropriated",
                    "Authorize annual funding",
                    "Congress authorizes $15 million annually for fiscal years 2027 through 2029.",
                    "permitted",
                    ("15000000", "USD", "dollars", None),
                ),
                (
                    second,
                    "shall award grants",
                    "Award grants",
                    "The Secretary must award grants to eligible entities for maternal and child health.",
                    "required",
                    None,
                ),
            ],
            "this section",
            "Congress authorizes $15 million annually for fiscal years 2027 through 2029 for grants to eligible entities.",
        )
    if bill == "119hr9300ih":
        return (
            [
                (
                    evidence[3]["quote"].split("—", 1)[1],
                    "not reserved under section 4",
                    "Reserve evidence-based funding",
                    "At least 20 percent of the remaining annual appropriation supports evidence-based grants.",
                    "required",
                    ("20", None, "percent", "remaining annual appropriation"),
                ),
                (
                    evidence[2]["quote"],
                    "shall reserve 2 percent",
                    "Reserve Tribal funding",
                    "The Secretary reserves 2 percent of the total annual appropriation for grants to eligible Indian entities.",
                    "required",
                    ("2", None, "percent", "total annual appropriation"),
                ),
            ],
            "section 4",
            "At least 20 percent of the remaining annual appropriation supports evidence-based grants after the 2 percent Tribal reservation.",
        )
    first, second = evidence[1]["quote"].split(".\n", 1)
    return (
        [
            (
                second.split("Notification\n")[1],
                "until after notifying",
                "Notify next of kin",
                "The Secretary must notify Fernando V. Cota’s next of kin before disinterment.",
                "required",
                None,
            ),
            (
                first + ".",
                "shall disinter",
                "Disinter the remains",
                "The Secretary must disinter the remains within one year of enactment.",
                "required",
                None,
            ),
            (
                AMENDMENT,
                "inserting September 30, 2030",
                "Extend the deadline",
                "The amendment replaces September 30, 2025 with September 30, 2030.",
                "required",
                None,
            ),
        ],
        "subsection (a)",
        "The Secretary must disinter the remains within one year of enactment and only after notifying Fernando V. Cota’s next of kin.",
    )


class MeaningModel(RecordedModel):
    def __init__(self, rules, joint):
        super().__init__()
        self.rules, self.joint = rules, joint

    def _map(self, request):
        sources = request.source_snapshot
        records, policies, financial = [], [], []
        policy = dict.fromkeys(policy_passages(sources), "context")
        money = dict.fromkeys(money_candidates(sources), "not_financial")
        for source in sources:
            for passage in citation_passages(source):
                q = passage["quote_id"]
                if not q or q not in source.get("review_quote_ids", [q]):
                    continue
                key = source["source_ref"] + ":" + q
                claims = []
                for _, marker, title, text, modal, amount in self.rules:
                    if marker not in passage["text"]:
                        continue
                    claim = _claim(key)
                    claim.update(
                        actor="The Secretary",
                        action=text,
                        modality=modal,
                        money=[],
                        timing=[],
                        affected_people=[],
                    )
                    if "next of kin" in text:
                        claim["conditions"] = {
                            "operator": "leaf",
                            "text": "Prior notification of next of kin.",
                            "evidence_ids": [key],
                        }
                    if amount:
                        number, currency, measure, base = amount
                        claim["money"] = [
                            dict(
                                amount=number,
                                currency=currency,
                                measure=measure,
                                base=base,
                                purpose=title,
                                period="annual",
                                comparator="at least" if number == "20" else None,
                            )
                        ]
                        financial.append(
                            dict(
                                label=title,
                                text=text,
                                amount_display=text,
                                fiscal_years=[],
                                source_quotes=[_quote(key)],
                            )
                        )
                        money[key] = "financial"
                    claims.append(claim)
                    policies.append(
                        dict(title=title, text=text, source_quotes=[_quote(key)])
                    )
                    policy[key] = "explained"
                if source.get("factual_map"):
                    records.append(
                        dict(
                            record_id=key, claims=claims, definitions=[], references=[]
                        )
                    )
        return dict(
            factual_records=records,
            policy_checks=policy,
            money_checks=money,
            policy_changes=policies,
            additional_changes=[],
            financial_items=financial,
        )

    def _dependency(self, request):
        env = request.request_envelope
        packet = env["source_packet"]
        items = {
            k: copy.deepcopy(v["value"]) for k, v in packet["review_items"].items()
        }
        checks = {}
        for fact in packet["dependency_records"]:
            key = fact["record_id"]
            applies = any(c["action"] == self.rules[1][3] for c in fact["claims"])
            targets = [
                k
                for k, item in items.items()
                if applies and item.get("title") == self.rules[0][2]
            ]
            checks[key] = dict(
                status="applies" if targets else "not_applicable",
                item_ids=targets,
                reason=None if targets else "This rule does not govern this item.",
            )
            for k in targets:
                items[k]["text"] = self.joint
                if _quote(key) not in items[k]["source_quotes"]:
                    items[k]["source_quotes"].append(_quote(key))
        return dict(
            page_id=env["dependency_review"]["page_id"],
            items=items,
            record_checks=checks,
        )

    def _summary(self, request):
        citations = [
            {"source_ref": s["source_ref"], "quote_id": p["quote_id"]}
            for s in request.request_envelope["source_packet"]["sources"]
            for p in s["citation_passages"]
            if p["quote_id"] and any(r[1] in p["text"] for r in self.rules[:2])
        ]
        return dict(
            schema_version="1.4",
            explanations=[],
            summary=[dict(text=self.joint, source_quotes=citations)],
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("bill", ["119s4387is", "119hr9300ih", "119s1071eah"])
def test_pinned_terms_survive_map_reconciliation_and_publication(
    bill, tmp_path, enhancement_owner, enhancement_settings, monkeypatch
):
    from .test_large_bill_staged_flow import GRANT, MATCHING

    rules, link, joint = fixture(bill)
    primary = escape(rules[0][0]).replace(
        link, f'<internal-xref idref="requirements">{link}</internal-xref>'
    )
    raw = (
        _cross_section_source()
        .replace(GRANT.encode(), primary.encode())
        .replace(MATCHING.encode(), escape(rules[1][0]).encode())
    )
    if len(rules) > 2:
        raw = raw.replace(
            b"</legis-body>",
            f"<section><enum>3.</enum><text>{escape(rules[2][0])}</text></section></legis-body>".encode(),
        )
    model = MeaningModel(rules, joint)
    monkeypatch.setattr("apps.legislation.tasks.get_provider", lambda _: model)
    client = APIClient()
    client.force_authenticate(enhancement_owner)
    with (
        enhancement_settings,
        override_settings(
            STORAGES={
                "default": {
                    "BACKEND": "django.core.files.storage.FileSystemStorage",
                    "OPTIONS": {"location": tmp_path},
                }
            },
            LLM_READER_OWNED_TOKEN_TARGET=0,
            LLM_READER_MAX_CALLS=0,
            LLM_READER_CALLS_PER_DELIVERY=1000,
            LLM_SOURCE_FIRST_ENABLED=False,
        ),
    ):
        document = _stored_document(raw, tmp_path, number=bill)
        _valid_credential(enhancement_owner)
        attempt = _confirmation(client, document.bill)
        outcome = run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)
        attempt.refresh_from_db()
        assert outcome["status"] == "succeeded", attempt.failure_detail
        result = client.get(f"/api/bills/{document.bill_id}/enhancements/latest/").data[
            "active_reader"
        ]["result"]
        review = result["source_review"]
        saved_review = attempt.result_json["source_review"]
        claims = [c for rec in saved_review["factual_records"] for c in rec["claims"]]
        for _, _, _, action, modality, amount in rules:
            claim = next(c for c in claims if c["action"] == action)
            assert claim["modality"] == modality
            if amount:
                assert (
                    tuple(
                        claim["money"][0][k]
                        for k in ("amount", "currency", "measure", "base")
                    )
                    == amount
                )
        if bill == "119s1071eah":
            assert any(
                c["conditions"] and "notification" in c["conditions"]["text"]
                for c in claims
            )
            assert any(
                "2025 with September 30, 2030" in p["text"]
                for p in review["policy_changes"]
            )
        assert any(stage == "dependency" for stage, _, _ in model.calls)
        assert any(
            check["status"] == "applies"
            for page in saved_review["dependency_review"]["pages"]
            for check in page["response"]["record_checks"].values()
        )
        primary_item = next(
            p for p in saved_review["policy_drafts"] if p["title"] == rules[0][2]
        )
        assert any(joint in p["text"] for p in review["policy_changes"])
        assert primary_item["text"] == joint
        assert all(
            any(rule[1] in q["quote"] for q in primary_item["source_quotes"])
            for rule in rules[:2]
        )
        assert result["summary"][0]["text"] == joint
