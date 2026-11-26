# Bill enhancement pipeline

A signed-in reader can request a cited explanation of a federal bill using a provider key saved in Settings. Opening the bill first looks for an existing reader. Generating a new one requires an estimate and explicit confirmation. The original bill text and deterministic analysis remain available throughout.

## From bill page to worker

1. **Look up existing work.** The bill page loads the latest enhancement and any compatible published reader. Signed-in users can share completed results or follow work already in progress for the same source. Compatibility depends on the document and its text, plus the extraction contract where the reader uses contract items. Attempt history and credentials remain private to the payer.
2. **Prepare an estimate.** When the user requests one, Django selects the stored bill document and plans work for the selected provider and model. It returns source and request fingerprints and the applicable limits. This step makes no generation call. For new free OpenRouter requests, the model must be a selectable concrete ID from the catalog. Operators can exclude incompatible IDs with `LLM_OPENROUTER_EXCLUDED_MODELS`.
3. **Confirm and queue.** The client submits the confirmation from that estimate. The API locks the bill and checks for reusable work again so concurrent confirmations can share one job. Before authorizing new work it validates the source, request, credential identity and revision, and execution configuration. A stale confirmation requires a refreshed estimate. The accepted attempt goes to the Celery enhancement worker.
4. **Execute and publish.** The worker checks its authority to run and executes the confirmed plan through the selected adapter. Reader and source-first jobs record each dispatch before contacting the provider, retain available usage, and check the approved identity again before publication. The client polls the job and displays the saved result when available.

## How the planner chooses a path

The rules below run in order. “Source-first” refers specifically to schema `2.0-source-first`. The batched reader also reviews source text, but has a different output and recovery contract.

| First applicable condition | Execution path |
| --- | --- |
| No partial result is being reused, and the document exceeds the inline limit or an owned-token planning target is set | **Batched reader (1.4).** Plan batches across the document, using aligned XML sections when available. |
| `LLM_SOURCE_FIRST_ENABLED` is enabled | **Source-first (2.0).** Build a graph of pinned passages and provision units. Plan generation for eligible units and account for accepted units on a partial retry. |
| The document has a reader contract | **Batched reader (1.4).** Use the contract's targets for item explanations alongside the full-source review. |
| Otherwise | **Legacy enhancement.** Select complete source sections within the request limit and plan glossary batches when definition targets exist. |

The [planner](../../legislation-tracker-backend/apps/legislation/enhancements/source_packet.py) owns this precedence. Enabling source-first alone does not route every bill to schema 2.0.

## What runs after confirmation

**Batched reader.** The worker explains target items and reviews source passages for policies and financial provisions. It resolves citation IDs against stored text, checks coverage and financial evidence, and builds the summary from the completed review. Durable work records let a later delivery reuse validated batches. A known truncated batch can split within the confirmed allowance. If execution pauses, the user can review a continuation estimate. See the [reader publication and recovery contract](../reader-full-source-review.md).

For staged readers the estimate reserves the planned map and synthesis calls, bounded split and summary recovery, and a dependency allowance for each owner with deferred records. Each owner can start with one page per record up to eight pages, plus four recovery calls. For dense owners, the planner estimates pages from the selected model’s visible output budget, the provider’s schema limits and the bytes of cited evidence. The worker measures the complete requests after mapping supplies the actual items. The worker checks the confirmed ceiling before each new dispatch. If the pages need more calls, the worker saves progress and pauses for confirmation. A confirmed continuation can replay validated pages from storage for free. If the provider returns an unresolved dependency, an invalid summary repair, or a truncated response at the output ceiling, a new confirmation can retry the failed call. The worker reuses validated responses and skips earlier requests that already led to that repair.

In strict schema mode, the four provider adapters send a nonrecursive schema for staged maps and decode JSON-encoded conditions and exceptions. OpenRouter’s JSON-object and prompt-only modes also accept native condition trees and exception arrays. All modes check condition depth before recursive schema validation. If local validation fails after the provider responds, the worker records the response ID and reported usage as a known failure. Reconciliation consumes the validated trees. Public readers receive the reviewed prose and citations.

**Source-first.** The worker generates provision explanations from the planned units, validates evidence and conditions locally, and can spend the reserved calls on targeted repair and a synopsis. Unresolved units remain visible in coverage. A partial retry can improve a saved result only when it preserves accepted explanations and reduces the unresolved set for the same document. Mechanical validation establishes source linkage and coverage of inventoried units. Legal accuracy still requires semantic review. See the [source-first execution contract](../../legislation-tracker-backend/docs/SOURCE_FIRST_ANALYSIS.md).

**Source-first preflight reuse.** A worker delivery builds its initial plan from current inputs. Before another dispatch and before publication, it reads the inputs again and compares a guard covering document ID and version, text and XML digests, provider, model and planning limits, reasoning effort, reused provisions, and prompt and schema versions. A match lets it skip XML alignment, graph construction and planning. A mismatch rebuilds the plan and checks it against the approved request. Feature availability, model eligibility and capabilities, credential revision, worker lease and request identity are still checked. A later delivery builds its own initial plan. See the [guard](../../legislation-tracker-backend/apps/legislation/enhancements/source_first_preflight.py) and [dispatch checkpoints](../../legislation-tracker-backend/apps/legislation/enhancements/source_first_worker.py).

## When a provider may already have charged

If a reader call times out after dispatch and its outcome is unknown, the reservation stays in place. The bill page shows the possible-charge warning and offers **Check current model estimate**. The fence survives planner upgrades. For older reservations, the worker checks any surviving source snapshot and can reconstruct historical request keys from the verified original XML. Selecting the same pinned OpenRouter model directly also keeps an identical operation blocked. Rotating the credential alone leaves the same call blocked pending reconciliation. Selecting a different eligible provider or model can yield a distinct estimate. The user must confirm that estimate before a new request starts. A failed attempt leaves the previous published reader available.

For provider setup, diagnostic retention, and the bounded transport-comparison harness, see the [AI enhancement guide](../../legislation-tracker-backend/docs/LLM_ENHANCEMENTS.md).
