# Bill reader implementation

Goal: Put a concise sourced summary first and make supporting information easy to browse.
Architecture: Shared reader navigation with persistent tab panels; existing data loaders, financial pagination, AI compatibility checks and source endpoints remain authoritative.
Tech stack: Next.js, React, TypeScript, Django prompt builders.
Spec: User-approved bill-reader-tabs mockup and request of November 9.

Global constraints: No fictional data, hidden financial omissions, inferred total costs, paid AI calls, or service shutdowns. Preserve Original/AI controls and source evidence. Single-agent implementation.
Review focus: Keyboard navigation, state preservation, source dismissal, empty/legacy analysis, financial access and prompt versioning.

- [x] Add regression tests for tab navigation/state and numbered source popovers.
- [x] Implement shared reader tabs; separate summary, changes, money, terms, votes/sponsor and versions without duplicating data loads.
- [x] Replace current reader source disclosures with accessible numbered popovers; retain exact quotations and document links.
- [x] Update versioned AI instructions for plain language, audience, implementation and financial context without weakening factual safeguards.
- [x] Run frontend and backend tests; inspect rendered layout and record limitations.

## Verification

- Frontend: 222 component/unit tests and 59 API tests passed; TypeScript passed.
- Backend: 1,602 passed, 16 skipped using the SQLite test profile. This is not PostgreSQL coverage.
- Browser: nine reader tests passed against isolated real test API/frontend servers. Covered 101 financial items, filter/pagination state, source pagination/download/document access, nested glossary sources on mobile, keyboard focus and votes. Desktop and 390px mobile screenshots inspected during implementation.
- AI integration: the existing durable-enhancement browser test passed once in legacy mode and once with LLM_SOURCE_FIRST_ENABLED=True, using the fake provider and exact source fixture. The reader schema-1.4 budget is covered by provider regression tests, not a paid browser run.
- Long evidence initially overflowed the viewport; the popover height now uses available viewport space and the source-pagination browser test passes.
- The E2E startup script supports E2E_VENV to select an existing complete Python environment; its default is unchanged.
- No paid AI runs. Prompt wiring is tested, but the new prose instructions have not been evaluated against live model output. Existing saved analyses are unchanged; these instructions apply on the next enhancement.
- Legacy analysis formats retain their existing fallback presentation. The tabbed detailed reader targets the current 2.1 analysis format; votes and versions are available even without a current analysis.

## Review corrections

- Preserve the confirmed per-request output budget across reader prompt revisions. The old provider check was pinned to reader-2 and would silently fall back to the general token limit for reader-3. Regression tests cover both revisions.
- Keep nested citation portals in their parent disclosure, restore logical keyboard navigation, and close sources when their tab is hidden. Ignore queued scroll events that do not move the citation anchor.
- Move readers to the start of a newly loaded financial page without stealing focus from another tab.
- Label federal and state sessions correctly without hard-coded ordinal suffixes.
- Store browser screenshots in Playwright's output directory, not an absolute machine-specific path.
- Review covered the full PR, source/definition identity and retries, financial request fencing, saved-AI compatibility and session isolation, prompt schema/budget/version dependencies, and stale-job preflight checks. No new migrations or public API contracts.
