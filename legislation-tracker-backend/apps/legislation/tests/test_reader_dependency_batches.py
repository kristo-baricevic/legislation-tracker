"""Exercise request execution when legal conditions live in another source."""

import copy
import hashlib
from collections import Counter
from dataclasses import replace

import pytest
from django.test import override_settings
from jsonschema import ValidationError

from apps.legislation.enhancements.providers.base import ProviderResult, ProviderUsage
from apps.legislation.enhancements.reader_batches import execute_reader_batches
from apps.legislation.enhancements.reader_capacity import fits
from apps.legislation.enhancements.reader_citations import citation_passages
from apps.legislation.enhancements.reader_discovery import (
    money_candidates,
    policy_passages,
    resolve_discovery,
)
from apps.legislation.enhancements.reader_partial import validated_components
from apps.legislation.enhancements.reader_sizing import select_review_units
from apps.legislation.enhancements.source_packet import build_enhancement_preflight
from apps.legislation.tests.test_reader_enhancement_pipeline import install_reader


def _source(text, start, end, ref):
    quoted = text[start:end]
    return {
        "source_ref": ref,
        "kind": "document_chunk",
        "field_path": None,
        "section_label": "Test bill",
        "start_char": start,
        "end_char": end,
        "quoted_text": quoted,
        "text_sha256": hashlib.sha256(quoted.encode()).hexdigest(),
        "discovery_source": True,
        "context_source_refs": [],
        "context_quote_ids": {},
        "dependencies": [],
        "omitted_dependency_ranges": [],
        "context_planner_version": 1,
        "section_context_complete": True,
        "unresolved_dependencies": [],
    }


@pytest.fixture
def dependency_plan(source_bill, enhancement_settings, settings, monkeypatch):
    sections = [
        "SEC. 1. Library support\nA qualifying school may apply for library support.\n",
        "SEC. 2. Reports\nThe Secretary shall publish annual program reports.\n",
        "SEC. 3. Definitions\nA qualifying school means a public school with fewer than 500 students.\n",
    ]
    text = "".join(sections)
    document = source_bill.documents.get()
    document.extracted_text = text
    document.save()
    install_reader(source_bill, count=0)

    def planner(document, actual, first_ref, target, xml_sections):
        assert actual == text
        cursor = 0
        sources = []
        for index, section in enumerate(sections):
            sources.append(
                _source(
                    actual,
                    cursor,
                    cursor + len(section),
                    f"src_{first_ref + index:04d}",
                )
            )
            cursor += len(section)
        sources[0]["context_source_refs"] = [sources[2]["source_ref"]]
        sources[0]["context_quote_ids"] = {sources[2]["source_ref"]: ["p0001"]}
        return sources

    monkeypatch.setattr(
        "apps.legislation.enhancements.reader_chunking.planned_sources", planner
    )
    with enhancement_settings, override_settings(LLM_READER_OWNED_TOKEN_TARGET=1000):
        yield build_enhancement_preflight(source_bill)


