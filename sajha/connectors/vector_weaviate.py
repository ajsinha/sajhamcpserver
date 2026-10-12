"""
SAJHA MCP Server — Data Connectors: the Weaviate adapter.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Weaviate over its REST and GraphQL API, with no Python package (the ``weaviate-client`` SDK
is not used, so nothing needs installing and nothing can fail at import):

* collections are Weaviate classes: ``GET /v1/schema`` lists them, ``GET /v1/schema/{class}``
  gives the properties; ``allow.tables`` / ``deny_tables`` allowlist them like Qdrant's;
* a search is one ``POST /v1/graphql`` ``Get`` query that SAJHA writes: ``nearVector`` with the
  query embedded by the intelligence layer (or the caller's ``vector``; ``vector.vector_name``
  targets a named vector), or ``bm25`` keyword search when ``vector.embedding_model`` is
  ``none``; equality ``filters`` become a ``where`` filter with an ``Equal`` operand per field.
  Class, property and filter names are checked against the schema and GraphQL's name rule,
  values are written as JSON literals, so no query text comes from the caller;
* the selection is the class's scalar properties minus masked ``hide`` columns; results are
  ``{id, score, text, metadata}`` (``vector.text_field``, default ``text``, is the text) and
  then masked like every other search kind (vector.py).

Auth: ``secrets.api_key`` as ``Authorization: Bearer``. Requests use the connector HTTP client
(vector.py ``_HTTP``), the same as Qdrant and Elasticsearch: an administrator sets the URL, and
it is not passed through the tools' outbound fetch guard. Design: docs/architecture/Data
Connectors.md, section 9.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from sajha.connectors.drivers import ConnectorError
from sajha.connectors.vector import VectorAdapter, _HTTP, _secret

_GQL_NAME = re.compile(r"^[_A-Za-z][_0-9A-Za-z]{0,230}$")
_SCALARS = {"text", "string", "int", "number", "boolean", "date", "uuid", "text[]", "string[]", "int[]",
            "number[]", "boolean[]", "date[]", "uuid[]", "phoneNumber", "geoCoordinates"}
_VALUE_KEY = {"int": "valueInt", "number": "valueNumber", "boolean": "valueBoolean", "date": "valueDate",
              "text": "valueText", "string": "valueText", "uuid": "valueText"}


def _literal(v: Any) -> str:
    """A GraphQL literal for a scalar (JSON's string escapes are GraphQL's)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ConnectorError("filter values must be finite numbers")
        return repr(v)
    return json.dumps(str(v))


