# Online budget and Blind JD batch

Based on merged PR #52 (7e4dbfde7faeca29d400f0cefa2f4ff06f14c787).
Candidate only. No live AI, public routing, real data or VPS changes.

- Operator-only cumulative spending ceiling with explicit compare-and-set:
  `docker compose -p cvcloud-online-workspace -f cloud/deploy/compose.online-workspace.yaml run --rm budget --tenant hyppies --new --limit 10000000 --confirm`
  Example only, NOT approved spending or a command to execute on production.
  10,000,000 micro-USD = USD 10. Existing limits require --expected-limit.
  Lowering to zero blocks new reserves; outstanding holds and settled charges
  are retained, and actual bills may exceed reservation estimates. No automatic
  monthly reset, top-up, reconciliation or billing guarantee.
- New additive report grant install preserves existing signed grant history.
  Enables report option writes for document role and result writes for worker.
- Blind JD is independently enabled in API, original UI and worker claim
  selection. Company Profile remains disabled pending research integration;
  JobAdder/Create Profile remains disabled pending reviewed CRM integration.
- Disposable tests cover budget creation/conflict/settlement and Blind JD
  processing with fictional input, output review and tenant separation.
- Live worker remains disabled by default; internal networks and no external
  egress. Real provider pricing, reviewed egress/credentials, remaining
  modules and backup/restore are separate acceptance gates.

CI has not been run on this branch yet.
