import unittest
from cloud.deploy.online_owner import normalize_owner, provision_owner
from cloud.deploy.online_serve import server_options

class OwnerInputsTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_owner("hyppies"," Owner@Example.test ","a-long-owner-password"),("hyppies","owner@example.test"))
        for tenant,email,pw in (("Bad","x@y.test","a-long-owner-password"),("a","@test","a-long-owner-password"),("a","x@y.test","short"),("a","x@y.test","long-password\x00here")):
            with self.subTest(tenant=tenant,email=email),self.assertRaises(ValueError):
                normalize_owner(tenant,email,pw)

    def test_server_options_preserve_raw_proxy_headers(self):
        options=server_options()
        self.assertFalse(options["clear_untrusted_proxy_headers"])
        self.assertNotIn("trusted_proxy",options)
        self.assertFalse(options["expose_tracebacks"])
        self.assertEqual(options["max_request_body_size"],4096)

    def test_wrong_database_refused(self):
        class Result:
            def fetchone(self):
                return ("hiringplug","cvcloud_schema_owner","cvcloud_schema_owner",True,True,True)
        class Connection:
            def __enter__(self):
                return self
            def __exit__(self,*args):
                pass
            def execute(self,sql,*args):
                if not sql.startswith("SELECT current_database()"):
                    raise AssertionError("unexpected database mutation")
                return Result()
        with self.assertRaises(RuntimeError):
            provision_owner(Connection,tenant="test",email="owner@example.test",password="a-long-owner-password")
