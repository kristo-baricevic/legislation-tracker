import pytest
from jsonschema import ValidationError
from apps.legislation.enhancements.reader_discovery import validate_policy_copy


@pytest.mark.parametrize("text", [".", "...", "! ?", "   ."])
def test_punctuation_is_not_a_policy_explanation(text):
    with pytest.raises(ValidationError):
        validate_policy_copy({"title": "Creates a program", "text": text})


def test_complete_plain_english_explanation_is_accepted():
    validate_policy_copy({"title": "College support",
                          "text": "Colleges can apply for grants to help students graduate."})
