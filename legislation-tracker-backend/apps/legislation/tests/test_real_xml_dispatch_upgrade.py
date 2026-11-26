"""An orphaned pre-upgrade reservation is still a potential charge.

The golden keys are from the 2327c54 worker with this XML, bill ID, model and
settings. The upstream stub timed out on the first or second dependency page
or on its final synthesis call.
That worker persisted its actual dispatching cache row; removing its step did
not remove the reservation. The request digest covers the complete envelope
seen by the upstream provider. No git checkout is needed by the regression.
"""

# ruff: noqa: F401, F811
import hashlib
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.ingestion.document_download import extract_document_text
from apps.legislation.enhancements.providers.base import ProviderError
from apps.legislation.enhancements.reader_steps import (
    DurableReaderProvider,
    ReaderDeliveryComplete,
)
from apps.legislation.enhancements.source_packet import (
    build_enhancement_preflight,
    canonical_json_bytes,
)
from apps.legislation.models import Bill, BillDocument, BillEnhancementCallCache
from apps.legislation.tasks import run_bill_enhancement_attempt

from .test_enhancement_service import (
    _valid_credential,
    enhancement_owner,
    enhancement_settings,
)
from .test_large_bill_staged_flow import (
    GRANT,
    RecordedModel,
    _confirmation,
    _cross_section_source,
)


def _table_source():
    # Separate the project and both headers into different owned chunks.
    directory = "".join(
        f"<row><entry>Location {i}</entry><entry>{'Housing inventory. ' * 22}</entry></row>"
        for i in range(75)
    )
    table = (
        '<table><tgroup cols="3"><colspec colname="account" colnum="1"/>'
        '<colspec colname="state" colnum="2"/><colspec colname="amount" colnum="3"/>'
        '<tbody><row><entry colname="account">Army construction</entry></row>'
        f"{directory}<row><entry/><entry>Alaska</entry></row>"
        f"<row><entry>Anchorage</entry><entry>{GRANT}</entry></row></tbody></tgroup></table>"
    )
    return (
        _cross_section_source()
        .replace(f"<text>{GRANT}</text>".encode(), table.encode())
        .replace(b"legis-body>", b"engrossed-amendment-body>")
    )


