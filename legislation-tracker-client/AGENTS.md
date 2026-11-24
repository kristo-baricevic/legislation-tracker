<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->


## In-place card actions

Keep the surrounding rows mounted and interactive when a card action is pending. For changes to dashboard actions, run the Playwright scroll-stability cases in `e2e/recommendations.spec.ts` on desktop and mobile. Extend those cases when introducing a new in-place action so they check the viewport during a delayed response and after it settles.
