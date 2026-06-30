"""
SAJHA MCP Server — Semantic Tool Discovery
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Resolves natural language intent to the right SAJHA tool(s).
Uses vector embeddings of tool descriptions for similarity search.

"find me companies with high debt-to-equity ratios"
  → openbb_equity_fundamental_ratios (confidence: 0.92)
  → fmp_key_metrics (confidence: 0.85)

Usage:
    from sajha.ai.tool_resolver import get_resolver
    resolver = get_resolver()
    matches = resolver.resolve("What's Apple's P/E ratio?", top_k=3)
"""

import json
import math
import hashlib
import logging
import threading
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ToolMatch:
    """A tool matched by semantic search."""
    tool_name: str
    description: str
    confidence: float       # 0.0–1.0 similarity score
    category: str = ''
    suggested_params: Dict = None  # LLM-extracted parameters (Phase 2b)

    def to_dict(self):
        return {
            'tool_name': self.tool_name,
            'description': self.description,
            'confidence': round(self.confidence, 4),
            'category': self.category,
            'suggested_params': self.suggested_params or {},
        }


_INDEX_REL = 'data/tool_search_index.json'
_INDEX_VERSION = 1


def _embedding_text(name, cfg, schema):
    """Build the text representation of a tool that gets embedded.
    Includes name + description + parameter names + tags + optional literature."""
    desc = cfg.get('description', '') or ''
    md = cfg.get('metadata') or {}
    tags = md.get('tags') or []
    literature = cfg.get('literature') or cfg.get('documentation') or ''
    parts = [f"{name}: {desc}".strip()]
    if isinstance(schema, dict) and schema.get('properties'):
        params = list(schema['properties'].keys())[:12]
        if params:
            parts.append("Parameters: " + ", ".join(params))
    if tags:
        parts.append("Tags: " + ", ".join(str(t) for t in tags[:8]))
    if literature:
        parts.append(str(literature)[:2000])  # cap long literature
    return "  ".join(p for p in parts if p)


