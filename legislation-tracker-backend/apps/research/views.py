from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.http import FileResponse, Http404
from django.db.models import Q
from django.core.files.storage import default_storage
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView
from config.api import StrictQuerySerializer
from apps.congress.models import Representative
from apps.campaign_finance.models import FinanceSnapshot
from apps.campaign_finance.progress import latest_preview, finance_progress
from .models import ResearchRun, RepresentativeBiography, RepresentativePortrait
from .services import request_research, validate_period
from .portraits import may_serve_portrait


class ResearchQuery(StrictQuerySerializer):
    period = serializers.IntegerField(required=False)

    def validate_period(self, value):
        try:
            return validate_period(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc


class ContributorsQuery(ResearchQuery):
    snapshot = serializers.UUIDField(required=False)
    cursor = serializers.IntegerField(min_value=0, default=0)
    sort = serializers.ChoiceField(choices=["amount", "date", "name"], default="amount")
    kind = serializers.ChoiceField(choices=["contribution", "refund"], default="contribution")


class SnapshotsQuery(ResearchQuery):
    cursor = serializers.IntegerField(min_value=0, default=0)


class ConnectionsQuery(ResearchQuery):
    snapshot = serializers.UUIDField(required=False)
    cursor = serializers.IntegerField(min_value=0, default=0)
    contributor = serializers.IntegerField(min_value=1, required=False)
    donor_cursor = serializers.IntegerField(min_value=0, default=0)
    related_cursor = serializers.IntegerField(min_value=0, default=0)
    legislative_start = serializers.DateField(required=False)
    legislative_end = serializers.DateField(required=False)

    def validate(self, data):
        start, end = data.get("legislative_start"), data.get("legislative_end")
        if bool(start) != bool(end) or (start and start > end):
            raise serializers.ValidationError("Provide both legislative dates, with start on or before end.")
        return data


class StartQuery(StrictQuerySerializer):
    period = serializers.IntegerField()
    validate_period = ResearchQuery.validate_period


def parameters(request, serializer=ResearchQuery):
    query = serializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    data = query.validated_data
    year = timezone.now().year
    data.setdefault("period", year + year % 2)
    return data


def run_data(run):
    if not run:
        return None
    status = run.status
    work = run.work_item
    if status in {"running", "queued"} and work and work.status == "dead":
        status = "failed"
    return {"id": str(run.pk), "status": status, "sections": run.sections, "created_at": run.created_at, "finished_at": run.finished_at, "retry_at": work.available_at if work and work.status == "pending" else None, "error": "Research failed. You can retry." if status == "failed" else None}


def source_data(source):
    return {"url": source.url, "attribution": source.attribution, "license": source.license, "fetched_at": source.fetched_at}


def saved_research(rep, period):
    run = ResearchRun.objects.filter(representative=rep, period=period).select_related("work_item").order_by("-created_at").first()
    bio = RepresentativeBiography.objects.filter(representative=rep).select_related("source").order_by("-id").first()
    photo = RepresentativePortrait.objects.filter(representative=rep).select_related("source").order_by("-id").first()
    snapshot = FinanceSnapshot.objects.filter(representative=rep, period=period, active=True, invalidated=False).first()
    preview = latest_preview(rep.pk, period)
    progress = finance_progress(preview or snapshot)
    snapshot = snapshot or preview
    job = run_data(run)
    return {"status": job["status"] if job else "not_started", "period": period, "run": job, "finance_progress": progress, "biography": {"text": bio.text, "source": source_data(bio.source), "kind": bio.evidence.get("kind")} if bio else None, "portrait": {"url": f"/api/representatives/{rep.pk}/portraits/{photo.pk}/" if photo.object_key and may_serve_portrait(photo) else photo.image_url, "source": source_data(photo.source)} if photo else None, "snapshot": str(snapshot.pk) if snapshot else None}


class ResearchView(APIView):
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get(self, request, representative_id):
        rep = get_object_or_404(Representative, pk=representative_id)
        return Response(saved_research(rep, parameters(request)["period"]))

    def post(self, request, representative_id):
        get_object_or_404(Representative, pk=representative_id)
        data = StartQuery(data=request.data)
        data.is_valid(raise_exception=True)
        run = request_research(representative_id, data.validated_data["period"], request.user.pk)
        return Response(run_data(run), status=202)


class ResearchRunView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, representative_id, run_id):
        return Response(run_data(get_object_or_404(ResearchRun.objects.select_related("work_item"), pk=run_id, representative_id=representative_id)))