class WeaviateAdapter(VectorAdapter):
    def _http(self, conn) -> _HTTP:
        key = _secret(conn, "api_key")
        hdrs = {"Content-Type": "application/json"}
        if key:
            hdrs["Authorization"] = f"Bearer {key}"
        return _HTTP(conn, hdrs, used=[key])

    def needs_vector(self, conn) -> bool:
        """nearVector unless ``vector.embedding_model`` is ``none`` (then bm25 keyword search)."""
        return str(conn.vector.get("embedding_model") or "").strip().lower() != "none"

    def version(self, conn):
        data = self._http(conn).call("GET", "/v1/meta")
        return f"Weaviate {(data or {}).get('version', '')}".strip()

    def list_collections(self, conn):
        data = self._http(conn).call("GET", "/v1/schema")
        return [{"name": c.get("class"), "type": "collection"} for c in (data or {}).get("classes") or []
                if c.get("class")]

    def describe(self, conn, name):
        data = self._http(conn).call("GET", f"/v1/schema/{quote(name, safe='')}") or {}
        fields = {}
        for p in data.get("properties") or []:
            dt = (p.get("dataType") or ["?"])[0]
            if p.get("name") and dt in _SCALARS:          # cross-references (a class name) are left out
                fields[p["name"]] = dt
        vcfg = data.get("vectorConfig") or {}
        return {"fields": fields, "vectorizer": data.get("vectorizer"),
                "named_vectors": sorted(vcfg) if isinstance(vcfg, dict) else [],
                "multi_tenancy": bool((data.get("multiTenancyConfig") or {}).get("enabled"))}

    def _fields(self, conn, name) -> Dict[str, str]:
        from sajha.connectors import catalog
        info = catalog.described(conn, "", name, lambda: self.describe(conn, name))
        return dict(info.get("fields") or {})

    def search(self, conn, name, text, vector, top_k, filters):
        if not _GQL_NAME.match(name or ""):
            raise ConnectorError(f"{name!r} is not a Weaviate class name")
        fields = self._fields(conn, name)
        text_field = conn.vector.get("text_field") or "text"
        tables = [("", name)]
        select = [f for f in fields if _GQL_NAME.match(f) and not _hidden(conn, f, tables)]
        if not select:
            raise ConnectorError(f"class {name} has no properties SAJHA may return")
        args = [f"limit: {int(top_k)}"]
        if vector is not None:
            if not all(math.isfinite(x) for x in vector):
                raise ConnectorError("vector must hold finite numbers")
            near = "vector: [" + ",".join(f"{x:.7g}" for x in vector) + "]"
            vname = conn.vector.get("vector_name")
            if vname:
                if not _GQL_NAME.match(str(vname)):
                    raise ConnectorError("vector.vector_name is not a valid name")
                near += f", targetVectors: [{json.dumps(str(vname))}]"
            args.append("nearVector: {" + near + "}")
        else:
            if not text:
                raise ConnectorError('a Weaviate keyword search needs "query"')
            args.append("bm25: {query: " + json.dumps(text) + "}")
        if filters:
            ops = []
            for k, v in filters.items():
                if k not in fields or not _GQL_NAME.match(k):
                    raise ConnectorError(f"filter {k}: not a property of {name} "
                                         f"({', '.join(sorted(fields)) or 'none'})")
                key = _VALUE_KEY.get(fields[k].rstrip("[]"), "valueText")
                if key == "valueInt" and not (isinstance(v, int) and not isinstance(v, bool)):
                    raise ConnectorError(f"filter {k}: a whole number")
                if key == "valueNumber" and not (isinstance(v, (int, float)) and not isinstance(v, bool)):
                    raise ConnectorError(f"filter {k}: a number")
                if key == "valueBoolean" and not isinstance(v, bool):
                    raise ConnectorError(f"filter {k}: true or false")
                ops.append("{path: [" + json.dumps(k) + "], operator: Equal, " + key + ": " + _literal(v) + "}")
            args.append("where: " + (ops[0] if len(ops) == 1 else "{operator: And, operands: [" + ", ".join(ops) + "]}"))
        query = ("{ Get { " + name + "(" + ", ".join(args) + ") { " + " ".join(select) +
                 " _additional { id distance score } } } }")
        data = self._http(conn).call("POST", "/v1/graphql", {"query": query}) or {}
        if data.get("errors"):
            msg = "; ".join(str(e.get("message") or e) for e in data["errors"][:3] if isinstance(e, dict))
            raise ConnectorError(f"{conn.id}: Weaviate refused the search: {msg[:300]}")
        out = []
        for obj in ((data.get("data") or {}).get("Get") or {}).get(name) or []:
            obj = dict(obj or {})
            extra = obj.pop("_additional", None) or {}
            score: Optional[float] = None
            if extra.get("distance") is not None:
                d = float(extra["distance"])
                score = 1.0 - d if conn.vector.get("distance", "cosine") == "cosine" else -d
            elif extra.get("score") is not None:
                score = float(extra["score"])
            out.append({"id": extra.get("id"), "score": score, "text": obj.pop(text_field, None), "metadata": obj})
        return out


def _hidden(conn, field: str, tables: List) -> bool:
    r = conn.mask_rules_for(field, tables)
    return r is not None and r.mode == "hide"
