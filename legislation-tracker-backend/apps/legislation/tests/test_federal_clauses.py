from apps.legislation.extraction.federal_clauses import iter_operative_clauses
from apps.legislation.extraction.federal_structure import parse_federal_structure

INHERITED_LIST_SOURCE = """SEC. 2. DUTIES
The Secretary shall—
(A) publish the report; and
(B) send the report to Congress.
"""


def test_clause_parser_inherits_actor_without_combining_list_items():
    clauses = tuple(
        iter_operative_clauses(
            INHERITED_LIST_SOURCE,
            parse_federal_structure(INHERITED_LIST_SOURCE),
        )
    )

    assert [clause.text for _, clause, _ in clauses] == [
        "The Secretary shall—",
        "publish the report; and",
        "send the report to Congress.",
    ]
    assert [section.label for section, _, _ in clauses] == ["Sec. 2", "(A)", "(B)"]
    assert {context.actor for _, _, context in clauses if context is not None} == {
        "The Secretary"
    }


def test_clause_parser_splits_two_modals_and_excludes_amendment_quotation_blocks():
    source = """SEC. 3. DUTIES
The Secretary shall publish a report and may issue guidance.
[[QUOTED_BLOCK_START]]
(A) The Administrator shall not disclose the quoted text.
[[QUOTED_BLOCK_END]]
"""

    clauses = tuple(iter_operative_clauses(source, parse_federal_structure(source)))

    assert [clause.text for _, clause, _ in clauses] == [
        "The Secretary shall publish a report",
        "may issue guidance.",
    ]
    assert clauses[1][2] is not None
    assert clauses[1][2].actor == "The Secretary"
