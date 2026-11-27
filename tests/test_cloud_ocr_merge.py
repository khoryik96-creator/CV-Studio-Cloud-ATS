import io
import unittest
from pypdf import PdfWriter
from cloud.file_extract import extract,ExtractionError
from cloud.ocr import PageText

def pdf():
    writer=PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=200,height=200)
    buf=io.BytesIO()
    writer.write(buf)
    return buf.getvalue()

class TestOcrMerge(unittest.TestCase):
    def test_order_and_review(self):
        def fake(raw,pages):
            self.assertEqual(pages,[1,2])
            return {2:PageText("Second"),1:PageText("First")}
        result=extract(pdf(),"application/pdf",ocr=fake)
        self.assertEqual(result.text,"First\nSecond")
        self.assertTrue(result.ocr_used)
    def test_missing_or_unreadable_page_rejected(self):
        for values in ({1:PageText("First")},{1:PageText("First"),2:PageText("")}):
            with self.assertRaises(ExtractionError):
                extract(pdf(),"application/pdf",ocr=lambda *_:values)
    def test_verified_blank_page(self):
        result=extract(pdf(),"application/pdf",ocr=lambda *_:{1:PageText("First"),2:PageText("",True)})
        self.assertEqual(result.text,"First")
        self.assertTrue(result.ocr_used)
