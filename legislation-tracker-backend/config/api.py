from rest_framework import serializers


class StrictQuerySerializer(serializers.Serializer):
    """Reject undeclared query keys instead of silently widening a list request."""

    def to_internal_value(self, data):
        unknown_fields = sorted(set(data.keys()) - set(self.fields))
        if unknown_fields:
            raise serializers.ValidationError(
                {field: ["Unknown query parameter."] for field in unknown_fields}
            )
        return super().to_internal_value(data)


class PaginatedQuerySerializer(StrictQuerySerializer):
    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100)
