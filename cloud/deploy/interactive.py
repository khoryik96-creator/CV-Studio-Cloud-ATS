"""Local synthetic-only staging lifecycle. Not a production entrypoint."""
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "https://cv.example.test"
HOST = "cv.example.test"
ADMIN = "postgresql://postgres:synthetic-ci-only@db:5432/cvcloud_test"
RUNTIME = "postgresql://cvcloud_runtime:synthetic-runtime-only@db:5432/cvcloud_test"
TENANT = "10000000-0000-4000-8000-000000000001"
USER = "20000000-0000-4000-8000-000000000001"
OTHER_TENANT = "10000000-0000-4000-8000-000000000002"
OTHER_USER = "20000000-0000-4000-8000-000000000002"
PASSWORD = "fictional-staging-only-123"
EMAIL = "synthetic@example.test"
STORAGE = "/srv/cvcloud/data"
CERT = "/tmp/cvcloud.crt"

def connect():
    import psycopg
    if os.environ.get("CVCLOUD_TEST_RUNTIME_DSN") != RUNTIME:
        raise RuntimeError("Synthetic runtime DSN required")
    return psycopg.connect(RUNTIME, connect_timeout=5,
                           options="-c statement_timeout=5000 -c lock_timeout=3000")

def seed():
    import psycopg
    from cloud.auth import password_hash
    if os.environ.get("CVCLOUD_TEST_DSN") != ADMIN:
        raise RuntimeError("Synthetic admin DSN required")
    migrations = sorted((ROOT / "cloud/migrations").glob("*.sql"))
    if not migrations:
        raise RuntimeError("No migrations")
    signature = hashlib.sha256(b"".join(p.read_bytes() for p in migrations)).hexdigest()
    with psycopg.connect(ADMIN, connect_timeout=5) as db:
        db.execute("SELECT pg_advisory_xact_lock(20261128, 40)")
        if db.execute("SELECT to_regnamespace('cvcloud')").fetchone()[0] is not None:
            if db.execute("SELECT to_regclass('public.cvcloud_fixture_marker')").fetchone()[0] is None:
                raise RuntimeError("Refusing existing unmarked database")
            if db.execute("SELECT signature FROM public.cvcloud_fixture_marker").fetchall() != [(signature,)]:
                raise RuntimeError("Fixture schema changed; use a fresh disposable project")
            return
        db.execute("CREATE ROLE cvcloud_runtime LOGIN PASSWORD 'synthetic-runtime-only' NOSUPERUSER NOBYPASSRLS")
        for path in migrations:
            # The standalone SQL files each wrap their own transaction. Keep
            # their statements inside the seed transaction instead.
            prefix, begin, statements = path.read_text(encoding="utf-8").partition("\nBEGIN;\n")
            if not begin:
                statements = prefix.removeprefix("BEGIN;\n")
                if statements == prefix:
                    raise RuntimeError(f"Missing transaction wrapper in {path.name}")
                prefix = ""
            statements = statements.rstrip()
            if not statements.endswith("\nCOMMIT;"):
                raise RuntimeError(f"Missing transaction wrapper in {path.name}")
            db.execute(prefix + "\n" + statements.removesuffix("\nCOMMIT;"), prepare=False)
        db.execute("GRANT USAGE ON SCHEMA cvcloud TO cvcloud_runtime")
        db.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA cvcloud TO cvcloud_runtime")
        for tenant, user, slug in ((TENANT, USER, "fictional"), (OTHER_TENANT, OTHER_USER, "fictional-other")):
            db.execute("INSERT INTO cvcloud.tenants (id,slug) VALUES (%s,%s)", (tenant,slug))
            db.execute("INSERT INTO cvcloud.users (tenant_id,id,email_normalized,password_hash,role) VALUES (%s,%s,%s,%s,'recruiter')",
                       (tenant,user,EMAIL,password_hash(PASSWORD)))
            db.execute("INSERT INTO cvcloud.ai_budgets (tenant_id,limit_microusd) VALUES (%s,1000000)", (tenant,))
        db.execute("CREATE TABLE public.cvcloud_fixture_marker (signature text PRIMARY KEY)")
        db.execute("INSERT INTO public.cvcloud_fixture_marker VALUES (%s)", (signature,))

def environment(*, reverse=False):
    from cloud.auth import Principal
    from cloud.staging import compose_synthetic
    fixtures = ROOT / "tests/fixtures"
    principals=[Principal(TENANT,USER,"recruiter",""),Principal(OTHER_TENANT,OTHER_USER,"recruiter","")]
    if reverse:
        principals.reverse()
    return compose_synthetic(connect=connect,storage_root=STORAGE,
        principals=principals,
        public_origin=ORIGIN,fixture_source=(fixtures/"cloud_cv_source.txt").read_text(encoding="utf-8"),
        fixture_answer=(fixtures/"cloud_cv_parse.json").read_text(encoding="utf-8"),
        fixture_blind_answer=(fixtures/"cloud_cv_blind.json").read_text(encoding="utf-8"),
        strict_upload=True,enable_batch=True,concurrency=1)

def web():
    from werkzeug.serving import make_ssl_devcert, run_simple
    # Local synthetic development TLS only. Never disable TLS verification.
    os.umask(0o077)
    cert = make_ssl_devcert("/tmp/cvcloud",host=HOST)
    run_simple("0.0.0.0",8443,environment().app,ssl_context=cert,
               threaded=True,use_reloader=False,use_debugger=False)

def worker():
    # A new process per bounded tick; the existing runner renews leases.
    # On timeout terminate its whole process group, including Node renderer.
    # Expired fenced leases are reconciled by the next rounds, not replayed.
    def stop(_signal, _frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    reverse = False
    while True:
        action = "tick-other" if reverse else "tick"
        reverse = not reverse
        child = subprocess.Popen([sys.executable,"-m","cloud.deploy.interactive",action],start_new_session=True)
        try:
            child.wait(timeout=660)
        except subprocess.TimeoutExpired:
            print("Synthetic worker round exceeded deadline",flush=True)
        finally:
            if child.poll() is None:
                os.killpg(child.pid,signal.SIGKILL)
                child.wait()
        time.sleep(3)

def main():
    actions={"seed":seed,"web":web,"worker":worker,"tick":lambda:environment().worker.tick(),
             "tick-other":lambda:environment(reverse=True).worker.tick()}
    if len(sys.argv)!=2 or sys.argv[1] not in actions:
        raise SystemExit("Specify seed, web, worker or tick")
    actions[sys.argv[1]]()

if __name__ == "__main__":
    main()
