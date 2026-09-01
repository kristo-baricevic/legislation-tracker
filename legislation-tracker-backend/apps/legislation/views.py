import re
from collections import Counter

from django.core.files.storage import FileSystemStorage, default_storage
from django.db.models import Q
from django.http import FileResponse, HttpResponse, HttpResponseRedirect
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.congress.current import current_congress
from config.api import StrictQuerySerializer

from .models import Bill, BillContract, BillDocument, BillSimilarity, BillTopic, Topic
from .reader_api import (
    ReaderContractUnavailable,
    contract_evidence_page,
    definition_items_page,
    financial_items_page,
    official_summary_projection,
    reader_items_page,
    timeline_items_page,
)
from .search import BillSearchQuery, apply_bill_list_filters, search_bills
from .serializers import (
    BillContractListQuerySerializer,
    BillContractSerializer,
    BillContractSummarySerializer,
    BillDetailQuerySerializer,
    BillDetailSerializer,
    BillDetailSummarySerializer,
    BillDocumentListQuerySerializer,
    BillDocumentSerializer,
    BillListQuerySerializer,
    BillListSerializer,
    BillRelatedQuerySerializer,
    DefinitionItemsQuerySerializer,
    EvidenceQuerySerializer,
    FinancialItemsQuerySerializer,
    ReaderItemsQuerySerializer,
    TimelineItemsQuerySerializer,
    TopicListQuerySerializer,
    TopicSerializer,
)
from .throttles import BillSearchThrottle
from .topic_taxonomy import TOPICS


class TopicViewSet(viewsets.ReadOnlyModelViewSet):
    """List policy topics for bill filters. Public."""

    authentication_classes = []
    permission_classes = [AllowAny]
    queryset = Topic.objects.all().order_by("name")
    serializer_class = TopicSerializer
    pagination_class = None

    def get_queryset(self):
        query = TopicListQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        return super().get_queryset()


class BillDocumentViewSet(viewsets.ReadOnlyModelViewSet):
    """Public access to the stored original and extracted text for a bill version."""

    authentication_classes = []
    permission_classes = [AllowAny]
    queryset = BillDocument.objects.select_related("bill").order_by("id")
    serializer_class = BillDocumentSerializer

    def get_queryset(self):
        query_serializer = (
            BillDocumentListQuerySerializer
            if self.action == "list"
            else StrictQuerySerializer
        )
        query = query_serializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        return super().get_queryset()

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        document = self.get_object()
        if document.object_storage_key:
            if isinstance(default_storage, FileSystemStorage):
                if not default_storage.exists(document.object_storage_key):
                    raise NotFound("The stored document is unavailable.")
                response = FileResponse(
                    default_storage.open(document.object_storage_key, "rb"),
                    content_type=document.content_type or "application/octet-stream",
                )
                response["Content-Disposition"] = (
                    f'attachment; filename="bill-{document.bill_id}-{document.version_label}"'
                )
                return response
            # S3-backed storage yields its configured signed/public object URL
            # without exposing the internal object key in API payloads.
            return HttpResponseRedirect(
                default_storage.url(document.object_storage_key)
            )

        text = document.raw_text or document.extracted_text
        if not text:
            raise NotFound("No stored document content is available.")
        response = HttpResponse(text, content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="bill-{document.bill_id}-{document.version_label}.txt"'
        )
        return response

    @action(detail=True, methods=["get"])
    def text(self, request, pk=None):
        document = self.get_object()
        text = document.raw_text or document.extracted_text
        if not text:
            raise NotFound("No extracted text is available.")
        return Response({"text": text})


