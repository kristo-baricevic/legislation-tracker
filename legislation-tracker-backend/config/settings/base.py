"""
Django base settings for legislation-tracker-backend.
All env-based configuration uses django-environ; defaults are for local dev.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, True),
    DATABASE_URL=(str, f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
    REDIS_URL=(str, "redis://localhost:6379/0"),
    CELERY_BROKER_URL=(str, ""),  # default: use REDIS_URL
)

# Read .env from backend root (same dir as manage.py)
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="change-me-in-production-use-env")

DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    # Local apps
    "apps.congress",
    "apps.legislation",
    "apps.changelog",
    "apps.ingestion",
    "apps.accounts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Database
DATABASES = {"default": env.db()}

# Cache / Redis (used by Celery broker and optional API cache)
REDIS_URL = env("REDIS_URL")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# Celery
CELERY_BROKER_URL = env("CELERY_BROKER_URL") or REDIS_URL
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
# A worker process can disappear after receiving a downstream document, vote,
# or contract task. Acknowledge only after completion and return that delivery
# to the broker when the child process is lost so the pipeline is at-least-once.
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True

# Optional user-owned LLM bill enhancements. The feature is off by default and
# configuration is validated before any credential or provider operation.
LLM_ENHANCEMENTS_ENABLED = env.bool("LLM_ENHANCEMENTS_ENABLED", default=False)
LLM_CREDENTIAL_ENCRYPTION_KEYS = env(
    "LLM_CREDENTIAL_ENCRYPTION_KEYS",
    default="",
)
LLM_CREDENTIAL_ACTIVE_KEY_ID = env(
    "LLM_CREDENTIAL_ACTIVE_KEY_ID",
    default="",
)
LLM_ENHANCEMENT_PROVIDER = (
    env("LLM_ENHANCEMENT_PROVIDER", default="openai").strip().lower()
)
LLM_ENHANCEMENT_MODEL = env("LLM_ENHANCEMENT_MODEL", default="gpt-5.6-luna").strip()
LLM_ENHANCEMENT_REASONING_EFFORT = (
    env(
        "LLM_ENHANCEMENT_REASONING_EFFORT",
        default="none",
    )
    .strip()
    .lower()
)
LLM_ENHANCEMENT_MAX_REQUEST_BYTES = env.int(
    "LLM_ENHANCEMENT_MAX_REQUEST_BYTES",
    default=120000,
)
LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS = env.int(
    "LLM_ENHANCEMENT_MAX_ESTIMATED_INPUT_TOKENS",
    default=60000,
)
LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS = env.int(
    "LLM_ENHANCEMENT_MAX_OUTPUT_TOKENS",
    default=4000,
)
LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS = env.int(
    "LLM_ENHANCEMENT_PROVIDER_TIMEOUT_SECONDS",
    default=90,
)
LLM_ENHANCEMENT_RUN_LEASE_SECONDS = env.int(
    "LLM_ENHANCEMENT_RUN_LEASE_SECONDS",
    default=180,
)
LLM_ENHANCEMENT_CREATE_RATE = env(
    "LLM_ENHANCEMENT_CREATE_RATE",
    default="10/hour",
)
LLM_ENHANCEMENT_VALIDATION_RATE = env(
    "LLM_ENHANCEMENT_VALIDATION_RATE",
    default="5/hour",
)
LLM_ENHANCEMENT_ALLOW_INSECURE_HTTP_IN_DEBUG = env.bool(
    "LLM_ENHANCEMENT_ALLOW_INSECURE_HTTP_IN_DEBUG",
    default=False,
)
LLM_ENHANCEMENT_PRODUCTION_TLS_CONFIRMED = env.bool(
    "LLM_ENHANCEMENT_PRODUCTION_TLS_CONFIRMED",
    default=False,
)
LLM_ENHANCEMENT_SECRET_LOG_REDACTION_CONFIRMED = env.bool(
    "LLM_ENHANCEMENT_SECRET_LOG_REDACTION_CONFIRMED",
    default=False,
)
# Internal settings-module marker. Production overrides this to ensure runtime
# gates do not infer deployment mode from DEBUG (which test runners also alter).
LLM_ENHANCEMENT_PRODUCTION_SECURITY_REQUIRED = False
# Dedicated non-production key used only by the explicitly gated evaluation
# management command. It is never read by user request or worker paths.
LLM_ENHANCEMENT_EVALUATION_API_KEY = env(
    "LLM_ENHANCEMENT_EVALUATION_API_KEY",
    default="",
)

# REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_RATES": {
        "llm_enhancement": LLM_ENHANCEMENT_CREATE_RATE,
        "llm_validation": LLM_ENHANCEMENT_VALIDATION_RATE,
    },
}

# JWT (Simple JWT)
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

# Congress.gov API (ingestion)
CONGRESS_API_KEY = env("CONGRESS_API_KEY", default="")

# Document storage — MinIO (S3-compatible, local) or AWS S3; see README
# When USE_LOCAL_DOCUMENT_STORAGE=True, files go to local_media/ (no MinIO/S3 needed).
USE_LOCAL_DOCUMENT_STORAGE = env.bool("USE_LOCAL_DOCUMENT_STORAGE", default=False)
AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", default="")
AWS_STORAGE_BUCKET_NAME = env(
    "AWS_STORAGE_BUCKET_NAME", default="legislation-tracker-documents"
)
AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", default="")
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="us-east-1")
AWS_DEFAULT_ACL = None
AWS_S3_ADDRESSING_STYLE = env("AWS_S3_ADDRESSING_STYLE", default="path")
AWS_S3_FILE_OVERWRITE = False

if USE_LOCAL_DOCUMENT_STORAGE:
    MEDIA_ROOT = BASE_DIR / "local_media"
    MEDIA_URL = "/media/"
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            "OPTIONS": {"location": str(BASE_DIR / "local_media")},
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
else:
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

# CORS: allow explicit deployed app and extension origins only. A blanket
# chrome-extension regex would allow every installed extension to call the API.
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:3000", "http://127.0.0.1:3000"],
)
CORS_ALLOWED_ORIGIN_REGEXES = env.list("CORS_ALLOWED_ORIGIN_REGEXES", default=[])

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Custom user (must be before first migration that touches auth)
AUTH_USER_MODEL = "accounts.User"
