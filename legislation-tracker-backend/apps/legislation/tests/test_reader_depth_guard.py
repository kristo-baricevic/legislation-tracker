import pytest
from jsonschema import ValidationError

from apps.legislation.enhancements.reader_discovery import resolve_discovery
from apps.legislation.enhancements.reader_partial import validated_components

from .test_reader_facts import _output, _sources


@pytest.mark.parametrize("field", ["conditions", "exceptions"])
@pytest.mark.parametrize("depth", [8, 9])
def test_map_checks_condition_depth_before_serialization(field, depth, monkeypatch):
    sources = _sources("The agency must report.")
    result = _output(sources)
    node = {"operator": "leaf", "text": "report", "evidence_ids": ["src_0001:p0001"]}
    for _ in range(depth):
        node = {"operator": "all", "children": [node]}
    result["factual_records"][0]["claims"][0][field] = (
        [node] if field == "exceptions" else node
    )

    if depth == 8:
        assert (
            resolve_discovery(result, sources)["factual_records"]
            == result["factual_records"]
        )
        return

    def forbid(*args, **kwargs):
        pytest.fail("Serialized over-depth provider output")

    monkeypatch.setattr(
        "apps.legislation.enhancements.reader_discovery.json.dumps", forbid
    )
    with pytest.raises(ValidationError, match="condition_depth"):
        resolve_discovery(result, sources)
    with pytest.raises(ValidationError, match="condition_depth"):
        validated_components(result, sources)
