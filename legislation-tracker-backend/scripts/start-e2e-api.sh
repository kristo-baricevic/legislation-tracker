#!/usr/bin/env bash
set -euo pipefail

E2E_DATABASE_PATH="/private/tmp/legislation-tracker-e2e.sqlite3"
E2E_API_HOST="127.0.0.1"
E2E_API_PORT="${E2E_API_PORT:-18000}"
E2E_CLIENT_ORIGIN="${E2E_CLIENT_ORIGIN:-http://127.0.0.1:13100}"
rm -f "$E2E_DATABASE_PATH"

export DATABASE_URL="sqlite:////private/tmp/legislation-tracker-e2e.sqlite3"
export DJANGO_SETTINGS_MODULE="config.settings.dev"
export USE_LOCAL_DOCUMENT_STORAGE="True"
export CORS_ALLOWED_ORIGINS="$E2E_CLIENT_ORIGIN"

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
exec .venv/bin/python manage.py runserver "$E2E_API_HOST:$E2E_API_PORT" --noreload
