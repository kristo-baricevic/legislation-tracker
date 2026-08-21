"""
Production settings. Set DEBUG=False and ALLOWED_HOSTS via env.
"""

from .base import *

DEBUG = False
LLM_ENHANCEMENT_PRODUCTION_SECURITY_REQUIRED = True
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
WHITENOISE_AUTOREFRESH = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    default=True,
)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Ensure these are set in production
if SECRET_KEY == "change-me-in-production-use-env":
    raise ValueError("Set DJANGO_SECRET_KEY in production")

if not ALLOWED_HOSTS:
    raise ValueError("Set ALLOWED_HOSTS in production")

if LLM_ENHANCEMENTS_ENABLED:
    from apps.accounts.llm_credentials import llm_feature_configuration_errors

    llm_configuration_errors = llm_feature_configuration_errors(production=True)
    if llm_configuration_errors:
        raise ValueError(
            "Invalid production LLM enhancement configuration: "
            + ", ".join(llm_configuration_errors)
        )
