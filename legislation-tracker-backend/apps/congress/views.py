from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from .models import Representative, Vote
from .serializers import (
    RepresentativeSerializer,
    VoteDetailSerializer,
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
        state = self.request.query_params.get("state", "").strip().upper()[:2]
        if state:
            qs = qs.filter(state=state)
        chamber = self.request.query_params.get("chamber", "").strip().lower()
        if chamber in ("house", "senate"):
            qs = qs.filter(chamber=chamber)
        return qs


class VoteViewSet(viewsets.ReadOnlyModelViewSet):
    """Public roll-call votes, filterable by the canonical bill ID."""

    authentication_classes = []
    permission_classes = [AllowAny]
    queryset = (
        Vote.objects.select_related("bill")
        .prefetch_related("records__representative")
        .order_by("-vote_date", "-id")
    )

    def get_serializer_class(self):
        return VoteListSerializer if self.action == "list" else VoteDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        bill = self.request.query_params.get("bill")
        if bill:
            try:
                qs = qs.filter(bill_id=int(bill))
            except ValueError:
                pass
        return qs
