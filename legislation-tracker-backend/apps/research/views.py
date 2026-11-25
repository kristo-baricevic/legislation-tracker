from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.http import FileResponse, Http404
from django.db import transaction
from django.db.models import Q, OuterRef, Subquery, Sum, Min
from django.core.files.storage import default_storage
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView
from config.api import StrictQuerySerializer
from apps.congress.models import Representative
from apps.campaign_finance.models import FinanceSnapshot
from apps.campaign_finance.progress import latest_preview, finance_progress
from apps.campaign_finance.periods import discover_periods
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
    all_periods = serializers.BooleanField(default=False)
    by_size = serializers.BooleanField(default=False)
    aggregate = serializers.BooleanField(default=False)
    snapshot = serializers.UUIDField(required=False)
    cursor = serializers.IntegerField(min_value=0, default=0)
    sort = serializers.ChoiceField(choices=["amount", "date", "name"], default="amount")
    kind = serializers.ChoiceField(choices=["contribution", "refund"], default="contribution")


class SnapshotsQuery(ResearchQuery):
    cursor = serializers.IntegerField(min_value=0, default=0)


class OutsideSpendingQuery(SnapshotsQuery):
    all_periods = serializers.BooleanField(default=False)
    scope = serializers.ChoiceField(choices=['all_years', 'last_ten_years'], default='all_years')
    revision = serializers.CharField(max_length=64, required=False)
    position = serializers.ChoiceField(choices=["S", "O", "M"], required=False)


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
    refresh = serializers.BooleanField(default=False)
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
    status = run.effective_status
    work = run.work_item
    return {"id": str(run.pk), "status": status, "sections": run.sections, "created_at": run.created_at, "finished_at": run.finished_at, "retry_at": work.available_at if work and work.status == "pending" else None, "error": "Research failed. You can retry." if status == "failed" else None}


def source_data(source):
    return {"url": source.url, "attribution": source.attribution, "license": source.license, "fetched_at": source.fetched_at}


def funding_periods(rep):
    latest_run = ResearchRun.objects.filter(representative=rep, period=OuterRef("period")).order_by("-created_at").values("pk")[:1]
    snapshots = FinanceSnapshot.objects.filter(representative=rep, invalidated=False).filter(
        Q(active=True) | (Q(run_id=Subquery(latest_run), published_at__isnull=True, run__status__in=["queued", "running"]) & ~Q(run__work_item__status__in=ResearchRun.terminal_work_statuses))
    ).prefetch_related("checkpoints")
    periods = set(discover_periods(rep))
    for snapshot in snapshots:
        has_totals = any(cp.schedule == "totals" and cp.complete and cp.source_totals.get("records") for cp in snapshot.checkpoints.all())
        if has_totals or snapshot.transactions.filter(effective=True, kind__in=["contribution", "refund"]).exists() or snapshot.outside_scans.filter(totals__isnull=False).exists():
            periods.add(snapshot.period)
    return sorted(periods, reverse=True)


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
        return Response({**saved_research(rep, parameters(request)["period"]), "available_periods": funding_periods(rep)})

    def post(self, request, representative_id):
        get_object_or_404(Representative, pk=representative_id)
        data = StartQuery(data=request.data)
        data.is_valid(raise_exception=True)
        run = request_research(representative_id, data.validated_data["period"], request.user.pk, refresh=data.validated_data["refresh"])
        return Response(run_data(run), status=202)


class ResearchRunView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, representative_id, run_id):
        return Response(run_data(get_object_or_404(ResearchRun.objects.select_related("work_item"), pk=run_id, representative_id=representative_id)))


