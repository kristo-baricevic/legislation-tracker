"""Exercise public wording independently of the provider's proposed summary."""

from types import SimpleNamespace

import pytest

from apps.legislation.enhancements.funding_publication import UNRESOLVED
from apps.legislation.enhancements.serializers import _expanded_result


@pytest.mark.parametrize("version", ["1.1", "1.3", "1.4", "2.0-source-first"])
@pytest.mark.parametrize(
    "source,proposal,expected",
    [
        (
            "The Secretary shall spend between $50 and $100 per year for grants only if Congress approves.",
            "The Governor may spend exactly $100 for grants.",
            "The Secretary must spend between $50 and $100 per year for grants only if Congress approves.",
        ),
        (
            "The Secretary shall spend at most $100 for salaries.",
            "The Secretary must spend at most $100 for salaries.",
            "The Secretary must spend at most $100 for salaries.",
        ),
        (
            "There is authorized to be appropriated $100 for grants.",
            "Congress gives the program the cash.",
            "The bill authorizes appropriations of $100 for grants.",
        ),
        (
            "For grants, subject to section 9: $100.",
            "The bill appropriates $100 for grants.",
            "For grants, subject to section 9: $100.",
        ),
        ("", "The bill appropriates $100.", UNRESOLVED),
    ],
)
def test_reader_projects_funding_from_complete_pinned_passages(
    version, source, proposal, expected
):
    ref = "src_0001"
    sources = [{"source_ref": ref, "quoted_text": source}] if source else []
    if version == "2.0-source-first":
        raw = {
            "schema_version": version,
            "synopsis": {
                "status": "complete",
                "text": proposal,
                "explanation_ids": ["u1"],
            },
            "provisions": [
                {
                    "unit_id": "u1",
                    "status": "explained",
                    "summary": proposal,
                    "details": [proposal],
                    "evidence": [{"id": ref, "text": source}] if source else [],
                    "claims": [
                        {
                            "action": proposal,
                            "money": [{}],
                            "evidence_ids": [ref] if source else [],
                        }
                    ],
                }
            ],
        }
    else:
        key = "summary" if version == "1.4" else "overview"
        raw = {
            "schema_version": version,
            key: [{"text": proposal, "source_refs": [ref]}],
            "explanations": [],
        }
        if source:
            raw[key][0]["source_quotes"] = [
                {"source_ref": ref, "quote": source.split(" only if")[0]}
            ]
    saved = SimpleNamespace(
        result_json=raw,
        source_snapshot_json=sources,
        source_manifest_json={
            "document_id": 1,
            "document_content_hash": "test",
            "contract_id": None,
            "contract_hash": None,
        },
    )
    public = _expanded_result(saved)
    if version == "2.0-source-first":
        assert (
            public["synopsis"]["text"] == public["provisions"][0]["summary"] == expected
        )
        claim = public["provisions"][0]["claims"][0]
        assert claim["funding_text"] == claim["action"] == expected
        assert claim["money"] == []
        assert public["provisions"][0]["details"] == []
    else:
        assert public[key][0]["text"] == expected
        assert _expanded_result(saved, preview_only=True)[key][0]["text"] == expected