def test_dependencies_are_citable_without_duplicate_review_obligations(dependency_plan):
    plan = dependency_plan
    requests = [
        r for r in plan.reader_batches if r.request_envelope.get("source_review")
    ]
    scans = [s for s in plan.source_snapshot if s.get("discovery_source")]
    first = requests[0]
    assert len(first.source_snapshot) == 2
    owned, context = first.source_snapshot
    assert owned["review_quote_ids"] == ["p0001"]
    assert context["review_quote_ids"] == []
    assert context["source_ref"] == scans[2]["source_ref"]
    wire_context = first.request_envelope["source_packet"]["sources"][1]
    assert wire_context["citation_passages"] == citation_passages(context)
    assert wire_context["review_quote_ids"] == []
    for wire, snapshot in zip(
        first.request_envelope["source_packet"]["sources"],
        first.source_snapshot,
        strict=True,
    ):
        for key in (
            "context_source_refs",
            "context_quote_ids",
            "dependencies",
            "omitted_dependency_ranges",
            "context_planner_version",
        ):
            global_source = next(
                s for s in scans if s["source_ref"] == snapshot["source_ref"]
            )
            assert key in global_source
            assert key not in wire
            if key != "context_planner_version":
                assert key not in snapshot
        assert wire["section_context_complete"] == snapshot["section_context_complete"]
        assert wire["unresolved_dependencies"] == snapshot["unresolved_dependencies"]
    counts = Counter(k for r in requests for k in policy_passages(r.source_snapshot))
    assert counts == Counter(policy_passages(scans))
    assert all(fits(r.request_envelope) for r in requests)

    own_quote = {"source_ref": owned["source_ref"], "quote_id": "p0001"}
    context_quote = {"source_ref": context["source_ref"], "quote_id": "p0001"}
    output = {
        "financial_items": [],
        "additional_changes": [],
        "money_checks": {},
        "policy_checks": {f"{owned['source_ref']}:p0001": "explained"},
        "policy_changes": [
            {
                "title": "Support small public schools",
                "text": "Public schools with fewer than 500 students may apply for library support.",
                "source_quotes": [context_quote, own_quote],
            },
            {
                "title": "Define schools",
                "text": "Qualifying schools have fewer than 500 students.",
                "source_quotes": [context_quote],
            },
        ],
    }
    valid = resolve_discovery(output, first.source_snapshot)
    assert len(valid["policy_changes"]) == 1
    assert valid["policy_changes"][0]["source_quotes"] == [
        {"source_ref": owned["source_ref"], "quote": owned["quoted_text"]},
        {"source_ref": context["source_ref"], "quote": context["quoted_text"]},
    ]


@pytest.mark.parametrize("durable", [False, True])
def test_execution_reviews_owners_in_order_and_publishes_dependency_citations(
    dependency_plan, source_bill, enhancement_owner, monkeypatch, durable
):
    plan = dependency_plan
    scans = [s for s in plan.source_snapshot if s.get("discovery_source")]
    seen = []

    class Provider:
        def enhance_bill(self, *, request, **kwargs):
            if request.request_envelope.get("source_review"):
                owner = request.source_snapshot[0]
                seen.append(owner["source_ref"])
                index = next(
                    i
                    for i, s in enumerate(scans)
                    if s["source_ref"] == owner["source_ref"]
                )
                texts = [
                    "Public schools with fewer than 500 students may apply for library support.",
                    "The Secretary must publish annual program reports.",
                    "Qualifying schools are public schools with fewer than 500 students.",
                ]
                quotes = [
                    {"source_ref": s["source_ref"], "quote_id": "p0001"}
                    for s in request.source_snapshot
                ]
                output = {
                    "financial_items": [],
                    "additional_changes": [],
                    "money_checks": {},
                    "policy_changes": [
                        {
                            "title": "Library support",
                            "text": texts[index],
                            "source_quotes": quotes,
                        }
                    ],
                    "policy_checks": {f"{owner['source_ref']}:p0001": "explained"},
                }
            else:
                # This is the real reduce path, using the completed inventory.
                assert (
                    len(request.request_envelope["source_packet"]["validated_changes"])
                    == 3
                )
                output = {
                    "schema_version": "1.4",
                    "explanations": [],
                    "summary": [
                        {
                            "text": "The bill offers library support to small public schools and requires annual reports.",
                            "source_quotes": [
                                {
                                    "source_ref": scans[0]["source_ref"],
                                    "quote_id": "p0001",
                                },
                                {
                                    "source_ref": scans[1]["source_ref"],
                                    "quote_id": "p0001",
                                },
                            ],
                        }
                    ],
                }
            return ProviderResult(output, ProviderUsage(10, 5, 15), "offline", "test")

    if durable:
        from apps.legislation.tasks import run_bill_enhancement_attempt
        from apps.legislation.tests.test_enhancement_tasks import _pending_attempt

        monkeypatch.setattr("apps.legislation.tasks.get_provider", lambda _: Provider())
        with override_settings(LLM_READER_CALLS_PER_DELIVERY=2):
            attempt = _pending_attempt(enhancement_owner, source_bill)
            statuses = []
            for _ in range(4):
                result = run_bill_enhancement_attempt(
                    attempt.pk, attempt.dispatch_token
                )
                statuses.append(result["status"])
                attempt.refresh_from_db()
                if result["status"] != "pending":
                    break
            assert statuses == ["pending", "succeeded"], attempt.failure_detail
            attempt.enhancement.refresh_from_db()
            output = attempt.enhancement.result_json
            assert attempt.steps.count() == 4
            assert attempt.work_units.filter(status="validated").count() == 4
    else:
        result = execute_reader_batches(plan, Provider(), "offline", lambda *_: None)
        output = result.output
    assert seen == [s["source_ref"] for s in scans]
    review = output["source_review"]
    assert review["reviewed_sources"] == seen
    assert set(review["policy_checks"]) == set(policy_passages(scans))
    assert len(review["policy_drafts"]) == 3
    assert output["summary"]
    assert (
        review["policy_drafts"][0]["source_quotes"][1]["source_ref"]
        == scans[2]["source_ref"]
    )


