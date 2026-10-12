"""
SAJHA MCP Server — ``sajha_search_my_docs``: search the caller's own documents from connected accounts.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Configured in config/tools/sajha/sajha_search_my_docs.json. The caller is the signed-in user
the call came from (sajha/observability/caller.py); the search covers only that user's
passages, read from ``ai.rag.accounts.sources`` with that user's linked tokens
(personal.py). A source not synced recently starts a background sync, named in ``syncing``;
a source whose provider the user has not linked is named in ``not_linked`` with the page to
link it. Results are per user, so the tool is never cached.
"""

from typing import Any, Dict

from sajha.tools.base_mcp_tool import BaseMCPTool

TOOL_NAME = "sajha_search_my_docs"
PASSAGE_CHARS = 500

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "What to look for, in plain words (a question works)."},
        "top_k": {"type": "integer", "minimum": 1, "maximum": 20,
                  "description": "How many passages to return (default: the server's ai.rag.top_k)."},
        "source": {"type": "string", "description": "Only this source (a name from ai.rag.accounts.sources)."},
    },
    "required": ["query"],
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "results": {"type": "array", "items": {"type": "object"}},
        "count": {"type": "integer"},
        "syncing": {"type": "array", "items": {"type": "string"}},
        "not_linked": {"type": "array", "items": {"type": "object"}},
    },
}


class SajhaSearchMyDocsTool(BaseMCPTool):
    def __init__(self, config: Dict = None):
        cfg = {"name": TOOL_NAME, "description": "Search your own documents from connected accounts.",
               "version": "1.0.0", "enabled": True}
        cfg.update(config or {})
        super().__init__(cfg)

    @property
    def enabled(self) -> bool:
        """Listed only while ai.rag.accounts has sources (like a connected-account tool)."""
        if not self._enabled:
            return False
        from sajha.ai.rag.personal import get_personal_index
        return get_personal_index() is not None

    def get_input_schema(self) -> Dict:
        return INPUT_SCHEMA

    def get_output_schema(self) -> Dict:
        return OUTPUT_SCHEMA

    def execute(self, arguments: Dict[str, Any]) -> Any:
        from sajha.ai.rag.personal import get_personal_index, is_user, personal_error
        from sajha.observability.caller import current
        index = get_personal_index()
        if index is None:
            why = personal_error()
            raise RuntimeError("documents from connected accounts are not set up on this server"
                               + (f" ({why})" if why else " (ai.rag.accounts.sources is empty)"))
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        caller = current()
        user = caller.user_id
        if not is_user(user, caller.auth_type):
            raise PermissionError("documents from connected accounts belong to signed-in users; this caller is not one")
        source = str(arguments.get("source") or "").strip()
        if source and index.source(source) is None:
            raise ValueError(f"no such source {source!r}; sources: {', '.join(s.name for s in index.cfg.sources)}")
        names = [source] if source else None
        syncing = index.refresh_in_background(user, names)
        results = index.search(user, query, arguments.get("top_k") or None, names)
        for r in results:
            if len(r["text"]) > PASSAGE_CHARS:
                r["text"] = r["text"][:PASSAGE_CHARS - 1] + "…"
        not_linked = []
        for s in index.cfg.sources:
            if (not names or s.name in names) and not index.linked(user, s.provider):
                not_linked.append({"source": s.name, "provider": s.provider,
                                   "connect": f"/account/connections?connect={s.provider}"})
        return {"query": query, "results": results, "count": len(results), "syncing": syncing,
                "not_linked": not_linked}
