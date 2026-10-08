# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Documents as RAG sources (sajha/ai/rag/extract.py): PDF and Word files beside the text types,
read through optional packages, skipped by byte hash when unchanged, and a clear "install X"
message when the reader is missing."""

import io
import sys

import pytest

from sajha.ai.llm.settings import RagSettings
from sajha.ai.rag import extract
from sajha.ai.rag.index import DocIndex, UPLOADS
from sajha.core.storage import LocalStorageBackend
from tests.ai.conftest import make_gateway


def make_pdf(text: str) -> bytes:
    """A one-page PDF with ``text`` in Helvetica (enough for pypdf's text extraction)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


def make_docx(title: str, sections) -> bytes:
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_heading(title, 0)
    for head, body in sections:
        d.add_heading(head, 1)
        d.add_paragraph(body)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


@pytest.fixture
def storage(tmp_path, monkeypatch):
    st = LocalStorageBackend(str(tmp_path))
    monkeypatch.setattr("sajha.ai.rag.index._storage", lambda: st)
    st.write_text("kb/notes.txt", "Quarterly notes. The zebra protocol renews every ninety days.")
    return st


def index(**kw):
    cfg = {"index_sajha_docs": False, "persist": False, "store": "memory",
           "sources": [{"name": "kb", "path": "kb", "pattern": "*"}], **kw}
    return DocIndex(RagSettings(**cfg), make_gateway())


def test_word_documents_are_split_by_heading_and_skipped_when_unchanged(storage, monkeypatch):
    storage.write_bytes("kb/handbook.docx", make_docx("Treasury Handbook", [
        ("Settlement", "Trades settle two business days after the trade date, known as T plus two."),
        ("Collateral", "Collateral is called daily and the haircut on gilts is two percent.")]))
    idx = index()
    s = idx.build()
    assert s["indexed"] == 2 and not s["errors"]
    hit = idx.search("what haircut applies to gilts collateral", 1)[0]
    assert hit["document"] == "kb/handbook.docx" and hit["title"] == "Treasury Handbook"
    assert hit["section"] == "Collateral"
    # unchanged bytes: not even extracted again
    monkeypatch.setattr(extract, "extract_text", lambda *a: (_ for _ in ()).throw(AssertionError("re-read")))
    assert idx.build()["unchanged"] == 2
    monkeypatch.undo()
    monkeypatch.setattr("sajha.ai.rag.index._storage", lambda: storage)
    storage.write_bytes("kb/handbook.docx", make_docx("Treasury Handbook", [
        ("Settlement", "Trades now settle one business day after the trade date.")]))
    s = idx.build()
    assert s["indexed"] == 1 and s["unchanged"] == 1


def test_pdf_documents_are_indexed(storage):
    pytest.importorskip("pypdf")
    storage.write_bytes("kb/policy.pdf", make_pdf("The okapi limit for overnight exposure is forty million."))
    idx = index()
    s = idx.build()
    assert s["indexed"] == 2 and not s["errors"]
    hit = idx.search("okapi overnight exposure limit", 1)[0]
    assert hit["document"] == "kb/policy.pdf" and hit["title"] == "policy" and "forty million" in hit["text"]


def test_a_missing_reader_is_named_and_the_rest_still_indexes(storage, monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdf", None)            # import pypdf now fails
    storage.write_bytes("kb/policy.pdf", make_pdf("Anything at all."))
    idx = index()
    s = idx.build()
    assert s["indexed"] == 1 and any("install pypdf" in e for e in s["errors"])
    assert idx.search("zebra protocol", 1)[0]["document"] == "kb/notes.txt"
    with pytest.raises(ValueError, match="install pypdf"):
        idx.save_upload("policy.pdf", make_pdf("x"))
    assert extract.available()[".pdf"] is False


def test_uploads_accept_word_files_and_reject_empty_ones(storage):
    idx = index()
    idx.build()
    out = idx.save_upload("Runbook.docx", make_docx("Runbook", [("Keys", "Rotate the quokka keys every Tuesday.")]))
    assert out["document"] == "data/rag/uploads/Runbook.docx" and out["title"] == "Runbook"
    hit = idx.search("when are the quokka keys rotated", 1)[0]
    assert hit["source"] == UPLOADS and hit["document"].endswith("Runbook.docx")
    assert idx.build()["unchanged"] == 2                         # the upload is hashed on its bytes too
    with pytest.raises(ValueError, match="no text"):
        idx.save_upload("Empty.docx", make_docx("", []))
