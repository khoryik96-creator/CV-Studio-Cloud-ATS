import copy
import io
import json
from pathlib import Path
import shutil
import unittest
import zipfile
from cloud.cv_engine import process,answer_json,EngineError,prepare_source,verify_blind_identity

FIXTURES=Path(__file__).with_name("fixtures")
SOURCE=(FIXTURES/"cloud_cv_source.txt").read_text(encoding="utf-8")
PARSED=json.loads((FIXTURES/"cloud_cv_parse.json").read_text(encoding="utf-8"))
class TestEngine(unittest.TestCase):
    def test_source_salary_removed_and_payroll_retained(self):
        result=prepare_source(SOURCE)
        self.assertNotIn("9,000",result)
        self.assertIn("Supported payroll",result)
    def test_bad_response(self):
        for text in ("invalid", '{"candidate":{},"candidate":{},"work_experiences":[]}', '{"candidate":{},"work_experiences":[],"_private":true}', '{"candidate":{},"work_experiences":[],"n":NaN}', '{"candidate":{},"work_experiences":[],"n":1e999}'):
            with self.assertRaises(EngineError):
                answer_json(text)
    def test_identity_sweep_detects_split_runs_and_links(self):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,"w") as archive:
            archive.writestr("word/document.xml",'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Avery </w:t></w:r><w:r><w:t>Example</w:t></w:r></w:p></w:body></w:document>')
            archive.writestr("word/_rels/document.xml.rels",'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="mailto:avery@example.invalid"/></Relationships>')
        with self.assertRaises(EngineError):
            verify_blind_identity(buf.getvalue(),PARSED)
    def test_existing_generic_label_is_not_identity_leak(self):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,"w") as archive:
            archive.writestr("word/document.xml",'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>the candidate</w:t></w:r></w:p></w:body></w:document>')
        verify_blind_identity(buf.getvalue(),PARSED)
    @unittest.skipUnless(shutil.which("node"),"Node renderer unavailable")
    def test_format_real_word_document(self):
        calls=[]
        def fake(stage,system,user,limit):
            calls.append(stage)
            return json.dumps(PARSED)
        result=process(SOURCE,complete=fake,alignment="justify")
        self.assertEqual(calls,["parse"])
        with zipfile.ZipFile(io.BytesIO(result.document)) as archive:
            xml=archive.read("word/document.xml").decode()
        self.assertIn("Disaster Recovery Automation",xml)
        self.assertNotIn("9,000",xml)
        self.assertIn('w:val="both"',xml)
    @unittest.skipUnless(shutil.which("node"),"Node renderer unavailable")
    def test_blind_real_word_document(self):
        def fake(stage,system,user,limit):
            if stage=="parse":
                return json.dumps(PARSED)
            value=json.loads(user.split("\n\n",1)[1])
            value["candidate"].update(name="Candidate",email="[Email Redacted]",phone="[Phone Redacted]",current_company="Technology Company")
            for entry in value["work_experiences"]:
                entry["company"]="Technology Company"
            for edu in value["education"]:
                edu["institution"]="University"
            return json.dumps(value)
        result=process(SOURCE,complete=fake,blind=True)
        self.assertTrue(result.requires_review)
        with zipfile.ZipFile(io.BytesIO(result.document)) as archive:
            xml=archive.read("word/document.xml").decode().casefold()
        self.assertNotIn("avery",xml)
        self.assertNotIn("avery@example.invalid",xml)
