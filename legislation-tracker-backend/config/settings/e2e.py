"""Isolated browser-test settings with a real broker and fake provider edge."""

from pathlib import Path

from .dev import *

broker_root = Path(env("E2E_CELERY_BROKER_DIR"))
queue_directory = broker_root / "queue"
processed_directory = broker_root / "processed"
control_directory = broker_root / "control"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "legislation-tracker-e2e",
    }
}
CELERY_BROKER_URL = "filesystem://"
CELERY_RESULT_BACKEND = "cache+memory://"
CELERY_BROKER_TRANSPORT_OPTIONS = {
    "data_folder_in": str(queue_directory),
    "data_folder_out": str(queue_directory),
    "data_folder_processed": str(processed_directory),
    "control_folder": str(control_directory),
}
CELERY_TASK_ALWAYS_EAGER = False

LLM_ENHANCEMENTS_ENABLED = True
LLM_CREDENTIAL_ENCRYPTION_KEYS = env("LLM_CREDENTIAL_ENCRYPTION_KEYS")
LLM_CREDENTIAL_ACTIVE_KEY_ID = "e2e"
LLM_ENHANCEMENT_PROVIDER = "e2e"
LLM_ENHANCEMENT_MODEL = "e2e-model"
LLM_ENHANCEMENT_REASONING_EFFORT = "none"
LLM_ENHANCEMENT_ALLOW_INSECURE_HTTP_IN_DEBUG = True
LLM_ENHANCEMENT_E2E_FAKE_PROVIDER_ENABLED = True
LLM_ENHANCEMENT_CREATE_RATE = "100/hour"
LLM_ENHANCEMENT_VALIDATION_RATE = "100/hour"
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].update(
    {
        "llm_enhancement": LLM_ENHANCEMENT_CREATE_RATE,
        "llm_validation": LLM_ENHANCEMENT_VALIDATION_RATE,
    }
)
