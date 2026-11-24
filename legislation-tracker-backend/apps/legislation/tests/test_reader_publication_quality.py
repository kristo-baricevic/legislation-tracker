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


@pytest.mark.parametrize('verb', ['must allocate', 'shall spend', 'will appropriate'])
def test_s4387_authorization_is_not_mandatory_spending(verb):
    from apps.legislation.enhancements.reader_integrity import validate_numbers
    item = {'text': f'The Secretary {verb} $15 million annually for FY 2027–2029.',
            'source_quotes': [{'quote': 'The Secretary shall award grants. There are authorized to be appropriated $15,000,000 for each of fiscal years 2027 through 2029.'}]}
    with pytest.raises(ValidationError):
        validate_numbers(item, path=['policy_changes'])


@pytest.mark.parametrize('text,evidence', [
    ('Authorizes $15 million annually.', 'There are authorized to be appropriated $15,000,000 annually.'),
    ('Must allocate $15 million annually.', 'The Secretary shall allocate $15,000,000 annually.'),
    ('Must allocate $15 million annually.', 'There are authorized to be appropriated $20,000,000. Of this amount the Secretary shall allocate $15,000,000 annually.'),
])
def test_authorization_guard_preserves_supported_funding(text, evidence):
    from apps.legislation.enhancements.reader_integrity import validate_numbers
    validate_numbers({'text': text, 'source_quotes': [{'quote': evidence}]}, path=['policy_changes'])