class ToolEmbeddingIndex:
    """
    In-memory vector index with incremental, hash-based sync and storage persistence.

    Each tool's embedding text is hashed (including the embedder name). On sync, only
    tools whose hash changed are re-embedded; removed tools are dropped; unchanged tools
    keep their vectors. The index is persisted through the storage backend (local | s3 |
    azure | gcs) with a header recording the embedder + dimension, so a restart reloads
    vectors and a changed embedder forces a clean rebuild. Search is a single normalized
    matrix-vector product (cosine).
    """

    def __init__(self, persist: bool = True, index_rel: str = _INDEX_REL):
        self._vectors = {}        # name -> normalized vector (list[float])
        self._hashes = {}         # name -> content hash
        self._meta = {}           # name -> {description, category, tags}
        self._names = []          # ordered names aligned to _matrix rows
        self._matrix = None       # np.ndarray (N, D), L2-normalized
        self._dimension = 0
        self._embedder_name = ''
        self._persist = persist
        self._index_rel = index_rel
        self._lock = threading.RLock()
        self._built = False

    # ---- persistence ----
    def load(self, embedder_name: str) -> bool:
        if not self._persist:
            return False
        try:
            from sajha.core.storage import get_storage
            storage = get_storage()
            if not storage.exists(self._index_rel):
                return False
            data = storage.read_json(self._index_rel)
        except Exception as e:
            logger.warning(f"Tool index load failed: {e}")
            return False
        if data.get('version') != _INDEX_VERSION or data.get('embedder') != embedder_name:
            logger.info("Tool index header mismatch (embedder/version) — will rebuild")
            return False
        tools = data.get('tools', {})
        with self._lock:
            self._vectors = {n: t['vector'] for n, t in tools.items()}
            self._hashes = {n: t['hash'] for n, t in tools.items()}
            self._meta = {n: t.get('meta', {}) for n, t in tools.items()}
            self._embedder_name = embedder_name
            self._dimension = data.get('dimension', 0)
            self._rebuild_matrix()
            self._built = len(self._vectors) > 0
        logger.info(f"Tool index loaded from storage: {len(self._vectors)} vectors ({embedder_name})")
        return True

    def _persist_index(self):
        if not self._persist:
            return
        try:
            from sajha.core.storage import get_storage
            payload = {
                'version': _INDEX_VERSION,
                'embedder': self._embedder_name,
                'dimension': self._dimension,
                'tools': {
                    n: {'hash': self._hashes[n], 'vector': self._vectors[n], 'meta': self._meta.get(n, {})}
                    for n in self._vectors
                },
            }
            get_storage().write_json(self._index_rel, payload)
        except Exception as e:
            logger.warning(f"Tool index persist failed: {e}")

    # ---- core incremental sync ----
    def sync(self, tools_registry, embedder):
        """Re-embed only changed/new tools; drop removed ones. Returns a small summary dict."""
        import numpy as np

        desired = {}
        for name, tool in tools_registry.tools.items():
            cfg = getattr(tool, 'config', {}) or {}
            try:
                schema = tool.get_input_schema() if hasattr(tool, 'get_input_schema') else {}
            except Exception:
                schema = {}
            text = _embedding_text(name, cfg, schema)
            h = hashlib.sha256(f"{embedder.name}\x00{text}".encode('utf-8')).hexdigest()
            md = cfg.get('metadata') or {}
            desired[name] = (text, h, {
                'description': cfg.get('description', ''),
                'category': md.get('category', ''),
                'tags': md.get('tags', []),
            })

        with self._lock:
            if self._embedder_name and self._embedder_name != embedder.name:
                logger.info(f"Embedder changed {self._embedder_name} -> {embedder.name}; rebuilding index")
                self._vectors.clear(); self._hashes.clear(); self._meta.clear()
            self._embedder_name = embedder.name
            to_embed = [n for n, (t, h, m) in desired.items() if self._hashes.get(n) != h]
            removed = [n for n in list(self._vectors.keys()) if n not in desired]

        # Embed outside the lock (can be slow / network)
        new_vectors = {}
        if to_embed:
            texts = [desired[n][0] for n in to_embed]
            try:
                vecs = embedder.embed(texts)
                for n, v in zip(to_embed, vecs):
                    new_vectors[n] = self._normalize(v)
                if embedder.dimension:
                    self._dimension = embedder.dimension
                elif vecs:
                    self._dimension = len(vecs[0])
            except Exception as e:
                logger.warning(f"Embedding failed for {len(to_embed)} tools; keeping prior vectors: {e}",
                               exc_info=True)

        with self._lock:
            for n, v in new_vectors.items():
                self._vectors[n] = v
                self._hashes[n] = desired[n][1]
                self._meta[n] = desired[n][2]
            for n, (t, h, m) in desired.items():   # keep metadata fresh for unchanged tools
                if n in self._vectors:
                    self._meta[n] = m
            for n in removed:
                self._vectors.pop(n, None); self._hashes.pop(n, None); self._meta.pop(n, None)
            self._rebuild_matrix()
            self._built = len(self._vectors) > 0

        self._persist_index()
        result = {'embedded': len(new_vectors), 'removed': len(removed), 'total': len(self._vectors)}
        logger.info(f"Tool index sync: +{result['embedded']} embedded, -{result['removed']} removed, "
                    f"{result['total']} total ({self._embedder_name})")
        return result

    @staticmethod
    def _normalize(v):
        import numpy as np
        a = np.asarray(v, dtype=np.float32)
        n = float(np.linalg.norm(a))
        return (a / n).tolist() if n else a.tolist()

    def _rebuild_matrix(self):
        import numpy as np
        self._names = list(self._vectors.keys())
        self._matrix = (np.asarray([self._vectors[n] for n in self._names], dtype=np.float32)
                        if self._names else None)

    def search(self, query_vec, top_k: int = 5):
        import numpy as np
        with self._lock:
            if self._matrix is None or not self._names:
                return []
            q = np.asarray(self._normalize(query_vec), dtype=np.float32)
            scores = self._matrix @ q
            k = min(top_k, len(self._names))
            idx = np.argpartition(-scores, k - 1)[:k]
            idx = idx[np.argsort(-scores[idx])]
            out = []
            for i in idx:
                name = self._names[int(i)]
                md = self._meta.get(name, {})
                out.append(ToolMatch(
                    tool_name=name, description=md.get('description', ''),
                    confidence=float(scores[int(i)]), category=md.get('category', '')))
            return out

    def stats(self):
        return {
            'indexed_tools': len(self._vectors),
            'dimensions': self._dimension,
            'embedder': self._embedder_name,
            'persisted': self._persist,
            'built': self._built,
        }


