from rest_framework import serializers


class ManualBillIngestionSerializer(serializers.Serializer):
    congress = serializers.IntegerField(min_value=1, max_value=999)
    bill_type = serializers.ChoiceField(choices=("hr", "s"))
    bill_number = serializers.RegexField(regex=r"^\d+$", max_length=32)

    def validate_bill_number(self, value):
        canonical_number = str(int(value))
        if canonical_number == "0":
            raise serializers.ValidationError("Must be a positive integer.")
        return canonical_number
