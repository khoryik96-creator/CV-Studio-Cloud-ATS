"""Bounded literal-text preview derived exclusively from the published DOCX.

Never read source CVs or provider intermediate JSON. No external relationships,
embedded objects, headers, HTML or styles are rendered. This is not a visual
Word rendering or guaranteed anonymisation. Review restrictions are enforced
by the same authenticated output lookup as download.
"""
from io import BytesIO
from zipfile import ZipFile,BadZipFile
from lxml import etree

W="{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MAX_XML=20_000_000
MAX_PARAGRAPHS=2000
MAX_TOTAL=200000
MAX_LINE=20000

class PreviewError(ValueError):
    pass

def preview_paragraphs(raw):
    try:
        with ZipFile(BytesIO(raw)) as z:
            info=z.getinfo("word/document.xml")
            if info.file_size>MAX_XML:
                raise PreviewError("preview_limit")
            root=etree.fromstring(z.read(info),etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False))
        if root.tag!=W+"document" or root.getroottree().docinfo.doctype:
            raise PreviewError("invalid_preview")
        body=root.find(W+"body")
        if body is None:
            raise PreviewError("invalid_preview")
        paragraphs=[]
        total=0
        for p in body.iter(W+"p"):
            parts=[]
            for node in p.iter(W+"t"):
                # Ignore nested text boxes (each paragraph handled separately)
                # and deleted/hidden content. No field instructions or attributes.
                parent=node.getparent()
                include=True
                while parent is not None and parent is not p:
                    if parent.tag in {W+"p",W+"del",W+"moveFrom"} or (parent.tag==W+"r" and parent.find(W+"rPr/"+W+"vanish") is not None):
                        include=False
                        break
                    parent=parent.getparent()
                if include:
                    parts.append(node.text or "")
            line="".join(parts)
            if not line.strip():
                continue
            total+=len(line.encode("utf-16-le"))//2
            if len(line.encode("utf-16-le"))//2>MAX_LINE or total>MAX_TOTAL or len(paragraphs)>=MAX_PARAGRAPHS:
                raise PreviewError("preview_limit")
            paragraphs.append(line)
        return paragraphs
    except (BadZipFile,KeyError,TypeError,ValueError,etree.XMLSyntaxError) as exc:
        if isinstance(exc,PreviewError):
            raise
        raise PreviewError("invalid_preview") from None
