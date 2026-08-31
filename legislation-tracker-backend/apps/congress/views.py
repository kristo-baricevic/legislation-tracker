from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from config.api import StrictQuerySerializer

from .models import Representative, Vote
from .serializers import (
    RepresentativeListQuerySerializer,
    RepresentativeSerializer,
    VoteDetailSerializer,
    VoteListQuerySerializer,
    VoteListSerializer,
)


class RepresentativeViewSet(viewsets.ReadOnlyModelViewSet):
    """List representatives. Public. Filter by state=XX or chamber=house|senate."""

    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = RepresentativeSerializer
    queryset = Representative.objects.all().order_by("state", "name")

    def get_queryset(self):
        qs = super().get_queryset()
        query_serializer = (
            RepresentativeListQuerySerializer
            if self.action == "list"
            else StrictQuerySerializer
        )
        query = query_serializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        if self.action != "list":
            return qs
        params = query.validated_data

        state = params.get("state")
        if state:
            qs = qs.filter(state=state)
        chamber = params.get("chamber")
        if chamber:
            qs = qs.filter(chamber=chamber)
        if "is_current" in params:
            qs = qs.filter(is_current=params["is_current"])
        return qs


class VoteViewSet(viewsets.ReadOnlyModelViewSet):
    """Public roll-call votes, filterable by the canonical bill ID."""

    authentication_classes = []
    permission_classes = [AllowAny]
    queryset = Vote.objects.select_related("bill").order_by("-vote_date", "-id")

    def get_serializer_class(self):
        return VoteListSerializer if self.action == "list" else VoteDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "retrieve":
            qs = qs.prefetch_related("records__representative")
        query_serializer = (
            VoteListQuerySerializer if self.action == "list" else StrictQuerySerializer
        )
        query = query_serializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        if self.action != "list":
            return qs
        params = query.validated_data

        bill = params.get("bill")
        if bill is not None:
            qs = qs.filter(bill_id=bill)
        congress = params.get("congress")
        if congress is not None:
            qs = qs.filter(bill__session=congress)
        chamber = params.get("chamber")
        if chamber:
            qs = qs.filter(chamber=chamber)
        session_number = params.get("session_number")
        if session_number is not None:
            qs = qs.filter(session_number=session_number)
        roll_number = params.get("roll_number")
        if roll_number is not None:
            qs = qs.filter(roll_number=roll_number)
        vote_date = params.get("vote_date")
        if vote_date is not None:
            qs = qs.filter(vote_date__date=vote_date)
        return qs
