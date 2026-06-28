from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from .models import Representative
from .serializers import RepresentativeSerializer


class RepresentativeViewSet(viewsets.ReadOnlyModelViewSet):
    """List representatives. Public. Filter by state=XX or chamber=house|senate."""

    permission_classes = [AllowAny]
    serializer_class = RepresentativeSerializer
    queryset = Representative.objects.all().order_by("state", "name")

    def get_queryset(self):
        qs = super().get_queryset()
        state = self.request.query_params.get("state", "").strip().upper()[:2]
        if state:
            qs = qs.filter(state=state)
        chamber = self.request.query_params.get("chamber", "").strip().lower()
        if chamber in ("house", "senate"):
            qs = qs.filter(chamber=chamber)
        return qs
