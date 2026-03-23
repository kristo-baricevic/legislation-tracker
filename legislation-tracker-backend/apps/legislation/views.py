from django.db.models import Q
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Bill, Topic
from .serializers import (
    BillDetailSerializer,
    BillListSerializer,
    TopicSerializer,
)


class TopicViewSet(viewsets.ReadOnlyModelViewSet):
    """List policy topics (for bill filter dropdowns)."""

    queryset = Topic.objects.all().order_by("name")
    serializer_class = TopicSerializer
    pagination_class = None


class BillViewSet(viewsets.ReadOnlyModelViewSet):
    """List and retrieve ingested bills. Query params: session, jurisdiction, id, bill_number, status, sponsor, topic, topic_id."""

    queryset = (
        Bill.objects.all()
        .order_by("-updated_at")
        .select_related("sponsor", "latest_contract")
        .prefetch_related("documents", "latest_contract__evidence_spans")
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
