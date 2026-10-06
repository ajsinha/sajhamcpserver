"""
SAJHA MCP Server — RAG: splitting documents into passages.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Markdown is split at headings first (each passage remembers its heading path and the
heading's anchor, so a citation can link to the section), then long sections into passages
of about ``size`` characters at paragraph boundaries, with ``overlap`` characters carried
over. Plain text and HTML (tags stripped) are split by paragraphs alone. Code fences are
kept whole where they fit.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import List

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_TAGS = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)
TEXT_TYPES = (".md", ".markdown", ".txt", ".rst", ".html", ".htm")


@dataclass
class Chunk:
    text: str
    heading: str = ""                     # "Section > Subsection"
    anchor: str = ""                      # the deepest heading's anchor (python-markdown toc slug)
    ordinal: int = 0
    meta: dict = field(default_factory=dict)


def slugify(value: str) -> str:
    """The anchor python-markdown's toc extension gives a heading (what the guide pages use)."""
    try:
        from markdown.extensions.toc import slugify as md_slugify
        return md_slugify(value, "-")
    except Exception:
        value = re.sub(r"[^\w\s-]", "", value).strip().lower()
        return re.sub(r"[-\s]+", "-", value)


def _clean_heading(text: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return text.replace("*", "").strip()


def html_to_text(raw: str) -> str:
    text = _TAGS.sub(" ", raw)
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()


def _paragraphs(text: str) -> List[str]:
    """Paragraphs, keeping fenced code blocks together."""
    out, buf, fence = [], [], False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            fence = not fence
        if not line.strip() and not fence:
            if buf:
                out.append("\n".join(buf).strip())
                buf = []
            continue
        buf.append(line)
    if buf:
        out.append("\n".join(buf).strip())
    return [p for p in out if p]


def _pack(paragraphs: List[str], size: int, overlap: int) -> List[str]:
    chunks, cur = [], ""
    for p in paragraphs:
        while len(p) > size * 1.5:               # a huge paragraph: cut at a sentence or a space
            cut = p.rfind(". ", 0, size)
            cut = cut + 1 if cut > size // 2 else (p.rfind(" ", 0, size) if p.rfind(" ", 0, size) > 0 else size)
            head, p = p[:cut].strip(), p[cut:].strip()
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(head)
        if cur and len(cur) + len(p) + 2 > size:
            chunks.append(cur)
            tail = cur[-overlap:] if overlap > 0 else ""
            sp = tail.find(" ")
            cur = (tail[sp + 1:] + "\n\n" if 0 <= sp < len(tail) - 1 else "") + p
        else:
            cur = (cur + "\n\n" + p) if cur else p
    if cur:
        chunks.append(cur)
    return chunks


def chunk_markdown(text: str, size: int = 1200, overlap: int = 150) -> List[Chunk]:
    sections: List[tuple] = []           # (heading path, anchor, body)
    path: List[str] = []
    levels: List[int] = []
    anchor, body, fence = "", [], False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            fence = not fence
        m = None if fence else _HEADING.match(line)
        if m:
            if body:
                sections.append((list(path), anchor, "\n".join(body)))
                body = []
            level, title = len(m.group(1)), _clean_heading(m.group(2))
            levels = [lv for lv in levels if lv < level] if levels else []
            path = path[: len(levels)] + [title]
            levels.append(level)
            anchor = slugify(title)
            continue
        body.append(line)
    if body:
        sections.append((list(path), anchor, "\n".join(body)))
    out: List[Chunk] = []
    for heads, anc, body_text in sections:
        if len(heads) <= 1 and levels_of_first_is_title(text):
            heads, anc = [], ""             # the text under the title: the guide page drops the H1
        heading = " > ".join(heads[1:] if len(heads) > 1 else heads)
        for piece in _pack(_paragraphs(body_text), size, overlap):
            if len(piece.strip()) < 20:
                continue
            out.append(Chunk(piece.strip(), heading, anc, len(out)))
    return out


def levels_of_first_is_title(text: str) -> bool:
    """True when the document's first heading is a level-1 title."""
    for line in text.split("\n"):
        m = _HEADING.match(line)
        if m:
            return len(m.group(1)) == 1
    return False


def chunk_text(text: str, size: int = 1200, overlap: int = 150) -> List[Chunk]:
    return [Chunk(p, "", "", i) for i, p in enumerate(_pack(_paragraphs(text), size, overlap)) if p.strip()]


def chunk_document(name: str, text: str, size: int = 1200, overlap: int = 150) -> List[Chunk]:
    low = name.lower()
    if low.endswith((".html", ".htm")):
        return chunk_text(html_to_text(text), size, overlap)
    if low.endswith((".md", ".markdown")):
        return chunk_markdown(text, size, overlap)
    return chunk_text(text, size, overlap)


def title_of(name: str, text: str) -> str:
    for line in text.split("\n")[:20]:
        if line.startswith("# "):
            return _clean_heading(line[2:])
    m = re.search(r"<title>(.*?)</title>", text[:2000], re.I | re.S)
    if m:
        return html.unescape(m.group(1)).strip()
    base = name.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[0]
