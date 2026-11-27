"""Native OCR smoke: fictional raster PDF, no real CV or external AI."""
import io
import os
import shutil
import unittest
from PIL import Image,ImageDraw,ImageFont
from cloud.ocr import read_pages

class TestNativeOcr(unittest.TestCase):
    def test_raster_pdf_and_blank_page(self):
        if not shutil.which("tesseract"):
            if os.environ.get("CVCLOUD_REQUIRE_NATIVE_OCR")=="1":
                self.fail("Native Tesseract is required in cloud CI")
            self.skipTest("Tesseract unavailable")
        try:
            font=ImageFont.truetype("DejaVuSans.ttf",60)
        except OSError:
            if os.environ.get("CVCLOUD_REQUIRE_NATIVE_OCR")=="1":
                self.fail("DejaVu font is required in cloud CI")
            self.skipTest("Synthetic test font unavailable")
        with Image.new("RGB",(1400,650),"white") as page, Image.new("RGB",(1400,650),"white") as blank:
            ImageDraw.Draw(page).text((90,190),"FICTIONAL ENGINEER",font=font,fill="black")
            buf=io.BytesIO()
            page.save(buf,format="PDF",resolution=144,save_all=True,append_images=[blank])
        calls=[]
        result=read_pages(buf.getvalue(),[1,2],keep_alive=lambda:calls.append(1))
        self.assertIn("FICTIONAL ENGINEER",result[1].text.upper())
        self.assertFalse(result[1].blank)
        self.assertTrue(result[2].blank)
        self.assertEqual(len(calls),4)
