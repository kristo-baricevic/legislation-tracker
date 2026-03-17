# Phase 3: Celery and Ingestion Tasks — Expanded Plan

## Goal

Implement the ingestion pipeline so the backend can **poll Congress.gov for updated bills**, **process each bill** (metadata, versions, votes), **short-circuit when nothing changed** (via hashes), and **write ChangeLog entries** so RSS/newsletters can consume events. Phase 3 covers only the **Congress API** and **DB/S3-agnostic** tasks; document download (GovInfo/S3) is Phase 4.

**ELI5:** We check the mailbox (Congress.gov) regularly for new or changed bills. For each bill we write down the basics and “what changed” in a diary (ChangeLog). We only do extra work when something actually changed (using a fingerprint/hash). We don’t download the actual bill PDFs yet—that’s Phase 4.

---

## Architecture (task flow)

- **poll_congress**: Lightweight; fetches bill identifiers, updates IngestionState, enqueues `process_bill` per bill.
- **process_bill**: Orchestrator. Fetches bill detail, compares metadata_hash, updates Bill and ChangeLog, enqueues `process_bill_versions` and `process_bill_votes`.
- **process_bill_versions**: Fetches text version list; creates/updates BillDocument rows and enqueues `download_document` (Phase 4 stub).
- **process_bill_votes**: Fetches vote refs; creates Vote, VoteRecord, Representative; inserts ChangeLog(vote).

**ELI5:** A scheduler (Beat) “checks the mailbox” often. For every bill in the list it drops a “process this bill” job into a queue. One worker picks up each job: it updates the bill’s card, then drops two more jobs—“fetch document versions” and “fetch votes”—so other workers can do those without blocking.

---

## 1. Congress API client / helpers

**Location**: New module under `apps/ingestion/` (e.g. `congress_client.py`).

- **Settings**: CONGRESS_API_KEY from Django settings. Base URL: `https://api.congress.gov/v3`.
- **Functions**: bill_list, bill_detail, bill_text_list, vote_detail (all use requests/urllib and api_key from settings).
- **Rate limiting**: Optional delay between requests.
- **Error handling**: Raise CongressAPIError on non-2xx; Celery retries on retryable codes.
- **Note**: Use IngestionState.last_bill_update_seen_at for fromDateTime; filter by congress in path.

**ELI5:** A small helper that knows how to talk to Congress.gov: “give me the list of bills,” “give me this bill’s details,” “give me this bill’s text versions,” “give me this vote.” If the API says no or errors, we raise so the task can retry later.

---

## 2. Task: poll_congress

**File**: `apps/ingestion/tasks.py`.

- Get or create IngestionState; build from_date_time from last_bill_update_seen_at (or None first run).
- For each bill type (hr, s), call bill_list; collect (congress, type, number); update IngestionState; enqueue process_bill per bill.
- Idempotent. Beat: e.g. every 10 min.

**ELI5:** “Check the mailbox” on a timer. We only ask for bills updated since last time. We write down “last time we looked” so next run we don’t re-fetch everything. For each bill we just add a “process this bill” slip to the pile—we don’t do the heavy work here.

---

## 3. Task: process_bill

**File**: `apps/ingestion/tasks.py`.

- Parse bill_key; fetch bill detail; get/create Representative (sponsor); compute metadata_hash; get/create Bill; if hash unchanged set processing_status=complete and return; else update Bill, insert ChangeLog(status_update), enqueue process_bill_versions and process_bill_votes. On exception set processing_status=failed; retries via Celery.

**ELI5:** For one bill we fetch its details and make a fingerprint. If the fingerprint is the same as before we do nothing. If it changed we update the bill’s card, write a line in the diary (“status updated”), and add two new jobs: “fetch document versions” and “fetch votes.”

---

## 4. Task: process_bill_versions

**File**: `apps/ingestion/tasks.py`.

- Load Bill; call bill_text_list; for each version get/create BillDocument, set is_active_version; enqueue download_document (stub in Phase 3). Idempotent; short-circuit if no new versions.

**ELI5:** We ask “what document versions exist for this bill?” (introduced, amended, etc.). For each we create or update a “document” row and mark which one is current. We then add a “download this document” job (Phase 3: that job is a stub that does nothing; Phase 4 will actually download).

---

## 5. Task: process_bill_votes

**File**: `apps/ingestion/tasks.py`.

- Load Bill; fetch bill detail for vote refs; for each vote not already stored call vote_detail; get/create Vote, VoteRecord, Representative; insert ChangeLog(vote). Idempotent. House may be XML; Phase 3 can do JSON first.

**ELI5:** We look at the bill’s vote links. For each vote we don’t already have we fetch it, create the vote and each member’s yes/no, and write a diary line (“vote recorded”).

---

## 6. Beat schedule

**File**: `config/celery.py`.

- poll-congress every 10 min. Optional fetch_congress_members daily. Ensure apps.ingestion in INSTALLED_APPS for autodiscover.

**ELI5:** The scheduler runs “check the mailbox” every 10 minutes so we always have a fresh list of bills to process.

---

## 7. Retry and dead-letter behavior

- process_bill (and optionally versions/votes): autoretry_for=CongressAPIError, retry_backoff, max_retries=2. On final failure log to IngestionTaskFailure table or structured log (task_id, bill_id, exception). Document in README.

**ELI5:** If something fails (e.g. Congress.gov is slow) we wait a bit and try again a few times. If it still fails we write down “this task failed” so we can fix it later instead of losing it.

**Operational note:** On repeated failures, check logs or the `IngestionTaskFailure` table (task_id, bill_id, task_name, error_message, created_at) to debug.

---

## 8. Dependency and field mapping notes

- Bill.bill_number: consistent form (e.g. "HR 1234"). metadata_hash: canonical string, normalized. IngestionState per (jurisdiction, congress). Phase 4 implements download_document.

**ELI5:** We use the same spelling for bill numbers everywhere so we can match them. We make the fingerprint from a single consistent string so tiny formatting changes don’t trigger rework.

---

## 9. Implementation order (checklist)

1. Congress API key in settings; congress_client with bill_list, bill_detail, bill_text_list, vote_detail.
2. poll_congress.
3. process_bill.
4. process_bill_versions; stub download_document.
5. process_bill_votes.
6. Beat schedule in config/celery.py.
7. Retry options and dead-letter (IngestionTaskFailure or logging).
8. Manual test: worker + beat, trigger poll_congress, confirm bills and ChangeLog.

---

## 10. Out of scope for Phase 3

GovInfo/S3 (Phase 4); NLP/BillContract (Phase 5); topics/similarity (Phase 6); RSS/newsletters (Phase 8/9).
