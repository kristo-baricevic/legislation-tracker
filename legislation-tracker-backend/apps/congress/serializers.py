from rest_framework import serializers

from .models import Representative


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
