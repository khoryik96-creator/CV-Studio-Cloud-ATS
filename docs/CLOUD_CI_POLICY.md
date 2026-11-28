# Change-aware CI policy

Routine cloud development should be grouped into cohesive PRs, not a PR for
each trivial edit. Finish a related change on its feature branch before
opening a PR; do not push every small intermediate edit to an open PR.
Never skip checks by adding a skip-CI commit message.

The five existing workflows retain their names and always report a routing
job. Heavy jobs run only when the conservative diff classifier selects them:

| Scope | Windows/macOS | PostgreSQL + Linux cloud regression | VPS/online smoke | Fixture + interactive smoke |
| --- | --- | --- | --- | --- |
| Documentation only | No | No | No | No |
| Isolated online-auth deployment | No | Yes | Yes | No |
| Cloud-only | No | Yes | Yes | Yes |
| Shared/desktop, dependencies, CI policy or unknown | Yes | Yes | Yes | Yes |

Manual dispatch, tag pushes, missing history, ambiguous diffs and code
deletions select the full suite. Shared files such as the desktop engine,
root HTML, JavaScript renderer, package and Python requirements also select
full checks. A routing failure fails its workflow and defaults its dependent
jobs to full checks. The existing security/integration tests are not removed.
Linux runs cloud Python and JS regression coverage when desktop tests are
not needed. Pip cache is enabled; superseded runs are automatically cancelled.
No dependency lockfile is currently present, so Node/Docker caching is a
separate optimization after reproducibility and profiling.

Merge only after checking the exact head, selected scope, all applicable
jobs and review; a skipped required job is not evidence a test executed.
Run and verify the full suite before approving a production release.
Do not deploy the private synthetic fixture publicly or change HyPlug.

Before this policy is merged, full CI and classifier tests must pass.
After merge, verify a real reduced-scope PR routes correctly. Preserve
existing branch protection; no changes to required-check settings are made.