# (orphaned key, SHA-256 of provider envelope)
CAPTURES = {
    "table_summary": [
        (
            "ea604a5f0ff641826e95c73c52cb375813158818f5d9d5062f3b41e20e9c8d66",
            "cfbe3035b859bfd19a9bd3de1da1e19b92e8a6130d6cb66fc5520b26f2895380",
        ),
    ],
    "s1071": [
        (
            "a3989ab9762cd6c3e0faf24adbb456fba6f94739447e69b3644a66b38ca87058",
            "4297a61c0ffa360a4cdc6aaed261be67e08f7c70caf6906f8e54d1ae0768cfc9",
        ),
        (
            "c08363f6a7c2d0269d262f22fe1e7058ca36b7c5da0b06684d17d4a1dc7186af",
            "2b160caa24f1caf8fb0650d5ef651751533cbb16e867c9a346c1720b647980ac",
        ),
    ],
    "summary": [
        (
            "f8c99ba30316e428b3a4753e7328ff8f6942eccf03d5f16e49d88dc6d6e3042f",
            "81cd6abed9c7fc5e17238f4be17e93657e9e63a380728b8d024ce0b17369d3a1",
        ),
    ],
    "cross_section": [
        (
            "b19e8194c8c6a57abd9fb4797a12747996d425358b097b39c7670339c7c34c34",
            "3f6a5646ed7afda765cd82f9cddcc74b5536d7dfdb51a72a8df12feec869241c",
        ),
        (
            "6c9e3889bf7064ac0e98b7a20422e3184ff7137ab150ca7ee2184a3a948eaf60",
            "3cf3e0af03d99bb4e59617d6b97f6e4d6c80d36891f3463c49d5b45de97ae507",
        ),
    ],
}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "source,reserved_page,history",
    [
        ("s1071", 0, "orphan"),
        ("s1071", 1, "orphan"),
        ("s1071", 0, "saved"),
        ("s1071", 0, "1365612"),
        ("s1071", 0, "acf4eba"),
        ("s1071", 0, "no_file_digest"),
        ("s1071", 0, "missing_xml"),
        ("s1071", 0, "changed_xml"),
        ("cross_section", 0, "orphan"),
        ("cross_section", 1, "orphan"),
        ("summary", 0, "orphan"),
        ("table_summary", 0, "orphan"),
    ],
    ids=[
        "s1071-identical",
        "s1071-different",
        "s1071-saved",
        "s1071-planner-v2",
        "s1071-planner-v3",
        "s1071-no-file-digest",
        "s1071-missing-xml",
        "s1071-changed-xml",
        "cross-identical",
        "cross-different",
        "summary-identical",
        "mixed-grid-summary-identical",
    ],
)
def test_worker_respects_real_xml_orphan(
    source,
    reserved_page,
    history,
    enhancement_owner,
    enhancement_settings,
    tmp_path,
    monkeypatch,
):
    if source == "s1071":
        raw = (
            Path(__file__).parent / "fixtures/xml_inventory/s1071_eah_excerpt.xml"
        ).read_bytes()
        limits = dict(
            LLM_READER_OWNED_TOKEN_TARGET=128,
            LLM_ENHANCEMENT_MAX_REQUEST_BYTES=24000,
            LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS=24000,
        )
    elif source == "table_summary":
        raw = _table_source()
        limits = dict(LLM_READER_OWNED_TOKEN_TARGET=0)
    else:
        raw = _cross_section_source().replace(
            b"</legis-body>",
            b'<section id="limit"><enum>3.</enum><text>Only public schools may qualify under section 1 of this Act.</text></section></legis-body>',
        )
        limits = dict(LLM_READER_OWNED_TOKEN_TARGET=0)
    model = RecordedModel()
    monkeypatch.setattr("apps.legislation.tasks.get_provider", lambda _: model)
    with (
        enhancement_settings,
        override_settings(
            STORAGES={
                "default": {
                    "BACKEND": "django.core.files.storage.FileSystemStorage",
                    "OPTIONS": {"location": tmp_path},
                }
            },
            LLM_READER_MAX_CALLS=0,
            LLM_READER_CALLS_PER_DELIVERY=1000,
            LLM_SOURCE_FIRST_ENABLED=False,
            LLM_READER_MAX_OUTPUT_TOKENS=24000,
            **limits,
        ),
    ):
        bill = Bill.objects.create(
            pk=606856357,
            jurisdiction="federal",
            session=119,
            bill_number="S 1071",
            title="S.1071 real XML upgrade regression",
            status="introduced",
        )
        (tmp_path / "bill.xml").write_bytes(raw)
        document = BillDocument.objects.create(
            bill=bill,
            version_label="Engrossed Amendment House",
            is_active_version=True,
            extracted_text=extract_document_text(raw, "application/xml", "bill.xml"),
            content_hash=(
                "" if history == "no_file_digest" else hashlib.sha256(raw).hexdigest()
            ),
            content_type="application/xml",
            object_storage_key="bill.xml",
            file_size_bytes=len(raw),
        )
        plan = build_enhancement_preflight(bill, reuse_publication=False)
        assert document.content_hash != plan.source_manifest["document_content_hash"]
        if history == "no_file_digest":
            assert (
                plan.source_manifest["document_xml_sha256"]
                == hashlib.sha256(raw).hexdigest()
            )
        client = APIClient()
        client.force_authenticate(enhancement_owner)
        _valid_credential(enhancement_owner)
        attempt = _confirmation(client, bill)
        model.attempt = attempt
        dispatch = DurableReaderProvider.enhance_bill
        observed = []

        def stop_at_page(provider, *, request, **kwargs):
            envelope = request.request_envelope
            selected = (
                envelope.get("source_packet", {}).get("validated_changes")
                if source.endswith("summary")
                else envelope.get("dependency_review")
            )
            if selected:
                observed.append(
                    hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()
                )
                if len(observed) == 1:
                    raise ReaderDeliveryComplete()
                # Simulate loss/replacement between the final worker checkpoint
                # and the ambiguous-reservation lookup. Rendered text is equal.
                if history == "missing_xml":
                    BillDocument.objects.filter(pk=document.pk).update(
                        object_storage_key=""
                    )
                elif history == "changed_xml":
                    changed = raw + b"\n"
                    (tmp_path / "bill.xml").write_bytes(changed)
                    BillDocument.objects.filter(pk=document.pk).update(
                        content_hash=hashlib.sha256(changed).hexdigest()
                    )
            return dispatch(provider, request=request, **kwargs)

        # Yield at the real worker boundary, with earlier stages durably saved.
        monkeypatch.setattr(DurableReaderProvider, "enhance_bill", stop_at_page)
        assert (
            run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)["status"]
            == "pending"
        )
        assert model.calls and (
            source.endswith("summary")
            or all(stage == "map" for stage, _, _ in model.calls)
        )
        if history == "saved":
            old = deepcopy(attempt.enhancement)
            old.pk = None
            old.request_fingerprint = "2327c54-saved-plan"
            old.source_manifest_json["execution_settings"][
                "reader_execution_version"
            ] = 14
            # These two fields were the only changes in the 21 captured S.1071
            # source rows. Recreate the stored snapshot even though its paid
            # step and the original planning environment are no longer present.
            for row in old.source_snapshot_json:
                if "context_planner_version" in row:
                    row.update(
                        context_planner_version=4,
                        unresolved_dependencies=["section 1701"],
                    )
            old.save(force_insert=True)
            from apps.legislation.enhancements import reader_batches

            build = reader_batches.build_reader_preflight

            def forbid_legacy_rebuild(*args, **kwargs):
                assert not kwargs.get(
                    "source_planner"
                ), "Historical snapshot was already available"
                return build(*args, **kwargs)

            monkeypatch.setattr(
                reader_batches, "build_reader_preflight", forbid_legacy_rebuild
            )
        key, old_wire = CAPTURES[source][reserved_page]
        # The v2 and v3 workers sent the same page bytes using their own
        # planner-stamped source inventories. These are their persisted keys.
        key = {
            "1365612": "0d658f97850f70f6aa860b38481cfc4f3ec80c37c0c79cc73e4230b96693deef",
            "acf4eba": "9fac3ffb97570dd056457bb937bee73a2b66a86e4a349a2908c605a1bd70b942",
        }.get(history, key)
        reservation = BillEnhancementCallCache.objects.create(
            fingerprint=key, dispatch_identity=key, status="dispatching"
        )
        assert not attempt.steps.filter(request_fingerprint=key).exists()
        # An attempted second charge is observable even if the worker ends
        # in outcome_unknown for both a duplicate dispatch and a correct fence.
        upstream = Mock(
            side_effect=ProviderError("outcome_unknown", outcome_unknown=True)
        )
        monkeypatch.setattr(model, "enhance_bill", upstream)
        attempt.refresh_from_db()
        result = run_bill_enhancement_attempt(attempt.pk, attempt.dispatch_token)
        if history in {"missing_xml", "changed_xml"}:
            assert result == {"status": "failed", "category": "source_unavailable"}
        else:
            assert result["status"] == "outcome_unknown"
        assert observed == [CAPTURES[source][0][1]] * 2
        assert (observed[0] == old_wire) == (reserved_page == 0)
        assert upstream.call_count == (0 if reserved_page == 0 else 1)
        assert not attempt.steps.filter(request_fingerprint=key).exists()
        reservation.refresh_from_db()
        assert reservation.status == "dispatching"
