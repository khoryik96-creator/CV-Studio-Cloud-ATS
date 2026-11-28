"""Run only the existing synthetic CV integration case in disposable Compose."""
import os
import unittest

def main():
    # Fail closed: the test module skips when DSNs are absent. Never accept a
    # caller-supplied external DB, production account or alternate credentials.
    expected = {
        "CVCLOUD_TEST_DSN": "postgresql://postgres:synthetic-ci-only@db:5432/cvcloud_test",
        "CVCLOUD_TEST_RUNTIME_DSN": "postgresql://cvcloud_runtime:synthetic-runtime-only@db:5432/cvcloud_test",
    }
    if any(os.environ.get(k) != v for k, v in expected.items()):
        raise SystemExit("Disposable fixture DSNs required")
    import psycopg
    with psycopg.connect(expected["CVCLOUD_TEST_DSN"], connect_timeout=5) as conn:
        if conn.execute("SELECT to_regnamespace('cvcloud')").fetchone()[0] is not None:
            raise SystemExit("Refusing nonempty fixture schema")
        conn.execute("CREATE ROLE cvcloud_runtime LOGIN PASSWORD 'synthetic-runtime-only' NOSUPERUSER NOBYPASSRLS")
    suite = unittest.defaultTestLoader.loadTestsFromName(
        "tests.cloud_postgres_integration.TestPostgres.test_synthetic_staging_composition"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() and result.testsRun == 1 and not result.skipped else 1

if __name__ == "__main__":
    raise SystemExit(main())
