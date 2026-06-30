"""
SAJHA MCP Server — Tool-Search Embedders
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Tool search runs on a dependency-free lexical BM25 ranker by default (no model, no key,
no network — see sajha/ai/lexical.py). Optionally, an API-driven embedding model can be
enabled for vector similarity search, selected by config:

    ai.tool_search.embedder: bm25      # default — lexical BM25/TF-IDF, no embedder
    ai.tool_search.embedder: gateway   # vector search via the LLM gateway's embedding
                                        # provider (e.g. OpenAI text-embedding-3)

When 'gateway' is selected, get_embedder() returns a GatewayEmbedder; otherwise it returns
None and the resolver uses BM25 directly. Either way BM25 remains the always-available
fallback, so search never returns empty.

Every embedder exposes a stable `.name` (e.g. 'gateway:text-embedding-3-small'); the vector
index records it and rebuilds if it changes, since vectors from different models are not
comparable.
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Optional

logger = logging.getLogger(__name__)


class Embedder(ABC):
    """A text -> vector embedder. Vectors within one embedder share a space + dimension."""

    name: str = 'embedder'
    dimension: int = 0

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts. Returns one vector (list of floats) per input text."""
        ...


class GatewayEmbedder(Embedder):
    """Delegates to the LLM gateway's embedding provider (any API model, e.g. OpenAI)."""

    def __init__(self, gateway, model: str = ''):
        self._gw = gateway
        self._model_id = model or 'default'
        self.name = f'gateway:{self._model_id}'
        self.dimension = 0

    def embed(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        resp = self._gw.embed(list(texts))
        embeddings = getattr(resp, 'embeddings', None) or []
        if getattr(resp, 'dimensions', 0):
            self.dimension = resp.dimensions
        elif embeddings:
            self.dimension = len(embeddings[0])
        return embeddings


def get_embedder(config, gateway=None) -> Optional[Embedder]:
    """
    Return the configured vector embedder, or None to use lexical BM25 search.

    Config:
        ai.tool_search.embedder   'bm25' (default -> returns None) | 'gateway' (API vectors)
        ai.embedding_model        model label recorded for the gateway embedder

    'gateway' requires a configured LLM gateway with an embedding provider; if none is
    available we fall back to None (BM25) rather than failing.
    """
    provider = (config.get('ai.tool_search.embedder', 'bm25') or 'bm25').lower()

    if provider in ('gateway', 'api'):
        if gateway is None:
            logger.warning("Tool search embedder 'gateway' selected but no LLM gateway is "
                           "available - using lexical BM25 search instead")
            return None
        return GatewayEmbedder(gateway, model=config.get('ai.embedding_model', ''))

    # 'bm25' | 'lexical' | 'none' | anything else -> no vector embedder; BM25 is used.
    return None
