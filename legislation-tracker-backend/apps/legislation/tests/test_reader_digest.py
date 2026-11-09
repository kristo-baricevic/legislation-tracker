import pytest
from apps.legislation.extraction.reader_language import build_reader_copy


def line(id, text, heading="Content of application", section="s1"):
    return {"id": id, "source_id": id, "section_id": section, "kind": "requirement",
            "display_text": text, "actor": None, "action": None, "effect": None,
            "section_path": [{"id": section, "level": "section", "label": "Sec. 4", "heading": "Applications"},
                             {"id": section + "a", "level": "subsection", "label": "(a)", "heading": heading}],
            "evidence_paths": ["/" + id], "exact_financial_refs": [], "timeline_refs": [], "definition_refs": []}


def test_application_clauses_become_one_change_without_losing_sources():
    payload = {"line_items": [
        line("a", "An application submitted under this section must include A plan to evaluate the reform or practice."),
        line("b", "An application submitted under this section must include Annual benchmarks for student outcomes."),
        line("c", "An application submitted under this section must include Demographics of enrolled students."),
    ]}
    groups = build_reader_copy(payload, "h")["groups"]
    assert len(groups) == 1
    assert groups[0]["member_ids"] == ["a", "b", "c"]
    assert groups[0]["evidence_paths"] == ["/a", "/b", "/c"]
    assert len(groups[0]["reader_text"].split()) <= 45
    assert "evaluate" in groups[0]["reader_text"]
    assert "students" in groups[0]["reader_text"]


def test_same_heading_in_different_sections_does_not_merge_unrelated_programs():
    payload = {"line_items": [line("a", "Applicants must report results.", section="s1"),
                              line("b", "Applicants must report results.", section="s2")]}
    assert len(build_reader_copy(payload, "h")["groups"]) == 2


def test_brief_distinguishes_set_asides_from_zero_cost():
    payload = {"orientation": {"purpose_clause": "This bill aims to help students finish college."},
               "line_items": [], "financial_items": [{"id": "f1", "financial_action": "set_aside", "amount": "2", "amount_type": "percentage"}]}
    brief = build_reader_copy(payload, "h")["brief"]
    assert "sets aside" in brief["money"].lower()
    assert "no cost" not in brief["money"].lower()
    assert "total" not in brief["money"].lower()


def test_permission_and_exceptions_are_not_turned_into_unconditional_entitlement():
    item = line("a", "Agencies may provide grants only to rural hospitals, except private clinics.", heading="Grants")
    item["kind"] = "permission"
    text = build_reader_copy({"line_items": [item]}, "h")["groups"][0]["reader_text"]
    assert "may" in text and "only" in text and "except private clinics" in text


def test_brief_uses_source_purpose_when_no_explicit_purpose_section_exists():
    brief = build_reader_copy({"line_items": []}, "h", "To provide grants to repair rural hospitals, and for other purposes.")["brief"]
    assert brief["summary"] == "This bill aims to provide grants to repair rural hospitals."


def test_large_unrecognized_group_keeps_every_member_without_breaking_reader_limit():
    items = [line(str(i), f"Agency {i} must " + "retain records " * 230 + ".", heading="Records") for i in range(4)]
    groups = build_reader_copy({"line_items": items}, "h")["groups"]
    assert all(len(group["reader_text"]) <= 8000 for group in groups)
    assert [member for group in groups for member in group["member_ids"]] == [item["id"] for item in items]
    assert [ref for group in groups for ref in group["evidence_paths"]] == ["/0", "/1", "/2", "/3"]


def test_plain_replacement_keeps_the_indefinite_article_grammatical():
    item = line("a", "An eligible entity must apply.", heading="Application")
    assert build_reader_copy({"line_items": [item]}, "h")["groups"][0]["reader_text"] == "A qualifying organization must apply."


@pytest.mark.parametrize("kind,text", [
    ("amendment", "Section 2 is amended by striking “shall” and inserting “may”."),
    ("amendment", "Strike prior to and insert subsequent to."),
    ("requirement", 'The term "eligible entity" shall retain its meaning.'),
])
def test_group_projection_preserves_amendments_and_quoted_terms(kind, text):
    item = line("a", text, heading="Rules")
    item["kind"] = kind
    expected = text if kind == "amendment" else 'The term "eligible entity" must retain its meaning.'
    assert build_reader_copy({"line_items": [item]}, "h")["groups"][0]["reader_text"] == expected


@pytest.mark.parametrize("kind,text", [
    ("permission", "Applicants may include an evaluation plan."),
    ("prohibition", "Applicants must not include student demographics."),
    ("requirement", "Applicants must report outcomes only if they receive a grant, except small institutions."),
    ("requirement", "An application submitted under this section must include an evaluation plan unless exempt under section 9."),
])
def test_application_groups_keep_modality_and_full_qualifications(kind, text):
    item = line("a", text)
    item["kind"] = kind
    actual = build_reader_copy({"line_items": [item]}, "h")["groups"][0]["reader_text"]
    assert actual == text
    if kind != "requirement":
        assert "must" not in build_reader_copy({"line_items": [item]}, "h")["groups"][0]["section_path"][-1]["heading"].lower()


def test_long_application_rule_does_not_lose_exception_in_general_overview():
    text = "Applicants must submit an application describing the proposed program, the people it serves, the location, the duration, the staffing plan, the evaluation method, the proposed spending, and the planned reporting schedule, unless they have already submitted an approved application under section 9 of this Act."
    item = line("a", text, heading="Applications")
    assert build_reader_copy({"line_items": [item]}, "h")["groups"][0]["reader_text"] == text


def test_mixed_application_clauses_keep_their_individual_obligations():
    items = [line("a", "Applicants must report outcomes."), line("b", "Applicants may include an evaluation plan.")]
    items[1]["kind"] = "permission"
    group = build_reader_copy({"line_items": items}, "h")["groups"][0]
    assert group["reader_text"] == "Applicants must report outcomes. Applicants may include an evaluation plan."


def test_previous_saved_projection_is_rebuilt_without_changing_source():
    from types import SimpleNamespace
    from apps.legislation.extraction.reader_language import projection
    text = "Strike “shall” and insert “may”."
    item = line("a", text)
    item["kind"] = "amendment"
    contract = SimpleNamespace(contract_hash="h", contract_json={"line_items": [item]}, document=None,
                               reader_copy={"version": "brief-1", "contract_hash": "h", "groups": [{"reader_text": "wrong"}]})
    assert projection(contract)["groups"][0]["reader_text"] == text
    assert contract.contract_json["line_items"][0]["display_text"] == text
