import copy
from contextlib import nullcontext

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


@pytest.mark.parametrize(
    "mandatory,source_is_authorization", [(True, True), (False, True), (True, False)]
)
def test_s4387_authorization_is_not_a_mandatory_typed_outlay(
    mandatory, source_is_authorization
):
    import json
    from pathlib import Path

    pinned = json.loads(
        (Path(__file__).parent / "fixtures/harness/119s4387is.json").read_text()
    )
    quote = pinned["evidence"][0]["quote"]
    if not source_is_authorization:
        quote = quote.replace("authorized to be appropriated", "appropriated")
    sources = _sources(quote)
    (key,) = factual_record_ids(sources)
    output = _output(sources)
    claim = _claim(
        key,
        "Spend the grant funding." if mandatory else "Authorize appropriations.",
        modality="required" if mandatory else "permitted",
    )
    claim["money"] = [
        dict(
            amount="15000000",
            currency="USD",
            measure="dollars",
            comparator=None,
            purpose="grant funding",
            period="each of fiscal years 2027 through 2029",
            base=None,
        )
    ]
    output["factual_records"][0]["claims"] = [claim]
    policy = output["policy_changes"][0]
    policy["text"] = quote
    output["money_checks"][key] = "financial"
    output["financial_items"] = [
        dict(
            label="Grant funding",
            amount_display="$15 million annually",
            fiscal_years=[],
            text=quote,
            source_quotes=policy["source_quotes"],
        )
    ]
    if mandatory and source_is_authorization:
        with pytest.raises(ValidationError) as failure:
            resolve_discovery(output, sources)
        assert failure.value.validator == "reader_amount_conflict"
        return
    resolved = resolve_discovery(output, sources)
    validate_source_review(
        {**resolved, "reviewed_sources": [sources[0]["source_ref"]]}, sources
    )
    assert resolved["factual_records"][0]["claims"][0] == claim


@pytest.mark.parametrize(
    "source_index,number,basis,wrong",
    [(2, "2", "total", "remaining"), (3, "20", "remaining", "total")],
)
def test_hr9300_reservations_cannot_swap_percentage_bases(
    source_index, number, basis, wrong
):
    import json
    from pathlib import Path

    from apps.legislation.enhancements.reader_integrity import validate_numbers

    quote = json.loads(
        (Path(__file__).parent / "fixtures/harness/119hr9300ih.json").read_text()
    )["evidence"][source_index]["quote"]
    sources = _sources(quote)
    (key,) = factual_record_ids(sources)
    claim = _claim(
        key,
        "Reserve funding.",
        money=[
            dict(
                amount=number,
                currency=None,
                measure="percent",
                purpose="grant funding",
                period="annual",
                comparator=None,
                base=basis + " annual appropriation",
            )
        ],
    )
    resolve_factual_records([_record(key, claims=[claim])], sources)
    claim["money"][0]["base"] = wrong + " annual appropriation"
    with pytest.raises(ValidationError) as failure:
        resolve_factual_records([_record(key, claims=[claim])], sources)
    assert failure.value.validator == "reader_amount_conflict"
    with pytest.raises(ValidationError) as failure:
        validate_numbers(
            {
                "text": f"Reserve {number} percent of the {wrong} annual appropriation.",
                "source_quotes": [{"quote": quote}],
            },
            path=["summary"],
        )
    assert failure.value.validator == "reader_amount_conflict"