class ConfirmCandidateView(APIView):
    permission_classes = [IsAuthenticatedOrReadOnly]

    @transaction.atomic
    def post(self, request, representative_id, run_id):
        from apps.campaign_finance.models import CandidateIdentity, ConfirmedCandidate, RepresentativeCandidate
        from apps.campaign_finance.identity import review_choices, resolve_candidate
        from .services import _request_period

        rep = get_object_or_404(Representative.objects.select_for_update(), pk=representative_id)
        run = get_object_or_404(ResearchRun, pk=run_id, representative=rep)
        latest = ResearchRun.objects.filter(representative=rep, period=run.period).order_by("-created_at").first()
        if latest.pk != run.pk or run.status != "needs_review" or resolve_candidate(rep.pk, run.period).status == "verified":
            return Response({"detail": "This review has changed. Reload the saved research."}, status=409)
        choices = review_choices(rep, run.sections.get("finance", {}).get("candidates", []))
        choice = next((row for row in choices if row["candidate_id"] == request.data.get("candidate_id")), None)
        if not choice:
            return Response({"detail": "Choose one of the suggested FEC records."}, status=400)
        if RepresentativeCandidate.objects.filter(representative=rep, candidate_id=choice["candidate_id"], revoked=True).exists():
            return Response({"detail": "This mapping requires staff review."}, status=409)
        candidate, _ = CandidateIdentity.objects.update_or_create(fec_id=choice["candidate_id"],
            defaults={key: choice[key] for key in ("name", "state", "office")})
        mapping, created = RepresentativeCandidate.objects.get_or_create(representative=rep, candidate=candidate,
            defaults={"verified": True, "periods": [run.period], "evidence_url": f"https://www.fec.gov/data/candidate/{candidate.pk}/"})
        if not created:
            if not mapping.verified or not mapping.evidence_url:
                # Fresh confirmation covers this election cycle only.
                mapping.verified = True
                mapping.periods = [run.period]
                mapping.evidence_url = f"https://www.fec.gov/data/candidate/{candidate.pk}/?cycle={run.period}"
                mapping.save(update_fields=["verified", "periods", "evidence_url"])
            elif run.period not in mapping.periods:
                mapping.periods = sorted({*mapping.periods, run.period})
                mapping.save(update_fields=["periods"])
        ConfirmedCandidate.objects.update_or_create(representative=rep, period=run.period, defaults=dict(candidate=candidate,
            review_run=run, confirmed_by=request.user))
        resumed = _request_period(rep.pk, run.period, request.user.pk, refresh=True, finance_only=True)
        resumed.sections = {**run.sections, "finance": {"status": "queued"}}
        resumed.save(update_fields=["sections"])
        return Response(run_data(resumed), status=202)


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
        snapshots = [snapshot] if snapshot else []
        collecting = bool(preview) and not data.get("snapshot")
        if data["all_periods"]:
            if data.get("snapshot"):
                raise serializers.ValidationError("Choose a snapshot or all periods, not both.")
            snapshots = []
            collecting = False
            for period in FinanceSnapshot.objects.filter(representative_id=representative_id, invalidated=False).values_list("period", flat=True).distinct():
                preview = latest_preview(representative_id, period)
                collecting = collecting or bool(preview)
                saved = FinanceSnapshot.objects.filter(representative_id=representative_id, period=period, active=True, invalidated=False).first() or preview
                if saved:
                    snapshots.append(saved)
        if not snapshots:
            if data["by_size"]:
                return Response({"status": "not_researched", "total": "0", "refunds": "0", "results": []})
            return Response({"status": "not_researched", "snapshot": None, "results": [], "count": 0, "next_cursor": None})
        from apps.campaign_finance.models import FinanceTransaction
        transactions = FinanceTransaction.objects.filter(snapshot__in=snapshots, effective=True)
        status = "collecting" if collecting or any(saved.published_at is None for saved in snapshots) else "partial"
        rows = transactions.filter(kind=data["kind"]).select_related("contributor", "committee")
        if data["by_size"]:
            bands = [("Under $200", Q(amount__lt=200)), ("$200–$999", Q(amount__gte=200, amount__lt=1000)), ("$1,000–$4,999", Q(amount__gte=1000, amount__lt=5000)), ("$5,000+", Q(amount__gte=5000))]
            totals = transactions.filter(kind="contribution", amount__gt=0).aggregate(**{f"band_{i}": Sum("amount", filter=condition) for i, (_, condition) in enumerate(bands)})
            return Response({"status": status, "refunds": str(transactions.filter(kind="refund").aggregate(total=Sum("amount"))["total"] or 0),
                "total": str(sum(value or 0 for value in totals.values())),
                "results": [{"label": label, "amount": str(totals[f"band_{i}"] or 0)} for i, (label, _) in enumerate(bands)]})
        if data["aggregate"]:
            donors = rows.filter(contributor__isnull=False).values("contributor_id", "contributor__name").annotate(amount=Sum("amount"), source=Min("source_url")).filter(amount__gt=0).order_by("-amount", "contributor_id")
            return Response({"status": status,
                "results": [{"id": row["contributor_id"], "name": row["contributor__name"], "amount": str(row["amount"]), "source_url": row["source"]} for row in donors[:5]]})
        rows = rows.order_by({"amount": "-amount", "date": "-date", "name": "contributor__name"}[data["sort"]], "id")
        count, offset = rows.count(), data["cursor"]
        return Response({"status": status, "snapshot": str(snapshot.pk) if snapshot and not data["all_periods"] else None, "period": None if data["all_periods"] else data["period"], "published_at": snapshot.published_at if snapshot and not data["all_periods"] else None, "totals": snapshot.totals if snapshot and not data["all_periods"] else {}, "individuals_visible": True, "count": count, "next_cursor": offset + 20 if offset + 20 < count else None, "results": [{"id": row.pk, "contributor_id": row.contributor_id, "name": row.contributor.name if row.contributor else "Unidentified", "type": row.contributor.kind if row.contributor else "unknown", "amount": str(row.amount), "date": row.date, "committee": row.committee.name, "source_url": row.source_url} for row in rows[offset:offset + 20]]})


