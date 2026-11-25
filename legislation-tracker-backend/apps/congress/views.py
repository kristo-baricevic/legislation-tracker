from dataclasses import asdict

from django.db.models import F, Prefetch, Q
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.accounts.dashboard_bill_cards import add_card_summaries
from apps.legislation.serializers import BillListSerializer
from config.api import StrictQuerySerializer

from .biography import (
    BiographyThrottle,
    representative_biography,
    unavailable_biography,
)
from .insights import compare_representatives, representative_summary
from .models import BillCosponsor, Committee, CommitteeMembership, Representative, Vote
from .profile_api import (
    ProfileQuerySerializer,
    ProfileVoteQuerySerializer,
    recorded_vote_data,
)
from .profiles import (
    recorded_votes,
    representative_profile,
    vote_coverage,
    vote_topic_summary,
)
from .serializers import (
    BillCosponsorSerializer,
    CommitteeDirectoryQuerySerializer,
    CommitteeDirectorySerializer,
    CommitteeMembershipSerializer,
    CommitteeSerializer,
    RepresentativeBillQuerySerializer,
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
    queryset = Representative.objects.all().order_by("state", "name", "id")

    def get_authenticators(self):
        # Public browsing must still work with an expired login cookie.
        if self.request.GET.get("tracking") in {"tracked", "untracked"}:
            from rest_framework.settings import api_settings

            return [auth() for auth in api_settings.DEFAULT_AUTHENTICATION_CLASSES]
        return []

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        if request.query_params.get("tracking"):
            from django.utils.cache import patch_vary_headers

            response["Cache-Control"] = "private, no-store"
            patch_vary_headers(response, ["Cookie", "Authorization"])
        return response

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "list":
            query_serializer = RepresentativeListQuerySerializer
        elif self.action in {"sponsored_bills", "cosponsored_bills"}:
            query_serializer = RepresentativeBillQuerySerializer
        elif self.action in {
            "insights",
            "committees",
        }:
            query_serializer = RepresentativeInsightQuerySerializer
        elif self.action == "compare":
            query_serializer = RepresentativeCompareQuerySerializer
        elif self.action in {"profile", "vote_summary"}:
            query_serializer = ProfileQuerySerializer
        elif self.action == "voting_record":
            query_serializer = ProfileVoteQuerySerializer
        else:
            query_serializer = StrictQuerySerializer
        query = query_serializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        if self.action != "list":
            return qs
        params = query.validated_data
        tracking = params.get("tracking")
        if tracking:
            from rest_framework.exceptions import NotAuthenticated

            from apps.accounts.models import TrackedLegislator

            if not self.request.user.is_authenticated:
                raise NotAuthenticated("Log in to filter tracked representatives.")
            ids = TrackedLegislator.objects.filter(user=self.request.user).values(
                "representative_id"
            )
            qs = (
                qs.filter(pk__in=ids)
                if tracking == "tracked"
                else qs.exclude(pk__in=ids)
            )

        for token in params.get("search", "").split():
            qs = qs.filter(name__icontains=token)

        state = params.get("state")
        if state:
            qs = qs.filter(state=state)
        chamber = params.get("chamber")
        if chamber:
            qs = qs.filter(chamber=chamber)
        party = params.get("party")
        if party:
            aliases = {
                "D": ("D", "Democrat", "Democratic"),
                "R": ("R", "Republican"),
                "I": ("I", "ID", "Independent"),
            }
            party_query = Q()
            for alias in aliases[party]:
                party_query |= Q(party__iexact=alias)
            qs = qs.filter(party_query)
        if "is_current" in self.request.query_params:
            qs = qs.filter(is_current=params["is_current"])
        else:
            qs = qs.filter(is_current=True)
        return qs

    @action(detail=True, methods=["get"])
    def card(self, request, pk=None):
        from apps.accounts.legislator_cards import cards_for_representatives

        representative = self.get_object()
        return Response(
            cards_for_representatives([representative.pk])[representative.pk]
        )

    @action(detail=True, methods=["get"])
    def profile(self, request, pk=None):
        query = ProfileQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(
            representative_profile(self.get_object(), **query.validated_data)
        )

    @action(detail=True, methods=["get"], throttle_classes=[BiographyThrottle])
    def biography(self, request, pk=None):
        representative = self.get_object()
        from apps.research.models import RepresentativeBiography

        saved = (
            RepresentativeBiography.objects.filter(
                representative=representative, source__provider="wikipedia"
            )
            .order_by("-id")
            .first()
        )
        if saved is None:
            return Response(unavailable_biography("not_researched"))
        result = unavailable_biography(None)
        result.update(saved.evidence.get("source_snapshot", {}))
        result.update(status="available", text=saved.text)
        return Response(result)

    @action(detail=True, methods=["get"], url_path="topic-activity")
    def topic_activity(self, request, pk=None):
        representative = self.get_object()  # Strict no-query contract and 404 first.
        try:
            from .topic_activity import representative_topic_activity
        except ModuleNotFoundError as error:
            if error.name != "apps.congress.topic_activity":
                raise
            # Parent integrates the separately reviewed recommendation module.
            return Response(
                {"detail": "Topic activity is unavailable in this build."}, status=503
            )
        return Response(
            representative_topic_activity(representative.id, captured_at=timezone.now())
        )

    @action(detail=True, methods=["get"], url_path="voting-record")
    def voting_record(self, request, pk=None):
        query = ProfileVoteQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        representative = self.get_object()
        congress = query.validated_data["congress"]
        chamber = query.validated_data.get("chamber")
        rows = recorded_votes(representative, congress, chamber)
        position = query.validated_data.get("position")
        if position == "no_vote":
            rows = rows.filter(position__in=("present", "not_voting"))
        elif position:
            rows = rows.filter(position=position)
        if topic_id := query.validated_data.get("topic_id"):
            rows = rows.filter(vote__bill__bill_topics__topic_id=topic_id).distinct()
        page = self.paginate_queryset(rows)
        response = self.get_paginated_response(
            [recorded_vote_data(row) for row in page]
        )
        response.data.update(
            {
                "page_read_at": timezone.now(),
                "pagination_mode": "live_pages",
                "coverage": vote_coverage(representative, congress, chamber),
            }
        )
        return response

    @action(detail=True, methods=["get"], url_path="vote-summary")
    def vote_summary(self, request, pk=None):
        query = ProfileQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(
            vote_topic_summary(
                self.get_object(),
                query.validated_data["congress"],
                query.validated_data.get("chamber"),
            )
        )

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
        query = RepresentativeBillQuerySerializer(data=request.query_params)
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
        if topic_id := query.validated_data.get("topic_id"):
            bills = bills.filter(bill_topics__topic_id=topic_id).distinct()
        page = self.paginate_queryset(bills)
        cards = BillListSerializer(page, many=True).data
        add_card_summaries([{"bill": card} for card in cards])
        return self.get_paginated_response(cards)

    @action(detail=True, methods=["get"], url_path="cosponsored-bills")
    def cosponsored_bills(self, request, pk=None):
        query = RepresentativeBillQuerySerializer(data=request.query_params)
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
        if topic_id := query.validated_data.get("topic_id"):
            relationships = relationships.filter(
                bill__bill_topics__topic_id=topic_id
            ).distinct()
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
        memberships = (
            CommitteeMembership.objects.filter(
                representative=self.get_object(),
                congress=query.validated_data["congress"],
            )
            .select_related("committee")
            .order_by("committee__name", "id")
        )
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
            for representative in Representative.objects.filter(
                pk__in=[left_id, right_id]
            )
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
    serializer_class = CommitteeDirectorySerializer
    queryset = Committee.objects.select_related("parent").order_by(
        "chamber", "name", "id"
    )

    def directory_scope(self):
        from .current import current_congress

        query = CommitteeDirectoryQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        return query.validated_data.get(
            "congress", current_congress()
        ), query.validated_data.get("chamber")

    def get_queryset(self):
        congress, chamber = self.directory_scope()
        members = (
            CommitteeMembership.objects.filter(congress=congress, is_current=True)
            .select_related("representative")
            .order_by(F("rank").asc(nulls_last=True), "representative__name", "id")
        )
        qs = super().get_queryset().filter(is_current=True)
        if chamber:
            qs = qs.filter(chamber=chamber)
        query = CommitteeDirectoryQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        for token in filters.get("search", "").split():
            qs = qs.filter(name__icontains=token)
        if filters.get("level"):
            qs = qs.filter(parent__isnull=filters["level"] == "committee")
        if filters.get("member"):
            matching_members = members
            for token in filters["member"].replace(",", " ").split():
                matching_members = matching_members.filter(
                    representative__name__icontains=token
                )
            qs = qs.filter(pk__in=matching_members.values("committee_id"))
        if filters.get("topic_id"):
            from apps.legislation.models import Bill

            sponsors = Bill.objects.filter(
                jurisdiction="federal",
                session=congress,
                bill_topics__topic_id=filters["topic_id"],
            ).values("sponsor_id")
            qs = qs.filter(
                pk__in=members.filter(representative_id__in=sponsors).values(
                    "committee_id"
                )
            )
        return qs.prefetch_related(
            Prefetch("memberships", queryset=members, to_attr="directory_members")
        )

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        response.data["congress"] = self.directory_scope()[0]
        return response

    @action(detail=True, methods=["get"], url_path="introduced-bills")
    def introduced_bills(self, request, pk=None):
        from apps.legislation.models import Bill

        congress, _ = self.directory_scope()
        committee = self.get_object()
        members = CommitteeMembership.objects.filter(
            committee=committee, congress=congress, is_current=True
        ).values("representative_id")
        bills = (
            Bill.objects.filter(
                jurisdiction="federal", session=congress, sponsor_id__in=members
            )
            .select_related("sponsor")
            .prefetch_related("bill_topics__topic")
            .order_by(F("introduced_at").desc(nulls_last=True), "-id")
        )
        query = CommitteeDirectoryQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        if query.validated_data.get("topic_id"):
            bills = bills.filter(bill_topics__topic_id=query.validated_data["topic_id"])
        page = self.paginate_queryset(bills)
        cards = BillListSerializer(page, many=True).data
        add_card_summaries([{"bill": card} for card in cards])
        return self.get_paginated_response(cards)


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
