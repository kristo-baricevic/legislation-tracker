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
    q = serializers.CharField(required=False, allow_blank=False, trim_whitespace=True)
    sort = serializers.ChoiceField(
        choices=("recent_activity", "relevance"),
        required=False,
    )
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100)

    def validate_q(self, value):
        from .search import normalize_search_text

        try:
            return normalize_search_text(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate(self, attrs):
        if attrs.get("sort") == "relevance" and not attrs.get("q"):
            raise serializers.ValidationError({"sort": "relevance requires q."})
        return attrs


class BillContractListQuerySerializer(PaginatedQuerySerializer):
    bill = serializers.IntegerField(required=False, min_value=1)
    view = serializers.ChoiceField(choices=("summary", "full"), required=False)


class BillDetailQuerySerializer(StrictQuerySerializer):
    contract_view = serializers.ChoiceField(choices=("summary", "full"), required=False)


class ReaderItemsQuerySerializer(PaginatedQuerySerializer):
    pass


class FinancialItemsQuerySerializer(PaginatedQuerySerializer):
    financial_action = serializers.ChoiceField(
        choices=(
            "appropriation",
            "authorization",
            "allocation",
            "transfer",
            "rescission",
            "reduction",
            "cancellation",
            "set_aside",
            "limitation",
            "other_explicit",
        ),
        required=False,
    )
    fiscal_year = serializers.IntegerField(
        required=False, min_value=1000, max_value=9999
    )
    line_item_id = serializers.CharField(
        required=False, allow_blank=False, max_length=255
    )
    section_id = serializers.CharField(
        required=False, allow_blank=False, max_length=255
    )

    def validate(self, attrs):
        if "line_item_id" in attrs and "section_id" in attrs:
            raise serializers.ValidationError(
                {"non_field_errors": ["Choose one association scope."]}
            )
        return attrs


class TimelineItemsQuerySerializer(PaginatedQuerySerializer):
    line_item_id = serializers.CharField(
        required=False, allow_blank=False, max_length=255
    )
    section_id = serializers.CharField(
        required=False, allow_blank=False, max_length=255
    )

    def validate(self, attrs):
        if "line_item_id" in attrs and "section_id" in attrs:
            raise serializers.ValidationError(
                {"non_field_errors": ["Choose one association scope."]}
            )
        return attrs


class DefinitionItemsQuerySerializer(PaginatedQuerySerializer):
    line_item_id = serializers.CharField(
        required=False, allow_blank=False, max_length=255
    )
    unlinked = serializers.BooleanField(required=False)

    def validate(self, attrs):
        if "line_item_id" in attrs and "unlinked" in self.initial_data:
            raise serializers.ValidationError(
                {"non_field_errors": ["Choose one association scope."]}
            )
        return attrs


class EvidenceQuerySerializer(PaginatedQuerySerializer):
    line_item_id = serializers.CharField(
        required=False, allow_blank=False, max_length=255
    )
    financial_item_id = serializers.CharField(
        required=False, allow_blank=False, max_length=255
    )
    definition_item_id = serializers.CharField(
        required=False, allow_blank=False, max_length=255
    )

    def validate(self, attrs):
        item_fields = (
            "line_item_id",
            "financial_item_id",
            "definition_item_id",
        )
        if sum(field in attrs for field in item_fields) != 1:
            raise serializers.ValidationError(
                {"non_field_errors": ["Provide exactly one supported item ID."]}
            )
        return attrs


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
            "source_order",
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


class SectionPathItemPublicSerializer(serializers.Serializer):
    level = serializers.ChoiceField(
        choices=(
            "division",
            "title",
            "subtitle",
            "chapter",
            "subchapter",
            "part",
            "subpart",
            "account",
            "subaccount",
            "subsubaccount",
            "subsubsubaccount",
            "article",
            "subdivision",
            "section",
            "appropriations_paragraph",
            "subsection",
            "paragraph",
            "subparagraph",
            "clause",
            "subclause",
            "item",
            "subitem",
        )
    )
    label = serializers.CharField(allow_blank=False, max_length=200)
    heading = serializers.CharField(allow_null=True, allow_blank=False, max_length=4000)


class FinancialPreviewPublicSerializer(serializers.Serializer):
    id = serializers.CharField(allow_blank=False, max_length=255)
    display_text = serializers.CharField(allow_blank=False, max_length=4000)
    financial_action = serializers.ChoiceField(
        choices=(
            "appropriation",
            "authorization",
            "allocation",
            "transfer",
            "rescission",
            "reduction",
            "cancellation",
            "set_aside",
            "limitation",
            "other_explicit",
        )
    )
    direction = serializers.ChoiceField(
        choices=("increase", "decrease", "neutral_transfer", "limit")
    )
    amount = serializers.CharField(allow_null=True, allow_blank=False, max_length=100)
    amount_type = serializers.ChoiceField(
        choices=("specified", "such_sums", "percentage", "ceiling")
    )
    currency = serializers.ChoiceField(choices=("USD",), allow_null=True)
    fiscal_years = serializers.ListField(
        child=serializers.IntegerField(min_value=1000, max_value=9999)
    )


class TimelinePreviewPublicSerializer(serializers.Serializer):
    id = serializers.CharField(allow_blank=False, max_length=255)
    display_text = serializers.CharField(allow_blank=False, max_length=4000)
    timeline_type = serializers.ChoiceField(
        choices=("absolute", "relative", "effective")
    )
    date = serializers.DateField(allow_null=True)
    relative_value = serializers.IntegerField(allow_null=True, min_value=0)
    relative_unit = serializers.ChoiceField(
        choices=("days", "months", "years"), allow_null=True
    )
    trigger = serializers.CharField(allow_null=True, allow_blank=False, max_length=4000)


class ReaderLineItemPublicSerializer(serializers.Serializer):
    id = serializers.CharField(allow_blank=False, max_length=255)
    source_id = serializers.CharField(allow_blank=False, max_length=255)
    section_id = serializers.CharField(allow_blank=False, max_length=255)
    section_path = SectionPathItemPublicSerializer(many=True, allow_empty=False)
    kind = serializers.ChoiceField(
        choices=(
            "requirement",
            "prohibition",
            "permission",
            "amendment",
            "applicability",
            "financial",
            "timeline",
        )
    )
    display_text = serializers.CharField(allow_blank=False, max_length=4000)
    actor = serializers.CharField(allow_null=True, allow_blank=False, max_length=4000)
    action = serializers.CharField(allow_null=True, allow_blank=False, max_length=4000)
    effect = serializers.CharField(allow_null=True, allow_blank=False, max_length=4000)
    exact_financial_count = serializers.IntegerField(min_value=0)
    exact_financial_preview = FinancialPreviewPublicSerializer(many=True)
    timeline_count = serializers.IntegerField(min_value=0)
    timeline_preview = TimelinePreviewPublicSerializer(many=True)
    definition_count = serializers.IntegerField(min_value=0)

    def validate(self, attrs):
        if len(attrs["exact_financial_preview"]) > 3:
            raise serializers.ValidationError(
                {"exact_financial_preview": ["At most three previews are allowed."]}
            )
        if len(attrs["timeline_preview"]) > 3:
            raise serializers.ValidationError(
                {"timeline_preview": ["At most three previews are allowed."]}
            )
        return attrs


class FinancialItemPublicSerializer(FinancialPreviewPublicSerializer):
    source_id = serializers.CharField(allow_blank=False, max_length=255)
    section_id = serializers.CharField(allow_blank=False, max_length=255)
    section_label = serializers.CharField(
        allow_null=True, allow_blank=False, max_length=200
    )
    section_path = SectionPathItemPublicSerializer(many=True, allow_empty=False)
    purpose = serializers.CharField(allow_null=True, allow_blank=False, max_length=4000)
    source_account = serializers.CharField(
        allow_null=True, allow_blank=False, max_length=4000
    )
    destination_account = serializers.CharField(
        allow_null=True, allow_blank=False, max_length=4000
    )


class TimelineItemPublicSerializer(TimelinePreviewPublicSerializer):
    source_id = serializers.CharField(allow_blank=False, max_length=255)
    section_id = serializers.CharField(allow_blank=False, max_length=255)
    section_label = serializers.CharField(
        allow_null=True, allow_blank=False, max_length=200
    )
    section_path = SectionPathItemPublicSerializer(many=True, allow_empty=False)


class DefinitionItemPublicSerializer(serializers.Serializer):
    id = serializers.CharField(allow_blank=False, max_length=255)
    source_id = serializers.CharField(allow_blank=False, max_length=255)
    section_id = serializers.CharField(allow_blank=False, max_length=255)
    section_label = serializers.CharField(
        allow_null=True, allow_blank=False, max_length=200
    )
    section_path = SectionPathItemPublicSerializer(many=True, allow_empty=False)
    display_text = serializers.CharField(allow_blank=False, max_length=4000)
    term = serializers.CharField(allow_blank=False, max_length=1000)
    definition = serializers.CharField(allow_blank=False, max_length=4000)
    definition_type = serializers.ChoiceField(choices=("means", "includes", "excludes"))


class EvidenceSpanPublicSerializer(serializers.Serializer):
    start_char = serializers.IntegerField(min_value=0)
    end_char = serializers.IntegerField(min_value=1)
    quoted_text = serializers.CharField(allow_blank=False)
    page_number = serializers.IntegerField(allow_null=True, min_value=1)

    def validate(self, attrs):
        if attrs["end_char"] <= attrs["start_char"]:
            raise serializers.ValidationError(
                {"end_char": ["Must be greater than start_char."]}
            )
        return attrs


class ReaderOrientationPublicSerializer(serializers.Serializer):
    purpose_clause = serializers.CharField(
        allow_null=True, allow_blank=False, max_length=4000
    )
    purpose_line_item_id = serializers.CharField(
        allow_null=True, allow_blank=False, max_length=255
    )

    def validate(self, attrs):
        if (attrs["purpose_clause"] is None) != (attrs["purpose_line_item_id"] is None):
            raise serializers.ValidationError(
                {"non_field_errors": ["Purpose fields must both be present or null."]}
            )
        return attrs


class ReaderStatsPublicSerializer(serializers.Serializer):
    line_item_count = serializers.IntegerField(min_value=0)
    financial_item_count = serializers.IntegerField(min_value=0)
    timeline_item_count = serializers.IntegerField(min_value=0)
    definition_item_count = serializers.IntegerField(min_value=0)
    section_group_count = serializers.IntegerField(min_value=0)


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


class BillContractSummarySerializer(serializers.ModelSerializer):
    document_version_label = serializers.CharField(
        source="document.version_label", read_only=True
    )
    coverage_note = serializers.SerializerMethodField()
    orientation = serializers.SerializerMethodField()
    reader_stats = serializers.SerializerMethodField()

    class Meta:
        model = BillContract
        fields = [
            "id",
            "schema_version",
            "contract_hash",
            "computed_at",
            "document",
            "document_version_label",
            "coverage_note",
            "orientation",
            "reader_stats",
        ]

    @staticmethod
    def _reader_value(obj, field, serializer_class):
        if (
            obj.schema_version != "2.1-legal-nlp"
            or obj.contract_json.get("schema_version") != "2.1-legal-nlp"
        ):
            return None
        value = obj.contract_json.get(field)
        serializer = serializer_class(data=value)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def get_coverage_note(self, obj):
        if (
            obj.schema_version != "2.1-legal-nlp"
            or obj.contract_json.get("schema_version") != "2.1-legal-nlp"
        ):
            return None
        field = serializers.CharField(allow_blank=False, max_length=4000)
        return field.run_validation(obj.contract_json.get("coverage_note"))

    def get_orientation(self, obj):
        return self._reader_value(obj, "orientation", ReaderOrientationPublicSerializer)

    def get_reader_stats(self, obj):
        return self._reader_value(obj, "reader_stats", ReaderStatsPublicSerializer)


class BillListSerializer(serializers.ModelSerializer):
    """For list view: bill fields + sponsor name + topics."""

    sponsor_name = serializers.SerializerMethodField()
    topics = BillTopicSerializer(source="bill_topics", many=True, read_only=True)
    search_rank = serializers.SerializerMethodField()
    highlights = serializers.SerializerMethodField()

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
            "search_rank",
            "highlights",
        ]

    def get_sponsor_name(self, obj):
        if obj.sponsor_id is None:
            return None
        return str(obj.sponsor)

    def get_search_rank(self, obj):
        return self.context.get("search_ranks", {}).get(obj.id)

    def get_highlights(self, obj):
        return self.context.get("search_highlights", {}).get(obj.id, [])


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
            "summary_source",
            "summary_action_date",
            "summary_version_code",
            "summary_last_updated_at",
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


class BillDetailSummarySerializer(BillDetailSerializer):
    latest_contract = BillContractSummarySerializer(read_only=True)
    summary_preview = serializers.SerializerMethodField()
    summary_has_more = serializers.SerializerMethodField()

    class Meta(BillDetailSerializer.Meta):
        fields = [
            field for field in BillDetailSerializer.Meta.fields if field != "summary"
        ]
        fields[5:5] = ["summary_preview", "summary_has_more"]

    def get_summary_preview(self, obj):
        from .reader_api import official_summary_projection

        return official_summary_projection(obj, full=False)["summary_preview"]

    def get_summary_has_more(self, obj):
        from .reader_api import official_summary_projection

        return official_summary_projection(obj, full=False)["summary_has_more"]
