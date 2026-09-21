from apps.legislation.evaluation.reader_quality import nlp_items, score_reader
from apps.legislation.tests.test_reader_quality import extract_fixture


def test_glossary_explains_terms_and_discloses_unresolved_references():
    _, result = extract_fixture()
    terms = {d["term"].lower(): d for d in result.contract_json["definitions"]}
    assert "two-year" in terms["completion rate"]["display_text"]
    assert "four-year" in terms["completion rate"]["display_text"]
    assert "transfer" in terms["completion rate"]["display_text"]
    assert "public" in terms["eligible entity"]["display_text"].lower()
    assert (
        "cost-effectiveness"
        in terms["evidence tier 2 reform or practice"]["display_text"]
    )
    assert "unclear" in terms["evidence tier 3 reform or practice"]["display_text"]
    assert (
        "Unresolved legal reference"
        in terms["first generation college student"]["display_text"]
    )
    assert "402A(h)" in terms["first generation college student"]["definition"]
    assert (
        score_reader({}, nlp_items(result.contract_json))["metrics"][
            "unexplained_definition_count"
        ]
        == 0
    )


def test_glossary_eval_rejects_citation_only_explanations_and_reports_coverage():
    report = score_reader(
        {},
        [
            {
                "category": "definition",
                "text": "Defines “student” to mean the meaning given the term in section 101.",
            }
        ],
    )
    assert not report["passed"]
    assert report["metrics"]["unexplained_definition_count"] == 1
    disclosed = score_reader(
        {},
        [
            {
                "category": "definition",
                "text": "Unresolved legal reference. This bill uses a definition from another law; its meaning has not been verified here.",
            }
        ],
    )
    assert disclosed["passed"]
    assert disclosed["metrics"]["unresolved_definition_count"] == 1


def test_glossary_rules_do_not_reuse_explanation_when_legal_meaning_changes():
    from apps.legislation.extraction.glossary import explain_definition

    text = "a public institution of higher education; a partnership between a nonprofit educational organization and an institution of higher education; or a consortium of institutions of higher education"
    assert explain_definition("eligible entity", text, "means").startswith(
        "Public colleges"
    )
    assert explain_definition(
        "eligible entity", text + "; excluding community colleges", "means"
    ).startswith("Legal definition:")
    assert explain_definition("eligible entity", text, "excludes").startswith(
        "Excludes:"
    )


def test_glossary_gold_facts_catch_lost_qualifiers_and_wrong_term_attribution():
    case, result = extract_fixture()
    items = nlp_items(result.contract_json)
    assert score_reader(case, items, pipeline="nlp")["passed"]
    changed = [dict(item) for item in items]
    tier = next(
        item
        for item in changed
        if item.get("term") == "evidence tier 2 reform or practice"
    )
    tier["text"] = "An approach that has been successfully implemented."
    report = score_reader(case, changed, pipeline="nlp")
    assert "glossary_tier2_preserves_conditions" in report["missing_facts"]
    tier["text"] = next(
        item["text"] for item in items if item.get("term") == tier["term"]
    )
    tier["term"] = "different term"
    assert (
        "glossary_tier2_preserves_conditions"
        in score_reader(case, changed, pipeline="nlp")["missing_facts"]
    )
