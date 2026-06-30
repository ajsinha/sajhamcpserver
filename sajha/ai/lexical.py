"""
SAJHA MCP Server — Lexical BM25 Index
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

A compact, dependency-free BM25 ranker used as the last-resort tier for semantic tool
search: when no embedder is available (no local model, no API key), the resolver still
returns useful, ranked matches with zero models and zero network.

BM25 over the same rich text the embedder uses (name + description + parameters + tags +
literature), with proper tokenization and IDF weighting — so distinctive terms outrank
common ones, unlike a naive keyword-overlap. Pure Python on purpose: the fallback tier
must never itself depend on an optional package that might be absent.
"""

import re
import math
import logging
import threading
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Small stoplist: drops words that carry no discriminative signal for tool selection.
_STOPWORDS = {
    'the', 'a', 'an', 'of', 'to', 'for', 'and', 'or', 'in', 'on', 'with', 'by', 'as',
    'is', 'are', 'be', 'do', 'does', 'how', 'what', 'which', 'that', 'this', 'it', 'its',
    'from', 'at', 'into', 'i', 'me', 'my', 'we', 'our', 'you', 'your', 'get', 'find',
    'give', 'show', 'want', 'need', 'using', 'use', 'can', 'please',
}


def tokenize(text: str) -> List[str]:
    """Lowercase, split on non-alphanumerics, drop 1-char tokens and stopwords."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 1 and t not in _STOPWORDS]


class BM25Index:
    """
    Okapi BM25 over tool documents. Rebuilt wholesale on each refresh (tokenization over a
    few hundred short docs is sub-millisecond), so it stays accurate as tools change.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._tf: Dict[str, Dict[str, int]] = {}   # name -> {term: frequency}
        self._len: Dict[str, int] = {}             # name -> document length
        self._meta: Dict[str, Dict] = {}           # name -> {description, category}
        self._idf: Dict[str, float] = {}           # term -> inverse document frequency
        self._avgdl: float = 0.0
        self._lock = threading.RLock()
        self._built = False

    @property
    def built(self) -> bool:
        return self._built

    def build(self, items: Dict[str, Tuple[str, Dict]]) -> int:
        """Build the index. `items` maps tool name -> (rich_text, meta_dict)."""
        tf: Dict[str, Dict[str, int]] = {}
        length: Dict[str, int] = {}
        meta: Dict[str, Dict] = {}
        df: Dict[str, int] = {}

        for name, (text, md) in items.items():
            counts: Dict[str, int] = {}
            for tok in tokenize(text):
                counts[tok] = counts.get(tok, 0) + 1
            tf[name] = counts
            length[name] = sum(counts.values())
            meta[name] = md or {}
            for term in counts:
                df[term] = df.get(term, 0) + 1

        n = len(tf)
        avgdl = (sum(length.values()) / n) if n else 0.0
        # BM25 idf with +0.5 smoothing; the outer (1 + ...) keeps idf non-negative.
        idf = {term: math.log(1 + (n - d + 0.5) / (d + 0.5)) for term, d in df.items()}

        with self._lock:
            self._tf, self._len, self._meta = tf, length, meta
            self._idf, self._avgdl = idf, avgdl
            self._built = n > 0
        return n

    def search(self, query: str, top_k: int = 5) -> List[Tuple[str, str, float, str]]:
        """Return up to top_k (name, description, confidence, category), best first."""
        with self._lock:
            if not self._built:
                return []
            q_terms = tokenize(query)
            if not q_terms:
                return []

            avgdl = self._avgdl or 1.0
            scored: List[Tuple[str, float]] = []
            for name, counts in self._tf.items():
                dl = self._len.get(name, 0) or 1
                score = 0.0
                for term in q_terms:
                    f = counts.get(term, 0)
                    if not f:
                        continue
                    idf = self._idf.get(term, 0.0)
                    denom = f + self.k1 * (1.0 - self.b + self.b * dl / avgdl)
                    score += idf * (f * (self.k1 + 1.0)) / denom
                if score > 0:
                    scored.append((name, score))

            scored.sort(key=lambda x: x[1], reverse=True)
            results = []
            for name, score in scored[:top_k]:
                md = self._meta.get(name, {})
                # Saturating map to a 0–1 display score (not a probability).
                confidence = score / (score + 5.0)
                results.append((name, md.get('description', ''), confidence, md.get('category', '')))
            return results

    def stats(self) -> Dict:
        return {
            'lexical_docs': len(self._tf),
            'vocab': len(self._idf),
            'avg_doc_len': round(self._avgdl, 1),
            'built': self._built,
        }
