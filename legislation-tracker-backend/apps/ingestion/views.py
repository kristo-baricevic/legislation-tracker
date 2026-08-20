import uuid
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import TrackedBill
from apps.accounts.serializers import TrackedBillSerializer
from apps.ingestion.congress_client import CongressAPIError
from apps.ingestion.models import (
    IngestionTaskFailure,
    IngestionWorkItem,
    IngestionWorkStatus,
)
from apps.ingestion.tasks import (
    CURRENT_CONGRESS,
    _process_bill_impl,
    backfill_process_bill_versions_for_all_bills,
    bill_key,
    dispatch_ingestion_work,
    download_document,
    poll_congress,
    process_bill_versions,
    process_bill_votes,
    sync_representatives,
)
from apps.legislation.models import Bill
from apps.legislation.serializers import BillListSerializer
from apps.legislation.tasks import (
    backfill_update_topics,
    generate_contract,
    generate_contract_for_bill,
    update_topics,
)

REPLAYABLE_STAGE_TASKS = {
    "apps.ingestion.tasks.process_bill_versions": process_bill_versions,
    "apps.ingestion.tasks.process_bill_votes": process_bill_votes,
    "apps.ingestion.tasks.download_document": download_document,
    "apps.ingestion.tasks.sync_representatives": sync_representatives,
    "apps.legislation.tasks.generate_contract": generate_contract,
    "apps.legislation.tasks.generate_contract_for_bill": generate_contract_for_bill,
    "apps.legislation.tasks.update_topics": update_topics,
}
REPLAY_CLAIM_DURATION = timedelta(minutes=5)


def parse_int_param(raw_value, field_name, *, default=None):
    if raw_value in (None, ""):
        return default, None
    try:
        return int(raw_value), None
    except (TypeError, ValueError):
        return None, Response(
            {"error": f"{field_name} must be an integer"},
            status=status.HTTP_400_BAD_REQUEST,
        )


