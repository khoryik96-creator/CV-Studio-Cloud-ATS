# M4 — preserve the existing CV Studio interface

Owner decision: reuse original index.html, app.css, theme, controls and workflows. Replacement PR #15 remains closed and unmerged. This PR adds only independent cloud-side browser adapters and a fixture against the original markup. It does not serve the full desktop shell, change the original UI files or enable production routes.

## Audit and migration map

| Existing frontend | Cloud direction |
|---|---|
| index.html tabFormat/viewFormat; btnFormat, btnBlind, btnDocx, cvInput, fileInput, stepText, outputBox | Preserve layout and controls; bind explicit cloud client after safe composition |
| tabBatch/viewBatch; batch-format.js | Preserve batch UI; submit immutable jobs and show authoritative per-document state |
| tabAppraiser/viewAppraiser; cv-scoring.js | Preserve assessment view; replace desktop lock and provider access with role-aware server workflow |
| tabCompany/viewCompany; company-profile.js | Preserve briefing UI; integrate server-sourced research and citations |
| tabJDAnon/viewJDAnon; blind-jd.js | Preserve preview, controls and export; enforce server-side output review |
| api-transport.js, ai-keys.js, ai-routing.js, input-file.js, runtime-core.js, settings.js | Do not run desktop bootstraps in cloud; they restore browser keys, call local endpoints and initialize integrations |
| cv-format.js | Existing startFormat directly calls /parse, /blind, /generate-docx and may auto-upload to JobAdder. Do not expose these routes; replace orchestration through authenticated job API |
| page-tabs.js | Existing switchTab calls all modules, including desktop unlocks and integrations. Adapt navigation explicitly for cloud allowlist |
| All other tabs and integrations | Retain source, omit from cloud composition and deny server routes/jobs |

The explicit client uses only /api/auth/me, /api/auth/logout, /api/documents, /api/jobs, status and download. It never transmits provider credentials or caller-supplied URLs. An immutable submission intent supports manual retry with the same idempotency key; no automatic mutation retries. Existing controls binding refuses desktop onclick handlers, reads the original input and updates original status/output/download controls. It supports a caller-driven refresh and explicit human-review download. No fake progress. Dispose clears visible candidate input and result status. Auth login, safe allowlisted shell composition, actual UI mounting, polling lifecycle, session teardown, preview data, summary and formatting-review options, user settings, document history, batch support and remaining modules are still outstanding. Currently the adapter only displays textual job status, not the original structured CV preview. Do not substitute a status message for final parity. Unsupported desktop controls must be clearly disabled until supported, never silently ignored.

Security requirement: render only audited markup and scripts; no blanket serving index.html or legacy scripts and no global fetch override. Backend remains authoritative for permissions, CSRF, job IDs, validation and review state. Only synthetic fixtures; no live data or VPS changes.