def test_output_split_keeps_dependency_and_wire_ownership(dependency_plan):
    request = next(
        r for r in dependency_plan.reader_batches if len(r.source_snapshot) > 1
    )
    child = select_review_units(request, ["p0001"])
    assert child.source_snapshot[1:] == request.source_snapshot[1:]
    assert child.request_envelope["source_packet"]["sources"][0][
        "review_quote_ids"
    ] == ["p0001"]
    assert (
        child.request_envelope["source_packet"]["sources"][1]["review_quote_ids"] == []
    )
    assert (
        child.request_envelope["source_packet"]["sources"][1]["citation_passages"]
        == request.request_envelope["source_packet"]["sources"][1]["citation_passages"]
    )


def test_call_cache_ignores_dependency_locations_but_keeps_supplied_conditions(
    dependency_plan,
):
    from apps.legislation.enhancements.reader_cache import call_identity

    original = copy.deepcopy(
        next(r for r in dependency_plan.reader_batches if len(r.source_snapshot) > 1)
    )
    for source in original.source_snapshot:
        source.update(
            context_source_refs=["src_0099"],
            context_quote_ids={"src_0099": ["p0001"]},
            dependencies=[{"start": 100, "end": 200, "sha256": "same-public-source"}],
            omitted_dependency_ranges=[],
        )
    shifted = copy.deepcopy(original)
    for source in shifted.source_snapshot:
        source["start_char"] += 500
        source["end_char"] += 500
        source["dependencies"][0]["start"] += 500
        source["dependencies"][0]["end"] += 500
    for source in shifted.request_envelope["source_packet"]["sources"]:
        if "start_char" in source:
            source["start_char"] += 500
            source["end_char"] += 500
    assert call_identity(original)[0] == call_identity(shifted)[0]

    changed_condition = copy.deepcopy(shifted)
    context = changed_condition.source_snapshot[1]
    context["quoted_text"] = context["quoted_text"].replace(
        "500 students", "600 students"
    )
    context["text_sha256"] = hashlib.sha256(context["quoted_text"].encode()).hexdigest()
    for passage in changed_condition.request_envelope["source_packet"]["sources"][1][
        "citation_passages"
    ]:
        passage["text"] = passage["text"].replace("500 students", "600 students")
    assert call_identity(original)[0] != call_identity(changed_condition)[0]

    changed_selection = copy.deepcopy(shifted)
    changed_selection.source_snapshot[1]["allowed_quote_ids"] = []
    assert call_identity(original)[0] != call_identity(changed_selection)[0]
    changed_planner = replace(
        shifted,
        source_snapshot=[
            {**s, "context_planner_version": s["context_planner_version"] + 1}
            for s in shifted.source_snapshot
        ],
    )
    assert call_identity(original)[0] != call_identity(changed_planner)[0]


