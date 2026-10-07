"""
SAJHA MCP Server — retrieval over documents (RAG).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

chunking.py splits documents into passages; stores.py defines the store contract
(``VectorStore``) with the memory and pgvector stores, sqlite_vec.py the default sqlite-vec
store (a SQLite file of its own), registry.py picks one from ``ai.rag.store``; index.py syncs
and searches them; tool.py is the ``sajha_search_docs`` MCP tool. Configuration: ``ai.rag``
(docs/getting-started/Configuration Reference.md); design: docs/architecture/Intelligence
Layer.md; writing a store: docs/architecture/Extending the Intelligence Layer.md.

The public search API (stable; other modules call it read-only):

* ``get_doc_index()`` -> ``DocIndex`` or None (``ai.rag.enabled: false``);
* ``DocIndex.search(query, top_k=None, sources=None)`` -> a list, best first, of
  ``{citation, source, document, title, section, url, score, text}`` (``score`` is relative to
  the best hit, 1.0; ``text`` is clipped to 1500 characters);
* ``DocIndex.stats()`` -> the store's statistics plus build state.

Wave 2 changed nothing in that API: only where the passages live (``ai.rag.store``), that the
query is embedded with the "query" purpose, and that ``stats()`` gains ``chunks``,
``dimensions``, ``store_configured`` and ``store_fallback``.
"""

from sajha.ai.rag.index import DocIndex, get_doc_index, init_doc_index, set_doc_index  # noqa: F401
