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
    def test_font_signature_is_not_phone_but_contact_fields_are(self):
        ns="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        def document(part,xml):
            buf=io.BytesIO()
            with zipfile.ZipFile(buf,"w") as archive:
                archive.writestr(part,xml)
            return buf.getvalue()
        font=document("word/fontTable.xml",f'<w:fonts xmlns:w="{ns}"><w:font w:name="Calibri"><w:sig w:usb0="00000000" w:csb1="00000000"/></w:font></w:fonts>')
        verify_blind_identity(font,PARSED)
        for part,xml in (
            ("word/fontTable.xml",f'<w:fonts xmlns:w="{ns}"><w:font w:name="+60 10 000 0000"><w:sig w:usb0="00000000"/></w:font></w:fonts>'),
            ("word/header1.xml",f'<w:hdr xmlns:w="{ns}"><w:p><w:r><w:t>+60 10 000 0000</w:t></w:r></w:p></w:hdr>'),
            ("word/fontTable.xml",f'<w:fonts xmlns:w="{ns}"><w:font w:name="Calibri"><w:sig w:usb0="+60 10 000 0000"/></w:font></w:fonts>'),
        ):
            with self.assertRaises(EngineError):
                verify_blind_identity(document(part,xml),PARSED)
    def test_blind_brand_cleanup_preserves_ordinary_words(self):
        from cvstudio_blind_mask import _blind_collect_org_mask_terms, _blind_replace_org_terms_in_text

        ordinary = "Digital marketing, Digitalisation and DIGITAL operations."
        self.assertEqual(_blind_replace_org_terms_in_text(ordinary, ["Digi"]), ordinary)
        self.assertNotIn("Digi", _blind_collect_org_mask_terms({"summary_bullets": [ordinary]}))
        self.assertEqual(_blind_replace_org_terms_in_text("Launched DigiPrepaid and Maybank2u.", ["Digi", "Maybank"]),
                         "Launched [Company]Prepaid and [Company]2u.")

    def test_distinct_blind_roles_keep_their_employer_boundaries(self):
        from copy import deepcopy
        from cloud.cv_pipeline import postprocess_blind
        from cvstudio_cv_normalize import _merge_adjacent_continuous_company_stints

        original = {"work_experiences": [
            {"company": "Fictional North Ltd", "date_range": "Jan 2020 - Jan 2021",
             "roles": [{"title": "Engineer", "date_range": "Jan 2020 - Jan 2021", "bullets": ["Ran backups."]}]},
            {"company": "Fictional South Ltd", "date_range": "Feb 2021 - Dec 2021",
             "roles": [{"title": "Senior Engineer", "date_range": "Feb 2021 - Dec 2021", "bullets": ["Ran restores."]}]},
        ]}
        blinded = deepcopy(original)
        entries = blinded["work_experiences"]
        for entry in entries:
            entry["company"] = "Technology Company"
        self.assertEqual(len(_merge_adjacent_continuous_company_stints(entries)), 1)
        result = postprocess_blind(blinded, original)["work_experiences"]
        self.assertEqual(len(result), 2)
        self.assertEqual({row["roles"][0]["title"] for row in result}, {"Engineer", "Senior Engineer"})
        for entry in entries:
            entry["company"] = "[Company]"
        self.assertEqual(len(_merge_adjacent_continuous_company_stints(entries)), 2)

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
        # Surface fixed, content-free package-part categories only for diagnostics.
        from unittest.mock import patch
        from cloud.cv_engine import blind_identity_findings
        def checked(raw,original):
            self.assertEqual(blind_identity_findings(raw,original),())
            verify_blind_identity(raw,original)
        with patch("cloud.cv_engine.verify_blind_identity",side_effect=checked):
            result=process(SOURCE,complete=fake,blind=True)
        self.assertTrue(result.requires_review)
        with zipfile.ZipFile(io.BytesIO(result.document)) as archive:
            xml=archive.read("word/document.xml").decode().casefold()
        self.assertNotIn("avery",xml)
        self.assertNotIn("avery@example.invalid",xml)
