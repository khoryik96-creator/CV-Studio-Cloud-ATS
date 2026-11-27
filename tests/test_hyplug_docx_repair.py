"""Synthetic regression for HyPlug Word repair; no personal documents."""
import io
import zipfile
import unittest
from lxml import etree
from cvstudio_docx_repair import W, repair

NS = "{" + W + "}"
class TestDocxRepair(unittest.TestCase):
    def test_schema_order_and_text_preservation(self):
        document = f'<w:document xmlns:w="{W}"><w:body><w:p><w:pPr><w:jc w:val="both"/><w:ind w:left="720"/><w:spacing w:after="0"/><w:keepNext/></w:pPr><w:r><w:rPr><w:sz w:val="22"/><w:b/></w:rPr><w:t>Example duty</w:t></w:r></w:p><w:tbl><w:tr><w:trPr><w:trHeight w:type="exact" w:val="200"/></w:trPr></w:tr></w:tbl></w:body></w:document>'
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", document)
            z.writestr("docProps/app.xml", "<Properties><Pages/><Company>Example</Company></Properties>")
            z.writestr("word/media/image.png", b"unchanged")
        first = repair(buf.getvalue())
        with zipfile.ZipFile(io.BytesIO(first)) as z:
            root = etree.fromstring(z.read("word/document.xml"))
            self.assertEqual([e.tag for e in root.find(".//"+NS+"pPr")], [NS+x for x in ("keepNext","spacing","ind","jc")])
            self.assertEqual(root.find(".//"+NS+"jc").get(NS+"val"),"both")
            self.assertEqual(root.find(".//"+NS+"ind").get(NS+"left"),"720")
            self.assertEqual([e.tag for e in root.find(".//"+NS+"rPr")],[NS+"b",NS+"sz"])
            self.assertEqual(root.find(".//"+NS+"t").text,"Example duty")
            self.assertEqual(root.find(".//"+NS+"trHeight").get(NS+"hRule"),"exact")
            self.assertIsNone(root.find(".//"+NS+"trHeight").get(NS+"type"))
            self.assertIsNone(etree.fromstring(z.read("docProps/app.xml")).find("Pages"))
            self.assertEqual(z.read("word/media/image.png"), b"unchanged")
        with zipfile.ZipFile(io.BytesIO(first)) as z1, zipfile.ZipFile(io.BytesIO(repair(first))) as z2:
            self.assertEqual({n:z1.read(n) for n in z1.namelist()}, {n:z2.read(n) for n in z2.namelist()})

if __name__ == "__main__":
    unittest.main()
