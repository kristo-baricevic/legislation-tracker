from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.bill_views import acknowledge_bill_changes, unread_change_count
from apps.accounts.models import BillViewState
from apps.legislation.models import Bill

from .cursors import (
    ChangeCursor,
    ChangeCursorValidationError,
    decode_change_cursor,
    encode_change_cursor,
    strictly_after,
    strictly_before,
)
from .events import serialize_change_event
from .models import ChangeLog
from .serializers import ChangeTimelineQuerySerializer


def _cursor_for_event(event, *, direction, purpose):
    return encode_change_cursor(
        ChangeCursor(
            version=1,
            bill_id=event.bill_id,
            direction=direction,
            purpose=purpose,
            created_at=event.created_at,
            event_id=event.id,
        )
    )


class BillChangeTimelineView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, bill_id):
        bill = get_object_or_404(Bill, pk=bill_id)
        query = ChangeTimelineQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        page_size = values.get("page_size", 20)
        base = ChangeLog.objects.filter(bill=bill).select_related("document", "contract")
        after_cursor = None
        before_cursor = None
        stored_state = None
        try:
            if values.get("after_cursor"):
                after_cursor = decode_change_cursor(
                    values["after_cursor"],
                    expected_bill_id=bill.id,
                    allowed_purposes=frozenset({"acknowledge"}),
                    allowed_directions=frozenset({"after"}),
                )
            elif values.get("before_cursor"):
                before_cursor = decode_change_cursor(
                    values["before_cursor"],
                    expected_bill_id=bill.id,
                    allowed_purposes=frozenset({"browse"}),
                    allowed_directions=frozenset({"before"}),
                )
            elif request.user.is_authenticated:
                stored_state = BillViewState.objects.filter(user=request.user, bill=bill).first()
                if (
                    stored_state
                    and stored_state.last_seen_change_created_at is not None
                    and stored_state.last_seen_change_id is not None
                ):
                    after_cursor = ChangeCursor(
                        version=1,
                        bill_id=bill.id,
                        direction="after",
                        purpose="acknowledge",
                        created_at=stored_state.last_seen_change_created_at,
                        event_id=stored_state.last_seen_change_id,
                    )
        except ChangeCursorValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        has_more_newer = False
        has_more_older = False
        if after_cursor is not None:
            entries = list(base.filter(strictly_after(after_cursor)).order_by("created_at", "id")[: page_size + 1])
            has_more_newer = len(entries) > page_size
            entries = entries[:page_size]
        elif before_cursor is not None:
            entries = list(base.filter(strictly_before(before_cursor)).order_by("-created_at", "-id")[: page_size + 1])
            has_more_older = len(entries) > page_size
            entries = list(reversed(entries[:page_size]))
        else:
            entries = list(base.order_by("-created_at", "-id")[: page_size + 1])
            has_more_older = len(entries) > page_size
            entries = list(reversed(entries[:page_size]))

        if entries:
            has_more_older = has_more_older or base.filter(
                strictly_before(
                    ChangeCursor(
                        version=1,
                        bill_id=bill.id,
                        direction="before",
                        purpose="browse",
                        created_at=entries[0].created_at,
                        event_id=entries[0].id,
                    )
                )
            ).exists()
        head = base.order_by("-created_at", "-id").first()
        page_end_cursor = (
            _cursor_for_event(entries[-1], direction="after", purpose="acknowledge")
            if entries and before_cursor is None
            else None
        )
        unread_count = None
        if request.user.is_authenticated:
            unread_count = unread_change_count(user=request.user, bill=bill)
            if unread_count is None:
                unread_count = len(entries)
        return Response(
            {
                "results": [
                    {
                        "id": entry.id,
                        **serialize_change_event(
                            change_type=entry.change_type,
                            created_at=entry.created_at,
                            old_value=entry.old_value,
                            new_value=entry.new_value,
                            document_id=entry.document_id,
                            contract_id=entry.contract_id,
                        ),
                    }
                    for entry in entries
                ],
                "page_end_cursor": page_end_cursor,
                "stream_head_cursor": _cursor_for_event(head, direction="head", purpose="stream_head") if head else None,
                "older_cursor": _cursor_for_event(entries[0], direction="before", purpose="browse") if entries else None,
                "has_more_newer": has_more_newer,
                "has_more_older": has_more_older,
                "unread_count": unread_count,
                "personalized": bool(request.user.is_authenticated),
                "initial_window_truncated": before_cursor is None and after_cursor is None and has_more_older,
            }
        )


class BillChangeAcknowledgeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, bill_id):
        bill = get_object_or_404(Bill, pk=bill_id)
        cursor_value = request.data.get("cursor")
        if not isinstance(cursor_value, str):
            return Response({"cursor": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)
        try:
            cursor = decode_change_cursor(
                cursor_value,
                expected_bill_id=bill.id,
                allowed_purposes=frozenset({"acknowledge"}),
                allowed_directions=frozenset({"after"}),
            )
            state = acknowledge_bill_changes(
                user=request.user,
                bill=bill,
                cursor=cursor,
                acknowledged_at=cursor.created_at,
            )
        except (ChangeCursorValidationError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "last_seen_change_created_at": state.last_seen_change_created_at,
                "last_seen_change_id": state.last_seen_change_id,
                "unread_count": unread_change_count(user=request.user, bill=bill),
            }
        )
