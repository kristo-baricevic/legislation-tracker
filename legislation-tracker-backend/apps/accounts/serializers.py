from rest_framework import serializers

from apps.changelog.models import ChangeLog
from apps.congress.serializers import RepresentativeSerializer
from apps.legislation.serializers import BillListSerializer, TopicSerializer

from .models import TrackedBill, TrackedLegislator, TrackedTopic, UserPreference


class UserPreferenceSerializer(serializers.ModelSerializer):
    topic_name = serializers.CharField(source="topic.name", read_only=True)
    topic_slug = serializers.CharField(source="topic.slug", read_only=True)

    class Meta:
        model = UserPreference
        fields = ["id", "topic", "topic_name", "topic_slug", "state", "chamber"]
        extra_kwargs = {
            "topic": {"required": False, "allow_null": True},
        }


class FollowedTopicsSerializer(serializers.Serializer):
    """For the simple follow/unfollow endpoint."""

    topic_id = serializers.IntegerField()


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
