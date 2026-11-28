import unittest
from cloud.app import create_app
from cloud.modules import MODULES, SELECTED_MODULES

class CloudFoundationTest(unittest.TestCase):
    def test_scope(self):
        self.assertEqual(SELECTED_MODULES, {"cv_formatting", "cv_blinding", "cv_scoring", "company_profile", "blind_jd", "create_profile"})
        self.assertEqual(len(MODULES), len({m.key for m in MODULES}))

    def test_no_legacy_routes_exposed(self):
        client = create_app().test_client()
        self.assertEqual(client.get("/healthz").status_code, 200)
        self.assertEqual(client.get("/readyz").status_code, 503)
        for path in ("/", "/blind", "/parse", "/generate-docx", "/jobadder", "/apollo", "/ocr"):
            self.assertEqual(client.post(path).status_code, 404)
            self.assertEqual(client.get(path).status_code, 404)

if __name__ == "__main__":
    unittest.main()
