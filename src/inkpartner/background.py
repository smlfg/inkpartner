"""What is printed under the ink: the PDF page or the notebook template.

On a PDF the exercise is printed and only the answer is handwritten. Reading the strokes alone, the
agent sees "a^2+b^2" without knowing it was asked for (a+b)^2. The document's .content maps every
page id to a PDF page (`cPages.pages[i].redir.value`) or to a template (`template.value`: "Blank",
"P Lines medium", "P Grid medium", ...). Probed on the device 2026-10-24.

Assumption, not yet measured on the device: the PDF page is fitted into the 1620 x 2160 page and
centred (a 1620 x 2160 pt PDF maps 1:1, seen on "Getting started").
"""
from __future__ import annotations

import io
import json

from PIL import Image

PAGE = (1620, 2160)


def page_info(content: bytes | str, page_id: str) -> dict:
    d = json.loads(content)
    for p in (d.get("cPages") or {}).get("pages", []):
        if p.get("id") == page_id:
            redir = (p.get("redir") or {}).get("value")
            return {"file_type": d.get("fileType"), "pdf_page": redir if d.get("fileType") == "pdf" else None,
                    "template": (p.get("template") or {}).get("value")}
    return {"file_type": d.get("fileType"), "pdf_page": None, "template": None}


def fit(img: Image.Image, size=PAGE) -> Image.Image:
    """The printed page fitted into the page frame, centred, on white."""
    W, H = size
    k = min(W / img.width, H / img.height)
    w, h = max(1, round(img.width * k)), max(1, round(img.height * k))
    out = Image.new("RGB", size, "white")
    out.paste(img.convert("RGB").resize((w, h), Image.LANCZOS), ((W - w) // 2, (H - h) // 2))
    return out


def render_pdf_page(pdf: bytes, index: int, size=PAGE) -> Image.Image | None:
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None
    doc = pdfium.PdfDocument(io.BytesIO(pdf))
    if not 0 <= index < len(doc):
        return None
    page = doc[index]
    w, h = page.get_size()
    img = page.render(scale=min(size[0] / w, size[1] / h)).to_pil()
    return fit(img, size)
