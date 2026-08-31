from rest_framework import serializers

from config.api import PaginatedQuerySerializer, StrictQuerySerializer

from .models import (
    BillCosponsor,
    Committee,
    CommitteeMembership,
    Representative,
    Vote,
    VoteRecord,
)

CHAMBER_CHOICES = ("house", "senate")


class RepresentativeListQuerySerializer(PaginatedQuerySerializer):
    state = serializers.RegexField(
        regex=r"^[A-Za-z]{2}$",
        required=False,
        allow_blank=True,
    )
    chamber = serializers.ChoiceField(
        choices=CHAMBER_CHOICES,
        required=False,
        allow_blank=True,
    )
    is_current = serializers.BooleanField(required=False)

    def validate_state(self, value):
        return value.upper()


class VoteListQuerySerializer(PaginatedQuerySerializer):
    bill = serializers.IntegerField(required=False, min_value=1)
    congress = serializers.IntegerField(required=False, min_value=1)
    chamber = serializers.ChoiceField(
        choices=CHAMBER_CHOICES,
        required=False,
        allow_blank=True,
    )
    session_number = serializers.IntegerField(required=False, min_value=1)
    roll_number = serializers.IntegerField(required=False, min_value=1)
    vote_date = serializers.DateField(required=False)


class RepresentativeInsightQuerySerializer(StrictQuerySerializer):
    congress = serializers.IntegerField(min_value=1)


class RepresentativeCompareQuerySerializer(StrictQuerySerializer):
    ids = serializers.CharField(max_length=64)
    congress = serializers.IntegerField(min_value=1)

    def validate_ids(self, value):
        try:
            ids = [int(item) for item in value.split(",")]
        except ValueError as exc:
            raise serializers.ValidationError(
                "ids must be comma-separated integers."
            ) from exc
        if len(ids) != 2 or ids[0] == ids[1] or any(item < 1 for item in ids):
            raise serializers.ValidationError(
                "ids must contain exactly two distinct IDs."
            )
        return ids


class RepresentativeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Representative
        fields = [
            "id",
            "bioguide_id",
            "name",
            "chamber",
            "party",
            "state",
            "district",
            "first_name",
            "last_name",
            "official_website_url",
            "image_url",
            "is_current",
        ]


class VoteRecordSerializer(serializers.ModelSerializer):
    representative = RepresentativeSerializer(read_only=True)

    class Meta:
        model = VoteRecord
        fields = ["representative", "position"]


class VoteListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vote
        fields = [
            "id",
            "bill",
            "congress",
            "chamber",
            "session_number",
            "roll_number",
            "vote_date",
            "result",
            "yeas",
            "nays",
            "question",
            "source_url",
        ]


class VoteDetailSerializer(VoteListSerializer):
    records = VoteRecordSerializer(many=True, read_only=True)

    class Meta(VoteListSerializer.Meta):
        fields = VoteListSerializer.Meta.fields + ["records"]


class CommitteeSerializer(serializers.ModelSerializer):
    parent_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Committee
        fields = [
            "id",
            "system_code",
            "name",
            "chamber",
            "committee_type",
            "parent_id",
            "website_url",
            "is_current",
            "source_updated_at",
        ]


class CommitteeMembershipSerializer(serializers.ModelSerializer):
    committee = CommitteeSerializer(read_only=True)

    class Meta:
        model = CommitteeMembership
        fields = [
            "committee",
            "congress",
            "rank",
            "role",
            "party_side",
            "source_name",
            "source_code",
            "is_current",
        ]


class BillCosponsorSerializer(serializers.ModelSerializer):
    bill_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = BillCosponsor
        fields = [
            "bill_id",
            "sponsorship_date",
            "is_original_cosponsor",
            "withdrawn_at",
        ]
