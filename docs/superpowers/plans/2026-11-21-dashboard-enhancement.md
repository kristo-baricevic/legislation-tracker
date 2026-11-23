# Dashboard enhancement implementation plan

Goal: show the current saved brief on followed and recommended cards. Reuse the same token-confirmation dialog on cards and bill detail.

- [x] Project compact saved summaries into the two existing card responses. Prefer a compatible shared result, fall back to the original brief, and invalidate cached cards on enhancement updates.
- [x] Extract the existing confirmation into the native stacked dialog. Keep estimates read-only and bind submission to the confirmed request fingerprint.
- [x] Place Enhance beside Follow on both rows. Handle shared, queued, running, failed, and unavailable states without starting work automatically.
- [x] Verify with API and component tests, including cancellation and dashboard navigation. No live provider calls.
