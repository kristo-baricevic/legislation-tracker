from rest_framework import serializers

from config.api import StrictQuerySerializer


class ChangeTimelineQuerySerializer(StrictQuerySerializer):
    after_cursor = serializers.CharField(required=False, allow_blank=False)
    before_cursor = serializers.CharField(required=False, allow_blank=False)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100)

    def validate(self, attrs):
        if attrs.get("after_cursor") and attrs.get("before_cursor"):
            raise serializers.ValidationError(
                "after_cursor and before_cursor cannot be combined."
            )
        return attrs
