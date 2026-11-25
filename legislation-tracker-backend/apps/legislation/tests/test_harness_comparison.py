import json
from hashlib import sha256
from pathlib import Path

import pytest

from apps.legislation.evaluation.harness_comparison import run_comparison

FIXTURES = Path(__file__).parent / "fixtures" / "harness"


@pytest.mark.parametrize("case", ["119hr9300ih", "119s4387is"])
def test_evidence_offsets_match_pinned_source(case):
    manifest = json.loads((FIXTURES / f"{case}.json").read_text())
    source = (FIXTURES / f"{case}.txt").read_text()
    assert sha256(source.encode()).hexdigest() == manifest["text_sha256"]
    for item in manifest["evidence"]:
        assert source[item["start"] : item["end"]] == item["quote"]


def test_comparison_reports_unknown_usage_and_counts_dispatched_failures():
    manifest = json.loads((FIXTURES / "119s4387is.json").read_text())
    case = {
        "manifest": manifest,
        "dispatches": [
            {"input_tokens": 20, "reasoning_tokens": 10, "visible_output_tokens": 0},
            {"input_tokens": None, "reasoning_tokens": 3, "visible_output_tokens": 18},
        ],
        "elapsed_seconds": 3,
        "outcomes": {"readable": False},
    }
    result = run_comparison(case, "existing", "test-model", 1000, {"calls": 2})
    assert result.calls == 2 and result.input_tokens is None and result.cost is None
    assert result.visible_output_tokens == 18 and result.reasoning_tokens == 13
    assert result.outcomes == {"readable": False}
