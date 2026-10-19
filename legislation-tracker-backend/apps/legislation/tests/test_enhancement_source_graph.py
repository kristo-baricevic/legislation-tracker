from dataclasses import replace
from hashlib import sha256

from apps.legislation.enhancements.source_graph import audit_graph, build_source_graph


def test_condition_group_preserves_entire_tree_and_exact_source():
    text = "SEC. 1. BENEFIT\n(a) Grant aid only if--\n(1) income is below $20,000; and\n(2) the applicant is enrolled or employed.\nSEC. 2. REVIEW\nAn appropriate court may review a denial."
    graph = build_source_graph("1", "IH", text)
    group = next(u for u in graph.units if u.condition_group_id)
    selected = "".join(
        graph.passages[p].text
        for p in group.own_passage_ids + group.context_passage_ids
    )
    assert "only if" in selected and "enrolled or employed" in selected
    assert not audit_graph(graph, text)
    for p in graph.passages.values():
        assert text[p.start : p.end] == p.text
        assert sha256(p.text.encode()).hexdigest() == p.text_sha256
    court = graph.units[-1]
    assert "financial" not in court.inventory_kinds


def test_no_duplicate_parent_facts_and_no_dollar_authorization():
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. FUNDS\n(a) There are authorized to be appropriated such sums as necessary.\n(b) The Secretary shall pay $100.",
    )
    owned = [p for u in graph.units for p in u.own_passage_ids]
    assert len(owned) == len(set(owned))
    assert sum(graph.passages[p].text.count("$100") for p in owned) == 1
    assert any("financial" in u.inventory_kinds for u in graph.units)


def test_version_and_text_identity_are_not_interchangeable():
    a = build_source_graph("1", "IH", "SEC. 1. FEE\nPay $10.")
    b = build_source_graph("1", "ENR", "SEC. 1. FEE\nPay $10.")
    c = build_source_graph("1", "IH", "SEC. 1. FEE\nPay $20.")
    assert not set(a.passages) & set(b.passages)
    assert not set(a.passages) & set(c.passages)


def test_missing_ownership_is_visible_in_coverage():
    text = "SEC. 1. FIRST\nPay $10.\nSEC. 2. SECOND\nPay $20."
    graph = build_source_graph("1", "IH", text)
    assert audit_graph(replace(graph, units=graph.units[:-1]), text)


def test_external_references_are_not_resolved_as_this_bill():
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. CHANGE\nSection 2 of the Other Act is amended by striking ‘may’ and inserting ‘shall’.\nSEC. 2. DATE\nThis Act takes effect today.",
    )
    assert graph.units[0].unresolved_dependencies


def test_internal_references_and_cycles_keep_exact_context():
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. FIRST\nSubject to section 2 of this Act, pay $10.\nSEC. 2. SECOND\nSubject to section 1 of this Act, only residents qualify.",
    )
    assert all(u.context_passage_ids for u in graph.units)
    assert all(not u.unresolved_dependencies for u in graph.units)
    broken = replace(
        graph, units=(replace(graph.units[0], context_passage_ids=()), *graph.units[1:])
    )
    assert audit_graph(broken, graph.source_text)


def test_contents_are_retained_but_not_counted_as_operative_units():
    text = "TABLE OF CONTENTS\nSec. 1. Funds.\nSec. 2. Date.\nSEC. 1. FUNDS\nThere is appropriated $100.\nSEC. 2. DATE\nThis Act applies in 2027."
    graph = build_source_graph("1", "IH", text)
    assert len(graph.units) == 2
    assert not audit_graph(graph, text)
    assert any(
        p.role == "context" and "CONTENTS" in p.text for p in graph.passages.values()
    )


def test_unrecognized_text_is_preserved_as_unresolved():
    graph = build_source_graph(
        "1", "IH", "Quoted old law: may pay $10; amendment unclear."
    )
    assert len(graph.units) == 1
    assert graph.units[0].unresolved_dependencies == ("unrecognized_structure",)


def test_wrapped_contents_inside_section_one_not_operative():
    text = "SECTION 1. SHORT TITLE; TABLE OF CONTENTS.\n(a) This Act is the Test Act.\n(b) Table of Contents.--The table follows:\nSec. 1. Short title.\nSec. 102. Eligibility for\n  residents.\nSEC. 102. ELIGIBILITY\nResidents qualify."
    graph = build_source_graph("1", "IH", text)
    assert len(graph.units) == 2
    assert (
        "This Act is the Test Act"
        in graph.passages[graph.units[0].own_passage_ids[0]].text
    )


