# Synthetic CV container integration
Run from a disposable development or CI Docker host:
```sh
sh cloud/deploy/fixture-smoke.sh
```
This executes the existing synthetic staging composition test using real PostgreSQL, private temporary file storage, the original UI markup, authenticated Flask routes, the existing worker tick, fixture-only completion and Node Word rendering. A unique Compose project and internal runtime network expose no host ports. A separate non-superuser database role is used for the app fixture. No host data mounts, real credentials, live providers or JobAdder writes. The database and temporary files are disposable; build dependencies require network access during image build.

This is a containerized integration test, not an interactive staging server. It tests formatting only using the existing fixture. The browser, background service lifecycle, persistent storage, narrower database grants, dependency digest locking, other five modules and production deployment remain separate gates. Never substitute actual candidate data or point the test at an existing database.