@pytest.mark.parametrize(
    "reverse", [False, True], ids=["total-first", "remaining-first"]
)
@pytest.mark.parametrize("validator", ["typed", "prose"])
@pytest.mark.parametrize(
    "number,basis,supported",
    [
        ("2", "total", True),
        ("20", "remaining", True),
        ("2", "remaining", False),
        ("20", "total", False),
    ],
)
@pytest.mark.parametrize(
    "noun", ["appropriation", "funds", "amount", "amounts", "sums"]
)
def test_two_percentages_bind_to_their_own_appropriation(
    reverse, validator, number, basis, supported, noun
):
    from apps.legislation.enhancements.reader_integrity import validate_numbers

    clauses = [
        "2 percent of the total appropriation for Tribal grants",
        "20 percent of the remaining appropriation for implementation",
    ]
    source = (
        "The Secretary shall reserve "
        + " and ".join(reversed(clauses) if reverse else clauses)
        + "."
    )
    base = f"the {basis} {noun}"
    with nullcontext() if supported else pytest.raises(ValidationError) as error:
        if validator == "typed":
            sources = _sources(source)
            (key,) = factual_record_ids(sources)
            money = dict(
                amount=number,
                measure="percent",
                currency=None,
                base=base,
                purpose=None,
                period=None,
                comparator=None,
            )
            claim = _claim(key, "Reserve funding.", money=[money])
            resolve_factual_records([_record(key, claims=[claim])], sources)
        else:
            validate_numbers(
                {
                    "text": f"Reserve {number}% of {base}.",
                    "source_quotes": [{"quote": source}],
                },
                path=["summary"],
            )
    if not supported:
        assert error.value.validator == "reader_amount_conflict"


@pytest.mark.parametrize(
    "source,expected",
    [
        (
            "From the total appropriation for the remaining counties, reserve 2% for grants "
            "and 20% of the remaining appropriation for administration.",
            [("2", "total"), ("20", "remaining")],
        ),
        (
            "2% of total enrollment is eligible and 20% of the remaining appropriation is reserved.",
            [("20", "remaining")],
        ),
        (
            "Of the total amount appropriated and not reserved under section 4, use 20.5% "
            "for grants and 2% of total receipts for administration.",
            [("20.5", "remaining")],
        ),
        (
            "Reserve 2% of total funds raised via donations and 20% of the remaining funds.",
            [("20", "remaining")],
        ),
        (
            "Reserve 2% of the total and 20% of the remainder.",
            [("2", "total"), ("20", "remaining")],
        ),
    ],
)
def test_percentage_bases_follow_the_account_across_legal_word_orders(source, expected):
    from apps.legislation.enhancements.percentage_bases import percentage_bases

    assert [(str(rate), base) for rate, base in percentage_bases(source)] == expected


def test_prose_basis_from_one_reader_field_does_not_qualify_another_field():
    from apps.legislation.enhancements.reader_integrity import validate_numbers

    validate_numbers(
        {
            "text": "From the total appropriation, reserve 2% for grants",
            "amount_display": "20%",
            "source_quotes": [
                {
                    "quote": "Reserve 2% of the total appropriation for grants and 20% of the remaining appropriation for implementation."
                }
            ],
        },
        path=["financial_items"],
    )


@pytest.mark.parametrize("reverse_source", [False, True])
@pytest.mark.parametrize("amount,valid", [("2000000", True), ("15000000", False)])
def test_mixed_authority_is_amount_scoped_in_typed_claims(
    reverse_source, amount, valid
):
    parts = [
        "there are authorized to be appropriated $15 million for grants",
        "the Secretary shall allocate $2 million for training",
    ]
    sources = _sources(" and ".join(parts[::-1] if reverse_source else parts) + ".")
    (key,) = factual_record_ids(sources)
    claim = _claim(
        key,
        "Disburse funds.",
        money=[
            dict(
                amount=amount,
                currency="USD",
                measure="dollars",
                base=None,
                purpose=None,
                period=None,
                comparator=None,
            )
        ],
    )
    with nullcontext() if valid else pytest.raises(ValidationError) as error:
        resolve_factual_records([_record(key, claims=[claim])], sources)
    if not valid:
        assert error.value.validator == "reader_amount_conflict"


def _validate_cited_money(quote, statement, *, typed, amount, basis=None):
    from apps.legislation.enhancements.reader_integrity import validate_numbers

    if not typed:
        validate_numbers(
            {"text": statement, "source_quotes": [{"quote": quote}]}, path=["summary"]
        )
        return
    sources = _sources(quote)
    (key,) = factual_record_ids(sources)
    claim = _claim(
        key,
        "Reserve funding." if basis else statement,
        money=[
            dict(
                amount=amount,
                currency=None if basis else "USD",
                measure="percent" if basis else "dollars",
                base=basis,
                comparator=None,
                purpose=None,
                period=None,
            )
        ],
    )
    resolve_factual_records([_record(key, claims=[claim])], sources)


