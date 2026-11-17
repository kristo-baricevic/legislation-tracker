# Small-server capacity measurement — 2026-11-17

## Conclusion

An 8 GB server is not justified by the measured baseline. A tuned 2 GB / one-CPU deployment is plausible for a small beta, but this test does not establish readiness for the complete production corpus, live campaign-finance collection, or concurrent enhancement jobs. The unchanged production configuration should not be deployed blindly to that tier.

## Environment and isolation

- Commit: `1636fa2`. Built both checked-in production Dockerfiles successfully.
- Docker Desktop Linux ARM64; DigitalOcean's regular $12 instance is x86 with different CPU/disk performance. This is a local capacity approximation, not a cloud benchmark.
- Eight containers: PostgreSQL, Redis, Gunicorn API, standalone Next.js, ingestion worker, research worker, enhancement worker, Beat.
- All application containers pinned to the same single CPU. Load generator used a separate CPU and was excluded from memory totals.
- Dedicated disposable database and private Docker network; no original application data or secrets mounted. No paid AI calls or live FEC calls. Beat ran with external schedules disabled. Downstream tasks created by real contract generation still ran.
- 10,000 synthetic bill metadata records; public H.R. 10906 fixture (56,995 bytes), plus a clearly synthetic 10x repeated-text stress document (~570 KB). Database about 40 MB, not a copy of the production corpus.
- Normal worker explicitly constrained to concurrency 1 (the production Compose file otherwise uses automatic concurrency). Research and enhancement workers running but idle.

## Measurements

| Measurement | Result |
| --- | --- |
| Initial steady container memory | ~734 MiB |
| Peak simultaneous sampled memory, final run | 1,234.8 MiB |
| Final run last memory sample | 1,030.2 MiB |
| Final API peak sampled memory | 399.5 MiB |
| Final ingestion worker peak sampled memory | 362.8 MiB |
| Final valid HTTP requests | 260 successful responses; no transport/500 failures |
| Final successful-request p95 | 2.135 seconds; maximum 2.828 seconds |
| Final interval API OOM-kill counter change | 0 (13 before and after) |

Four HTTP clients repeatedly requested frontend pages, bill lists, a full bill detail and health. Initial harness requests used an incorrect financial URL and returned 404: those are excluded from successful request counts, not treated as application defects. The correct `/api/contracts/1/financial-items/` route was subsequently smoke-tested: HTTP 200, 5,367 bytes. It was not part of the successful load series.

The initial API allocation of 256 MiB was insufficient: both three-process and one-process configurations suffered memory kills under bill-list/detail traffic. Reallocating 512 MiB to a one-process/two-thread API eliminated additional kills during the final interval. This does not mean the whole server ran out of memory; it identifies an undersized per-container allocation.

Final container limits: API 512 MiB; ingestion 384; research 144; enhancement 144; Beat 112; PostgreSQL 192; Redis 48; frontend 128. Total 1,664 MiB, leaving 384 MiB of a 2 GiB machine for the OS, Docker and HTTPS proxy. Swap disabled for benchmark containers. The OS/proxy were not inside this aggregate budget test.

Both real-text and synthetic-large-document contracts completed, including fresh versions submitted during load. Some downstream ingestion jobs exceeded their existing 60-second soft time limit; a transaction-state error was also logged after a timeout. Consequently, end-to-end pipeline reliability under this resource budget is not established, even though the final HTTP run succeeded.

## Before using the $12 tier

1. Add a small-server deployment profile: one API process, two threads, explicitly bounded workers, memory caps, log rotation and separate builds.
2. Diagnose and address the timed-out downstream jobs; verify queue recovery, not just eventual document completion.
3. Repeat with a sanitized production-sized database, finance fixtures and enhancement response fixtures. Measure disk growth against the tier's 50 GiB limit.
4. Run a longer soak test including the OS/proxy, backups and worker activity. Validate on the actual x86 host before public launch.
5. Keep an upgrade path to 4 GB / two CPUs if contention or growth warrants it. No evidence here requires 8 GB initially.

Raw scripts/results: `/private/tmp/legislation-capacity-20261117/`. They are benchmark artifacts, not deployment configuration. No repository application code or running XT services were modified.

## Follow-up: identified timeout cause

Retained queue rows 3 and 11 have kind `similarity` and `SoftTimeLimitExceeded()`; row 9 was left processing. Topic updates and search indexing for the initial documents succeeded. This isolates the observed timeout to similarity computation, not summary extraction.

`_schedule_similarity_for_bill_impl` scans every other bill, recalculates both bills' features for every pair, and performs an update/delete per pair. `_bill_similarity_features` recursively flattens the complete contract JSON and tokenizes it each time. Its `bill_topics.values_list(...)` also executes queries rather than consuming the prefetched relationship objects.

Profiled the unchanged routine with candidates bounded to IDs 2–201, on the retained benchmark DB, with no HTTP traffic or competing workers:

| Diagnostic | Unchanged algorithm | Test-only per-run feature cache |
| --- | ---: | ---: |
| Wall time with cProfile | 8.058 s | 0.865 s |
| Feature computation calls | 400 | 201 |
| SELECT statements | 410 | 211 |
| UPDATE / DELETE statements | 2 / 198 | 2 / 198 |
| Time attributed to feature building | 7.694 s | 0.566 s |
| Result | 2 computed, 0 removed | 2 computed, 0 removed |

