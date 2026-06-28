import re
from collections import Counter

from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Bill, BillTopic, Topic
from .serializers import (
    BillDetailSerializer,
    BillListSerializer,
    TopicSerializer,
)
from .topic_taxonomy import TOPICS


class TopicViewSet(viewsets.ReadOnlyModelViewSet):
    """List policy topics (for bill filter dropdowns). Public."""

    permission_classes = [AllowAny]
    queryset = Topic.objects.all().order_by("name")
    serializer_class = TopicSerializer
    pagination_class = None


class BillViewSet(viewsets.ReadOnlyModelViewSet):
    """List and retrieve ingested bills. Public. Query params: session, jurisdiction, id, bill_number, status, sponsor, topic, topic_id."""

    permission_classes = [AllowAny]

    queryset = (
        Bill.objects.all()
        .order_by("-updated_at")
        .select_related("sponsor", "latest_contract")
        .prefetch_related(
            "documents",
            "latest_contract__evidence_spans",
            "bill_topics__topic",
        )
    )

    def get_serializer_class(self):
        if self.action == "list":
            return BillListSerializer
        return BillDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params

        session = params.get("session")
        if session is not None and str(session).strip() != "":
            try:
                qs = qs.filter(session=int(session))
            except ValueError:
                pass

        jurisdiction = params.get("jurisdiction")
        if jurisdiction:
            qs = qs.filter(jurisdiction=jurisdiction.strip())

        bill_pk = params.get("id")
        if bill_pk:
            try:
                qs = qs.filter(pk=int(bill_pk))
            except ValueError:
                pass

        bill_number = params.get("bill_number")
        if bill_number:
            qs = qs.filter(bill_number__icontains=bill_number.strip())

        status_q = params.get("status")
        if status_q:
            qs = qs.filter(status__icontains=status_q.strip())

        sponsor_q = params.get("sponsor")
        if sponsor_q:
            s = sponsor_q.strip()
            if s.isdigit():
                qs = qs.filter(sponsor_id=int(s))
            else:
                qs = qs.filter(sponsor__name__icontains=s)

        topic_id = params.get("topic_id")
        topic_text = params.get("topic")
        if topic_id:
            try:
                qs = qs.filter(bill_topics__topic_id=int(topic_id)).distinct()
            except ValueError:
                pass
        elif topic_text:
            t = topic_text.strip()
            qs = qs.filter(
                Q(bill_topics__topic__name__icontains=t)
                | Q(bill_topics__topic__slug__icontains=t)
            ).distinct()

        return qs

    @action(detail=False, methods=["get"], url_path="filter-options")
    def filter_options(self, request):
        """Distinct jurisdiction values present in the DB (for dropdowns)."""
        jurisdictions = (
            Bill.objects.order_by("jurisdiction")
            .values_list("jurisdiction", flat=True)
            .distinct()
        )
        return Response({"jurisdictions": list(jurisdictions)})

    @action(detail=True, methods=["get"])
    def documents(self, request, pk=None):
        """List documents for this bill (same as in detail)."""
        bill = self.get_object()
        from .serializers import BillDocumentSerializer
        return Response(BillDocumentSerializer(bill.documents.all(), many=True).data)

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
                {"error": "\"text\" field is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        text = text[:10000]
        text_lower = text.lower()

        # --- 1. Topic matching (reuses same taxonomy as update_topics) ---
        # Use word-boundary matching to avoid false positives from substrings
        # (e.g. "crime" inside "discriminate") and require multiple keyword
        # hits so a single generic word doesn't pull in a whole topic.
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
                    # Multi-word phrases: simple substring is fine
                    if kw in text_lower:
                        hit_count += 1
                else:
                    # Single words: require word boundary so "tax" doesn't
                    # match "taxonomy" and "energy" doesn't match "synergy"
                    if re.search(r"\b" + re.escape(kw) + r"\b", text_lower):
                        hit_count += 1

            min_hits = max(2, len(keywords) // 8)
            if hit_count >= min_hits:
                confidence = min(hit_count / len(keywords), 1.0)
                matched_topics.append({
                    "slug": slug,
                    "name": name,
                    "confidence": round(confidence, 4),
                    "keyword_hits": hit_count,
                })
                matched_slugs.add(slug)

        matched_topics.sort(key=lambda t: t["confidence"], reverse=True)
        matched_topics = matched_topics[:5]

        # --- 2. Extract key phrases from article ---
        stopwords = {
            "a", "an", "the", "of", "to", "and", "in", "for", "on", "at",
            "by", "or", "is", "it", "be", "as", "no", "not", "are", "was",
            "were", "has", "have", "had", "been", "will", "would", "could",
            "should", "their", "they", "them", "this", "that", "these",
            "those", "with", "from", "but", "its", "than", "more", "also",
            "about", "into", "over", "such", "can", "may", "just", "any",
            "new", "some", "all", "his", "her", "he", "she", "who", "which",
            "what", "when", "where", "how", "said", "says", "one", "two",
            "per", "out", "up", "so", "if", "do", "did", "get", "got",
            "like", "many", "much", "very", "other", "after", "before",
            "between", "through", "under", "only", "then", "each", "own",
        }
        words = re.findall(r"[a-z][a-z']{2,}", text_lower)
        word_counts = Counter(w for w in words if w not in stopwords)
        key_phrases = [w for w, _ in word_counts.most_common(20)]

        # --- 3. Find bills by topic overlap ---
        topic_bill_ids = set()
        if matched_slugs:
            topic_bill_ids = set(
                BillTopic.objects.filter(topic__slug__in=matched_slugs)
                .values_list("bill_id", flat=True)
            )

        # --- 4. Find bills by keyword hits in title/summary ---
        keyword_q = Q()
        for phrase in key_phrases[:10]:
            keyword_q |= Q(title__icontains=phrase) | Q(summary__icontains=phrase)

        keyword_bill_ids = set()
        if key_phrases:
            keyword_bill_ids = set(
                Bill.objects.filter(keyword_q)
                .values_list("id", flat=True)[:200]
            )

        # --- 5. Score and rank ---
        all_bill_ids = topic_bill_ids | keyword_bill_ids
        if not all_bill_ids:
            return Response({
                "topics": matched_topics,
                "key_phrases": key_phrases[:10],
                "bills": [],
                "article_url": article_url,
            })

        bills = (
            Bill.objects.filter(id__in=all_bill_ids)
            .select_related("sponsor")
            .prefetch_related("bill_topics__topic")
            .order_by("-updated_at")
        )

        bill_topic_map = {}
        for bt in BillTopic.objects.filter(bill_id__in=all_bill_ids).select_related("topic"):
            bill_topic_map.setdefault(bt.bill_id, set()).add(bt.topic.slug)

        scored = []
        for bill in bills:
            bill_slugs = bill_topic_map.get(bill.id, set())
            topic_overlap = len(bill_slugs & matched_slugs)

            title_lower = (bill.title or "").lower()
            summary_lower = (bill.summary or "").lower()
            kw_hits = sum(
                1 for kw in key_phrases[:10]
                if kw in title_lower or kw in summary_lower
            )

            score = (topic_overlap * 3) + kw_hits
            if score == 0:
                continue

            parts = str(bill.bill_number).strip().upper().split()
            congress_url = None
            if len(parts) >= 2:
                ordinal = f"{bill.session}th-congress"
                if parts[0] == "HR":
                    congress_url = f"https://www.congress.gov/bill/{ordinal}/house-bill/{parts[1]}"
                elif parts[0] == "S":
                    congress_url = f"https://www.congress.gov/bill/{ordinal}/senate-bill/{parts[1]}"

            scored.append({
                "id": bill.id,
                "bill_number": bill.bill_number,
                "title": bill.title,
                "status": bill.status,
                "session": bill.session,
                "sponsor_name": str(bill.sponsor) if bill.sponsor_id else None,
                "topics": sorted(bill_slugs & matched_slugs),
                "score": score,
                "congress_gov_url": congress_url,
            })

        scored.sort(key=lambda b: b["score"], reverse=True)

        return Response({
            "topics": matched_topics,
            "key_phrases": key_phrases[:10],
            "bills": scored[:20],
            "article_url": article_url,
        })
