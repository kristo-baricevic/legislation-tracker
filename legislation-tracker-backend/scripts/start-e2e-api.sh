#!/usr/bin/env bash
set -euo pipefail

E2E_DATABASE_PATH="/private/tmp/legislation-tracker-e2e.sqlite3"
E2E_API_HOST="127.0.0.1"
E2E_API_PORT="${E2E_API_PORT:-18000}"
E2E_CLIENT_ORIGIN="${E2E_CLIENT_ORIGIN:-http://127.0.0.1:13100}"
E2E_CELERY_BROKER_DIR="$(mktemp -d /private/tmp/legislation-tracker-e2e-broker.XXXXXX)"
rm -f "$E2E_DATABASE_PATH"
mkdir -p "$E2E_CELERY_BROKER_DIR/queue" "$E2E_CELERY_BROKER_DIR/processed" \
  "$E2E_CELERY_BROKER_DIR/control"

export DATABASE_URL="sqlite:////private/tmp/legislation-tracker-e2e.sqlite3"
export DJANGO_SETTINGS_MODULE="config.settings.e2e"
export DJANGO_SECRET_KEY="legislation-tracker-e2e-secret-key-with-safe-test-length"
export USE_LOCAL_DOCUMENT_STORAGE="True"
export CORS_ALLOWED_ORIGINS="$E2E_CLIENT_ORIGIN"
export E2E_CELERY_BROKER_DIR
export LLM_CREDENTIAL_ENCRYPTION_KEYS="e2e:MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="

.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py shell -c '
from apps.legislation.contract_json import contract_hash_from_dict
from apps.legislation.extraction.service import extract_contract
from apps.legislation.models import Bill, BillContract, BillDocument, EvidenceSpan, Topic

Topic.objects.get_or_create(name="Education", defaults={"slug": "education"})
Topic.objects.get_or_create(name="Health", defaults={"slug": "health"})

source_text = """SEC. 2. RURAL HOSPITAL GRANTS.
The Secretary of Health and Human Services shall award grants to rural hospitals.
There is authorized to be appropriated $25,000,000 for fiscal year 2027.
This Act takes effect 90 days after enactment."""
bill = Bill.objects.create(
    jurisdiction="federal",
    session=119,
    bill_number="HR E2E",
    title="Rural Hospital Grants Act",
    status="Introduced",
    processing_status="complete",
)
document = BillDocument.objects.create(
    bill=bill,
    version_label="Introduced",
    is_active_version=True,
    extracted_text=source_text,
    content_hash="e2e-contract-source",
)
result = extract_contract(document=document, bill=bill)
assert result.schema_version == "2.0-legal-nlp"
contract = BillContract.objects.create(
    bill=bill,
    document=document,
    schema_version=result.schema_version,
    contract_json=result.contract_json,
    contract_hash=contract_hash_from_dict(result.contract_json),
)
EvidenceSpan.objects.bulk_create([
    EvidenceSpan(
        bill=bill,
        document=document,
        contract=contract,
        field_path=span.field_path,
        start_char=span.start_char,
        end_char=span.end_char,
        quoted_text=span.quoted_text,
        page_number=span.page_number,
    )
    for span in result.evidence
])
bill.latest_contract = contract
bill.save(update_fields=["latest_contract"])
'

.venv/bin/celery -A config worker --loglevel=warning --pool=solo --concurrency=1 \
  --without-gossip --without-mingle --without-heartbeat &
E2E_WORKER_PID=$!

cleanup() {
  kill "$E2E_WORKER_PID" 2>/dev/null || true
  wait "$E2E_WORKER_PID" 2>/dev/null || true
  rm -rf "$E2E_CELERY_BROKER_DIR"
}
trap cleanup EXIT INT TERM

.venv/bin/python manage.py runserver "$E2E_API_HOST:$E2E_API_PORT" --noreload
