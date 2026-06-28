from rest_framework import serializers

from .models import UserPreference


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