def test_partial_recovery_retains_a_valid_conditioned_finding():
    raw = (
        "The agency may support qualifying schools. "
        + "Application details. " * 25
        + "\nThe agency must publish an annual report. "
        + "Reporting details. " * 20
        + "The report must include school enrollment."
    )
    source = _source(raw, 0, len(raw), "src_0001")
    source["policy_review"] = True
    ids = [p["quote_id"] for p in citation_passages(source) if p["quote_id"]]
    assert len(ids) == 2
    definition = "Qualifying schools are public schools with fewer than 500 students."
    context = _source(definition, 0, len(definition), "src_0002")
    context.update(review_quote_ids=[], allowed_quote_ids=["p0001"], policy_review=True)
    output = {
        "financial_items": [],
        "additional_changes": [],
        "money_checks": {},
        "policy_checks": {f"src_0001:{i}": "explained" for i in ids},
        "policy_changes": [
            {
                "title": "Support small schools",
                "text": "The agency may support public schools with fewer than 500 students.",
                "source_quotes": [
                    {"source_ref": "src_0001", "quote_id": ids[0]},
                    {"source_ref": "src_0002", "quote_id": "p0001"},
                ],
            },
            {
                "title": "Report annually",
                "text": "Incomplete",
                "source_quotes": [{"source_ref": "src_0001", "quote_id": ids[1]}],
            },
        ],
    }
    valid, pending = validated_components(output, [source, context])
    assert pending == [ids[1]]
    assert len(valid) == 1
    assert valid[0][0] == [ids[0]]
    assert (
        valid[0][1]["policy_changes"][0]["source_quotes"][1]["source_ref"] == "src_0002"
    )


def test_context_selection_preserves_global_quote_ids_and_rejects_unprovided_text(
    source_bill, enhancement_settings, monkeypatch
):
    rule = "SEC. 1. Libraries\nQualifying schools may apply for library support.\n"
    background = "".join(
        f"Program record {i}: The agency publishes general administrative background material.\n"
        for i in range(75)
    )
    definition = "The term qualifying school means a public school with fewer than 500 students.\n"
    tail = "".join(
        f"Later record {i}: Unrelated administrative information remains available to the public.\n"
        for i in range(25)
    )
    context_text = background + definition + tail
    assert len(context_text) > 8000
    text = rule + context_text
    document = source_bill.documents.get()
    document.extracted_text = text
    document.save()
    install_reader(source_bill, count=0)

    def planner(document, actual, first_ref, target, xml_sections):
        owner = _source(actual, 0, len(rule), f"src_{first_ref:04d}")
        context = _source(actual, len(rule), len(actual), f"src_{first_ref + 1:04d}")
        selected = [
            p["quote_id"]
            for p in citation_passages(context)
            if p["quote_id"] and "fewer than 500 students" in p["text"]
        ]
        assert len(selected) == 1 and selected != ["p0001"]
        owner["context_source_refs"] = [context["source_ref"]]
        owner["context_quote_ids"] = {context["source_ref"]: selected}
        return [owner, context]

    monkeypatch.setattr(
        "apps.legislation.enhancements.reader_chunking.planned_sources", planner
    )
    with enhancement_settings, override_settings(LLM_READER_OWNED_TOKEN_TARGET=1000):
        plan = build_enhancement_preflight(source_bill)
    request = next(
        r for r in plan.reader_batches if r.request_envelope.get("source_review")
    )
    owner, context = request.source_snapshot
    wire = request.request_envelope["source_packet"]["sources"][1]
    assert context["quoted_text"] == context_text
    assert len(wire["citation_passages"]) == 1
    supplied = wire["citation_passages"][0]
    assert supplied["quote_id"] != "p0001"
    assert len(supplied["text"]) <= 800
    assert "fewer than 500 students" in supplied["text"]
    assert context["allowed_quote_ids"] == [supplied["quote_id"]]
    assert len(request.request_bytes) < len(context_text) + 8000
    assert all(
        "allowed_quote_ids" not in s
        for s in plan.source_snapshot
        if s.get("discovery_source")
    )
    quote = {"source_ref": context["source_ref"], "quote_id": supplied["quote_id"]}
    output = {
        "financial_items": [],
        "additional_changes": [],
        "money_checks": {},
        "policy_checks": {f"{owner['source_ref']}:p0001": "explained"},
        "policy_changes": [
            {
                "title": "Support small public schools",
                "text": "Public schools with fewer than 500 students may apply for library support.",
                "source_quotes": [
                    {"source_ref": owner["source_ref"], "quote_id": "p0001"},
                    quote,
                ],
            }
        ],
    }
    valid = resolve_discovery(output, request.source_snapshot)
    assert valid["policy_changes"][0]["source_quotes"][1]["quote"] == supplied["text"]
    rejected = copy.deepcopy(output)
    rejected["policy_changes"][0]["source_quotes"].append(
        {"source_ref": context["source_ref"], "quote_id": "p0001"}
    )
    with pytest.raises(ValidationError):
        resolve_discovery(rejected, request.source_snapshot)
    child = select_review_units(request, ["p0001"])
    assert child.source_snapshot[1]["allowed_quote_ids"] == [supplied["quote_id"]]
    assert child.request_envelope["source_packet"]["sources"][1][
        "citation_passages"
    ] == [supplied]


