from rest_framework import serializers

from .models import Representative, Vote, VoteRecord


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
