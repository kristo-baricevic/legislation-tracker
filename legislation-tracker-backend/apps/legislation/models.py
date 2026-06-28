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
    raw_text_url = models.URLField(max_length=1024, null=True, blank=True)
    pdf_url = models.URLField(max_length=1024, null=True, blank=True)
    metadata_hash = models.CharField(max_length=64, null=True, blank=True, db_index=True)
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
    version_label = models.CharField(max_length=50)  # introduced, amended, engrossed, enrolled
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
        indexes = [
            models.Index(fields=["bill"]),
            models.Index(fields=["contract_hash"]),
            models.Index(fields=["bill", "-computed_at"]),
        ]

    def __str__(self):
        return f"Contract for Bill {self.bill_id} doc {self.document_id}"


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