class ToolResolver:
    """
    High-level resolver: natural language → tool matches.
    Combines embedding search with optional LLM-based parameter extraction.
    """

    def __init__(self, embedder, tools_registry, gateway=None, persist: bool = True):
        from sajha.ai.lexical import BM25Index
        self.embedder = embedder          # None → lexical BM25 only (default)
        self.gateway = gateway            # optional — only for LLM parameter extraction
        self.tools_registry = tools_registry
        self.index = ToolEmbeddingIndex(persist=persist) if embedder is not None else None
        self._bm25 = BM25Index()          # default + always-available lexical tier
        self._built = False               # True only when a vector index is active + built

    def build_index(self) -> int:
        """Build the search index. BM25 always; vector index too if an embedder is set."""
        lexical_count = self.refresh_lexical()
        if self.embedder is None or self.index is None:
            self._built = False
            return lexical_count
        self.index.load(self.embedder.name)
        result = self.index.sync(self.tools_registry, self.embedder)
        self._built = result['total'] > 0
        return result['total']

    def sync(self) -> dict:
        """Re-sync after tools change. Refreshes BM25 always; vector index if enabled."""
        self.refresh_lexical()
        if self.embedder is None or self.index is None:
            return {'embedded': 0, 'removed': 0, 'total': 0, 'mode': 'bm25'}
        result = self.index.sync(self.tools_registry, self.embedder)
        self._built = result['total'] > 0
        return result

    def refresh_lexical(self) -> int:
        """(Re)build the BM25 lexical index from the current tools (fast, dependency-free)."""
        items = {}
        for name, tool in self.tools_registry.tools.items():
            cfg = getattr(tool, 'config', {}) or {}
            try:
                schema = tool.get_input_schema() if hasattr(tool, 'get_input_schema') else {}
            except Exception:
                schema = {}
            text = _embedding_text(name, cfg, schema)
            md = {'description': cfg.get('description', ''),
                  'category': (cfg.get('metadata') or {}).get('category', '')}
            items[name] = (text, md)
        try:
            return self._bm25.build(items)
        except Exception as e:
            logger.warning(f"Lexical (BM25) index build failed: {e}", exc_info=True)
            return 0

    def resolve(self, query: str, top_k: int = 5, extract_params: bool = False) -> List[ToolMatch]:
        """
        Resolve a natural language query to matching tools.

        Args:
            query: Natural language description of what the user wants
            top_k: Number of results to return
            extract_params: If True, use LLM to extract parameters from the query

        Returns:
            List of ToolMatch objects sorted by confidence
        """
        if not self._built:
            # Lexical BM25 mode (default) or vector index not ready yet.
            if self.embedder is not None:
                logger.debug("Vector index not built yet; using BM25 lexical search")
            return self._fallback_search(query, top_k)

        # Embed the query
        try:
            vecs = self.embedder.embed([query])
            if not vecs:
                return self._fallback_search(query, top_k)
            query_vec = vecs[0]
        except Exception as e:
            logger.warning(f"Embedding failed, falling back to text search: {e}", exc_info=True)
            return self._fallback_search(query, top_k)

        # Vector search
        matches = self.index.search(query_vec, top_k=top_k)

        # Optional: LLM parameter extraction for top match
        if extract_params and matches and matches[0].confidence > 0.7:
            top = matches[0]
            try:
                params = self._extract_params(query, top.tool_name)
                top.suggested_params = params
            except Exception as e:
                logger.warning(f"Parameter extraction failed: {e}", exc_info=True)

        return matches

    def _fallback_search(self, query: str, top_k: int) -> List[ToolMatch]:
        """Lexical BM25 fallback when embeddings are unavailable (no model, no API key).

        Ranks over the same rich text the embedder uses (name + description + parameters +
        tags + literature) with IDF weighting, so distinctive terms outrank common ones.
        """
        if not self._bm25.built:
            self.refresh_lexical()
        rows = self._bm25.search(query, top_k)
        return [ToolMatch(tool_name=n, description=d, confidence=c, category=cat)
                for (n, d, c, cat) in rows]

    def _extract_params(self, query: str, tool_name: str) -> Dict:
        """Use LLM to extract tool parameters from natural language (needs a gateway)."""
        if self.gateway is None:
            return {}
        tool = self.tools_registry.get_tool(tool_name)
        if not tool:
            return {}

        schema = {}
        try:
            schema = tool.get_input_schema()
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {}

        system = (
            "You are a parameter extraction assistant. Given a natural language query and a tool's "
            "JSON Schema, extract the parameter values. Return ONLY a JSON object with the extracted "
            "parameters. If a parameter can't be determined, omit it."
        )
        prompt = f"Query: {query}\n\nTool: {tool_name}\nSchema: {json.dumps(schema, indent=2)}\n\nExtracted parameters (JSON only):"

        try:
            resp = self.gateway.complete(prompt, system=system, max_tokens=200, temperature=0.0)
            text = resp.content.strip()
            if text.startswith('{'):
                return json.loads(text)
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            pass
        return {}

    def stats(self) -> Dict:
        mode = 'vector' if self._built else 'bm25'
        vec = self.index.stats() if self.index is not None else {'indexed_tools': 0, 'built': False}
        return {**vec, 'mode': mode, 'fallback_mode': not self._built, 'lexical': self._bm25.stats()}


# ── Singleton ────────────────────────────────────────────────

_resolver: Optional[ToolResolver] = None

def init_resolver(embedder, tools_registry, gateway=None, persist: bool = True) -> ToolResolver:
    global _resolver
    _resolver = ToolResolver(embedder, tools_registry, gateway=gateway, persist=persist)
    return _resolver

def get_resolver() -> Optional[ToolResolver]:
    return _resolver
