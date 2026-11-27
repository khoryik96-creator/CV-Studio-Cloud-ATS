"""Opt-in local OCR, bounded per document. Requires an isolated Linux worker."""
from dataclasses import dataclass
import math
from contextlib import closing
import threading
import time
from cvstudio_document_safety import rendered_pdf_page_is_visually_blank

MAX_PAGES = 30
MAX_PIXELS = 16_000_000
MAX_SECONDS = 180
_GATE = threading.BoundedSemaphore(1)

class OcrError(ValueError):
    pass

@dataclass(frozen=True,repr=False)
class PageText:
    text: str
    blank: bool = False

def read_pages(raw, page_numbers, *, keep_alive=lambda:None):
    """One-based selected pages. Never guess a page was blank from empty OCR."""
    import pypdfium2 as pdfium
    import pytesseract
    pages=tuple(page_numbers)
    if not 1<=len(pages)<=MAX_PAGES or len(set(pages))!=len(pages) or any(type(p) is not int or p<1 for p in pages):
        raise OcrError("invalid_ocr_page_selection")
    if not _GATE.acquire(timeout=2):
        raise OcrError("ocr_capacity_exhausted")
    deadline=time.monotonic()+MAX_SECONDS
    result={}
    try:
        with pdfium.PdfDocument(raw) as document:
            if max(pages)>len(document):
                raise OcrError("invalid_ocr_page_selection")
            for number in pages:
                keep_alive()
                if time.monotonic()>=deadline:
                    raise OcrError("ocr_deadline")
                with closing(document[number-1]) as page:
                    width,height=page.get_size()
                    scale=3.0
                    if not all(math.isfinite(n) and n>0 for n in (width,height)) or math.ceil(width*scale)*math.ceil(height*scale)>MAX_PIXELS:
                        raise OcrError("ocr_page_dimensions")
                    with closing(page.render(scale=scale)) as bitmap:
                        image=bitmap.to_pil().copy()
                        try:
                            if image.width*image.height>MAX_PIXELS:
                                raise OcrError("ocr_page_dimensions")
                            if rendered_pdf_page_is_visually_blank(image):
                                result[number]=PageText("",True)
                            else:
                                remaining=deadline-time.monotonic()
                                if remaining<1:
                                    raise OcrError("ocr_deadline")
                                text=pytesseract.image_to_string(image,lang="eng",timeout=min(35,int(remaining))).strip()
                                if not text:
                                    raise OcrError("ocr_unreadable_page")
                                result[number]=PageText(text)
                        finally:
                            image.close()
                if time.monotonic()>deadline:
                    raise OcrError("ocr_deadline")
                keep_alive()
        return result
    except OcrError:
        raise
    except Exception:
        raise OcrError("ocr_failed") from None
    finally:
        _GATE.release()
