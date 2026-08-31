from rest_framework import serializers

from config.api import PaginatedQuerySerializer, StrictQuerySerializer

from .models import Bill, BillContract, BillDocument, BillTopic, EvidenceSpan, Topic


class BillListQuerySerializer(PaginatedQuerySerializer):
    session = serializers.IntegerField(required=False, min_value=1)
    congress = serializers.IntegerField(required=False, min_value=1)
    id = serializers.IntegerField(required=False, min_value=1)
    jurisdiction = serializers.CharField(required=False, allow_blank=True)
    bill_number = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField(required=False, allow_blank=True)
    sponsor = serializers.CharField(required=False, allow_blank=True)
    topic = serializers.CharField(required=False, allow_blank=True)
    topic_id = serializers.IntegerField(required=False, min_value=1)


class BillContractListQuerySerializer(PaginatedQuerySerializer):
    bill = serializers.IntegerField(required=False, min_value=1)


class BillRelatedQuerySerializer(StrictQuerySerializer):
    limit = serializers.IntegerField(required=False, min_value=1, max_value=50)


class BillDocumentListQuerySerializer(PaginatedQuerySerializer):
    pass


class TopicListQuerySerializer(StrictQuerySerializer):
    pass


class TopicSerializer(serializers.ModelSerializer):
    """Policy topics for filters and tagging."""

    class Meta:
        model = Topic
        fields = ["id", "name", "slug"]


class BillTopicSerializer(serializers.ModelSerializer):
    """Topic tag on a bill, with name/slug inlined."""

    topic_id = serializers.IntegerField(source="topic.id", read_only=True)
    name = serializers.CharField(source="topic.name", read_only=True)
    slug = serializers.CharField(source="topic.slug", read_only=True)

    class Meta:
        model = BillTopic
        fields = ["topic_id", "name", "slug", "confidence_score"]


class BillDocumentSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()
    text_url = serializers.SerializerMethodField()

    class Meta:
        model = BillDocument
        fields = [
            "id",
            "version_label",
            "is_active_version",
            "content_type",
            "file_size_bytes",
            "source_url",
            "downloaded_at",
            "download_url",
            "text_url",
        ]

    def get_download_url(self, obj):
        if not (obj.object_storage_key or obj.raw_text or obj.extracted_text):
            return None
        return f"/api/documents/{obj.id}/download/"

    def get_text_url(self, obj):
        if not (obj.raw_text or obj.extracted_text):
            return None
        return f"/api/documents/{obj.id}/text/"


class EvidenceSpanSerializer(serializers.ModelSerializer):
    """Evidence rows for the latest contract (audit trail / citations)."""

    class Meta:
        model = EvidenceSpan
        fields = ["field_path", "start_char", "end_char", "quoted_text", "page_number"]


class BillContractSerializer(serializers.ModelSerializer):
    """Structured interpretation for a bill version (Phase 5)."""

    evidence_spans = EvidenceSpanSerializer(many=True, read_only=True)
    document_version_label = serializers.CharField(
        source="document.version_label", read_only=True
    )

    class Meta:
        model = BillContract
        fields = [
            "id",
            "schema_version",
            "contract_json",
            "contract_hash",
            "computed_at",
            "document",
            "document_version_label",
            "evidence_spans",
        ]


class BillListSerializer(serializers.ModelSerializer):
    """For list view: bill fields + sponsor name + topics."""

    sponsor_name = serializers.SerializerMethodField()
    topics = BillTopicSerializer(source="bill_topics", many=True, read_only=True)

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
            "topics",
        ]

    def get_sponsor_name(self, obj):
        if obj.sponsor_id is None:
            return None
        return str(obj.sponsor)


class BillDetailSerializer(serializers.ModelSerializer):
    """For retrieve: full bill + documents + latest plain-language contract + topics (Phase 5/6)."""

    sponsor_name = serializers.SerializerMethodField()
    documents = BillDocumentSerializer(many=True, read_only=True)
    congress_gov_url = serializers.SerializerMethodField()
    latest_contract = BillContractSerializer(read_only=True)
    topics = BillTopicSerializer(source="bill_topics", many=True, read_only=True)

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
            "source_api_id",
            "documents",
            "congress_gov_url",
            "latest_contract",
            "topics",
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
