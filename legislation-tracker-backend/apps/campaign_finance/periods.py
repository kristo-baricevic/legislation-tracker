"""Persist FEC reporting cycles separately from downloaded campaign records."""
from django.utils import timezone
from django.core.cache import cache
from .fec_client import get_page, FECError
from .models import CandidateIdentity, RepresentativeCandidate


def discover_periods(rep):
    year = timezone.now().year
    current = year + year % 2
    periods = set()
    mappings = RepresentativeCandidate.objects.filter(representative=rep, verified=True).exclude(evidence_url="").select_related("candidate")
    for mapping in mappings:
        candidate = mapping.candidate
        saved = candidate.reporting_periods
        lock = f"fec-period-discovery:{candidate.pk}"
        if saved.get("checked_cycle") != current and cache.add(lock, True, timeout=60):
            try:
                page = get_page("candidates/search/", {"candidate_id": candidate.pk, "per_page": 100})
                rows = [row for row in page["results"] if row.get("candidate_id") == candidate.pk]
                if len(rows) == 1 and isinstance(rows[0].get("cycles"), list):
                    cycles = sorted({cycle for cycle in rows[0]["cycles"] if type(cycle) is int and 1980 <= cycle <= current and cycle % 2 == 0})
                    saved = {"checked_cycle": current, "periods": cycles}
                    CandidateIdentity.objects.filter(pk=candidate.pk).update(reporting_periods=saved)
            except FECError:
                # Keep saved choices; retry later without hammering the provider.
                pass
        periods.update(saved.get("periods", []))
    return sorted(periods, reverse=True)
