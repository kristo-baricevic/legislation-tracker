from rest_framework.throttling import AnonRateThrottle


class RegistrationThrottle(AnonRateThrottle):
    scope = "auth_register"


class LoginThrottle(AnonRateThrottle):
    scope = "auth_login"


class RefreshThrottle(AnonRateThrottle):
    scope = "auth_refresh"
