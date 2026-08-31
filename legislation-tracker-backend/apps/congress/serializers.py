from rest_framework import serializers

from config.api import PaginatedQuerySerializer

from .models import Representative, Vote, VoteRecord

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
            "chamber",
            "session_number",
            "roll_number",
            "vote_date",
            "result",
            "yeas",
            "nays",
        ]


class VoteDetailSerializer(VoteListSerializer):
    records = VoteRecordSerializer(many=True, read_only=True)

    class Meta(VoteListSerializer.Meta):
        fields = VoteListSerializer.Meta.fields + ["records"]
