import copy

import pytest
from jsonschema import Draft202012Validator, ValidationError

from apps.legislation.enhancements.reader_citations import citation_passages
from apps.legislation.enhancements.reader_discovery import (
    discovery_schema,
    discovery_sources,
    resolve_discovery,
    validate_source_review,
)
from apps.legislation.enhancements.reader_facts import (
    MAX_FACT_RECORD_BYTES,
    factual_evidence,
    factual_record_ids,
    factual_records_schema,
    resolve_factual_records,
)


def _sources(text, first_ref=1):
    return [
        {**source, "factual_map": True, "policy_review": True}
        for source in discovery_sources(text, first_ref)
    ]


def _claim(record_id, action="Publish the annual report.", **overrides):
    return {
        "actor": "The agency",
        "action": action,
        "modality": "required",
        "affected_people": ["The public"],
        "money": [],
        "timing": ["Annually"],
        "conditions": None,
        "exceptions": [],
        "evidence_ids": [record_id],
        **overrides,
    }


def _record(record_id, **overrides):
    return {
        "record_id": record_id,
        "claims": [_claim(record_id)],
        "definitions": [],
        "references": [],
        **overrides,
    }


def _output(sources):
    ids = factual_record_ids(sources)
    return {
        "financial_items": [],
        "additional_changes": [],
        "money_checks": {},
        "policy_changes": [
            {
                "title": "Publish reports",
                "text": "The agency must publish an annual report.",
                "source_quotes": [
                    {"source_ref": key.split(":")[0], "quote_id": key.split(":")[1]}
                ],
            }
            for key in ids
        ],
        "policy_checks": dict.fromkeys(ids, "explained"),
        "factual_records": [_record(key) for key in ids],
    }


def test_factual_map_is_required_only_for_staged_sources():
    sources = _sources("The agency shall publish an annual report.")
    output = _output(sources)
    Draft202012Validator.check_schema(discovery_schema(sources))
    resolve_discovery(output, sources)
    incomplete = {k: v for k, v in output.items() if k != "factual_records"}
    with pytest.raises(ValidationError):
        resolve_discovery(incomplete, sources)

    legacy = [{k: v for k, v in sources[0].items() if k != "factual_map"}]
    resolve_discovery(incomplete, legacy)
    with pytest.raises(ValidationError):
        resolve_discovery(output, legacy)


def test_structured_condition_tree_definition_and_references_survive_publication():
    sources = _sources(
        "The agency shall publish an annual report. A report means a public document. "
        "The report is due annually only if the program operates and either a project "
        "is active or a hearing is held, except during an emergency. See section 4."
    )
    output = _output(sources)
    key = factual_record_ids(sources)[0]

    def leaf(text):
        return {"operator": "leaf", "text": text, "evidence_ids": [key]}

    record = output["factual_records"][0]
    record["claims"][0].update(
        conditions={
            "operator": "all",
            "children": [
                leaf("The program operates."),
                {
                    "operator": "any",
                    "children": [
                        leaf("A project is active."),
                        leaf("A hearing is held."),
                    ],
                },
            ],
        },
        exceptions=[leaf("During an emergency.")],
    )
    record["definitions"] = [
        {
            "term": "report",
            "meaning": "a public document",
            "scope": None,
            "evidence_ids": [key],
        }
    ]
    record["references"] = [
        {
            "text": "See section 4.",
            "target": "section 4",
            "relation": "other",
            "evidence_ids": [key],
        }
    ]
    resolved = resolve_discovery(output, sources)
    assert resolved["factual_records"] == output["factual_records"]
    review = {**resolved, "reviewed_sources": [s["source_ref"] for s in sources]}
    validate_source_review(review, sources)
    assert (
        review["factual_records"][0]["claims"][0]["conditions"]
        == record["claims"][0]["conditions"]
    )
    assert factual_evidence(sources)[key]["quote"] == sources[0]["quoted_text"]


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "wrong_owner", "empty"])
def test_factual_map_cannot_skip_or_reassign_an_explained_passage(mutation):
    sources = _sources("The agency shall publish an annual report.")
    output = _output(sources)
    if mutation == "missing":
        output["factual_records"] = []
    elif mutation == "duplicate":
        output["factual_records"] *= 2
    elif mutation == "wrong_owner":
        output["factual_records"][0]["record_id"] = "src_9999:p0001"
    else:
        output["factual_records"][0]["claims"] = []
    with pytest.raises(ValidationError):
        resolve_discovery(output, sources)


