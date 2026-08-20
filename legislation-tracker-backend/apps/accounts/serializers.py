from rest_framework import serializers

from apps.changelog.models import ChangeLog
from apps.congress.serializers import RepresentativeSerializer
from apps.legislation.serializers import BillListSerializer, TopicSerializer

from .models import TrackedBill, TrackedLegislator, TrackedTopic, UserPreference


class UserPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPreference
        fields = ["id", "state", "chamber"]


class TrackedBillSerializer(serializers.ModelSerializer):
    bill = BillListSerializer(read_only=True)

    class Meta:
        model = TrackedBill
        fields = ["id", "bill", "created_at"]


class TrackedTopicSerializer(serializers.ModelSerializer):
    topic = TopicSerializer(read_only=True)

    class Meta:
        model = TrackedTopic
        fields = ["id", "topic", "created_at"]


class TrackedLegislatorSerializer(serializers.ModelSerializer):
    representative = RepresentativeSerializer(read_only=True)

    class Meta:
        model = TrackedLegislator
        fields = ["id", "representative", "created_at"]


class TrackingFeedEntrySerializer(serializers.ModelSerializer):
    bill = BillListSerializer(read_only=True)

    class Meta:
        model = ChangeLog
        fields = [
            "id",
            "bill",
            "change_type",
            "old_value",
            "new_value",
            "created_at",
        ]
