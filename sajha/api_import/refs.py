"""
SAJHA MCP Server — API Import: ``$ref`` resolution.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

:class:`RefResolver` inlines every reference so each tool schema is self-contained.
Local pointers, relative documents (resolved against the document's URL) and absolute
URLs are followed; remote documents are fetched through the SSRF guard
(:mod:`sajha.api_import.fetch`), at most ``api_import.max_ref_documents`` of them. A
reference cycle is cut where it closes: the inner occurrence becomes ``{}`` with a
``$comment`` naming the reference.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import unquote, urldefrag, urljoin

MAX_DEPTH = 64


class RefError(ValueError):
    """A reference cannot be resolved."""


def parse_text(text: str) -> Any:
    """JSON or YAML text → Python data."""
    import json
    stripped = (text or '').lstrip()
    if stripped.startswith(('{', '[')):
        try:
            return json.loads(stripped)
        except ValueError:
            pass
    import yaml
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise RefError(f'the document is neither JSON nor YAML ({str(e).splitlines()[0]})')


def _pointer(doc: Any, pointer: str, ref: str) -> Any:
    node = doc
    if pointer in ('', '/'):
        return node
    if not pointer.startswith('/'):
        raise RefError(f'$ref {ref!r}: the fragment is not a JSON pointer')
    for raw in pointer[1:].split('/'):
        token = unquote(raw).replace('~1', '/').replace('~0', '~')
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            raise RefError(f'$ref {ref!r} points at nothing')
    return node


class RefResolver:
    def __init__(self, root: Any, base_url: Optional[str] = None,
                 fetcher: Optional[Callable[[str], str]] = None, max_documents: int = 20):
        self.root = root
        self.base_url = base_url or ''
        self._fetcher = fetcher
        self._max_documents = max_documents
        self._documents: Dict[str, Any] = {}
        if self.base_url:
            self._documents[urldefrag(self.base_url)[0]] = root
        self._cache: Dict[str, Any] = {}

    # ── documents ──────────────────────────────────────────────────
    def _document(self, url: str) -> Any:
        if not url:
            return self.root
        if url in self._documents:
            return self._documents[url]
        if self._fetcher is None:
            raise RefError(f'$ref to {url!r} needs the document to be fetched, and this import cannot '
                           f'fetch (an uploaded spec has no URL to resolve relative references against)')
        if len([u for u in self._documents if u != urldefrag(self.base_url)[0]]) >= self._max_documents:
            raise RefError(f'more than {self._max_documents} referenced documents (api_import.max_ref_documents)')
        doc = parse_text(self._fetcher(url))
        self._documents[url] = doc
        return doc

    def lookup(self, ref: str, base: str) -> Tuple[Any, str, str]:
        """(target node, the base URL of its document, the absolute ref key)."""
        if ref.startswith('#'):
            doc_url, fragment = (urldefrag(base)[0] if base else ''), ref[1:]
        else:
            if not base:
                if self._fetcher is None or '://' not in ref:
                    raise RefError(f'$ref {ref!r} is relative and this spec has no URL to resolve it against')
                absolute = ref
            else:
                absolute = urljoin(base, ref)
            doc_url, fragment = urldefrag(absolute)
        doc = self._document(doc_url) if doc_url and doc_url != urldefrag(self.base_url)[0] else self.root
        return _pointer(doc, fragment, ref), doc_url or base, f'{doc_url}#{fragment}'

    # ── inlining ───────────────────────────────────────────────────
    def deref(self, node: Any, base: Optional[str] = None) -> Any:
        """A deep copy of ``node`` with every $ref inlined (cycles cut)."""
        return self._deref(node, self.base_url if base is None else base, [], 0)

    def _deref(self, node: Any, base: str, stack: List[str], depth: int) -> Any:
        if depth > MAX_DEPTH:
            return {'$comment': 'nested too deeply; not expanded'}
        if isinstance(node, list):
            return [self._deref(v, base, stack, depth + 1) for v in node]
        if not isinstance(node, dict):
            return node
        ref = node.get('$ref')
        if isinstance(ref, str):
            target, target_base, key = self.lookup(ref, base)
            if key in stack:
                return {'$comment': f'recursive reference to {ref} not expanded'}
            siblings = {k: v for k, v in node.items() if k != '$ref'}
            if key in self._cache and not siblings:
                return copy.deepcopy(self._cache[key])
            resolved = self._deref(target, target_base, stack + [key], depth + 1)
            if not siblings:
                if not any(k in stack for k in [key]):
                    self._cache[key] = resolved
                return copy.deepcopy(resolved)
            merged = dict(resolved) if isinstance(resolved, dict) else {'allOf': [resolved]}
            for k, v in siblings.items():
                merged[k] = self._deref(v, base, stack, depth + 1)
            return merged
        return {k: self._deref(v, base, stack, depth + 1) for k, v in node.items()}
