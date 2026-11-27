import pytest
from jsonschema import ValidationError

from apps.legislation.enhancements.reader_discovery import validate_policy_copy


@pytest.mark.parametrize("text", [".", "...", "! ?", "   ."])
def test_punctuation_is_not_a_policy_explanation(text):
    with pytest.raises(ValidationError):
        validate_policy_copy({"title": "Creates a program", "text": text})


def test_complete_plain_english_explanation_is_accepted():
    validate_policy_copy(
        {
            "title": "College support",
            "text": "Colleges can apply for grants to help students graduate.",
        }
    )


@pytest.mark.parametrize("verb", ["must allocate", "shall spend", "will appropriate"])
def test_s4387_authorization_is_not_mandatory_spending(verb):
    from apps.legislation.enhancements.reader_integrity import validate_numbers

    item = {
        "text": f"The Secretary {verb} $15 million annually for FY 2027–2029.",
        "source_quotes": [
            {
                "quote": "The Secretary shall award grants. There are authorized to be appropriated $15,000,000 for each of fiscal years 2027 through 2029."
            }
        ],
    }
    with pytest.raises(ValidationError):
        validate_numbers(item, path=["policy_changes"])


@pytest.mark.parametrize(
    "text,evidence",
    [
        (
            "Authorizes $15 million annually.",
            "There are authorized to be appropriated $15,000,000 annually.",
        ),
        (
            "Must allocate $15 million annually.",
            "The Secretary shall allocate $15,000,000 annually.",
        ),
        (
            "Must allocate $15 million annually.",
            "There are authorized to be appropriated $20,000,000. Of this amount the Secretary shall allocate $15,000,000 annually.",
        ),
    ],
)
def test_authorization_guard_preserves_supported_funding(text, evidence):
    from apps.legislation.enhancements.reader_integrity import validate_numbers

    validate_numbers(
        {"text": text, "source_quotes": [{"quote": evidence}]}, path=["policy_changes"]
    )


@pytest.mark.parametrize("reverse_source", [False, True])
@pytest.mark.parametrize("reverse_prose", [False, True])
@pytest.mark.parametrize("swap", [False, True], ids=["correct", "invented-mandate"])
@pytest.mark.parametrize("passive", [False, True], ids=["active", "passive"])
def test_each_outlay_in_a_single_sentence_keeps_its_authority(
    reverse_source, reverse_prose, swap, passive
):
    from contextlib import nullcontext

    from apps.legislation.enhancements.reader_integrity import validate_numbers

    source = [
        "there are authorized to be appropriated $15 million for grants",
        "the Secretary shall allocate $2 million for training",
    ]
    prose = [
        (
            "Congress authorizes $2 million for training"
            if swap
            else "Congress authorizes $15 million for grants"
        ),
        (
            "the Secretary must allocate $15 million for grants"
            if swap
            else "the Secretary must allocate $2 million for training"
        ),
    ]
    if passive:
        amount = "$15 million" if swap else "$2 million"
        prose[1] = f"{amount} must be allocated"
    with nullcontext() if not swap else pytest.raises(ValidationError):
        validate_numbers(
            {
                "text": " and ".join(prose[::-1] if reverse_prose else prose) + ".",
                "source_quotes": [
                    {
                        "quote": " and ".join(
                            source[::-1] if reverse_source else source
                        )
                        + "."
                    }
                ],
            },
            path=["summary"],
        )


@pytest.mark.parametrize("amount", ["2", "15"])
def test_a_list_of_authorized_amounts_stays_under_the_same_authority(amount):
    from apps.legislation.enhancements.reader_integrity import validate_numbers

    with pytest.raises(ValidationError):
        validate_numbers(
            {
                "text": f"The Secretary must allocate ${amount} million.",
                "source_quotes": [
                    {
                        "quote": "There are authorized to be appropriated $15 million for grants and $2 million for training."
                    }
                ],
            },
            path=["summary"],
        )
