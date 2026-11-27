from hashlib import sha256
from unittest.mock import Mock

import pytest
from rest_framework.test import APIClient

from apps.legislation.enhancements import provision_pipeline
from apps.legislation.enhancements.shared import validation_key
from apps.legislation.enhancements.source_graph import build_source_graph
from apps.legislation.models import (
    Bill,
    BillDocument,
    BillEnhancement,
    BillProcessingCache,
)

from .test_source_first_schema import explanation


@pytest.mark.django_db
@pytest.mark.parametrize(
    "missing,corruption",
    [
        (0, None),
        (1, None),
        (33, None),
        (1, "summary"),
        (33, "evidence"),
        (33, "coverage"),
        (1, "unresolved"),
        (1, "synopsis"),
        (0, "authority"),
        (1, "completeness"),
    ],
)
def test_saved_reader_validates_its_publication_without_planning_missing_work(
    missing, corruption, enhancement_owner, monkeypatch
):
    text = "SEC. 1. PAYMENT\nThe Secretary shall pay $100." + "".join(
        f"\nSEC. {i}. REVIEW\n" + "The agency may review the application. " * 40
        for i in range(2, missing + 2)
    )
    bill = Bill.objects.create(
        jurisdiction="federal",
        session=119,
        bill_number="S 1125",
        title="Payment",
        status="introduced",
    )
    document = BillDocument.objects.create(
        bill=bill, version_label="IH", extracted_text=text
    )
    graph = build_source_graph(str(document.pk), document.version_label, text)
    plan = provision_pipeline.plan_analysis(graph, {"per_call_input": 12000})

    def invoke(call):
        if call.stage == "synopsis":
            return {
                "text": "The Secretary must pay $100.",
                "explanation_ids": [graph.units[0].id],
            }
        return {"provisions": [explanation(graph, 0)]}

    result = provision_pipeline.run_analysis(plan, invoke, lambda *args: None)
    assert result.completeness == ("partial" if missing else "complete")
    output = result.output
    assert [r["unresolved_reason"] for r in output["provisions"][1:]] == [
        "input_limit"
    ] * missing
    saved = BillEnhancement.objects.create(
        user=enhancement_owner,
        bill=bill,
        status="succeeded",
        result_json=output,
        result_completeness=result.completeness,
        output_schema_version=output["schema_version"],
        source_fingerprint=graph.document_fingerprint,
        source_manifest_json={
            "document_id": document.pk,
            "document_version_label": "IH",
            "source_kind": "pinned_passages",
        },
    )
    client = APIClient()
    client.force_authenticate(enhancement_owner)
    url = f"/api/bills/{bill.pk}/enhancements/{saved.pk}/"
    # An older projection cached the wrong decision for a valid partial.
    if missing == 1 and not corruption:
        old = sha256(
            f"bill-validation:projection-16:{saved.source_fingerprint}:{saved.output_schema_version}:2:{saved.validation_digest}".encode()
        ).hexdigest()
        BillProcessingCache.objects.create(
            pk=old, kind="reader-validation", result_json={"valid": False}
        )
    if corruption:
        if corruption == "authority":
            output["provisions"][0][
                "summary"
            ] = "The Secretary may keep the $100 for grants."
            output["synopsis"]["text"] = output["provisions"][0]["summary"]
            # A prior validator might have accepted this result. Neither an
            # old boolean receipt nor its preview is public evidence.
        elif corruption == "summary":
            output["provisions"][0]["summary"] = "The Secretary must pay $999."
        elif corruption == "evidence":
            output["provisions"][0]["evidence"][0]["text"] = "Different source."
        elif corruption == "coverage":
            output["coverage"]["unresolved_unit_ids"].pop()
        elif corruption == "unresolved":
            output["provisions"][-1]["unresolved_reason"] = ""
        elif corruption == "synopsis":
            output["synopsis"]["text"] = "The Secretary must pay $999."
        elif corruption == "completeness":
            assert client.get(url).data["result"]["coverage"] == output["coverage"]
            saved.result_completeness = "complete"
        saved.result_json = output
        saved.save()
        saved.refresh_from_db()
        if corruption == "authority":
            old_key = sha256(
                f"bill-validation:projection-17:{saved.source_fingerprint}:{saved.output_schema_version}:2:{saved.validation_digest}:{saved.result_completeness}".encode()
            ).hexdigest()
            BillProcessingCache.objects.create(
                pk=old_key, kind="reader-validation", result_json={"valid": True}
            )

    planner = Mock(wraps=provision_pipeline._plan_built_graph)
    prepare = Mock(wraps=provision_pipeline._call)
    monkeypatch.setattr(provision_pipeline, "_plan_built_graph", planner)
    monkeypatch.setattr(provision_pipeline, "_call", prepare)
    response = client.get(url)
    assert response.status_code == 200
    public = response.data["result"]
    if corruption and corruption != "authority":
        assert public is None
    else:
        assert public["coverage"] == output["coverage"]
        assert public["provisions"][1:] == output["provisions"][1:]
        expected = "SEC. 1. PAYMENT\nThe Secretary shall pay $100."
        assert public["provisions"][0]["summary"] == expected
        assert public["provisions"][0]["claims"][0]["funding_text"] == expected
        assert public["synopsis"]["text"] == expected
    receipt = BillProcessingCache.objects.get(pk=validation_key(saved)).result_json
    assert receipt["valid"] is (public is not None)
    assert receipt["preview"] == (public["synopsis"]["text"] if public else "")
    if corruption == "authority":
        from apps.accounts.dashboard_bill_cards import add_card_summaries
        from apps.legislation.enhancements.shared import source_first_reuse

        # Reuse the private checkpoint without a provider call. The same public
        # projection also supplies the warm card receipt, and a repeated read.
        assert (
            source_first_reuse(saved)["provisions"][0]["unit_id"] == graph.units[0].id
        )
        assert client.get(url).data["result"] == public
        row = {"bill": {"id": bill.pk}}
        add_card_summaries([row])
        assert row["bill"]["card_summary"] == " ".join(expected.split())
    planner.assert_not_called()
    prepare.assert_not_called()