The cache experiment was a process-local monkeypatch, not an application change. These are profiled sample timings, not a prediction that full jobs will run 9x faster. An unbounded reproduction was stopped to avoid spending minutes repeating the known timeout.

The hourly `recompute_similarity_batch` schedules all current-Congress bills, and each compares against all stored bills. At 10,000 bills all in the selected Congress, that means 99,990,000 pair evaluations per scheduled pass, including both directions. Retries begin the whole per-bill scan again without a saved candidate cursor.

Recommended correction: reuse bill features, consume prefetched topics, batch writes/deletes, process bounded resumable candidate chunks, and avoid hourly recomputation of unchanged inputs. Preserve scores and stale-pair removal with regressions. Separately cover interrupted-database-connection recovery; the observed transaction-state error followed a timeout, but it was not independently reproduced in this follow-up. Increasing RAM or merely raising the timeout does not address the confirmed repeated work.

## Implemented correction and repeat measurement

The working tree now implements persistent `BillSimilarityState` features and checkpoints (migration `0022_similarity_checkpoints`). A fingerprint covers scoring method, title, summary, immutable contract identity and sorted topic slugs. Unrelated metadata changes do not invalidate it. Future scoring/tokenization changes must bump `SIMILARITY_METHOD` to invalidate saved features and completion markers.

Each transaction handles at most 100 candidate bills, loads changed contracts in a batch, bulk-upserts qualifying pairs, and deletes obsolete pairs in one query. Features, pair writes and the keyset cursor commit atomically. Sorted bill locks serialize overlapping comparisons; durable deliveries are fenced by token and lease. Changed inputs reset their checkpoint. New/changed bills compare against existing bills, so unchanged neighbors do not need their own full scan. The hourly sweep skips completed fingerprints and pending/dispatched/processing jobs.

Deliveries process checkpointed batches for a 10-second target before yielding to the existing durable dispatcher. This is a between-batch budget, not a hard per-batch deadline. The existing 60-second soft timeout remains unchanged. A failure rolls back only the current batch, not already committed progress. A completed scan may need one final delivery to mark the durable work row succeeded after its payload was advanced. Cold initialization still requires all-pairs work; this change removes repeated hourly all-pairs work, not the initial quadratic algorithm.

### Final rerun

Same eight-container, single-core, 1,664 MiB aggregate allocation as above; API image rebuilt from the fixed working tree. The corrected financial endpoint was included in the load generator. Beat retained only the normal 30-second durable dispatcher; external discovery, hourly full-corpus scheduling, research and paid enhancements stayed disabled.

| Measurement | Fixed pipeline |
| --- | ---: |
| HTTP requests during 60 seconds / four clients | 322 / all HTTP 200 |
| p50 / p95 / maximum response | 0.040 / 2.163 / 3.253 seconds |
| Peak simultaneous sampled container memory | 1,066.2 MiB |
| API / ingestion worker sampled peaks | 412.8 / 258.9 MiB |
| API and ingestion worker OOM counters | 0 |
| Worker timeout/error logs | None during final run |
| Retained benchmark queue at completion | 32 succeeded; 0 unfinished |

The terminal queue includes 2 fresh document-contract jobs, 9 topic updates, 14 search-index jobs, and 7 similarity jobs (including retained duplicates). The three bill scans reached ID 10,000. Fresh real-text and synthetic-large-document analyses completed. Every terminal work row had `attempt_count=1`; normal continuations reset the failure-attempt counter as intended.

After the load run, two concurrent PostgreSQL scans against all 9,999 other bills completed in 2.957 and 2.852 seconds with cached features. Each used 100 chunks; maximum individual chunk times were 0.068 and 0.061 seconds. There were no deadlocks. An unchanged rerun took 0.008 seconds, performed 9 SELECTs and **zero writes**, and did not read contract JSON. An hourly sweep limited to the three completed test bills enqueued **zero** jobs. These warm timings are not cold-cache or full-production-corpus predictions.

Verification: backend suite **1,717 passed, 16 skipped**, including 12 new similarity regressions; migration applied successfully on PostgreSQL; migration drift check and `git diff --check` clean. Existing skipped tests remain unverified by the SQLite suite; the concurrent-scan check above ran separately on PostgreSQL. Regressions cover cached features, batched writes, unchanged skips, interrupted-batch rollback/resume, source/candidate/topic/summary/contract changes, new bills, stale-delivery fencing, retry-budget preservation and dispatched-work deduplication.

The $12-sized configuration remains plausible for a small beta, now with the observed similarity timeout resolved in this workload. It is **not** a production-readiness certification: the real full-text corpus, busy research/enhancement workers, OS/proxy overhead, disk growth and a longer x86-host soak still need measurement. The prior database-connection error was not independently reproduced; this rerun avoided its triggering similarity timeout rather than proving every interrupted-connection recovery path.

Raw repeat evidence: `fixed-final-http.json`, `fixed-final-memory.json`, and `fixed-profile.txt` in `/private/tmp/legislation-capacity-20261117/`. Only the isolated capacity database was migrated/mutated. The application and XT services were left untouched.