class OutsideSpendingView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, representative_id):
        from apps.campaign_finance.models import OutsideSpendingTotal
        from apps.campaign_finance.models import OutsideSpendingRevision
        from django.core.cache import cache
        import hashlib
        import json
        get_object_or_404(Representative, pk=representative_id)
        data = parameters(request, OutsideSpendingQuery)
        from apps.campaign_finance.outside import outside_complete
        from apps.ingestion.models import IngestionWorkItem
        year = timezone.now().year
        def in_scope(period):
            return type(period) is int and 1980 <= period <= year + year % 2 and (data['scope'] == 'all_years' or period >= year - 9)
        revision_row, _ = OutsideSpendingRevision.objects.get_or_create(representative_id=representative_id)
        generation = (str(revision_row.epoch), revision_row.generation)
        periods = FinanceSnapshot.objects.filter(representative_id=representative_id, invalidated=False).values_list("period", flat=True).distinct() if data["all_periods"] else [data["period"]]
        snapshots = []
        collecting = False
        pending_periods = set()
        failed_periods = set()
        history_failed = False
        latest_run = ResearchRun.objects.filter(representative_id=representative_id, period=OuterRef('period')).order_by('-created_at').values('pk')[:1]
        runs = ResearchRun.objects.filter(representative_id=representative_id, pk=Subquery(latest_run)).exclude(financesnapshot__invalidated=True).select_related('work_item')
        if not data['all_periods']:
            runs = runs.filter(period=data['period'])
        runs = list(runs)
        if data['all_periods']:
            runs = [run for run in runs if in_scope(run.period)]
            periods = {period for period in periods if in_scope(period)}
        for run in runs:
            if (run.work_item and run.work_item.status == 'dead') or run.effective_status in {'failed', 'needs_review'}:
                failed_periods.add(run.period)
            elif run.status in {'queued', 'running'}:
                pending_periods.add(run.period)
        if data['all_periods']:
            from apps.ingestion.models import IngestionWorkItem
            from apps.campaign_finance.models import RepresentativeCandidate
            # A missing run is missing coverage, not evidence of zero spending.
            # Use saved provider periods; never perform source I/O on a read.
            expected_periods = set()
            year = timezone.now().year
            for known, reporting in RepresentativeCandidate.objects.filter(
                    representative_id=representative_id, verified=True).exclude(evidence_url='').values_list(
                    'periods', 'candidate__reporting_periods'):
                expected_periods.update(p for p in [*known, *reporting.get('periods', [])]
                    if in_scope(p))
            periods = set(periods) | {run.period for run in runs}
            failed_periods.update(expected_periods - periods)
            history_keys = [f'history:{pk}' for pk in ResearchRun.objects.filter(representative_id=representative_id).values_list('pk', flat=True)]
            history = IngestionWorkItem.objects.filter(kind='representative_research', dedupe_key__in=history_keys).order_by('-source_updated_at', '-pk').first()
            history_failed = bool(history and history.status == 'dead')
            collecting = bool(history and history.status in {'pending', 'dispatched', 'processing'})
        else:
            expected_periods = {data['period']}
        # Outside-only work reuses the saved finance snapshot and has its own
        # durable status; it need not keep a full research run open.
        jobs = IngestionWorkItem.objects.filter(kind='representative_research',
            dedupe_key__startswith=f'outside:{representative_id}:').order_by('-source_updated_at', '-pk')
        seen_periods = set()
        for job in jobs:
            period = job.payload_json.get('period')
            if period in seen_periods or (data['all_periods'] and not in_scope(period)) or (not data['all_periods'] and period != data['period']):
                continue
            seen_periods.add(period)
            if job.status in {'pending', 'dispatched', 'processing'}:
                pending_periods.add(period)
                failed_periods.discard(period)
                collecting = True
            elif job.status == 'dead':
                failed_periods.add(period)
        periods = set(periods) | pending_periods
        candidates = list(FinanceSnapshot.objects.filter(representative_id=representative_id, period__in=periods, invalidated=False)
            .filter(Q(active=True) | Q(run_id__in=[run.pk for run in runs], published_at__isnull=True))
            .prefetch_related("outside_scans"))
        active = {item.period: item for item in candidates if item.active}
        previews = {item.run_id: item for item in candidates if item.published_at is None}
        run_by_period = {run.period: run for run in runs}
        def complete(snapshot):
            return bool(snapshot and outside_complete(snapshot))
        for period in periods:
            run = run_by_period.get(period)
            preview = previews.get(run.pk) if run and period in pending_periods else None
            saved = active.get(period)
            preview_complete = complete(preview)
            snapshot = preview if preview_complete else saved or preview
            if snapshot and list(snapshot.outside_scans.all()):
                snapshots.append(snapshot)
                scan_complete = complete(snapshot)
                if not scan_complete:
                    if period in pending_periods:
                        collecting = True
                    else:
                        failed_periods.add(period)
                if period in pending_periods and not preview_complete:
                    collecting = True
            elif preview or period in pending_periods:
                collecting = True
            elif any(run.period == period for run in runs):
                failed_periods.add(period)
        coverage = {'failed_periods': sorted(failed_periods, reverse=True), 'history_failed': history_failed,
            'scope': data['scope'] if data['all_periods'] else 'period',
            'start_year': min(periods | expected_periods) - 1 if periods or expected_periods else None,
            'end_year': max(periods | expected_periods) if periods or expected_periods else None}
        status = 'collecting' if collecting else 'partial' if failed_periods or history_failed else 'available'
        revision = hashlib.sha256(json.dumps([generation, sorted(str(s.pk) for s in snapshots), status, coverage], sort_keys=True).encode()).hexdigest()
        if data.get("revision") and data["revision"] != revision:
            return Response({"detail": "Spending data changed; refresh from the first page."}, status=409)
        empty = {"status": "not_researched", "support": None, "oppose": None, "mentions": None, "results": [], "count": 0, "next_cursor": None}
        if not snapshots:
            if status != 'available':
                empty["status"] = status
            return Response({**empty, **coverage, "revision": revision})
        rows = OutsideSpendingTotal.objects.filter(scan__snapshot__in=snapshots)
        cache_key = f"outside-totals:v2:{revision}"
        try:
            totals = cache.get(cache_key)
        except Exception:
            totals = None
        if totals is None:
            totals = rows.aggregate(S=Sum("amount", filter=Q(position__in=["S", "24F"])), O=Sum("amount", filter=Q(position__in=["O", "24N"])), M=Sum("amount", filter=Q(position="M")))
            totals = {side: value or 0 for side, value in totals.items()}
            try:
                cache.set(cache_key, totals, timeout=3600)
            except Exception:
                pass  # Cached totals are optional; revision changes invalidate immediately.
        if data.get("position"):
            rows = rows.filter(position__in={'S': ['S', '24F'], 'O': ['O', '24N'], 'M': ['M']}[data["position"]])
        rows = rows.select_related("scan__snapshot").order_by("-amount", "pk")
        count, offset = rows.count(), data["cursor"]
        source_paths = {'independent': 'independent-expenditures', 'communication': 'communication-costs', 'electioneering': 'electioneering-communications'}
        def source_url(row):
            url = f"https://www.fec.gov/data/{source_paths[row.scan.category]}/?committee_id={row.spender_id}&candidate_id={row.scan.candidate_id}&cycle={row.scan.snapshot.period}"
            position = {'24F': 'S', '24N': 'O'}.get(row.position, row.position)
            return url + (f'&support_oppose_indicator={position}' if position != 'M' else '')
        result = {"status": status, **coverage, "revision": revision, "support": str(totals["S"]), "oppose": str(totals["O"]), "mentions": str(totals["M"]), "count": count,
            "next_cursor": offset + 20 if offset + 20 < count else None,
            "results": [{"id": row.pk, "name": row.spender_name, "amount": str(row.amount), "position": {'24F': 'S', '24N': 'O'}.get(row.position, row.position), "period": row.scan.snapshot.period,
                "category": row.scan.category, "source_url": source_url(row)} for row in rows[offset:offset + 20]]}
        latest_revision = OutsideSpendingRevision.objects.get(representative_id=representative_id)
        if generation != (str(latest_revision.epoch), latest_revision.generation):
            return Response({"detail": "Spending data changed; refresh from the first page."}, status=409)
        return Response(result)


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
