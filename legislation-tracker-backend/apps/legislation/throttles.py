from rest_framework.throttling import SimpleRateThrottle


class PublicBillThrottle(SimpleRateThrottle):
    """Separate anonymous and authenticated public bill API buckets."""

    anonymous_scope = ""
    authenticated_scope = ""

    def allow_request(self, request, view):
        self.scope = (
            self.authenticated_scope
            if getattr(request.user, "is_authenticated", False)
            else self.anonymous_scope
        )
        self.rate = self.get_rate()
        if self.rate is None:
            return True
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        if getattr(request.user, "is_authenticated", False):
            ident = str(request.user.pk)
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class BillSearchThrottle(PublicBillThrottle):
    """Separate anonymous and authenticated search buckets."""

    scope = "bill_search_anon"
    anonymous_scope = "bill_search_anon"
    authenticated_scope = "bill_search_user"


class BillComparisonThrottle(PublicBillThrottle):
    """Separate anonymous and authenticated bounded-diff buckets."""

    scope = "bill_comparison_anon"
    anonymous_scope = "bill_comparison_anon"
    authenticated_scope = "bill_comparison_user"
