from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import TrackedBill
from apps.accounts.serializers import TrackedBillSerializer
from apps.ingestion.congress_client import CongressAPIError
from apps.ingestion.models import IngestionTaskFailure, IngestionWorkStatus
from apps.ingestion.tasks import (
    _process_bill_impl,
    backfill_process_bill_versions_for_all_bills,
    bill_key,
    dispatch_ingestion_work,
    poll_congress,
    sync_representatives,
)
from apps.legislation.models import Bill
from apps.legislation.serializers import BillListSerializer
from apps.legislation.tasks import backfill_update_topics


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
            .filter(work_item__status=IngestionWorkStatus.DEAD)
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
        with transaction.atomic():
            failure = (
                IngestionTaskFailure.objects.select_for_update()
                .select_related("work_item")
                .filter(pk=failure_id)
                .first()
            )
            if failure is None:
                return Response({"error": "failure not found"}, status=status.HTTP_404_NOT_FOUND)
            if failure.work_item is None:
                return Response(
                    {"error": "this legacy failure has no replayable work item"},
                    status=status.HTTP_409_CONFLICT,
                )
            work_item = failure.work_item
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
            failure.replay_count += 1
            failure.last_replayed_at = timezone.now()
            failure.save(update_fields=["replay_count", "last_replayed_at"])

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
