from dataclasses import asdict

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.legislation.serializers import BillListSerializer
from config.api import StrictQuerySerializer

from .insights import compare_representatives, representative_summary
from .models import BillCosponsor, Committee, CommitteeMembership, Representative, Vote
from .serializers import (
    BillCosponsorSerializer,
    CommitteeMembershipSerializer,
    CommitteeSerializer,
    RepresentativeCompareQuerySerializer,
    RepresentativeInsightQuerySerializer,
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
        if self.action == "list":
            query_serializer = RepresentativeListQuerySerializer
        elif self.action in {
            "insights",
            "sponsored_bills",
            "cosponsored_bills",
            "committees",
        }:
            query_serializer = RepresentativeInsightQuerySerializer
        elif self.action == "compare":
            query_serializer = RepresentativeCompareQuerySerializer
        else:
            query_serializer = StrictQuerySerializer
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
        if "is_current" in self.request.query_params:
            qs = qs.filter(is_current=params["is_current"])
        else:
            qs = qs.filter(is_current=True)
        return qs

    @action(detail=True, methods=["get"])
    def insights(self, request, pk=None):
        query = RepresentativeInsightQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(
            asdict(
                representative_summary(
                    representative=self.get_object(),
                    congress=query.validated_data["congress"],
                )
            )
        )

    @action(detail=True, methods=["get"], url_path="sponsored-bills")
    def sponsored_bills(self, request, pk=None):
        query = RepresentativeInsightQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        representative = self.get_object()
        bills = (
            representative.sponsored_bills.filter(
                session=query.validated_data["congress"]
            )
            .select_related("sponsor")
            .prefetch_related("bill_topics__topic")
            .order_by("-last_activity_sequence", "-id")
        )
        page = self.paginate_queryset(bills)
        return self.get_paginated_response(
            BillListSerializer(page, many=True).data
        )

    @action(detail=True, methods=["get"], url_path="cosponsored-bills")
    def cosponsored_bills(self, request, pk=None):
        query = RepresentativeInsightQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        relationships = (
            BillCosponsor.objects.filter(
                representative=self.get_object(),
                bill__session=query.validated_data["congress"],
            )
            .select_related("bill", "bill__sponsor")
            .prefetch_related("bill__bill_topics__topic")
            .order_by("-sponsorship_date", "-id")
        )
        page = self.paginate_queryset(relationships)
        return self.get_paginated_response(
            [
                {
                    "bill": BillListSerializer(item.bill).data,
                    **BillCosponsorSerializer(item).data,
                }
                for item in page
            ]
        )

    @action(detail=True, methods=["get"])
    def committees(self, request, pk=None):
        query = RepresentativeInsightQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        memberships = CommitteeMembership.objects.filter(
            representative=self.get_object(),
            congress=query.validated_data["congress"],
        ).select_related("committee").order_by("committee__name", "id")
        page = self.paginate_queryset(memberships)
        return self.get_paginated_response(
            CommitteeMembershipSerializer(page, many=True).data
        )

    @action(detail=False, methods=["get"])
    def compare(self, request):
        query = RepresentativeCompareQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        left_id, right_id = query.validated_data["ids"]
        representatives = {
            representative.id: representative
            for representative in Representative.objects.filter(pk__in=[left_id, right_id])
        }
        if len(representatives) != 2:
            return Response({"detail": "Representative not found."}, status=404)
        return Response(
            asdict(
                compare_representatives(
                    left=representatives[left_id],
                    right=representatives[right_id],
                    congress=query.validated_data["congress"],
                )
            )
        )


class CommitteeViewSet(viewsets.ReadOnlyModelViewSet):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = CommitteeSerializer
    queryset = Committee.objects.select_related("parent").order_by("chamber", "name")


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
            qs = qs.filter(congress=congress)
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
