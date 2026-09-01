from apps.legislation.extraction.display_text import normalize_reader_fragment
from apps.legislation.extraction.types import SourceSpan


def test_reader_cleanup_does_not_mutate_evidence():
    raw = "``(A) <<NOTE: Deadline.>> The Secretary shall re-\n evaluate the plan. [[Page 139 STAT. 81]]"
    span = SourceSpan(raw, 200, 200 + len(raw))

    assert normalize_reader_fragment(raw) == "The Secretary shall reevaluate the plan."
    assert span.text == raw
    assert (span.start_char, span.end_char) == (200, 200 + len(raw))


def test_reader_cleanup_removes_only_allowlisted_artifacts():
    assert normalize_reader_fragment("(A) The report uses [brackets] and `code`.") == (
        "The report uses [brackets] and `code`."
    )
