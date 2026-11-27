# CV Studio Cloud — foundation and HyPlug parity

This branch starts from desktop v24.6.586 (commit 33a9dad6723294e77f2e8084596bf1b1f7dbbda6). It does not modify the original desktop or ATS repositories.

## Product scope
Only CV formatting, CV blinding, CV scoring, company profile and Blind JD are selected. All other modules are preserved. JD generation is pending. No legacy module is exposed by the separate cloud application. Selection is not authorization.

## Architecture
- Separate Flask composition root; never import or expose desktop app.py from cloud service. Retain Python and Node renderer, extract pure domain adapters rather than rewriting.
- Next: server-side login/session, role and tenant enforcement on every route and object, CSRF, exact allowed HTTPS hosts, trusted proxy configuration. No desktop machine receipt or client-supplied provider keys in cloud.
- PostgreSQL with tenant-scoped tables and least-privileged credentials; separate from HyPlug. Durable job queue with per-tenant quotas, worker leases, idempotency, bounded document/OCR execution and retention. Never put CVs or secrets in logs.
- Persistent private document storage, opaque object keys, authorization before downloads, encrypted provider secrets, audit log, backup/restore.
- Existing Caddy is sole HTTPS entry. Join a dedicated shared proxy network only after readiness gates pass; no public container ports. Separate compose project and data volumes; cap worker resources and protect ATS latency.
- No production deployment until auth, isolation, upload safety, storage, readiness, regression and load tests pass.

## HyPlug parity
Source: HyPlug main, ai/cvstudio/engine/cvstudio_docx_extract.py; ai/src/hiringplug_ai/cvstudio.py; ai/src/hiringplug_ai/cvstudio_blind_guard.py and tests.
- DOCX nesting follows actual indentation and resets at headings; manual overrides precede numbering definitions.
- Preserve one-for-one role/subheading bullet structure, title/date punctuation, separated employers; transfer nested bullet levels after masking in single and batch.
- Renderer generate.js matches upstream by blob SHA at inspection time; left/justify behavior remains.
- Pending: evaluate modified HyPlug template, normalizer/mask diffs, English-word dictionary mask repair, DOCX schema repair, all output routes and visual regression. Do not copy an ATS-specific dependency blindly.
- Test synthetic DOCX indentation, blinding remap, ambiguity and cloud route absence. Do not use real CVs or live AI keys in tests.

## Local foundation smoke test
`docker compose -f deploy/cloud-compose.yml up --build -d` builds the foundation only (no host ports). `docker compose -f deploy/cloud-compose.yml exec cloud python -m unittest cloud.test_foundation` runs the small route/scope suite. /readyz intentionally returns 503. This is not a functional hosted CV Studio.
