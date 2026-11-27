"""Extract bounded DOCX, PDF or UTF-8 text; never follow external links.

Run in an isolated resource-limited worker. Scanned or mixed-text PDFs are
refused until the OCR integration can establish completeness.
"""
from dataclasses import dataclass
import io
from cloud.private_storage import validate_payload,DOCX
from cloud.cv_engine import MAX_SOURCE
from cvstudio_layout_parity import _extract_docx_bullet_levels
from cvstudio_document_safety import validate_zip_payload,MAX_PDF_PAGES

class ExtractionError(ValueError):
    pass

@dataclass(frozen=True,repr=False)
class Extracted:
    text: str
    levels: list

def _append(lines, text, total):
    total+=len(text)+1
    if total>MAX_SOURCE:
        raise ExtractionError("extracted_text_limit")
    lines.append(text)
    return total

def extract(raw,media_type):
    try:
        validate_payload(raw,media_type)
        lines,total,levels=[],0,[]
        if media_type=="text/plain":
            total=_append(lines,raw.decode("utf-8"),total)
        elif media_type==DOCX:
            import docx
            from docx.oxml.ns import qn
            validate_zip_payload(raw,"uploaded document")
            doc=docx.Document(io.BytesIO(raw))
            # Preserve body/table paragraph order and tabs, not just doc.paragraphs.
            from docx.text.paragraph import Paragraph
            for node in doc.element.body.iter(qn("w:p")):
                total=_append(lines,Paragraph(node,doc).text,total)
            levels=_extract_docx_bullet_levels(raw)
        elif media_type=="application/pdf":
            from pypdf import PdfReader
            reader=PdfReader(io.BytesIO(raw),strict=True)
            if reader.is_encrypted or not 1<=len(reader.pages)<=MAX_PDF_PAGES:
                raise ExtractionError("unsupported_pdf")
            for page in reader.pages:
                text=page.extract_text() or ""
                if not text.strip():
                    raise ExtractionError("pdf_requires_ocr")
                total=_append(lines,text,total)
        else:
            raise ExtractionError("unsupported_document")
        result="\n".join(lines)
        if not result.strip():
            raise ExtractionError("empty_document")
        return Extracted(result,levels)
    except ExtractionError:
        raise
    except Exception:
        raise ExtractionError("document_extraction_failed") from None