@pytest.mark.parametrize("typed", [False, True], ids=["prose", "mapped-claim"])
@pytest.mark.parametrize(
    "quote,amount,statement,valid",
    [
        (
            "There are authorized to be appropriated $15 million for grants. The Secretary shall allocate $2 million for training and the cost estimate is $15 million.",
            "15000000",
            "The Secretary must spend $15 million for training.",
            False,
        ),
        (
            "There are authorized to be appropriated $15 million for grants. The Secretary shall allocate $2 million for training; the cost estimate is $15 million.",
            "15000000",
            "The Secretary must spend $15 million for training.",
            False,
        ),
        (
            "There are authorized to be appropriated $15 million for grants. The cost estimate is $15 million and the Secretary shall allocate $2 million for training.",
            "15000000",
            "The Secretary must spend $15 million for training.",
            False,
        ),
        (
            "The Secretary shall allocate $2 million of the amounts that are authorized to be appropriated under section 3.",
            "2000000",
            None,
            True,
        ),
        (
            "The Secretary shall allocate $2 million of the $15 million that is authorized to be appropriated under section 3.",
            "2000000",
            None,
            True,
        ),
        (
            "The Secretary shall allocate $2 million of the $15 million that is authorized to be appropriated under section 3.",
            "15000000",
            "The Secretary must allocate $15 million.",
            False,
        ),
        (
            "There are authorized to be appropriated $15 million for grants. The Secretary shall allocate $2 million for hospitals and $15 million for training.",
            "15000000",
            "The Secretary must allocate $15 million for training.",
            True,
        ),
        (
            "There are authorized to be appropriated $2 million for hospital grants. The estimated cost of training is also $2 million.",
            "2000000",
            "The Secretary shall allocate $2 million for hospital grants.",
            False,
        ),
        (
            "The estimated cost of training is $2 million. There are authorized to be appropriated $2 million for grants.",
            "2000000",
            "The Secretary shall allocate $2 million for hospital grants.",
            False,
        ),
        (
            "Congress authorizes $15 million to be appropriated for general use and the Secretary shall allocate $2 million for grants.",
            "15000000",
            "The Secretary must spend $15 million for grants.",
            False,
        ),
        (
            "The Secretary shall allocate $2 million of the amounts authorized to be appropriated under section 3 for hospital grants.",
            "2000000",
            None,
            True,
        ),
        (
            "From funds authorized to be appropriated under section 3, the Secretary shall allocate $2 million for hospital grants.",
            "2000000",
            None,
            True,
        ),
        (
            "The Secretary shall allocate $2 million of the $15 million authorized to be appropriated under section 3.",
            "2000000",
            None,
            True,
        ),
        (
            "The Secretary shall allocate $2 million of the $15 million authorized to be appropriated under section 3.",
            "15000000",
            "The Secretary must allocate $15 million.",
            False,
        ),
        (
            "The $2 million authorized to be appropriated under section 3 shall be allocated for grants.",
            "2000000",
            None,
            True,
        ),
        (
            "The Secretary shall allocate $2 million of the amounts authorized to be appropriated under section 3 and Congress authorizes $15 million to be appropriated for general use.",
            "2000000",
            "The Secretary must spend $2 million for grants.",
            True,
        ),
        (
            "There are authorized to be appropriated $2 million for hospital grants.",
            "2000000",
            "The Secretary must allocate $2 million.",
            False,
        ),
        (
            "Of the $15 million authorized to be appropriated under section 3, $2 million shall be allocated for grants.",
            "2000000",
            None,
            True,
        ),
    ],
)
def test_allocation_from_authorized_funds(typed, quote, amount, statement, valid):
    with nullcontext() if valid else pytest.raises(ValidationError) as error:
        _validate_cited_money(quote, statement or quote, typed=typed, amount=amount)
    if not valid:
        assert error.value.validator == "reader_amount_conflict"


