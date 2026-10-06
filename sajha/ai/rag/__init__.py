"""
SAJHA MCP Server — retrieval over documents (RAG).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

chunking.py splits documents into passages, stores.py keeps them with their embeddings
(in process, or pgvector), index.py syncs and searches them, tool.py is the
``sajha_search_docs`` MCP tool. Configuration: ``ai.rag`` (docs/getting-started/Configuration
Reference.md); design: docs/architecture/Intelligence Layer.md.
"""

from sajha.ai.rag.index import DocIndex, get_doc_index, init_doc_index, set_doc_index  # noqa: F401