class ContributorsView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, representative_id):
        get_object_or_404(Representative, pk=representative_id)
        data = parameters(request, ContributorsQuery)
        qs = FinanceSnapshot.objects.filter(representative_id=representative_id, period=data["period"], invalidated=False)
        preview = latest_preview(representative_id, data["period"])
        if data.get("snapshot"):
            visible = Q(published_at__isnull=False)
            if preview:
                visible |= Q(pk=preview.pk)
            snapshot = get_object_or_404(qs.filter(visible), pk=data["snapshot"])
        else:
            snapshot = qs.filter(active=True).first() or preview
        if not snapshot:
            return Response({"status": "not_researched", "snapshot": None, "results": [], "count": 0, "next_cursor": None})
        rows = snapshot.transactions.filter(effective=True, kind=data["kind"]).select_related("contributor", "committee")
        rows = rows.order_by({"amount": "-amount", "date": "-date", "name": "contributor__name"}[data["sort"]], "id")
        count, offset = rows.count(), data["cursor"]
        return Response({"status": "collecting" if preview and snapshot.pk == preview.pk else snapshot.coverage, "snapshot": str(snapshot.pk), "period": snapshot.period, "published_at": snapshot.published_at, "totals": snapshot.totals, "individuals_visible": True, "count": count, "next_cursor": offset + 20 if offset + 20 < count else None, "results": [{"id": row.pk, "contributor_id": row.contributor_id, "name": row.contributor.name if row.contributor else "Unidentified", "type": row.contributor.kind if row.contributor else "unknown", "amount": str(row.amount), "date": row.date, "committee": row.committee.name, "source_url": row.source_url} for row in rows[offset:offset + 20]]})


class ConnectionsView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, representative_id):
        from apps.campaign_finance.connections import get_connections
        get_object_or_404(Representative, pk=representative_id)
        params = parameters(request, ConnectionsQuery)
        snapshot_id = params.pop("snapshot", None)
        snapshot = None
        if snapshot_id:
            snapshot = get_object_or_404(FinanceSnapshot, pk=snapshot_id, representative_id=representative_id, period=params["period"], invalidated=False, published_at__isnull=False)
        return Response(get_connections(representative_id, snapshot=snapshot, **params))


class SnapshotsView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, representative_id):
        get_object_or_404(Representative, pk=representative_id)
        params = parameters(request, SnapshotsQuery)
        rows = FinanceSnapshot.objects.filter(representative_id=representative_id, period=params["period"], invalidated=False, published_at__isnull=False).order_by("-published_at", "-pk")
        offset, count = params["cursor"], rows.count()
        return Response({"count": count, "next_cursor": offset + 20 if offset + 20 < count else None, "results": [{"id": str(row.pk), "published_at": row.published_at, "active": row.active, "coverage": row.coverage} for row in rows[offset:offset + 20]]})


class PortraitView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, representative_id, portrait_id):
        portrait = get_object_or_404(RepresentativePortrait, pk=portrait_id, representative_id=representative_id, mime_type="image/png")
        if not portrait.object_key or not may_serve_portrait(portrait):
            raise Http404
        try:
            stream = default_storage.open(portrait.object_key, "rb")
        except FileNotFoundError:
            raise Http404 from None
        response = FileResponse(stream, content_type="image/png")
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "no-store"
        return response