def test_money_cannot_exist_only_in_lossy_prose_when_a_factual_map_is_required():
    sources = _sources("The Secretary may award a grant of $100 to eligible hospitals.")
    key = factual_record_ids(sources)[0]
    output = _output(sources)
    quote = {"source_ref": sources[0]["source_ref"], "quote_id": key.split(":")[1]}
    output["financial_items"] = [
        {
            "label": "Hospital grants",
            "amount_display": "$100",
            "text": "The Secretary may award a $100 grant to eligible hospitals.",
            "fiscal_years": [],
            "source_quotes": [quote],
        }
    ]
    output["policy_changes"][0]["text"] = output["financial_items"][0]["text"]
    output["money_checks"] = {key: "financial"}
    claim = _claim(key, "Award a grant to eligible hospitals.", modality="permitted")
    output["factual_records"][0]["claims"] = [claim]
    with pytest.raises(ValidationError):
        resolve_discovery(output, sources)
    claim["money"] = [
        {
            "amount": "100",
            "currency": "USD",
            "measure": "dollars",
            "comparator": None,
            "purpose": "Hospital grants",
            "period": None,
            "base": None,
        }
    ]
    resolved = resolve_discovery(output, sources)
    assert resolved["factual_records"][0]["claims"][0]["modality"] == "permitted"
    claim["money"][0]["amount"] = "200"
    with pytest.raises(ValidationError) as caught:
        resolve_discovery(output, sources)
    assert caught.value.validator == "reader_amount_conflict"


def test_fact_context_keeps_original_ids_and_rejects_unsupplied_quotes():
    owner = _sources("The agency shall publish a report subject to section 2.")[0]
    context = _sources(
        "First administrative provision. "
        + "Other administrative details. " * 27
        + "\nThe report is required only while the program operates.",
        first_ref=2,
    )[0]
    passages = [p for p in citation_passages(context) if p["quote_id"]]
    assert len(passages) == 2
    supplied = passages[-1]["quote_id"]
    context.update(review_quote_ids=[], allowed_quote_ids=[supplied])
    sources = [owner, context]
    output = _output(sources)
    own = factual_record_ids(sources)[0]
    dependency = f"{context['source_ref']}:{supplied}"
    output["factual_records"][0]["claims"][0]["conditions"] = {
        "operator": "leaf",
        "text": "While the program operates.",
        "evidence_ids": [dependency],
    }
    resolved = resolve_discovery(output, sources)
    assert factual_record_ids(sources) == [own]
    assert resolved["factual_records"][0]["claims"][0]["conditions"][
        "evidence_ids"
    ] == [dependency]
    assert factual_evidence(sources)[dependency]["quote"] == passages[-1]["text"]
    hidden = f"{context['source_ref']}:{passages[0]['quote_id']}"
    assert hidden not in factual_evidence(sources)
    output["factual_records"][0]["claims"][0]["conditions"]["evidence_ids"] = [hidden]
    with pytest.raises(ValidationError):
        resolve_discovery(output, sources)


def test_factual_row_capacity_is_enforced_without_truncation():
    sources = _sources("The agency shall publish an annual report.")
    key = factual_record_ids(sources)[0]
    records = [_record(key)]
    records[0]["definitions"] = [
        {
            "term": str(i),
            "meaning": "meaning " * 740,
            "scope": None,
            "evidence_ids": [key],
        }
        for i in range(3)
    ]
    Draft202012Validator(factual_records_schema(sources)).validate(records)
    from apps.legislation.enhancements.source_packet import canonical_json_bytes

    assert len(canonical_json_bytes(records[0])) > MAX_FACT_RECORD_BYTES
    original = copy.deepcopy(records)
    with pytest.raises(ValidationError) as caught:
        resolve_factual_records(records, sources)
    assert caught.value.validator == "maxLength"
    assert records == original


def test_partial_recovery_keeps_typed_context_and_links_shared_conditions():
    from apps.legislation.enhancements.reader_partial import validated_components

    owner = _sources(
        "The agency shall publish an annual report. "
        + "Report content. " * 45
        + "\nThe agency shall publish a public registry. "
        + "Registry content. " * 20
    )[0]
    context = _sources(
        "Both duties apply only while the program operates.", first_ref=2
    )[0]
    context["review_quote_ids"] = []
    sources = [owner, context]
    keys = factual_record_ids(sources)
    assert len(keys) == 2
    output = _output(sources)
    output["policy_changes"][1]["text"] = "unfinished"
    condition = {
        "operator": "leaf",
        "text": "While the program operates.",
        "evidence_ids": [f"{context['source_ref']}:p0001"],
    }
    output["factual_records"][0]["claims"][0]["conditions"] = condition
    valid, pending = validated_components(output, sources)
    assert pending == [keys[1].split(":")[1]]
    assert len(valid) == 1
    assert valid[0][1]["factual_records"] == [output["factual_records"][0]]
    assert valid[0][1]["factual_records"][0]["claims"][0]["conditions"] == condition
    # Linking to another owned passage means its failed record cannot be dropped.
    output["factual_records"][0]["claims"][0]["conditions"]["evidence_ids"].append(
        keys[1]
    )
    valid, pending = validated_components(output, sources)
    assert valid == []
    assert pending == [key.split(":")[1] for key in keys]


