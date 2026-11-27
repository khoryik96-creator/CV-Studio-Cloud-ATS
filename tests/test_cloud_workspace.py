import unittest
from html.parser import HTMLParser
from flask import Flask
from cloud.app import create_app
from cloud.workspace import workspace

class Markup(HTMLParser):
    def __init__(self):
        super().__init__();self.ids=[];self.modules=[];self.scripts=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if "id" in a:self.ids.append(a["id"])
        if "data-module" in a:self.modules.append(a["data-module"])
        if tag=="script":self.scripts.append(a.get("src"))

class TestWorkspace(unittest.TestCase):
    def setUp(self):
        app=Flask(__name__,static_folder=None)
        app.register_blueprint(workspace)
        self.client=app.test_client()
    def test_opt_in_only(self):
        self.assertEqual(create_app().test_client().get("/workspace").status_code,404)
    def test_workspace_structure_and_headers(self):
        r=self.client.get("/workspace")
        self.assertEqual(r.status_code,200)
        self.assertIn("frame-ancestors 'none'",r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["Cache-Control"],"no-store")
        m=Markup();m.feed(r.get_data(as_text=True))
        self.assertEqual(len(m.ids),len(set(m.ids)))
        self.assertEqual(m.modules,["cv_formatting","cv_blinding"])
        self.assertEqual(m.scripts,["/workspace/assets/workspace.js"])
        for path in ("/workspace/assets/workspace.css","/workspace/assets/workspace.js"):
            self.assertEqual(self.client.get(path).status_code,200)
    def test_no_arbitrary_asset_access(self):
        self.assertEqual(self.client.get("/workspace/assets/index.html").status_code,404)
        self.assertEqual(self.client.get("/workspace/assets/secret.txt").status_code,404)
