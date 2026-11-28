# Company Profile and JobAdder consolidated batch

Based on merged #53 (b8350c571d4157f19f4d2a64c28c6165d34d11c4). Work in
progress, not deployed. Keep the existing interface and separate Company
Profile (company briefing) from Create Profile (candidate upload).

## Company Profile
- Optional operator-curated JSON source catalogue, bounded 2 MiB, at most
  100 company entries, exact normalized company and tenant UUID match,
  with dated HTTPS source excerpts. No URL retrieval or automatic search.
- Optional compose.online-research.yaml mounts the same reviewed catalogue
  into web and worker. The base Compose continues to disable company research.
  Existing live-worker approval remains required. No real sources or file
  contents are committed. Research catalogue configuration does not approve
  paid AI calls.
- Real restricted worker acceptance uses fictional excerpts, verifies evidence
  and cross-tenant denial. Tests are drafted, not executed.
- Automatic research requires a separately reviewed search provider, pricing,
  egress controls, provenance and operator approval. Unknown companies do not
  fall back to generated facts.

## Create Profile / JobAdder
- Candidate sandbox adapter uses existing repository's desktop API contracts
  for email lookup, candidate POST and Resume multipart attachment (fileData).
  Requires injected tenant/account/revision-pinned sandbox session and
  durable cross-worker attempt guard. No resolver/guard is wired yet.
- Explicit no retry and no 401 refresh on writes, duplicate blocking,
  uncertain outcomes require manual review; never attach to existing duplicate.
  PDF/DOCX only, no browser-supplied credentials.
- Fake-client tests cover duplicate, wrong account, incomplete lookup, upload
  failure and non-replay behavior. No actual API or credentials used.
- Do not mount or enable CRM before implementing verified OAuth sandbox
  account binding, a persistent unique job/email attempt journal, correct
  least-privilege grants and read-only reconciliation with verified remote
  candidate/attachment identity. Confirm request and response contracts with
  actual sandbox before any live use. No invented remote success.

Next: complete CRM role/grants, attempt journal and OAuth sandbox resolver,
then one cohesive PR and Linux CI. Keep public ingress and live external
writes disabled; no VPS or HyPlug modifications.
