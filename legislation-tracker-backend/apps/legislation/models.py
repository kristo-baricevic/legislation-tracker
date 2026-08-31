from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models


class ProcessingStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    COMPLETE = "complete", "Complete"
    FAILED = "failed", "Failed"


class Topic(models.Model):
    """Policy area or subject for tagging bills (e.g. climate, health care)."""

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100, unique=True, db_index=True)
    description = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "legislation_topic"

    def __str__(self):
        return self.name


class Bill(models.Model):
    """
    Canonical metadata for a single bill. No interpretation stored here.
    latest_contract is denormalized for performance (set in a later migration).
    """

    jurisdiction = models.CharField(max_length=20)  # federal, state
    session = models.IntegerField(db_index=True)  # e.g. 119
    bill_number = models.CharField(max_length=50, db_index=True)  # e.g. HR 1234
    title = models.TextField()
    summary = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=100)
    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
        db_index=True,
    )
    introduced_at = models.DateField(null=True, blank=True)
    last_action_at = models.DateTimeField(null=True, blank=True)
    sponsor = models.ForeignKey(
        "congress.Representative",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sponsored_bills",
    )
    latest_contract = models.ForeignKey(
        "legislation.BillContract",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    source_api_id = models.CharField(max_length=255, null=True, blank=True)
    metadata_hash = models.CharField(
        max_length=64, null=True, blank=True, db_index=True
    )
    last_activity_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_activity_sequence = models.BigIntegerField(
        null=True, blank=True, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "legislation_bill"
        constraints = [
            models.UniqueConstraint(
                fields=["session", "bill_number"],
                name="legislation_bill_session_number_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["-updated_at"]),
            models.Index(fields=["processing_status"]),
        ]

    def __str__(self):
        return f"{self.bill_number} ({self.session})"


class BillDocument(models.Model):
    """Original document version (PDF/XML). One per bill per version_label."""

    bill = models.ForeignKey(
        Bill,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    version_label = models.CharField(
        max_length=50
    )  # introduced, amended, engrossed, enrolled
    is_active_version = models.BooleanField(default=False, db_index=True)
    object_storage_key = models.CharField(max_length=512, null=True, blank=True)
    content_type = models.CharField(max_length=128, null=True, blank=True)
    file_size_bytes = models.PositiveIntegerField(null=True, blank=True)
    source_url = models.URLField(max_length=1024, null=True, blank=True)
    raw_text = models.TextField(null=True, blank=True)
    extracted_text = models.TextField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    downloaded_at = models.DateTimeField(null=True, blank=True)
    parsed_at = models.DateTimeField(null=True, blank=True)
    contract_generated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "legislation_billdocument"
        constraints = [
            models.UniqueConstraint(
                fields=["bill", "version_label"],
                name="legislation_billdocument_bill_version_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["bill"]),
            models.Index(fields=["version_label"]),
            models.Index(fields=["bill", "is_active_version"]),
        ]

    def __str__(self):
        return f"{self.bill_id} / {self.version_label}"


class BillContract(models.Model):
    """Structured interpretation of a bill version (plain-language contract)."""

    bill = models.ForeignKey(
        Bill,
        on_delete=models.CASCADE,
        related_name="contracts",
    )
    document = models.ForeignKey(
        BillDocument,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="contracts",
    )
    schema_version = models.CharField(max_length=20, default="1.0")
    contract_json = models.JSONField(default=dict)
    contract_hash = models.CharField(max_length=64, db_index=True)
    computed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "legislation_billcontract"
        constraints = [
            models.UniqueConstraint(
                fields=["document", "contract_hash"],
                condition=models.Q(document__isnull=False),
                name="legislation_contract_document_hash_uniq",
            ),
            models.UniqueConstraint(
                fields=["bill", "contract_hash"],
                condition=models.Q(document__isnull=True),
                name="legislation_metadata_contract_hash_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["bill"]),
            models.Index(fields=["contract_hash"]),
            models.Index(fields=["bill", "-computed_at"]),
        ]

    def __str__(self):
        return f"Contract for Bill {self.bill_id} doc {self.document_id}"


class BillSearchChunk(models.Model):
    """Bounded, rebuildable public-search projection for one bill source."""

    class Kind(models.TextChoices):
        METADATA = "metadata", "Metadata"
        CONTRACT = "contract", "Contract"
        DOCUMENT = "document", "Document"

    bill = models.ForeignKey(
        Bill,
        on_delete=models.CASCADE,
        related_name="search_chunks",
    )
    document = models.ForeignKey(
        BillDocument,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="search_chunks",
    )
    contract = models.ForeignKey(
        BillContract,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="search_chunks",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    source_key = models.CharField(max_length=255)
    ordinal = models.PositiveIntegerField(default=0)
    text = models.TextField()
    search_vector = SearchVectorField(null=True, editable=False)
    source_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "legislation_billsearchchunk"
        constraints = [
            models.UniqueConstraint(
                fields=["bill", "kind", "source_key", "ordinal"],
                name="legislation_search_chunk_source_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["bill", "kind"], name="leg_search_bill_kind_idx"),
            models.Index(fields=["bill", "source_hash"], name="leg_search_bill_hash_idx"),
            GinIndex(fields=["search_vector"], name="legislation_search_vector_gin"),
        ]


class EvidenceSpan(models.Model):
    """Maps a contract field back to exact source text (auditability)."""

    bill = models.ForeignKey(
        Bill,
        on_delete=models.CASCADE,
        related_name="evidence_spans",
    )
    document = models.ForeignKey(
        BillDocument,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="evidence_spans",
    )
    contract = models.ForeignKey(
        BillContract,
        on_delete=models.CASCADE,
        related_name="evidence_spans",
    )
    field_path = models.CharField(max_length=255)  # e.g. funding_allocations[0].amount
    start_char = models.PositiveIntegerField()
    end_char = models.PositiveIntegerField()
    quoted_text = models.TextField()
    page_number = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "legislation_evidencespan"
        indexes = [
            models.Index(fields=["contract"]),
            models.Index(fields=["bill"]),
        ]


class BillEnhancement(models.Model):
    """Private, immutable request identity and its promoted validated result."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        REFUSED = "refused", "Refused"
        OUTCOME_UNKNOWN = "outcome_unknown", "Outcome unknown"

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="bill_enhancements",
    )
    bill = models.ForeignKey(
        Bill,
        on_delete=models.CASCADE,
        related_name="private_enhancements",
    )
    provider = models.CharField(max_length=32)
    requested_model = models.CharField(max_length=128)
    reasoning_effort = models.CharField(max_length=16)
    prompt_version = models.CharField(max_length=32)
    output_schema_version = models.CharField(max_length=32)
    source_packet_version = models.CharField(max_length=32)
    source_fingerprint = models.CharField(max_length=64)
    request_fingerprint = models.CharField(max_length=64)
    source_manifest_json = models.JSONField(default=dict)
    source_snapshot_json = models.JSONField(default=list)
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    result_json = models.JSONField(null=True, blank=True)
    successful_attempt = models.OneToOneField(
        "BillEnhancementAttempt",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="promoted_enhancement",
    )
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    total_tokens = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "legislation_billenhancement"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "bill", "request_fingerprint"],
                name="legislation_enhancement_request_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["user", "bill", "-created_at"]),
            models.Index(fields=["bill", "request_fingerprint"]),
        ]


class BillEnhancementAttempt(models.Model):
    """Append-only paid-action authorization and durable work item."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        REFUSED = "refused", "Refused"
        OUTCOME_UNKNOWN = "outcome_unknown", "Outcome unknown"

    enhancement = models.ForeignKey(
        BillEnhancement,
        on_delete=models.CASCADE,
        related_name="attempts",
    )
    sequence = models.PositiveIntegerField()
    credential = models.ForeignKey(
        "accounts.LLMCredential",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="enhancement_attempts",
    )
    credential_revision = models.PositiveIntegerField()
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.PENDING,
    )
    available_at = models.DateTimeField()
    dispatch_token = models.CharField(max_length=64, blank=True, default="")
    dispatch_lease_expires_at = models.DateTimeField(null=True, blank=True)
    run_token = models.CharField(max_length=64, blank=True, default="")
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    estimated_input_tokens = models.PositiveIntegerField()
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    total_tokens = models.PositiveIntegerField(null=True, blank=True)
    provider_response_id = models.CharField(max_length=255, blank=True, default="")
    resolved_model = models.CharField(max_length=128, blank=True, default="")
    result_json = models.JSONField(null=True, blank=True)
    failure_category = models.CharField(max_length=64, blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "legislation_billenhancementattempt"
        constraints = [
            models.UniqueConstraint(
                fields=["enhancement", "sequence"],
                name="legislation_enhancement_attempt_sequence_uniq",
            ),
            models.UniqueConstraint(
                fields=["enhancement"],
                condition=models.Q(status__in=["pending", "running"]),
                name="legislation_enhancement_one_active_attempt",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "available_at"]),
            models.Index(fields=["status", "dispatch_lease_expires_at"]),
            models.Index(fields=["status", "lease_expires_at"]),
            models.Index(fields=["enhancement", "created_at"]),
        ]


class BillTopic(models.Model):
    """Many-to-many: bill tagged with topic (optional confidence)."""

    bill = models.ForeignKey(
        Bill,
        on_delete=models.CASCADE,
        related_name="bill_topics",
    )
    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        related_name="bill_topics",
    )
    confidence_score = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "legislation_billtopic"
        constraints = [
            models.UniqueConstraint(
                fields=["bill", "topic"],
                name="legislation_billtopic_bill_topic_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["topic"]),
            models.Index(fields=["bill"]),
            models.Index(fields=["topic", "bill"]),
        ]


class BillSimilarity(models.Model):
    """Precomputed similarity between two bills. Enforce bill_a_id < bill_b_id in app logic."""

    bill_a = models.ForeignKey(
        Bill,
        on_delete=models.CASCADE,
        related_name="similarity_as_a",
    )
    bill_b = models.ForeignKey(
        Bill,
        on_delete=models.CASCADE,
        related_name="similarity_as_b",
    )
    similarity_score = models.FloatField()
    method = models.CharField(max_length=50)  # embedding, title, etc.
    computed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "legislation_billsimilarity"
        constraints = [
            models.UniqueConstraint(
                fields=["bill_a", "bill_b", "method"],
                name="legislation_billsimilarity_uniq",
            ),
            models.CheckConstraint(
                check=models.Q(bill_a_id__lt=models.F("bill_b_id")),
                name="legislation_billsimilarity_ordered",
            ),
        ]
        indexes = [
            models.Index(fields=["bill_a"]),
            models.Index(fields=["bill_b"]),
            models.Index(fields=["-similarity_score"]),
        ]