@pytest.mark.parametrize("typed", [False, True], ids=["prose", "mapped-claim"])
@pytest.mark.parametrize(
    "account_first", [False, True], ids=["rate-first", "account-first"]
)
@pytest.mark.parametrize("base", ["remaining", "total"])
def test_hr9300_post_reservation_scope_in_either_word_order(typed, account_first, base):
    import json
    from pathlib import Path

    pinned = json.loads(
        (Path(__file__).parent / "fixtures/harness/119hr9300ih.json").read_text()
    )["evidence"][3]["quote"]
    account, action = pinned.split("From ", 1)[1].split(", the Secretary shall ", 1)
    if account_first:
        quote = pinned
    else:
        rate, purpose = action.split(" to award ", 1)
        quote = f"The Secretary shall {rate} of {account} to award {purpose}"
    valid = base == "remaining"
    with nullcontext() if valid else pytest.raises(ValidationError) as error:
        _validate_cited_money(
            quote,
            f"Reserve at least 20% of the {base} appropriation.",
            typed=typed,
            amount="20",
            basis=base + " appropriation",
        )
    if not valid:
        assert error.value.validator == "reader_amount_conflict"


@pytest.mark.parametrize(
    "quote,expected",
    [
        (
            "Reserve 2% of the total amount appropriated for a fiscal year for rural grants "
            "and 20% of the total amount appropriated for that fiscal year and not reserved under section 4.",
            [("2", "total"), ("20", "remaining")],
        ),
        (
            "Reserve 2% of the total appropriation for grants that are not reserved for veterans.",
            [("2", "total")],
        ),
        (
            "Reserve 2% of the total appropriation. Funds not reserved under section 4 support training.",
            [("2", "total")],
        ),
    ],
)
def test_post_reservation_modifier_stays_with_its_account(quote, expected):
    from apps.legislation.enhancements.percentage_bases import percentage_bases

    assert [(str(rate), base) for rate, base in percentage_bases(quote)] == expected


@pytest.mark.parametrize(
    "evidence,action,purpose,condition,valid",
    [
        (
            "There is authorized to be appropriated $100 for grants. There is appropriated $100 for salaries.",
            "Spend funds.",
            "grants",
            None,
            False,
        ),
        (
            "There is authorized to be appropriated $100 for grants. There is appropriated $100 for salaries.",
            "Spend funds.",
            "salaries",
            None,
            True,
        ),
        (
            "The Secretary shall spend $100 for grants only if Congress appropriates $100.",
            "Spend funds.",
            "grants",
            None,
            False,
        ),
        (
            "The Secretary shall spend $100 for grants only if Congress appropriates $100.",
            "The Secretary shall spend $100 for grants.",
            "grants",
            "only if Congress appropriates $100",
            True,
        ),
    ],
)
def test_typed_funding_decision_retains_purpose_and_condition(
    evidence, action, purpose, condition, valid
):
    sources = _sources(evidence)
    (key,) = factual_record_ids(sources)
    money = dict(
        amount="100",
        currency="USD",
        measure="dollars",
        comparator=None,
        base=None,
        period=None,
        purpose=purpose,
    )
    leaf = (
        {"operator": "leaf", "text": condition, "evidence_ids": [key]}
        if condition
        else None
    )
    claim = _claim(key, action, conditions=leaf, money=[money])
    with nullcontext() if valid else pytest.raises(ValidationError) as error:
        resolve_factual_records([_record(key, claims=[claim])], sources)
    if not valid:
        assert error.value.validator == "reader_amount_conflict"


@pytest.mark.parametrize(
    "operator,empty", [("all", False), ("any", False), ("all", True)]
)
def test_typed_funding_decision_requires_condition_in_every_alternative(
    operator, empty
):
    condition = "only if Congress appropriates $100"
    sources = _sources(
        "The Secretary shall spend $100 for grants "
        + condition
        + ". The agency publishes a report."
    )
    (key,) = factual_record_ids(sources)
    children = [
        {"operator": "leaf", "text": text, "evidence_ids": [key]}
        for text in (condition, "The agency publishes a report.")
    ]
    tree = {"operator": operator, "children": [] if empty else children}
    money = dict(
        amount="100",
        currency="USD",
        measure="dollars",
        comparator=None,
        base=None,
        period=None,
        purpose="grants",
    )
    claim = _claim(key, "Spend funds.", conditions=tree, money=[money])
    if operator == "all" and not empty:
        resolve_factual_records([_record(key, claims=[claim])], sources)
    else:
        with pytest.raises(ValidationError) as error:
            resolve_factual_records([_record(key, claims=[claim])], sources)
        assert error.value.validator == ("anyOf" if empty else "reader_amount_conflict")
