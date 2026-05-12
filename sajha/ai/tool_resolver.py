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


class ToolEmbeddingIndex:
    """
    In-memory vector index of tool descriptions.

    On init/reload:
    1. Collect name + description + schema summary for each tool
    2. Embed all descriptions via the configured embedding provider
    3. Store vectors for cosine similarity search

    On query:
    1. Embed the natural language query
    2. Cosine similarity against all tool vectors
    3. Return top-k matches with confidence scores
    """

    def __init__(self):
        self._tool_texts: Dict[str, str] = {}      # tool_name → full text for embedding
        self._tool_metadata: Dict[str, Dict] = {}   # tool_name → {description, category, schema}
        self._embeddings: Dict[str, List[float]] = {} # tool_name → vector
        self._dimension: int = 0
        self._lock = threading.Lock()
        self._built = False

    def build(self, tools_registry, gateway) -> int:
        """Build the index from the current tools registry.
        Called at startup and on hot-reload.
        Returns number of tools indexed.
        """
        from sajha.ai.gateway import LLMGateway

        texts_to_embed = {}
        metadata = {}

        for name, tool in tools_registry.tools.items():
            cfg = getattr(tool, 'config', {}) or {}
            desc = cfg.get('description', '')
            category = (cfg.get('metadata') or {}).get('category', '')
            tags = (cfg.get('metadata') or {}).get('tags', [])

            # Build rich text representation for embedding
            schema_summary = ''
            try:
                schema = tool.get_input_schema() if hasattr(tool, 'get_input_schema') else {}
                if schema and 'properties' in schema:
                    params = list(schema['properties'].keys())[:8]
                    schema_summary = f" Parameters: {', '.join(params)}"
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)
                pass

            text = f"{name}: {desc}{schema_summary}"
            if tags:
                text += f" Tags: {', '.join(tags[:5])}"

            texts_to_embed[name] = text
            metadata[name] = {
                'description': desc,
                'category': category,
                'tags': tags,
            }

        if not texts_to_embed:
            logger.warning("No tools to index")
            return 0

        # Embed in batches
        tool_names = list(texts_to_embed.keys())
        all_texts = [texts_to_embed[n] for n in tool_names]

        try:
            batch_size = 100
            all_vectors = []
            for i in range(0, len(all_texts), batch_size):
                batch = all_texts[i:i + batch_size]
                resp = gateway.embed(batch)
                all_vectors.extend(resp.embeddings)
                if resp.dimensions:
                    self._dimension = resp.dimensions

            with self._lock:
                self._tool_texts = texts_to_embed
                self._tool_metadata = metadata
                self._embeddings = {name: vec for name, vec in zip(tool_names, all_vectors)}
                self._built = True

            logger.info(f"Tool embedding index built: {len(self._embeddings)} tools, {self._dimension} dimensions")
            return len(self._embeddings)

        except Exception as e:
            logger.error(f"Failed to build tool embeddings: {e}", exc_info=True)
            return 0

    def search(self, query_embedding: List[float], top_k: int = 5) -> List[ToolMatch]:
        """Search for similar tools given a query embedding vector."""
        if not self._built:
            return []

        scores = []
        with self._lock:
            for name, tool_vec in self._embeddings.items():
                sim = self._cosine_similarity(query_embedding, tool_vec)
                meta = self._tool_metadata.get(name, {})
                scores.append(ToolMatch(
                    tool_name=name,
                    description=meta.get('description', ''),
                    confidence=sim,
                    category=meta.get('category', ''),
                ))

        scores.sort(key=lambda x: x.confidence, reverse=True)
        return scores[:top_k]

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        if len(a) != len(b) or not a:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def stats(self) -> Dict:
        return {
            'indexed_tools': len(self._embeddings),
            'dimensions': self._dimension,
            'built': self._built,
        }


class ToolResolver:
    """
    High-level resolver: natural language → tool matches.
    Combines embedding search with optional LLM-based parameter extraction.
    """

    def __init__(self, gateway, tools_registry):
        self.gateway = gateway
        self.tools_registry = tools_registry
        self.index = ToolEmbeddingIndex()
        self._built = False

    def build_index(self) -> int:
        """Build/rebuild the tool embedding index."""
        count = self.index.build(self.tools_registry, self.gateway)
        self._built = count > 0
        return count

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
            logger.warning("Tool index not built. Call build_index() first.")
            return self._fallback_search(query, top_k)

        # Embed the query
        try:
            resp = self.gateway.embed([query])
            if not resp.embeddings:
                return self._fallback_search(query, top_k)
            query_vec = resp.embeddings[0]
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
        """Text-based fallback when embeddings are unavailable."""
        query_lower = query.lower()
        results = []
        for name, tool in self.tools_registry.tools.items():
            cfg = getattr(tool, 'config', {}) or {}
            desc = cfg.get('description', '')
            text = f"{name} {desc}".lower()
            # Simple keyword overlap score
            words = set(query_lower.split())
            overlap = sum(1 for w in words if w in text and len(w) > 2)
            if overlap > 0:
                confidence = min(overlap / max(len(words), 1), 1.0)
                results.append(ToolMatch(
                    tool_name=name, description=desc, confidence=confidence,
                    category=(cfg.get('metadata') or {}).get('category', '')))

        results.sort(key=lambda x: x.confidence, reverse=True)
        return results[:top_k]

    def _extract_params(self, query: str, tool_name: str) -> Dict:
        """Use LLM to extract tool parameters from natural language."""
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
        return {**self.index.stats(), 'fallback_mode': not self._built}


# ── Singleton ────────────────────────────────────────────────

_resolver: Optional[ToolResolver] = None

def init_resolver(gateway, tools_registry) -> ToolResolver:
    global _resolver
    _resolver = ToolResolver(gateway, tools_registry)
    return _resolver

def get_resolver() -> Optional[ToolResolver]:
    return _resolver