class IngestBillView(APIView):
    """Staff-only: ingest one Congress bill and track it for the operator."""

    permission_classes = [IsAdminUser]

    def post(self, request):
        raw_congress = request.data.get("congress") or request.data.get("session") or 119
        raw_bill_type = (
            request.data.get("bill_type")
            or request.data.get("type")
            or request.data.get("billType")
        )
        raw_bill_number = (
            request.data.get("bill_number")
            or request.data.get("number")
            or request.data.get("billNumber")
        )

        if raw_bill_type in (None, ""):
            return Response(
                {"error": "bill_type is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if raw_bill_number in (None, ""):
            return Response(
                {"error": "bill_number is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        congress, error_response = parse_int_param(raw_congress, "congress")
        if error_response is not None:
            return error_response

        bill_type = str(raw_bill_type).strip().lower()
        bill_number = str(raw_bill_number).strip()
        if bill_type not in ("hr", "s"):
            return Response(
                {"error": "bill_type must be 'hr' or 's'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = _process_bill_impl(bill_key(congress, bill_type, bill_number))
        except CongressAPIError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        bill = Bill.objects.get(pk=result["bill_id"])
        tracked, created = TrackedBill.objects.get_or_create(
            user=request.user,
            bill=bill,
        )
        return Response(
            {
                "bill": BillListSerializer(bill).data,
                "tracked_bill": TrackedBillSerializer(tracked).data,
                "ingestion": result,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class PollCongressView(APIView):
    """Enqueue an immediate Congress polling task."""

    permission_classes = [IsAdminUser]

    def post(self, request):
        jurisdiction = str(request.data.get("jurisdiction") or "federal").strip()
        congress, error_response = parse_int_param(
            request.data.get("congress"),
            "congress",
            default=119,
        )
        if error_response is not None:
            return error_response

        result = poll_congress.delay(jurisdiction=jurisdiction, congress=congress)
        return Response(
            {
                "task_id": result.id,
                "task_name": "poll_congress",
                "jurisdiction": jurisdiction,
                "congress": congress,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class SyncRepresentativesView(APIView):
    """Enqueue a complete current-member roster refresh."""

    permission_classes = [IsAdminUser]

    def post(self, request):
        congress, error_response = parse_int_param(
            request.data.get("congress"),
            "congress",
            default=119,
        )
        if error_response is not None:
            return error_response
        if congress != CURRENT_CONGRESS:
            return Response(
                {"error": f"congress must be the current Congress ({CURRENT_CONGRESS})"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = sync_representatives.delay(congress=congress)
        return Response(
            {
                "task_id": result.id,
                "task_name": "sync_representatives",
                "congress": congress,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class IngestionFailureListView(APIView):
    """Staff-only view of durable work that exhausted its retry budget."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        failures = (
            IngestionTaskFailure.objects.select_related("work_item")
            .filter(
                Q(
                    work_item__status=IngestionWorkStatus.DEAD,
                    resolved_at__isnull=True,
                )
                | Q(
                    work_item__isnull=True,
                    task_name__in=REPLAYABLE_STAGE_TASKS,
                    resolved_at__isnull=True,
                )
            )
            .order_by("-created_at")
        )
        results = [
            {
                "id": failure.id,
                "task_id": failure.task_id,
                "task_name": failure.task_name,
                "work_item_id": failure.work_item_id,
                "bill_id": failure.bill_id,
                "error_message": failure.error_message,
                "replay_count": failure.replay_count,
            }
            for failure in failures
        ]
        return Response({"count": len(results), "results": results})


class ReplayIngestionFailureView(APIView):
    """Return one dead-lettered work item to the durable pending queue."""

    permission_classes = [IsAdminUser]

    def post(self, request, failure_id):
        stage_task = None
        stage_args = None
        stage_kwargs = None
        replay_claim_token = None
        with transaction.atomic():
            failure_reference = (
                IngestionTaskFailure.objects.filter(pk=failure_id)
                .values("work_item_id")
                .first()
            )
            if failure_reference is None:
                return Response(
                    {"error": "failure not found"}, status=status.HTTP_404_NOT_FOUND
                )

            # Lock the shared work item before any individual failure row. This
            # serializes concurrent replay attempts for duplicate failure history.
            work_item = None
            referenced_work_item_id = failure_reference["work_item_id"]
            if referenced_work_item_id is not None:
                work_item = (
                    IngestionWorkItem.objects.select_for_update()
                    .filter(pk=referenced_work_item_id)
                    .first()
                )
            failure = (
                IngestionTaskFailure.objects.select_for_update()
                .filter(pk=failure_id)
                .first()
            )
            if failure is None:
                return Response({"error": "failure not found"}, status=status.HTTP_404_NOT_FOUND)
            if failure.resolved_at is not None:
                return Response(
                    {"error": "failure has already been replayed"},
                    status=status.HTTP_409_CONFLICT,
                )
            if failure.work_item_id is None:
                now = timezone.now()
                if (
                    failure.replay_claim_expires_at is not None
                    and failure.replay_claim_expires_at > now
                ):
                    return Response(
                        {"error": "failure is already being replayed"},
                        status=status.HTTP_409_CONFLICT,
                    )
                stage_task = REPLAYABLE_STAGE_TASKS.get(failure.task_name)
                stage_args = failure.args_json.get("args") or []
                stage_kwargs = failure.args_json.get("kwargs") or {}
                if stage_task is None or not isinstance(stage_args, list) or not isinstance(
                    stage_kwargs, dict
                ):
                    return Response(
                        {"error": "this failure has no replayable work item"},
                        status=status.HTTP_409_CONFLICT,
                    )
                replay_claim_token = uuid.uuid4().hex
                failure.replay_claim_token = replay_claim_token
                failure.replay_claim_expires_at = now + REPLAY_CLAIM_DURATION
                failure.save(
                    update_fields=["replay_claim_token", "replay_claim_expires_at"]
                )
            else:
                if work_item is None or failure.work_item_id != work_item.id:
                    return Response(
                        {"error": "failure work item changed during replay"},
                        status=status.HTTP_409_CONFLICT,
                    )
                if work_item.status != IngestionWorkStatus.DEAD:
                    return Response(
                        {"error": "work item is not dead-lettered"},
                        status=status.HTTP_409_CONFLICT,
                    )

                work_item.status = IngestionWorkStatus.PENDING
                work_item.attempt_count = 0
                work_item.available_at = timezone.now()
                work_item.lease_expires_at = None
                work_item.celery_task_id = ""
                work_item.dispatch_token = ""
                work_item.last_error = ""
                work_item.completed_at = None
                work_item.save(
                    update_fields=[
                        "status",
                        "attempt_count",
                        "available_at",
                        "lease_expires_at",
                        "celery_task_id",
                        "dispatch_token",
                        "last_error",
                        "completed_at",
                        "updated_at",
                    ]
                )
                replayed_at = timezone.now()
                IngestionTaskFailure.objects.filter(
                    work_item=work_item,
                    resolved_at__isnull=True,
                ).update(resolved_at=replayed_at)
                failure.replay_count += 1
                failure.last_replayed_at = replayed_at
                failure.resolved_at = replayed_at
                failure.save(
                    update_fields=["replay_count", "last_replayed_at", "resolved_at"]
                )

        if stage_task is not None:
            try:
                result = stage_task.apply_async(args=stage_args, kwargs=stage_kwargs)
            except Exception as exc:
                IngestionTaskFailure.objects.filter(
                    pk=failure.id,
                    replay_claim_token=replay_claim_token,
                    resolved_at__isnull=True,
                ).update(replay_claim_token="", replay_claim_expires_at=None)
                return Response(
                    {"error": f"unable to enqueue replay: {exc}"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            replayed_at = timezone.now()
            resolved = IngestionTaskFailure.objects.filter(
                pk=failure.id,
                replay_claim_token=replay_claim_token,
                resolved_at__isnull=True,
            ).update(
                replay_count=failure.replay_count + 1,
                last_replayed_at=replayed_at,
                replay_claim_token="",
                replay_claim_expires_at=None,
                resolved_at=replayed_at,
            )
            if resolved:
                failure.replay_count += 1
            return Response(
                {
                    "id": failure.id,
                    "task_id": result.id,
                    "task_name": failure.task_name,
                    "status": "requeued",
                    "replay_count": failure.replay_count,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        try:
            dispatch_ingestion_work.delay()
        except Exception:
            # The row is already durable and beat will dispatch it shortly.
            pass
        return Response(
            {
                "id": failure.id,
                "work_item_id": work_item.id,
                "status": IngestionWorkStatus.PENDING,
                "replay_count": failure.replay_count,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class BackfillDocumentsView(APIView):
    """Enqueue document version processing for existing bills."""

    permission_classes = [IsAdminUser]

    def post(self, request):
        session, error_response = parse_int_param(request.data.get("session"), "session")
        if error_response is not None:
            return error_response

        result = backfill_process_bill_versions_for_all_bills.delay(session=session)
        body = {
            "task_id": result.id,
            "task_name": "backfill_process_bill_versions_for_all_bills",
        }
        if session is not None:
            body["session"] = session
        return Response(body, status=status.HTTP_202_ACCEPTED)


class BackfillTopicsView(APIView):
    """Enqueue topic assignment for existing bill contracts."""

    permission_classes = [IsAdminUser]

    def post(self, request):
        session, error_response = parse_int_param(request.data.get("session"), "session")
        if error_response is not None:
            return error_response

        result = backfill_update_topics.delay(session=session)
        body = {
            "task_id": result.id,
            "task_name": "backfill_update_topics",
        }
        if session is not None:
            body["session"] = session
        return Response(body, status=status.HTTP_202_ACCEPTED)
