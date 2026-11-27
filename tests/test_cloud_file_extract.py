import io
import unittest
import docx
from pypdf import PdfWriter
from cloud.file_extract import extract,ExtractionError
from cloud.private_storage import DOCX

class TestExtraction(unittest.TestCase):
    def test_text(self):
        self.assertEqual(extract(b"Example engineer","text/plain").text,"Example engineer")
    def test_docx_table_order(self):
        d=docx.Document()
        d.add_paragraph("Before")
        d.add_table(rows=1,cols=1).cell(0,0).text="Inside"
        d.add_paragraph("After")
        buf=io.BytesIO()
        d.save(buf)
        self.assertEqual(extract(buf.getvalue(),DOCX).text,"Before\nInside\nAfter")
    def test_empty_pdf_requires_ocr(self):
        w=PdfWriter()
        w.add_blank_page(width=200,height=200)
        buf=io.BytesIO()
        w.write(buf)
        with self.assertRaisesRegex(ExtractionError,"pdf_requires_ocr"):
            extract(buf.getvalue(),"application/pdf")