class BillContractViewSet(viewsets.ReadOnlyModelViewSet):
    """Public contract history for a bill, newest interpretation first."""

    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = BillContractSerializer
    queryset = BillContract.objects.select_related("bill", "document").order_by(
        "-computed_at", "-id"
    )

    def get_serializer_class(self):
        if self.action == "list" and self.request.query_params.get("view") == "summary":
            return BillContractSummarySerializer
        return BillContractSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "list":
            query_serializer = BillContractListQuerySerializer
        elif self.action in {
            "reader_items",
            "financial_items",
            "timeline_items",
            "definition_items",
            "evidence",
        }:
            return qs
        else:
            query_serializer = StrictQuerySerializer
        query = query_serializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        if self.action != "list":
            return qs.prefetch_related("evidence_spans")
        bill = query.validated_data.get("bill")
        if bill is not None:
            qs = qs.filter(bill_id=bill)
        if query.validated_data.get("view", "full") == "full":
            qs = qs.prefetch_related("evidence_spans")
        return qs

    @staticmethod
    def _page_response(request, result):
        def page_url(page_number):
            if page_number is None:
                return None
            params = request.query_params.copy()
            params["page"] = str(page_number)
            return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")

        return Response(
            {
                **result,
                "next": page_url(result["next"]),
                "previous": page_url(result["previous"]),
            }
        )

    def _reader_response(self, request, query_class, projection):
        query = query_class(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            result = projection(
                self.get_object(),
                page=query.validated_data.get("page", 1),
                page_size=query.validated_data.get("page_size", 25),
                **{
                    key: value
                    for key, value in query.validated_data.items()
                    if key not in {"page", "page_size"} and key in request.query_params
                },
            )
        except ReaderContractUnavailable:
            return Response(
                {
                    "code": "reader_contract_unavailable",
                    "detail": "This contract does not have a reader projection.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        return self._page_response(request, result)

    @action(detail=True, methods=["get"], url_path="reader-items")
    def reader_items(self, request, pk=None):
        return self._reader_response(
            request, ReaderItemsQuerySerializer, reader_items_page
        )

    @action(detail=True, methods=["get"], url_path="financial-items")
    def financial_items(self, request, pk=None):
        return self._reader_response(
            request, FinancialItemsQuerySerializer, financial_items_page
        )

    @action(detail=True, methods=["get"], url_path="timeline-items")
    def timeline_items(self, request, pk=None):
        return self._reader_response(
            request, TimelineItemsQuerySerializer, timeline_items_page
        )

    @action(detail=True, methods=["get"], url_path="definition-items")
    def definition_items(self, request, pk=None):
        return self._reader_response(
            request, DefinitionItemsQuerySerializer, definition_items_page
        )

    @action(detail=True, methods=["get"])
    def evidence(self, request, pk=None):
        return self._reader_response(
            request, EvidenceQuerySerializer, contract_evidence_page
        )


class BillViewSet(viewsets.ReadOnlyModelViewSet):
    """List and retrieve ingested bills. Public."""

    authentication_classes = []
    permission_classes = [AllowAny]
    queryset = (
        Bill.objects.all()
        .order_by("-updated_at")
        .select_related("sponsor", "latest_contract")
        .prefetch_related(
            "documents",
            "bill_topics__topic",
        )
    )

    def get_serializer_class(self):
        if self.action == "list":
            return BillListSerializer
        if (
            self.action == "retrieve"
            and self.request.query_params.get("contract_view") == "summary"
        ):
            return BillDetailSummarySerializer
        return BillDetailSerializer

    def get_throttles(self):
        if self.action == "list" and "q" in self.request.query_params:
            return [BillSearchThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "list":
            query_serializer = BillListQuerySerializer
        elif self.action == "retrieve":
            query_serializer = BillDetailQuerySerializer
        elif self.action == "related":
            query_serializer = BillRelatedQuerySerializer
        else:
            query_serializer = StrictQuerySerializer
        query = query_serializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        if self.action != "list":
            if (
                self.action == "retrieve"
                and query.validated_data.get("contract_view", "full") == "full"
            ):
                qs = qs.prefetch_related("latest_contract__evidence_spans")
            return qs
        return apply_bill_list_filters(qs, query.validated_data)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        query = BillListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        search_page = search_bills(
            queryset=queryset,
            query=BillSearchQuery.from_params(query.validated_data),
        )
        hit_by_bill = {hit.bill_id: hit for hit in search_page.hits}
        bill_ids = list(hit_by_bill)
        bills = list(queryset.filter(pk__in=bill_ids))
        bills.sort(key=lambda bill: bill_ids.index(bill.id))
        serializer = self.get_serializer(
            bills,
            many=True,
            context={
                "search_ranks": {
                    bill_id: hit.rank for bill_id, hit in hit_by_bill.items()
                },
                "search_highlights": {
                    bill_id: [
                        {
                            "kind": highlight.kind,
                            "segments": [
                                {"text": segment.text, "matched": segment.matched}
                                for segment in highlight.segments
                            ],
                        }
                        for highlight in hit.highlights
                    ]
                    for bill_id, hit in hit_by_bill.items()
                },
            },
        )
        page_number = query.validated_data.get("page", 1)
        page_size = query.validated_data.get("page_size", 20)

        def page_url(next_page):
            if next_page < 1 or (next_page - 1) * page_size >= search_page.count:
                return None
            params = request.query_params.copy()
            params["page"] = str(next_page)
            return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")

        return Response(
            {
                "count": search_page.count,
                "next": page_url(page_number + 1),
                "previous": page_url(page_number - 1),
                "results": serializer.data,
            }
        )

    @action(detail=False, methods=["get"], url_path="filter-options")
    def filter_options(self, request):
        """Distinct jurisdiction values present in the DB for dropdowns."""
        query = StrictQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        jurisdictions = (
            Bill.objects.order_by("jurisdiction")
            .values_list("jurisdiction", flat=True)
            .distinct()
        )
        return Response(
            {
                "jurisdictions": list(jurisdictions),
                "current_congress": current_congress(),
            }
        )

    @action(detail=True, methods=["get"])
    def documents(self, request, pk=None):
        """List documents for this bill."""
        bill = self.get_object()
        return Response(BillDocumentSerializer(bill.documents.all(), many=True).data)

    @action(detail=True, methods=["get"], url_path="official-summary")
    def official_summary(self, request, pk=None):
        query = StrictQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(official_summary_projection(self.get_object(), full=True))

    @action(
        detail=False,
        methods=["post"],
        url_path="match-article",
        permission_classes=[AllowAny],
    )
    def match_article(self, request):
        """Match article text against bill topics and keywords. Returns ranked bills."""
        text = (request.data.get("text") or "").strip()
        article_url = (request.data.get("url") or "").strip()

        if not text:
            return Response(
                {"error": '"text" field is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        text = text[:10000]
        text_lower = text.lower()

        keyword_index = [
            (entry["slug"], entry["name"], [kw.lower() for kw in entry["keywords"]])
            for entry in TOPICS
        ]
        matched_topics = []
        matched_slugs = set()
        for slug, name, keywords in keyword_index:
            hit_count = 0
            for kw in keywords:
                if " " in kw:
                    if kw in text_lower:
                        hit_count += 1
                elif re.search(r"\b" + re.escape(kw) + r"\b", text_lower):
                    hit_count += 1

            min_hits = max(2, len(keywords) // 8)
            if hit_count >= min_hits:
                confidence = min(hit_count / len(keywords), 1.0)
                matched_topics.append(
                    {
                        "slug": slug,
                        "name": name,
                        "confidence": round(confidence, 4),
                        "keyword_hits": hit_count,
                    }
                )
                matched_slugs.add(slug)

        matched_topics.sort(key=lambda t: t["confidence"], reverse=True)
        matched_topics = matched_topics[:5]

        stopwords = {
            "a",
            "an",
            "the",
            "of",
            "to",
            "and",
            "in",
            "for",
            "on",
            "at",
            "by",
            "or",
            "is",
            "it",
            "be",
            "as",
            "no",
            "not",
            "are",
            "was",
            "were",
            "has",
            "have",
            "had",
            "been",
            "will",
            "would",
            "could",
            "should",
            "their",
            "they",
            "them",
            "this",
            "that",
            "these",
            "those",
            "with",
            "from",
            "but",
            "its",
            "than",
            "more",
            "also",
            "about",
            "into",
            "over",
            "such",
            "can",
            "may",
            "just",
            "any",
            "new",
            "some",
            "all",
            "his",
            "her",
            "he",
            "she",
            "who",
            "which",
            "what",
            "when",
            "where",
            "how",
            "said",
            "says",
            "one",
            "two",
            "per",
            "out",
            "up",
            "so",
            "if",
            "do",
            "did",
            "get",
            "got",
            "like",
            "many",
            "much",
            "very",
            "other",
            "after",
            "before",
            "between",
            "through",
            "under",
            "only",
            "then",
            "each",
            "own",
        }
        words = re.findall(r"[a-z][a-z']{2,}", text_lower)
        word_counts = Counter(w for w in words if w not in stopwords)
        key_phrases = [w for w, _ in word_counts.most_common(20)]

        topic_bill_ids = set()
        if matched_slugs:
            topic_bill_ids = set(
                BillTopic.objects.filter(topic__slug__in=matched_slugs).values_list(
                    "bill_id", flat=True
                )
            )

        keyword_q = Q()
        for phrase in key_phrases[:10]:
            keyword_q |= Q(title__icontains=phrase) | Q(summary__icontains=phrase)

        keyword_bill_ids = set()
        if key_phrases:
            keyword_bill_ids = set(
                Bill.objects.filter(keyword_q).values_list("id", flat=True)[:200]
            )

        all_bill_ids = topic_bill_ids | keyword_bill_ids
        if not all_bill_ids:
            return Response(
                {
                    "topics": matched_topics,
                    "key_phrases": key_phrases[:10],
                    "bills": [],
                    "article_url": article_url,
                }
            )

        bills = (
            Bill.objects.filter(id__in=all_bill_ids)
            .select_related("sponsor")
            .prefetch_related("bill_topics__topic")
            .order_by("-updated_at")
        )

        bill_topic_map = {}
        for bill_topic in BillTopic.objects.filter(
            bill_id__in=all_bill_ids
        ).select_related("topic"):
            bill_topic_map.setdefault(bill_topic.bill_id, set()).add(
                bill_topic.topic.slug
            )

        scored = []
        for bill in bills:
            bill_slugs = bill_topic_map.get(bill.id, set())
            topic_overlap = len(bill_slugs & matched_slugs)

            title_lower = (bill.title or "").lower()
            summary_lower = (bill.summary or "").lower()
            kw_hits = sum(
                1 for kw in key_phrases[:10] if kw in title_lower or kw in summary_lower
            )

            score = (topic_overlap * 3) + kw_hits
            if score == 0:
                continue

            parts = str(bill.bill_number).strip().upper().split()
            congress_url = None
            if len(parts) >= 2:
                ordinal = f"{bill.session}th-congress"
                if parts[0] == "HR":
                    congress_url = (
                        f"https://www.congress.gov/bill/{ordinal}/house-bill/{parts[1]}"
                    )
                elif parts[0] == "S":
                    congress_url = f"https://www.congress.gov/bill/{ordinal}/senate-bill/{parts[1]}"

            scored.append(
                {
                    "id": bill.id,
                    "bill_number": bill.bill_number,
                    "title": bill.title,
                    "status": bill.status,
                    "session": bill.session,
                    "sponsor_name": str(bill.sponsor) if bill.sponsor_id else None,
                    "topics": sorted(bill_slugs & matched_slugs),
                    "score": score,
                    "congress_gov_url": congress_url,
                }
            )

        scored.sort(key=lambda b: b["score"], reverse=True)

        return Response(
            {
                "topics": matched_topics,
                "key_phrases": key_phrases[:10],
                "bills": scored[:20],
                "article_url": article_url,
            }
        )

    @action(detail=True, methods=["get"])
    def related(self, request, pk=None):
        """Ranked bills related to this bill by precomputed similarity."""
        query = BillRelatedQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        bill = self.get_object()
        limit = query.validated_data.get("limit", 10)
        rows = (
            BillSimilarity.objects.filter(Q(bill_a=bill) | Q(bill_b=bill))
            .select_related("bill_a", "bill_a__sponsor", "bill_b", "bill_b__sponsor")
            .prefetch_related(
                "bill_a__bill_topics__topic", "bill_b__bill_topics__topic"
            )
            .order_by("-similarity_score", "id")[:limit]
        )
        results = []
        for row in rows:
            related_bill = row.bill_b if row.bill_a_id == bill.id else row.bill_a
            results.append(
                {
                    "bill": BillListSerializer(related_bill).data,
                    "similarity_score": row.similarity_score,
                    "method": row.method,
                }
            )
        return Response({"results": results})
