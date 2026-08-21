from rest_framework import serializers


class LLMCredentialUpdateSerializer(serializers.Serializer):
    api_key = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        write_only=True,
        max_length=1000,
    )
    provider = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        max_length=32,
    )
    enabled = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("At least one setting is required.")
        if "provider" in attrs:
            attrs["provider"] = attrs["provider"].lower()
        return attrs
