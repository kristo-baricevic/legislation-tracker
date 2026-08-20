"""
Production settings. Set DEBUG=False and ALLOWED_HOSTS via env.
"""
from .base import *  # noqa: F401, F403

DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
WHITENOISE_AUTOREFRESH = False

# Ensure these are set in production
if SECRET_KEY == "change-me-in-production-use-env":
    raise ValueError("Set DJANGO_SECRET_KEY in production")

if not ALLOWED_HOSTS:
    raise ValueError("Set ALLOWED_HOSTS in production")
