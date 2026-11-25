from apps.legislation.extraction import federal_structure as structure
from apps.legislation.extraction import legal_rules


def test_subdivision_parser_does_not_resort_growing_document(monkeypatch):
    real_sorted = sorted
    sorted_items = []

    def counted(items, **kwargs):
        items = list(items)
        sorted_items.append(len(items))
        return real_sorted(items, **kwargs)

    monkeypatch.setattr(structure, "sorted", counted, raising=False)
    text = "".join(
        f"SEC. {i}. Grants\n(a) Provide grants.\n(1) Publish reports.\n(A) Include totals.\n"
        for i in range(1, 101)
    )
    sections = structure.parse_federal_structure(text)
    assert len(sections) == 400
    assert sum(sorted_items) < 2000


def test_heading_lookup_matches_containment_for_nested_sections():
    text = "SEC. 1. Definitions\n(a) General\n(1) The term agency means a department.\nSEC. 2. Grants\n(a) Definitions\n(1) The term award means a grant.\n(b) Reports\nThe agency shall publish reports.\n"
    sections = structure.parse_federal_structure(text)
    lookup = legal_rules._HeadingLookup(sections)
    for section in sections:
        for phrase in ("definition", "table of contents"):
            assert legal_rules._heading_contains(
                section, phrase, lookup
            ) == legal_rules._heading_contains(section, phrase, sections)


def test_parent_lookup_reuses_structure_index():
    sections = structure.parse_federal_structure(
        "SEC. 1. Grants\n(a) Reports\nThe agency shall publish reports.\n"
    )

    class IndexedOnly:
        parents = sections.parents

        def __iter__(self):
            raise AssertionError("must not scan the entire bill for each parent")

    assert legal_rules._parent_section(sections[1], IndexedOnly()) == sections[0]


def test_nonfinancial_clause_does_not_resolve_funding_ancestors(monkeypatch):
    text = "SEC. 1. Reports\n(a) The agency shall publish a report.\n"
    sections = structure.parse_federal_structure(text)

    def unexpected(*args):
        raise AssertionError("no amount or such-sums authority to extract")

    monkeypatch.setattr(legal_rules, "_inherited_funding_context", unexpected)
    assert legal_rules.extract_funding_claims(text, sections) == ()


def test_claim_categories_share_one_operative_parse(monkeypatch):
    text = "SEC. 1. Grants\n(a) The agency shall award $100 for fiscal year 2027.\nSEC. 2. Definitions\nThe term award means a grant.\n"
    sections = structure.parse_federal_structure(text)
    expected = legal_rules.extract_claims(text, sections, reader_mode=True)
    real_iter = legal_rules.iter_operative_clauses
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        yield from real_iter(*args, **kwargs)

    monkeypatch.setattr(legal_rules, "iter_operative_clauses", counted)
    assert legal_rules.extract_claims(text, sections, reader_mode=True) == expected
    assert len(calls) == 1


def test_payment_children_are_indexed_once():
    from dataclasses import replace

    from apps.legislation.extraction import financial_rules
    from apps.legislation.extraction.operative_context import parse_operative_clauses

    text = "".join(
        f"SEC. {i}. Fees\nApplicants shall pay a fee of $100.\n" for i in range(1, 31)
    )
    sections = structure.parse_federal_structure(text)
    clauses = parse_operative_clauses(text, sections)
    expected = tuple(financial_rules._payment_claims(text, sections, clauses))
    checks = []

    class CountedContext(tuple):
        def __contains__(self, value):
            checks.append(1)
            return super().__contains__(value)

    clauses = [replace(c, context=CountedContext(c.context)) for c in clauses]
    assert tuple(financial_rules._payment_claims(text, sections, clauses)) == expected
    assert len(checks) <= len(clauses) * 2


def test_clause_overlap_index_preserves_nested_and_boundary_matches():
    from types import SimpleNamespace

    from apps.legislation.extraction.source_coverage import _ClauseIndex

    clauses = [
        SimpleNamespace(span=SimpleNamespace(start_char=a, end_char=b))
        for a, b in [(20, 30), (0, 100), (0, 10), (10, 20), (20, 25), (110, 120)]
    ]
    index = _ClauseIndex(clauses)
    for a in range(0, 125, 5):
        b = a + 5
        assert index.overlapping(a, b) == [
            c for c in clauses if c.span.start_char < b and a < c.span.end_char
        ]


def test_synopsis_indexes_asserted_clauses_once():
    from apps.legislation.extraction.operative_context import parse_operative_clauses
    from apps.legislation.extraction.synopsis import structured_synopsis

    text = "".join(
        f"SEC. {i}. Reports\nThe agency shall publish reports.\n" for i in range(1, 31)
    )
    sections = structure.parse_federal_structure(text)
    clauses = parse_operative_clauses(text, sections)
    checks = []

    class CountedClause:
        def __init__(self, clause):
            self.clause = clause

        def __getattr__(self, name):
            return getattr(self.clause, name)

        @property
        def asserted(self):
            checks.append(1)
            return self.clause.asserted

    expected = structured_synopsis(sections, (), text, clauses)
    assert (
        structured_synopsis(sections, (), text, [CountedClause(c) for c in clauses])
        == expected
    )
    assert len(checks) <= len(clauses) * 2


def test_content_start_does_not_copy_entire_container():
    text = "TITLE I—Programs\nSEC. 1. Grants\n" + "Provide grants.\n" * 10000
    sections = structure.parse_federal_structure(text)
    expected = structure._content_start(sections[0], text)

    class BoundedSlices(str):
        def __getitem__(self, key):
            if isinstance(key, slice):
                assert (key.stop or len(self)) - (key.start or 0) < 1000
            return super().__getitem__(key)

    assert structure._content_start(sections[0], BoundedSlices(text)) == expected


def test_definition_linking_normalizes_each_source_once(monkeypatch):
    from types import SimpleNamespace

    from apps.legislation.extraction import reader_brief
    from apps.legislation.extraction.types import SourceSpan

    terms = ["agency", "grant", "grant funds", "fund", "a-b", "éducation", "", None]
    definitions = [
        SimpleNamespace(id=str(i), claim=SimpleNamespace(fields={"term": t}))
        for i, t in enumerate(terms)
    ]
    lines = [
        SimpleNamespace(evidence=(SourceSpan(text, 0, len(text)),), definition_refs=[])
        for text in [
            "The agency awards grant funds.",
            "A-B supports éducation.",
            "Agencywide grantfunds are not matches.",
        ]
    ]
    expected = [
        [
            d.id
            for d in definitions
            if reader_brief._definition_occurs(d.claim.fields["term"], line)
        ]
        for line in lines
    ]
    normalized = reader_brief._normalized
    calls = []

    def counted(value):
        calls.append(1)
        return normalized(value)

    monkeypatch.setattr(reader_brief, "_normalized", counted)
    reader_brief._attach_definition_refs(definitions, lines)
    assert [line.definition_refs for line in lines] == expected
    assert len(calls) <= len(definitions) + len(lines)
