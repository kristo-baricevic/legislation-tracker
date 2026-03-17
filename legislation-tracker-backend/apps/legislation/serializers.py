from rest_framework import serializers

from .models import Bill, BillDocument


class BillDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = BillDocument
        fields = [
            "id",
            "version_label",
            "is_active_version",
            "source_url",
            "downloaded_at",
        ]


class BillListSerializer(serializers.ModelSerializer):
    """For list view: bill fields + sponsor name."""

    sponsor_name = serializers.SerializerMethodField()

    class Meta:
        model = Bill
        fields = [
            "id",
            "jurisdiction",
            "session",
            "bill_number",
            "title",
            "status",
            "sponsor_name",
            "introduced_at",
            "last_action_at",
        ]

    def get_sponsor_name(self, obj):
        if obj.sponsor_id is None:
            return None
        return str(obj.sponsor)


class BillDetailSerializer(serializers.ModelSerializer):
    """For retrieve: full bill + documents."""

    sponsor_name = serializers.SerializerMethodField()
    documents = BillDocumentSerializer(many=True, read_only=True)
    congress_gov_url = serializers.SerializerMethodField()

    class Meta:
        model = Bill
        fields = [
            "id",
            "jurisdiction",
            "session",
            "bill_number",
            "title",
            "summary",
            "status",
            "processing_status",
            "sponsor",
            "sponsor_name",
            "introduced_at",
            "last_action_at",
            "raw_text_url",
            "pdf_url",
            "source_api_id",
            "documents",
            "congress_gov_url",
            "created_at",
            "updated_at",
        ]

    def get_sponsor_name(self, obj):
        if obj.sponsor_id is None:
            return None
        return str(obj.sponsor)

    def get_congress_gov_url(self, obj):
        """Build Congress.gov bill page URL from session and bill_number."""
        if not obj.bill_number or not obj.session:
            return None
        # e.g. HR 7898 -> house-bill/7898, S 123 -> senate-bill/123
        parts = str(obj.bill_number).strip().upper().split()
        if len(parts) < 2:
            return None
        congress_ordinal = f"{obj.session}th-congress"
        if parts[0] == "HR":
            return f"https://www.congress.gov/bill/{congress_ordinal}/house-bill/{parts[1]}"
        if parts[0] == "S":
            return f"https://www.congress.gov/bill/{congress_ordinal}/senate-bill/{parts[1]}"
        return None
