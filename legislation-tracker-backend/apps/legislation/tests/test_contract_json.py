from apps.legislation.contract_json import (
    canonical_json_string,
    contract_hash_from_dict,
)


def test_contract_hash_is_stable_for_key_order_and_string_whitespace():
    left = {
        "plain_summary": "  Creates   a pilot program. ",
        "schema_version": "1.0-stub",
        "items": [{"amount": 1.0, "label": " A "}],
    }
    right = {
        "items": [{"label": "A", "amount": 1.0}],
        "schema_version": "1.0-stub",
        "plain_summary": "Creates a pilot program.",
    }

    assert canonical_json_string(left) == canonical_json_string(right)
    assert contract_hash_from_dict(left) == contract_hash_from_dict(right)
