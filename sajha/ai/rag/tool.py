"""
SAJHA MCP Server — ``sajha_search_docs``: search SAJHA's documentation and the admin's document sources.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Configured in config/tools/sajha_search_docs.json like any tool, so it is in tools/list, its
access follows the usual role permissions, and Ask SAJHA's planner can call it. Each result
carries its citation: the document, its section and, for SAJHA's guides, the help-page link.
"""

from typing import Any, Dict

from sajha.tools.base_mcp_tool import BaseMCPTool

TOOL_NAME = "sajha_search_docs"
PASSAGE_CHARS = 500                     # per passage in the tool result

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "What to look for, in plain words (a question works)."},
        "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 3,
                  "description": "How many passages to return."},
        "source": {"type": "string",
                   "description": "Only this source: sajha_docs, uploads, or a configured source's name."},
    },
    "required": ["query"],
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "results": {"type": "array", "items": {"type": "object", "properties": {
            "citation": {"type": "integer"}, "source": {"type": "string"}, "document": {"type": "string"},
            "title": {"type": "string"}, "section": {"type": "string"}, "url": {"type": ["string", "null"]},
            "score": {"type": "number"}, "text": {"type": "string"}}}},
        "count": {"type": "integer"},
    },
}


class SajhaSearchDocsTool(BaseMCPTool):
    def __init__(self, config: Dict = None):
        cfg = {"name": TOOL_NAME, "description": "Search SAJHA's documentation and configured document sources.",
               "version": "1.0.0", "enabled": True}
        cfg.update(config or {})
        super().__init__(cfg)

    def get_input_schema(self) -> Dict:
        return INPUT_SCHEMA

    def get_output_schema(self) -> Dict:
        return OUTPUT_SCHEMA

    def execute(self, arguments: Dict[str, Any]) -> Any:
        from sajha.ai.rag.index import get_doc_index
        index = get_doc_index()
        if index is None:
            raise RuntimeError("document search is off (ai.rag.enabled is false)")
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        source = str(arguments.get("source") or "").strip()
        results = index.search(query, arguments.get("top_k") or None, [source] if source else None)
        for r in results:                     # keep a whole result list inside the ask loop's result cap
            if len(r["text"]) > PASSAGE_CHARS:
                r["text"] = r["text"][:PASSAGE_CHARS - 1] + "…"
        return {"query": query, "results": results, "count": len(results)}
