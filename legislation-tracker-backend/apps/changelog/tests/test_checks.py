from apps.changelog.checks import _inbound_changelog_reference_errors
from apps.changelog.models import ChangeLog


def test_inbound_changelog_references_are_rejected_before_migrations_fail():
    class ReferencingField:
        remote_field = type("RemoteField", (), {"model": ChangeLog})()
        name = "event"
        many_to_one = True

    class ReferencingModel:
        _meta = type(
            "Meta",
            (),
            {
                "label": "example.Reference",
                "get_fields": lambda self: [ReferencingField()],
            },
        )()

    errors = _inbound_changelog_reference_errors([ReferencingModel], ChangeLog)

    assert len(errors) == 1
    assert errors[0].id == "changelog.E001"
    assert "example.Reference.event" in errors[0].msg
