"""
SAJHA MCP Server — Data Connectors: the Chroma adapter.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Chroma over its HTTP API, with no Python package (the ``chromadb`` SDK is not used, so
nothing needs installing and nothing can fail at import):

* ``options.api_version``: ``v2`` (the default; Chroma 0.6 and later, under
  ``/api/v2/tenants/{tenant}/databases/{database}``, with ``options.tenant`` default
  ``default_tenant`` and ``options.database`` default ``default_database``) or ``v1`` (older
  servers, ``/api/v1``);
* collections are listed and allowlisted by ``allow.tables`` / ``deny_tables`` like Qdrant's;
  describing one gives its record count, dimension and the metadata keys seen in a sample
  of records (Chroma has no schema);
* a search is ``POST .../collections/{id}/query`` with the query embedded by the intelligence
  layer (or the caller's ``vector``), ``n_results`` and a ``where`` filter SAJHA writes from
  the equality ``filters`` (``{"field": {"$eq": value}}``, joined with ``$and``); Chroma's
  document is the result's text and its metadata the result's metadata, then masked like
  every other search kind (vector.py). ``vector.distance`` (the collection's space: ``cosine``,
  ``l2`` or ``inner``) turns the distance into a score (cosine: 1 - distance; else -distance).

Auth: ``secrets.api_key`` as the ``X-Chroma-Token`` header (``options.auth_header:
authorization`` sends ``Authorization: Bearer`` instead). Requests use the connector HTTP
client (vector.py ``_HTTP``), the same as Qdrant: an administrator sets the URL, and it is not
passed through the tools' outbound fetch guard. Design: docs/architecture/Data Connectors.md,
section 9.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict
from urllib.parse import quote

from sajha.connectors.drivers import ConnectorError
from sajha.connectors.vector import VectorAdapter, _HTTP, _secret

_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
SAMPLE = 20                      # records read to list a collection's metadata keys


class ChromaAdapter(VectorAdapter):
    def _http(self, conn) -> _HTTP:
        key = _secret(conn, "api_key")
        hdrs = {"Content-Type": "application/json"}
        if key:
            if str(conn.options.get("auth_header") or "").lower() == "authorization":
                hdrs["Authorization"] = f"Bearer {key}"
            else:
                hdrs["X-Chroma-Token"] = key
        return _HTTP(conn, hdrs, used=[key])

    def needs_vector(self, conn) -> bool:
        return True

    def _v1(self, conn) -> bool:
        v = str(conn.options.get("api_version") or "v2").lower()
        if v not in ("v1", "v2"):
            raise ConnectorError(f"{conn.id}: options.api_version is v1 or v2")
        return v == "v1"

    def _base(self, conn) -> str:
        if self._v1(conn):
            return "/api/v1"
        tenant = str(conn.options.get("tenant") or "default_tenant")
        database = str(conn.options.get("database") or "default_database")
        for label, v in (("tenant", tenant), ("database", database)):
            if not _SEGMENT.match(v):
                raise ConnectorError(f"{conn.id}: options.{label} has characters a Chroma name does not have")
        return f"/api/v2/tenants/{tenant}/databases/{database}"

    def version(self, conn):
        data = self._http(conn).call("GET", "/api/v1/version" if self._v1(conn) else "/api/v2/version")
        return f"Chroma {data if isinstance(data, str) else (data or {}).get('version', '')}".strip()

    def list_collections(self, conn):
        data = self._http(conn).call("GET", f"{self._base(conn)}/collections?limit=1000")
        return [{"name": c.get("name"), "type": "collection"} for c in data or [] if isinstance(c, dict) and c.get("name")]

    def _collection(self, conn, name) -> Dict[str, Any]:
        data = self._http(conn).call("GET", f"{self._base(conn)}/collections/{quote(name, safe='')}") or {}
        if not data.get("id"):
            raise ConnectorError(f"{conn.id}: Chroma has no collection {name}")
        return data

    def describe(self, conn, name):
        http = self._http(conn)
        col = self._collection(conn, name)
        cid = quote(str(col["id"]), safe="")
        base = self._base(conn)
        count = http.call("GET", f"{base}/collections/{cid}/count")
        sample = http.call("POST", f"{base}/collections/{cid}/get", {"limit": SAMPLE, "include": ["metadatas"]}) or {}
        fields: Dict[str, str] = {}
        for meta in sample.get("metadatas") or []:
            for k, v in (meta or {}).items():
                fields.setdefault(k, type(v).__name__ if v is not None else "null")
        return {"points": count if isinstance(count, int) else None, "dimension": col.get("dimension"),
                "fields": fields}

    def search(self, conn, name, text, vector, top_k, filters):
        if vector is None:
            raise ConnectorError('a Chroma search needs a vector: pass "query" (embedded by the gateway) or "vector"')
        if not all(math.isfinite(x) for x in vector):
            raise ConnectorError("vector must hold finite numbers")
        col = self._collection(conn, name)
        body: Dict[str, Any] = {"query_embeddings": [vector], "n_results": int(top_k),
                                "include": ["documents", "metadatas", "distances"]}
        if filters:
            terms = [{k: {"$eq": v}} for k, v in filters.items()]
            body["where"] = terms[0] if len(terms) == 1 else {"$and": terms}
        data = self._http(conn).call("POST", f"{self._base(conn)}/collections/{quote(str(col['id']), safe='')}/query",
                                     body) or {}

        def first(key):
            rows = data.get(key) or [[]]
            return list(rows[0] or []) if rows else []
        ids, docs, metas, dists = first("ids"), first("documents"), first("metadatas"), first("distances")
        cosine = conn.vector.get("distance", "cosine") == "cosine"
        out = []
        for i, rid in enumerate(ids):
            d = dists[i] if i < len(dists) else None
            score = None if d is None else (1.0 - float(d) if cosine else -float(d))
            out.append({"id": rid, "score": score, "text": docs[i] if i < len(docs) else None,
                        "metadata": dict((metas[i] if i < len(metas) else None) or {})})
        return out