@pytest.mark.django_db
def test_default_large_document_routes_through_dependency_planner(
    source_bill, enhancement_settings, monkeypatch
):
    document = source_bill.documents.get()
    document.extracted_text = "".join(
        f"SEC. {i}. Public reports\nThe agency shall publish program report number {i}.\n"
        for i in range(1800)
    )
    document.save()
    calls = []

    def planner(document, text, first_ref, target, xml_sections):
        calls.append(target)
        result = []
        cursor = 0
        for start in range(0, len(text), 2000):
            end = min(len(text), start + 2000)
            result.append(
                _source(text, start, end, f"src_{first_ref + len(result):04d}")
            )
            cursor = end
        assert cursor == len(text)
        return result

    monkeypatch.setattr(
        "apps.legislation.enhancements.reader_chunking.planned_sources", planner
    )
    with (
        enhancement_settings,
        override_settings(
            LLM_READER_OWNED_TOKEN_TARGET=0,
            LLM_SOURCE_FIRST_ENABLED=False,
            LLM_READER_MAX_CALLS=0,
        ),
    ):
        plan = build_enhancement_preflight(source_bill)
    assert calls == [8000]
    scans = [s for s in plan.source_snapshot if s.get("discovery_source")]
    assert "".join(s["quoted_text"] for s in scans) == document.extracted_text
    assert all(fits(r.request_envelope) for r in plan.reader_batches)


