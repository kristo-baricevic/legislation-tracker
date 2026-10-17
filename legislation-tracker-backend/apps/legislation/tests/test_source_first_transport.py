import copy
import json

import pytest
from jsonschema import Draft202012Validator, ValidationError

from apps.legislation.enhancements.source_first_transport import prepare_transport


def payload():
    return {
        "document_fingerprint": "document-hash",
        "units": [
            {
                "id": "unit-hash",
                "own_passage_ids": ["passage-hash"],
                "context_passage_ids": [],
                "parent_id": None,
                "condition_group_id": "unit-hash",
            }
        ],
        "passages": {
            "passage-hash": {
                "id": "passage-hash",
                "text": "exact text",
                "text_sha256": "text-hash",
                "start": 0,
                "end": 10,
            }
        },
        "findings": {"unit-hash": "condition_scope_unverified"},
    }


def output():
    return {
        "provisions": [
            {
                "unit_id": "u1",
                "status": "explained",
                "summary": "A rule.",
                "details": [],
                "unresolved_reason": None,
                "claims": [
                    {
                        "actor": None,
                        "action": "apply",
                        "modality": "required",
                        "money": [],
                        "conditions": {
                            "operator": "leaf",
                            "text": "exact text",
                            "evidence_ids": ["p1"],
                        },
                        "exceptions": [],
                        "evidence_ids": ["p1"],
                    }
                ],
            }
        ]
    }


@pytest.mark.parametrize("stage", ["generation", "repair"])
def test_short_refs_constrained_and_exactly_restored(stage):
    original = payload()
    before = copy.deepcopy(original)
    wire = prepare_transport(stage, original)
    assert original == before
    assert "hash" not in json.dumps(wire.payload)
    assert wire.payload["units"][0]["own_passage_ids"] == ["p1"]
    assert wire.payload["passages"]["p1"]["text"] == "exact text"
    assert wire.payload["findings"] == {"u1": "condition_scope_unverified"}
    decoded = wire.decode(output())
    assert decoded["provisions"][0]["unit_id"] == "unit-hash"
    claim = decoded["provisions"][0]["claims"][0]
    assert claim["evidence_ids"] == ["passage-hash"]
    assert claim["conditions"]["evidence_ids"] == ["passage-hash"]
    assert claim["conditions"]["text"] == "exact text"
    with pytest.raises(ValidationError):
        wire.decode({"provisions": []})


@pytest.mark.parametrize("ref", ["p2", "P1", "passage-hash", "p1 "])
def test_unknown_refs_are_not_fuzzily_repaired(ref):
    wire = prepare_transport("generation", payload())
    response = output()
    response["provisions"][0]["claims"][0]["evidence_ids"] = [ref]
    assert not Draft202012Validator(wire.schema).is_valid(response)
    with pytest.raises(ValidationError):
        wire.decode(response)


def test_duplicate_refs_still_rejected_locally():
    wire = prepare_transport("generation", payload())
    response = output()
    response["provisions"][0]["claims"][0]["evidence_ids"] = ["p1", "p1"]
    with pytest.raises(ValidationError):
        wire.decode(response)


def test_synopsis_refs_are_also_short_and_constrained():
    wire = prepare_transport(
        "synopsis",
        {
            "explanations": [
                {"unit_id": "unit-hash", "summary": "A rule.", "claims": []}
            ]
        },
    )
    assert wire.payload["explanations"][0]["unit_id"] == "u1"
    assert wire.decode({"text": "A rule.", "explanation_ids": ["u1"]}) == {
        "text": "A rule.",
        "explanation_ids": ["unit-hash"],
    }
    with pytest.raises(ValidationError):
        wire.decode({"text": "A rule.", "explanation_ids": ["u2"]})


def test_shared_condition_checklist_is_sent_once_not_once_per_unit():
    source = payload()
    source["units"][0]["required_conditions"] = [
        {"text": "only if enrolled", "evidence_ids": ["passage-hash"]}
    ]
    second = copy.deepcopy(source["units"][0])
    second["id"] = "second-unit"
    source["units"].append(second)
    wire = prepare_transport("generation", source)
    assert json.dumps(wire.payload).count("only if enrolled") == 1
    assert (
        wire.payload["units"][0]["required_condition_ids"]
        == wire.payload["units"][1]["required_condition_ids"]
    )


def test_all_pinned_bills_fit_existing_call_and_token_ceilings():
    from apps.legislation.enhancements.provision_pipeline import plan_analysis
    from apps.legislation.enhancements.source_graph import build_source_graph
    from apps.legislation.evaluation.whole_bill import load_cases

    for case in load_cases():
        plan = plan_analysis(build_source_graph(case["id"], case["id"], case["text"]))
        assert plan.maximum_calls <= 6
        assert plan.maximum_input <= 600000
        assert plan.maximum_output <= 48000


def test_condition_reference_expands_to_exact_server_source_without_model_copying():
    source = payload()
    source["units"][0]["required_conditions"] = [
        {"text": "only if enrolled and employed.", "evidence_ids": ["passage-hash"]}
    ]
    wire = prepare_transport("generation", source)
    response = output()
    response["provisions"][0]["claims"][0]["conditions"] = {
        "operator": "source",
        "condition_id": "c1",
    }
    decoded = wire.decode(response)
    assert decoded["provisions"][0]["claims"][0]["conditions"] == {
        "operator": "leaf",
        "text": "only if enrolled and employed.",
        "evidence_ids": ["passage-hash"],
    }
    response["provisions"][0]["claims"][0]["conditions"]["condition_id"] = "c2"
    with pytest.raises(ValidationError):
        wire.decode(response)