def test_section_heading_is_not_an_unresolved_reference():
    graph = build_source_graph(
        "1", "IH", "SECTION 1. REPORT\nThe Secretary shall publish a report."
    )
    assert graph.units[0].unresolved_dependencies == ()


def test_governing_title_prefix_is_sent_with_child():
    text = "TITLE I--BENEFITS\nOnly residents qualify for benefits under this title.\nSEC. 1. BENEFIT\nThe Secretary shall pay $100."
    graph = build_source_graph("1", "IH", text)
    unit = graph.units[0]
    assert any(
        "Only residents qualify" in graph.passages[p].text
        for p in unit.context_passage_ids
    )


def test_unambiguous_local_reference_includes_target_and_its_conditions():
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. PAYMENT\nSubject to section 2(a) of this Act, pay $100.\nSEC. 2. ELIGIBILITY\n(a) Only residents who are enrolled and employed qualify.",
    )
    unit = graph.units[0]
    assert not unit.unresolved_dependencies
    assert any(
        "enrolled and employed" in graph.passages[p].text
        for p in unit.context_passage_ids
    )


def test_bare_reference_resolves_only_outside_amended_law():
    local = build_source_graph(
        "1",
        "IH",
        "SEC. 1. PAYMENT\nSubject to section 2, pay $100.\nSEC. 2. ELIGIBILITY\nOnly residents qualify.",
    )
    assert not local.units[0].unresolved_dependencies
    assert local.units[1].own_passage_ids[0] in local.units[0].context_passage_ids
    amended = build_source_graph(
        "1",
        "IH",
        "SEC. 1. AMENDMENT\nSection 10 of the Other Act is amended by adding: ‘Subject to section 2, pay $100.’\nSEC. 2. DATE\nThis Act takes effect today.",
    )
    assert amended.units[0].unresolved_dependencies
    assert (
        amended.units[1].own_passage_ids[0] not in amended.units[0].context_passage_ids
    )


def test_qualified_external_reference_is_never_rebound_to_local_number():
    graph = build_source_graph(
        "1",
        "IH",
        "SEC. 1. RULE\nSubject to section 2(a) of the Other Act, pay $100.\nSEC. 2. DATE\nThis Act takes effect today.",
    )
    assert graph.units[0].unresolved_dependencies
    assert graph.units[1].own_passage_ids[0] not in graph.units[0].context_passage_ids


def test_oversized_section_splits_only_at_complete_subsections():
    first = (
        "    (a) Reports.--The Secretary shall publish reports.\n"
        + "Reporting text. " * 3300
    )
    second = (
        "\n    (b) Payment.--The Secretary shall pay $100 only if the applicant is enrolled and employed.\n"
        + "Payment text. " * 3300
    )
    text = "SEC. 1. PROGRAM\n" + first + second
    graph = build_source_graph("1", "IH", text)
    assert len(graph.units) == 2
    assert (
        "".join(graph.passages[p].text for u in graph.units for p in u.own_passage_ids)
        == text
    )
    payment = graph.units[1]
    assert payment.parent_id
    own = "".join(graph.passages[p].text for p in payment.own_passage_ids)
    assert "only if the applicant is enrolled and employed" in own
    assert any(
        "SEC. 1. PROGRAM" in graph.passages[p].text for p in payment.context_passage_ids
    )
    assert not audit_graph(graph, text)


def test_oversized_governing_conjunction_is_not_split():
    text = (
        "SEC. 1. ELIGIBILITY\nA person qualifies only if--\n    (a) the person is enrolled; and\n"
        + "condition text " * 6000
        + "\n    (b) the person is employed."
    )
    graph = build_source_graph("1", "IH", text)
    assert len(graph.units) == 1


def test_large_section_local_definition_cannot_be_separated_from_payment():
    text = (
        "SEC. 1. PROGRAM\n    (a) Definitions.--For purposes of this section, eligible applicant means a veteran.\n"
        + "Administrative text. " * 4200
        + "\n    (b) Payments.--The Secretary shall pay each eligible applicant $100."
    )
    graph = build_source_graph("1", "IH", text)
    assert len(graph.units) == 1
    assert (
        "eligible applicant means a veteran"
        in graph.passages[graph.units[0].own_passage_ids[0]].text
    )


def test_large_section_with_sibling_reference_remains_intact():
    text = (
        "SEC. 1. PROGRAM\n    (a) Payment.--The Secretary shall pay $100 under subsection (b).\n"
        + "Administrative text. " * 4200
        + "\n    (b) Qualifications.--Only veterans qualify."
    )
    graph = build_source_graph("1", "IH", text)
    assert len(graph.units) == 1