def test_output_splitting_retains_factual_assignments_and_context():
    from apps.legislation.enhancements.reader_sizing import (
        _SizingRequest,
        select_review_units,
        source_output_allowance,
    )

    source = _sources(
        "\n".join(
            f"The agency shall publish report {i}. " + f"Report {i} content. " * 40
            for i in range(6)
        )
    )[0]
    ids = factual_record_ids([source])
    assert len(ids) > 2
    request = _SizingRequest(
        [source],
        {
            "source_review": True,
            "instructions": "",
            "source_packet": {
                "sources": [
                    {
                        "source_ref": source["source_ref"],
                        "citation_passages": citation_passages(source),
                    }
                ]
            },
        },
    )
    selected = select_review_units(request, [ids[0].split(":")[1]])
    assert factual_record_ids(selected.source_snapshot) == ids[:1]
    assert selected.source_snapshot[0]["quoted_text"] == source["quoted_text"]
    assert (
        selected.request_envelope["output_schema"]["properties"]["factual_records"][
            "minItems"
        ]
        == 1
    )
    assert source_output_allowance(selected.source_snapshot) < source_output_allowance(
        [source]
    )


def test_reconciliation_metadata_is_rejected_on_legacy_review():
    sources = _sources("The agency shall publish an annual report.")
    output = _output(sources)
    resolved = resolve_discovery(output, sources)
    review = {**resolved, "reviewed_sources": [sources[0]["source_ref"]]}
    review.pop("factual_records")
    review["dependency_review"] = {"version": 1, "pages": []}
    sources[0].pop("factual_map")
    with pytest.raises(ValidationError):
        validate_source_review(review, sources)


@pytest.mark.django_db
def test_repeated_eligibility_passages_remain_citable_in_a_staged_plan(
    source_bill, enhancement_settings
):
    from collections import Counter

    from django.test import override_settings

    from apps.legislation.enhancements.reader_batches import build_reader_preflight
    from apps.legislation.enhancements.reader_capacity import fits
    from apps.legislation.tests.test_reader_enhancement_pipeline import install_reader

    eligibility = "Eligibility requires the applicant to be a public hospital."
    unit = eligibility + "\n" + "Administrative background. " * 27
    unit = unit[:790].ljust(799) + "\n"
    dependency = unit * 20 + "The final administrative heading ends here."
    original_passages = citation_passages({"quoted_text": dependency})
    assert any(
        p["quote_id"] is None and eligibility in p["text"] for p in original_passages
    )
    grant = (
        "SEC. 1. Hospital support\nThe agency may support applicants "
        "subject to section 2 of this Act.\n"
    )
    text = grant + dependency
    document = source_bill.documents.get()
    document.extracted_text = text
    document.save()
    install_reader(source_bill, count=0)
    sections = (
        ("support", 0, len(grant), "1", "Hospital support"),
        ("conditions", len(grant), len(text), "2", "Eligibility"),
    )
    with (
        enhancement_settings,
        override_settings(
            LLM_ENHANCEMENT_MAX_REQUEST_BYTES=22000,
            LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS=22000,
            LLM_READER_MAX_CALLS=0,
        ),
    ):
        plan = build_reader_preflight(
            document, xml_sections=sections, reuse_publication=False
        )
        assert all(fits(batch.request_envelope) for batch in plan.reader_batches)
    sources = [s for s in plan.source_snapshot if s.get("discovery_source")]
    assert "".join(s["quoted_text"] for s in sources) == text
    assert [s["start_char"] for s in sources] == [
        0,
        *[s["end_char"] for s in sources[:-1]],
    ]
    assert sources[-1]["end_char"] == len(text)
    assert len({s["source_ref"] for s in sources}) == len(sources)
    assert all(
        p["quote_id"] or not p["text"].strip()
        for source in sources
        for p in citation_passages(source)
    )
    owner = sources[0]
    assert owner.get("deferred_context_source_refs")
    evidence = factual_evidence(sources)
    deferred = {
        f"{ref}:{quote_id}"
        for ref, ids in owner["deferred_context_quote_ids"].items()
        for quote_id in ids
    }
    assert sum(eligibility in evidence[key]["quote"] for key in deferred) == 20
    mapped = Counter(
        key
        for batch in plan.reader_batches
        if batch.request_envelope.get("source_review")
        for key in factual_record_ids(batch.source_snapshot)
    )
    assert deferred <= set(mapped)
    assert all(count == 1 for count in mapped.values())