@pytest.mark.django_db
def test_later_matching_condition_is_citable_with_the_grant_it_qualifies(
    source_bill, enhancement_owner, enhancement_settings, monkeypatch
):
    from apps.legislation.enhancements.xml_sections import XmlProvision, XmlSections

    heading = "SEC. 1. School grants\n"
    grant = "(a) Grants.--The Secretary shall award grants to schools.\n"
    matching = (
        "(c) Matching funds.--A grant under subsection (a) is subject to a "
        "50 percent non-Federal matching contribution.\n"
    )
    directory = (
        "(b) Program directory.--" + "Administrative program material " * 1000 + ".\n"
    )
    text = heading + grant + directory + matching
    grant_start = len(heading)
    directory_start = grant_start + len(grant)
    matching_start = directory_start + len(directory)
    sections = XmlSections(
        [("s1", 0, len(text), "Sec. 1", "School grants")],
        [
            XmlProvision(0, len(text), "section", "1", "School grants", None, "s1", 0),
            XmlProvision(
                grant_start, directory_start, "subsection", "(a)", "Grants", 0, "s1", 0
            ),
            XmlProvision(
                directory_start,
                matching_start,
                "subsection",
                "(b)",
                "Program directory",
                0,
                "s1",
                0,
            ),
            XmlProvision(
                matching_start,
                len(text),
                "subsection",
                "(c)",
                "Matching funds",
                0,
                "s1",
                0,
            ),
        ],
    )
    document = source_bill.documents.get()
    document.extracted_text = text
    document.save()
    monkeypatch.setattr(
        "apps.legislation.enhancements.xml_sections.stored_xml_sections",
        lambda *_: sections,
    )
    with enhancement_settings, override_settings(LLM_READER_OWNED_TOKEN_TARGET=1000):
        plan = build_enhancement_preflight(source_bill)
    request = next(
        r
        for r in plan.reader_batches
        if r.request_envelope.get("source_review")
        and r.source_snapshot[0]["start_char"] == grant_start
    )
    contexts = request.source_snapshot[1:]
    condition = next(s for s in contexts if "50 percent" in s["quoted_text"])
    assert condition["review_quote_ids"] == []
    wire = next(
        s
        for s in request.request_envelope["source_packet"]["sources"]
        if s["source_ref"] == condition["source_ref"]
    )
    assert any(
        "50 percent" in p["text"] and p["quote_id"] for p in wire["citation_passages"]
    )
    assert fits(request.request_envelope)

    # Exercise this actual plan through confirmation, durable dispatch,
    # synthesis and publication. Only the upstream model is simulated.
    from apps.legislation.tasks import run_bill_enhancement_attempt
    from apps.legislation.tests.test_enhancement_tasks import _pending_attempt

    reviewed = []

    class Provider:
        def enhance_bill(self, *, request, **kwargs):
            if request.request_envelope.get("source_review"):
                owner = request.source_snapshot[0]
                reviewed.append(owner["source_ref"])
                owned_quotes = [
                    {"source_ref": owner["source_ref"], "quote_id": p["quote_id"]}
                    for p in citation_passages(owner)
                    if p["quote_id"] in owner["review_quote_ids"]
                ]
                policies, financial = [], []
                if "Secretary shall award grants" in owner["quoted_text"]:
                    condition_quotes = [
                        {"source_ref": s["source_ref"], "quote_id": p["quote_id"]}
                        for s in request.source_snapshot[1:]
                        for p in citation_passages(s)
                        if p["quote_id"] and "50 percent" in p["text"]
                    ]
                    assert condition_quotes
                    policies.append(
                        {
                            "title": "Award school grants",
                            "text": "The Secretary must award school grants requiring a 50 percent non-Federal matching contribution.",
                            "source_quotes": owned_quotes + condition_quotes,
                        }
                    )
                elif "50 percent" in owner["quoted_text"]:
                    policies.append(
                        {
                            "title": "Match school grants",
                            "text": "School grants require a 50 percent non-Federal matching contribution.",
                            "source_quotes": owned_quotes,
                        }
                    )
                    financial.append(
                        {
                            "label": "School grant matching",
                            "amount_display": "50 percent non-Federal match",
                            "text": "School grants require a 50 percent non-Federal matching contribution.",
                            "fiscal_years": [],
                            "source_quotes": owned_quotes,
                        }
                    )
                output = {
                    "financial_items": financial,
                    "additional_changes": [],
                    "money_checks": {
                        key: "financial" if financial else "not_financial"
                        for key in money_candidates(request.source_snapshot)
                    },
                    "policy_changes": policies,
                    "policy_checks": {
                        key: "explained" if policies else "context"
                        for key in policy_passages(request.source_snapshot)
                    },
                }
            else:
                matching_quotes = [
                    {"source_ref": s["source_ref"], "quote_id": p["quote_id"]}
                    for s in request.request_envelope["source_packet"]["sources"]
                    for p in s["citation_passages"]
                    if p["quote_id"] and "50 percent" in p["text"]
                ]
                assert matching_quotes
                output = {
                    "schema_version": "1.4",
                    "explanations": [],
                    "summary": [
                        {
                            "text": "School grants require a 50 percent non-Federal matching contribution.",
                            "source_quotes": matching_quotes,
                        }
                    ],
                }
            return ProviderResult(output, ProviderUsage(10, 5, 15), "offline", "test")

    monkeypatch.setattr("apps.legislation.tasks.get_provider", lambda _: Provider())
    with (
        enhancement_settings,
        override_settings(
            LLM_READER_OWNED_TOKEN_TARGET=1000,
            LLM_READER_CALLS_PER_DELIVERY=100,
        ),
    ):
        attempt = _pending_attempt(enhancement_owner, source_bill)
        outcome = run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)
    attempt.refresh_from_db()
    assert outcome["status"] == "succeeded", attempt.failure_detail
    attempt.enhancement.refresh_from_db()
    saved = attempt.enhancement.result_json
    expected_reviews = [
        s["source_ref"] for s in plan.source_snapshot if s.get("discovery_source")
    ]
    assert len(expected_reviews) > 10
    assert Counter(saved["source_review"]["reviewed_sources"]) == Counter(
        expected_reviews
    )
    # Identical background chunks can reuse a validated call at new offsets.
    # Every owned work unit still completes and appears in the published review.
    assert len(reviewed) == len(set(reviewed)) <= len(expected_reviews)
    assert (
        attempt.work_units.filter(status="validated").count()
        == len(expected_reviews) + 1
    )
    assert (
        saved["source_review"]["financial_items"][0]["amount_display"]
        == "50 percent non-Federal match"
    )
    assert "50 percent" in saved["summary"][0]["text"]
