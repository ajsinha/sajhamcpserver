"""
SAJHA MCP Server — RAG: optional OCR for scanned PDFs and images.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A scanned PDF has no text layer, so extract.py reports it as having no text. With
``ai.rag.ocr: true`` and an OCR engine installed, the text is read from the page images
instead, and image files (``.png``, ``.jpg``, ``.jpeg``, ``.tif``, ``.tiff``, ``.bmp``,
``.webp``) from document sources become documents too. SAJHA ships no OCR engine; either
of these optional dependencies is used, the first one found:

* ``rapidocr``: ``pip install rapidocr-onnxruntime`` (or the newer ``rapidocr``), pure pip;
* ``tesseract``: ``pip install pytesseract`` plus the ``tesseract`` program on the PATH.

Page images are taken from the PDF with ``pypdf`` (``page.images``), so a scanned PDF also
needs ``pypdf``; images are opened with Pillow. Without an engine an OCR request is refused
with :class:`OCRUnavailable`, whose message names the packages; nothing is installed or
downloaded at run time. Design: docs/architecture/Intelligence Layer.md, "Document search".
"""

from __future__ import annotations

import io
import shutil
from typing import Callable, Dict, List, Optional, Tuple

IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")
INSTALL_HINT = ("OCR needs an optional dependency that is not installed: pip install rapidocr-onnxruntime, "
                "or pip install pytesseract and put the tesseract program on the PATH")

#: tests and extensions: a callable bytes -> text that replaces the detected engine
_override: Optional[Callable[[bytes], str]] = None
_rapid = None


class OCRUnavailable(RuntimeError):
    """OCR was asked for and no OCR engine is installed (the message says what to install)."""


def set_engine(fn: Optional[Callable[[bytes], str]]) -> None:
    """Use ``fn(image_bytes) -> text`` as the OCR engine (tests); None restores detection."""
    global _override
    _override = fn


def is_image(name: str) -> bool:
    return (name or "").lower().endswith(IMAGE_TYPES)


def _has(module: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def engine() -> Optional[str]:
    """The OCR engine that would run: ``override``, ``rapidocr``, ``tesseract``, or None."""
    if _override is not None:
        return "override"
    if _has("rapidocr_onnxruntime") or _has("rapidocr"):
        return "rapidocr"
    if _has("pytesseract") and shutil.which("tesseract"):
        return "tesseract"
    return None


def available() -> Dict[str, object]:
    """For the index status: which engine runs, or why none does."""
    name = engine()
    return {"engine": name, "installed": name is not None, "hint": "" if name else INSTALL_HINT}


def require() -> str:
    name = engine()
    if name is None:
        raise OCRUnavailable(INSTALL_HINT)
    return name


def _rapidocr(data: bytes) -> str:
    global _rapid
    if _rapid is None:
        try:
            from rapidocr_onnxruntime import RapidOCR          # rapidocr-onnxruntime 1.x
        except ImportError:
            from rapidocr import RapidOCR                      # rapidocr 2.x
        _rapid = RapidOCR()
    out = _rapid(data)
    if isinstance(out, tuple):                                 # 1.x: (result, elapsed)
        rows = out[0] or []
        return "\n".join(str(r[1]) for r in rows if len(r) > 1)
    return "\n".join(str(t) for t in (getattr(out, "txts", None) or ()))


def _tesseract(data: bytes) -> str:
    import pytesseract
    from PIL import Image
    with Image.open(io.BytesIO(data)) as img:
        return pytesseract.image_to_string(img)


def image_text(data: bytes) -> str:
    """The text in one image. Raises OCRUnavailable without an engine."""
    name = require()
    if name == "override":
        return str(_override(data) or "")
    return (_rapidocr if name == "rapidocr" else _tesseract)(data)


def pdf_page_images(data: bytes, max_pages: int = 200) -> List[bytes]:
    """The images embedded in each page of a PDF (a scan is one image per page), in order."""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise OCRUnavailable("reading a scanned PDF needs pypdf (pip install pypdf)") from None
    reader = PdfReader(io.BytesIO(data))
    out: List[bytes] = []
    for i, page in enumerate(reader.pages):
        if i >= max_pages:
            break
        for img in getattr(page, "images", None) or []:
            raw = getattr(img, "data", None)
            if raw:
                out.append(raw)
    return out


def pdf_text(data: bytes, max_pages: int = 200) -> str:
    """OCR of a scanned PDF's page images, pages in order."""
    require()
    texts = [t.strip() for t in (image_text(b) for b in pdf_page_images(data, max_pages)) if t and t.strip()]
    return "\n\n".join(texts)


def extract_document(name: str, data: bytes, ocr: bool = False, max_pages: int = 200) -> Tuple[str, str]:
    """``(text, title)`` of a PDF, Word file or image, using OCR where it is on and needed.

    A PDF with a text layer is read by extract.py as usual. A PDF without one is OCR'd when
    ``ocr`` is true (else the ValueError says how to turn OCR on). An image needs ``ocr``.
    Raises extract.ExtractorMissing, OCRUnavailable or ValueError."""
    from sajha.ai.rag import extract
    label = (name or "").rsplit("/", 1)[-1]
    if is_image(name):
        if not ocr:
            raise ValueError(f"{label} is an image: set ai.rag.ocr to true (and install an OCR engine) to index it")
        text = image_text(data).strip()
        if not text:
            raise ValueError(f"{label}: OCR found no text")
        return text, ""
    try:
        return extract.extract_text(name, data)
    except ValueError as e:
        if not (name or "").lower().endswith(".pdf") or "has no text" not in str(e):
            raise
        if not ocr:
            raise ValueError(f"{label} has no text layer (a scanned PDF): set ai.rag.ocr to true and install an "
                             "OCR engine to read it") from None
    text = pdf_text(data, max_pages).strip()
    if not text:
        raise ValueError(f"{label}: OCR found no text")
    return text, ""
