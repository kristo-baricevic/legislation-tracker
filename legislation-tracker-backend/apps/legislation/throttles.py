from rest_framework.throttling import SimpleRateThrottle


class BillSearchThrottle(SimpleRateThrottle):
    """Separate anonymous and authenticated search buckets."""

    scope = "bill_search_anon"

    def allow_request(self, request, view):
        self.scope = (
            "bill_search_user"
            if getattr(request.user, "is_authenticated", False)
            else "bill_search_anon"
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
