# `ingestion` app

## Purpose

This app is the **pipeline** that pulls data from **Congress.gov** into our database: it keeps a **polling cursor**, runs **background jobs** to fetch bills, versions, and votes, and records **failures** when something breaks after retries. You can think of it as the automated “newsroom wire” that keeps our copy of federal legislation up to date.

## How it works (plain English + tech)

- **Celery** is a **task queue**: work is scheduled on **Redis** (the message broker). **Celery Beat** runs on a schedule (e.g. every 10 minutes) and **Celery workers** execute the tasks.
- **`congress_client.py`** talks to the **Congress.gov REST API v3** over **HTTPS** using **Python requests**; the API key comes from Django settings (`CONGRESS_API_KEY` in `.env`).
- **`poll_congress`** asks for recently updated bills (House and Senate types), updates **`IngestionState`** (last poll time, last “update seen” date), and queues **one task per bill**.
- **`process_bill`** loads full bill metadata, **hashes** key fields to skip unchanged work, updates **`Bill`** and **`ChangeLog`**, then queues **versions** and **votes** tasks.
- **`process_bill_versions`** loads text-version metadata and creates **`BillDocument`** rows; **`download_document`** is a stub until Phase 4 (real file download to **S3**).
- **`process_bill_votes`** creates **`Vote`** / **`VoteRecord`** / **`Representative`** rows and **`ChangeLog`** entries for new votes.

If a task fails repeatedly, **`IngestionTaskFailure`** stores a **dead-letter** record (task id, bill id, error message) so operators can debug without losing context.

## What you’ll find here

| Piece | Role |
|--------|------|
| `IngestionState` | Cursor per jurisdiction/congress so we don’t re-fetch everything every run. |
| `IngestionTaskFailure` | Failed task log after retries. |
| `congress_client.py` | HTTP client for Congress.gov. |
| `tasks.py` | Celery task definitions (`poll_congress`, `process_bill`, …). |

## Who should read this

Anyone changing **polling**, **Congress API** behavior, **Celery** configuration, or **retry/dead-letter** handling.
