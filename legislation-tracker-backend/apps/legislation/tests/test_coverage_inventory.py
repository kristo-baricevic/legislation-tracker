import hashlib

from apps.legislation.evaluation import coverage_inventory as coverage


def snapshot(text):
    return [
        {
            "source_ref": "src_0001",
            "quoted_text": text,
            "start_char": 0,
            "end_char": len(text),
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
    ]


def test_fine_and_fee_substitution_are_found_without_an_answer_key():
    text = (
        "SEC. 1. FEES\n(a) An applicant shall pay a processing fee instead of the application fee.\n"
        "SEC. 2. PENALTY\nAny person knowingly misusing information shall be fined not more than $10,000."
    )
    inventory = coverage.build_inventory(snapshot(text))
    assert any("fee" in row["kinds"] for row in inventory)
    assert any(
        "penalty" in row["kinds"] and "$10,000" in row["amounts"] for row in inventory
    )
    assert all(
        text[row["start_char"] : row["end_char"]] == row["source_text"]
        for row in inventory
    )


def test_condition_group_retains_both_conjuncts_and_alternative_children():
    text = (
        "SEC. 1. ELIGIBILITY\n(a) The Secretary shall grant status if the applicant--\n"
        "(1) holds a permit; and\n(2) completes training or performs service."
    )
    rows = coverage.build_inventory(snapshot(text))
    group = next(row for row in rows if "conditions" in row["kinds"])
    assert "holds a permit" in group["source_text"]
    assert "completes training or performs service" in group["source_text"]


def test_amount_only_in_quote_does_not_count_as_explained():
    text = "SEC. 1. PENALTY\nA person shall be fined up to $10,000 for knowingly disclosing records."
    sources = snapshot(text)
    inventory = coverage.build_inventory(sources)
    output = {
        "funding_and_timing": [
            {
                "text": "There is a fine.",
                "source_refs": ["src_0001"],
                "source_quotes": [{"source_ref": "src_0001", "quote": text}],
            }
        ]
    }
    report = coverage.assess_inventory(inventory, output, sources)
    assert report[0]["status"] == "missing_amount"
    assert report[0]["missing_amounts"] == ["$10,000"]


def test_correct_amount_still_needs_semantic_review_not_a_false_pass():
    text = "SEC. 1. PENALTY\nA person shall be fined up to $10,000 for knowingly disclosing records."
    sources = snapshot(text)
    output = {
        "funding_and_timing": [
            {
                "text": "A $10,000 grant is provided.",
                "source_refs": ["src_0001"],
                "source_quotes": [{"source_ref": "src_0001", "quote": text}],
            }
        ]
    }
    report = coverage.assess_inventory(
        coverage.build_inventory(sources), output, sources
    )
    assert report[0]["status"] == "needs_semantic_review"
    assert report[0]["semantic_verified"] is False


def test_unrelated_quote_in_same_chunk_does_not_cover_a_fine():
    text = (
        "SEC. 1. PENALTY\nA fine of $10,000 applies.\nSEC. 2. NOTICE\nPublish a notice."
    )
    sources = snapshot(text)
    output = {
        "overview": [
            {
                "text": "A fine of $10,000 applies.",
                "source_refs": ["src_0001"],
                "source_quotes": [
                    {"source_ref": "src_0001", "quote": "Publish a notice."}
                ],
            }
        ]
    }
    assert (
        coverage.assess_inventory(coverage.build_inventory(sources), output, sources)[
            0
        ]["status"]
        == "missing_explanation"
    )


def test_inventory_rejects_snapshot_drift():
    import pytest

    sources = snapshot("A fee of $25 applies.")
    sources[0]["quoted_text"] = "A fee of $50 applies."
    with pytest.raises(ValueError, match="hash"):
        coverage.build_inventory(sources)


def test_equivalent_dollar_formatting_is_not_an_omission():
    text = "SEC. 1. FEE\nA fee shall not exceed $495.00."
    sources = snapshot(text)
    output = {
        "funding_and_timing": [
            {
                "text": "The fee is capped at $495.",
                "source_refs": ["src_0001"],
                "source_quotes": [{"source_ref": "src_0001", "quote": text}],
            }
        ]
    }
    report = coverage.assess_inventory(
        coverage.build_inventory(sources), output, sources
    )
    assert report[0]["missing_amounts"] == []
    assert report[0]["status"] == "needs_semantic_review"


def test_full_document_preserves_conditions_across_trimmed_chunk_gaps():
    text = "SEC. 1. STATUS\n(a) Grant status if--\n(1) a permit is held; and\n(2) training is complete."
    cut = text.index("(1)")
    sources = []
    for index, (start, end) in enumerate(((0, cut - 1), (cut, len(text))), 1):
        raw = text[start:end]
        sources.append(
            {
                "source_ref": f"src_{index:04d}",
                "quoted_text": raw,
                "start_char": start,
                "end_char": end,
                "text_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            }
        )
    row = next(
        r
        for r in coverage.build_inventory(sources, document_text=text)
        if "conditions" in r["kinds"]
    )
    assert "training is complete" in row["source_text"]
    assert row["source_refs"] == ["src_0001", "src_0002"]


def test_pinned_bill_inventory_finds_fine_substitution_and_complete_conditions():
    from apps.legislation.evaluation.whole_bill import load_cases

    text = next(c["text"] for c in load_cases() if c["id"] == "BILLS-119hr1589ih")
    rows = coverage.build_inventory(snapshot(text))
    assert any("penalty" in r["kinds"] and "$10,000" in r["amounts"] for r in rows)
    assert any(
        "fee" in r["kinds"] and "shall not be required to pay" in r["source_text"]
        for r in rows
    )
    assert any(
        "conditions" in r["kinds"]
        and "has not abandoned" in r["source_text"]
        and "75 percent" in r["source_text"]
        for r in rows
    )


def test_appropriate_court_is_not_a_financial_provision():
    text = "SEC. 1. REVIEW\nThe appropriate court shall review the application."
    assert coverage.build_inventory(snapshot(text)) == []


def test_contents_entry_is_not_a_second_fee_provision():
    text = "Contents\nSec. 1. Application fee.\n\nSEC. 1. APPLICATION FEE.\nThe fee is $25."
    rows = coverage.build_inventory(snapshot(text))
    assert len(rows) == 1
    assert rows[0]["start_char"] == text.index("SEC. 1.")


def test_mandatory_fine_cannot_be_described_as_discretionary():
    text = "SEC. 1. PENALTY\nAny person who knowingly discloses records shall be fined not more than $10,000."
    sources = snapshot(text)
    output = {
        "key_impacts": [
            {
                "text": "Someone who knowingly discloses records may be fined up to $10,000.",
                "source_refs": ["src_0001"],
                "source_quotes": [{"source_ref": "src_0001", "quote": text}],
            }
        ]
    }
    report = coverage.assess_inventory(
        coverage.build_inventory(sources), output, sources
    )
    assert report[0]["status"] == "meaning_conflict"
    assert report[0]["meaning_errors"] == ["mandatory_fine_described_as_optional"]
