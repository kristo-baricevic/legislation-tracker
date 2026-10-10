# Local card dashboard

Only the home dashboard changes. The existing `Dashboard.tsx`, other routes, backend, schema, and API helpers remain unchanged.

## Local flag and rollback

Key: `legislation-tracker-dashboard-cards` in this frontend origin's localStorage. Missing values default to true and are initialized to `"true"` after hydration. Explicit `"false"` is respected across reloads. Storage denial falls back safely without crashing. The checkbox below the dashboard switches versions and saves the preference; it reports storage write failures.

In the browser console for the local frontend:

```js
localStorage.setItem("legislation-tracker-dashboard-cards", "false"); location.reload(); // original dashboard
localStorage.setItem("legislation-tracker-dashboard-cards", "true"); location.reload(); // cards
localStorage.removeItem("legislation-tracker-dashboard-cards"); location.reload(); // reset to default true
```

The preference belongs to the browser origin, including port. There is no remote flag service.

## Ingestion telemetry visual preview

The separate `legislation-tracker-ingestion-telemetry` localStorage flag defaults to true and preserves explicit `"false"`. The Show ingestion telemetry preview checkbox saves this setting. Set the key to `"false"` and reload to hide the panel, or remove the key to reset its default. The panel mounts only within the new card dashboard, so the original dashboard remains unchanged.

The operator-oriented sample preview is visible to dashboard viewers and is not a staff authorization mechanism. Sample data remains static and explicitly labeled; sample ingestion is disabled. Congress.gov API is the source represented by the samples. Nonstaff viewers unchecking Show sample data see unavailable values. Staff viewers instead see an operational panel: Refresh telemetry explicitly reads staff-only backend snapshots; it does not scan the source or start work. Start discovery and ingestion is a separate explicit action using the existing credentialed/CSRF API helper and a retained idempotency key. Prepare a new discovery request becomes available after a confirmed terminal discovery status. Source-ready counts expire after five minutes even without another fetch. No automatic ingestion requests or polling occur. Staff authorization is enforced by the backend, not by this UI flag. See backend TELEMETRY.md for migration and source-snapshot setup; an unconnected or unmigrated backend remains unavailable.

## Design and data

Dream App's actual `EntryCard`, `DreamMain`, `MainHeader`, and `DreamCatcher` informed the color-coded collection, expanded details, and layout options. Existing Geist typography, a light off-white background, white cards, and navy, burgundy, green, blue, violet, and teal bars define the dashboard palette. The site header matches this palette only while the card dashboard is rendered; other pages and the legacy dashboard keep their existing header. The distinct top bars supplement written topic headings and card topic labels.

Following shows every directly followed bill from `getMyTracking`. Each bill appears once, grouped under its first followed topic when available, otherwise its first recorded topic or Other legislation. Following a topic alone does not falsely mark its bills as directly followed. Manage topics opens the unchanged topics page.

All bills uses the same `getBills` endpoint as the existing bill table, sorted by recent activity, and preserves loaded pages with Load more. Grid is the default; List is available. Filters operate on loaded cards and say so explicitly. Search matches title/number. Other filters use recorded topics, status, sponsor name, and sponsor state. State comes from an exact sponsor-name match in the existing current representative directory; historical or unlisted sponsors cannot reliably be assigned a state. State is never inferred from political or personal data. Cards display actual status; summaries are fetched on opening details, avoiding one detail request for every card.

The modal uses `getBill` and `compareBillDocuments`. Document `source_order` identifies the preceding recorded version, never download date or ID. A selected version updates its document link, summary availability, predecessor label, and structural comparison. Comparison requests and displayed results are tied to the selected pair; stale responses are ignored. No AI service is called. A bill-level summary is shown separately with its source/version. A version summary is reused only when its identifier exactly matches the document version label; the API's differing identifiers can mean a linked summary is unavailable. Missing summaries, missing version order, earliest versions, partial comparisons, and fallback comparisons have explicit notices. Structural changes are never described as invented legal-effect summaries.

Native modal dialog makes the background inert, with explicit Tab/Shift+Tab wrapping, Escape, restored opener focus, scroll locking, and accessible title. Styles are scoped to the card dashboard and its modal, with mobile/tablet/desktop grids and long-title wrapping.

## Local preview and verification

From `legislation-tracker-client`, using RTK:

```sh
rtk proxy node node_modules/next/dist/bin/next dev --webpack --hostname 127.0.0.1 --port 13280
```

Open `http://127.0.0.1:13280`. Set the existing `NEXT_PUBLIC_API_URL` environment variable to the legislation API before starting if it is not at the existing default `http://localhost:8000`. No backend is started by this change. If the API is offline the dashboard shows recoverable errors. This port is separate from the XT audit dashboard on 8769.

The isolated browser regressions intercept existing API endpoints with explicit test fixtures; screenshots depict those fixtures, not a live account. They test filters, layout, follow/unfollow, all/followed collections, pagination, rollback/reload persistence, modal version changes, keyboard containment, responsive overflow, missing data, and API errors. They do not establish that the currently stopped backend contains version comparisons for every real bill.

```sh
rtk proxy node node_modules/typescript/bin/tsc --noEmit
rtk proxy node node_modules/eslint/bin/eslint.js .
rtk proxy node node_modules/vitest/vitest.mjs run
rtk proxy node --disable-warning=ExperimentalWarning --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --experimental-strip-types --test tests/*.test.ts
rtk proxy node node_modules/@playwright/test/cli.js test --config playwright.dashboard.config.ts
rtk proxy node node_modules/next/dist/bin/next build --webpack
```

The separate Playwright config targets only this dashboard and local port; it does not start the default E2E backend or touch another browser profile. Installed dependencies are reused through a local ignored node_modules symlink so the original checkout is not modified or reinstalled.

Inventory semantics: missing_unqueued_metadata is a full-source historical metadata gap count, not readiness for incremental Start. ready_to_start is the observed distinct bill-identity count that would create new bill work in the next incremental poll; incomplete, stale or changed-basis observations return null. Start retains the existing cursor and five-minute overlap; historical gaps may be omitted. No cursor reset or backfill was added. Malformed, naive or future source timestamps make all inventory counts unavailable. Prepare requires a terminal refreshed snapshot with the exact accepted run ID.

Cache configuration: base settings use django.core.cache.backends.redis.RedisCache at REDIS_URL; dev and prod inherit it. Test/e2e explicitly override with LocMemCache and cannot prove cross-process sharing. Deployment must give the inventory command and HTTP workers the same Redis location/database and key configuration. No running deployment cache configuration is claimed here.
