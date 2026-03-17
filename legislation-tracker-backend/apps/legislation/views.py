from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Bill
from .serializers import BillDetailSerializer, BillListSerializer


class BillViewSet(viewsets.ReadOnlyModelViewSet):
    """List and retrieve ingested bills. Optional filters: session, jurisdiction."""

    queryset = Bill.objects.all().order_by("-updated_at").select_related("sponsor")

    def get_serializer_class(self):
        if self.action == "list":
            return BillListSerializer
        return BillDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        session = self.request.query_params.get("session")
        if session is not None:
            try:
                qs = qs.filter(session=int(session))
            except ValueError:
                pass
        jurisdiction = self.request.query_params.get("jurisdiction")
        if jurisdiction:
            qs = qs.filter(jurisdiction=jurisdiction)
        return qs

    @action(detail=True, methods=["get"])
    def documents(self, request, pk=None):
        """List documents for this bill (same as in detail)."""
        bill = self.get_object()
        from .serializers import BillDocumentSerializer
        return Response(BillDocumentSerializer(bill.documents.all(), many=True).data)
