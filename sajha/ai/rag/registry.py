"""
SAJHA MCP Server — RAG: the store registry and ``ai.rag.store`` selection.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

``ai.rag.store`` names the store: ``auto`` (the default: ``sqlite_vec`` when the sqlite-vec
extension loads, else ``memory``), a registered name (``sqlite_vec``, ``memory``,
``pgvector``, or one added with ``register_store`` or through the ``sajha.rag.stores``
entry-point group), or ``package.module:Class`` (a ``VectorStore`` subclass). Each store's
settings are its ``defaults`` overlaid with ``ai.rag.stores.<name>`` and then with the
environment variables ``SAJHA_AI_RAG_STORES_<NAME>_<KEY>`` (e.g.
``SAJHA_AI_RAG_STORES_SQLITE_VEC_PATH``, ``SAJHA_AI_RAG_STORES_PGVECTOR_DSN``).

When the chosen store cannot run, the index falls back to the memory store and raises the
System Notice ``rag.store_fallback`` saying why; the notice clears once the store runs.
"""

from __future__ import annotations

import importlib
import logging
import os
import re
from typing import Any, Dict, Optional, Tuple, Type

from sajha.ai.rag.stores import InProcessVectorStore, PgVectorStore, StoreUnavailable, VectorStore  # noqa: F401

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "sajha.rag.stores"
NOTICE_ID = "rag.store_fallback"
ENV_PREFIX = "SAJHA_AI_RAG_STORES_"

_STORES: Dict[str, Type[VectorStore]] = {}
_entry_points_loaded = False


def register_store(cls=None, *, name: Optional[str] = None):
    """Class decorator: ``@register_store`` or ``@register_store(name="mine")``."""
    def deco(c):
        if not (isinstance(c, type) and issubclass(c, VectorStore)):
            raise TypeError(f"{c!r} is not a VectorStore subclass")
        n = name or getattr(c, "name", "")
        if not n or n == "base":
            raise ValueError(f"store {c.__name__} has no name")
        c.name = n
        _STORES[n] = c
        return c
    return deco(cls) if cls is not None else deco


def _load_entry_points() -> None:
    global _entry_points_loaded
    if _entry_points_loaded:
        return
    _entry_points_loaded = True
    try:
        from importlib.metadata import entry_points
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            try:
                cls = ep.load()
                register_store(cls, name=ep.name if getattr(cls, "name", "base") == "base" else cls.name)
            except Exception as e:
                logger.warning(f"rag store entry point {ep.name}: {e}")
    except Exception as e:
        logger.debug(f"rag store entry points: {e}")


def registered_stores() -> Dict[str, Type[VectorStore]]:
    _load_entry_points()
    return dict(_STORES)


def store_class(name: str) -> Type[VectorStore]:
    """A registered name, or ``package.module:Class``."""
    key = (name or "").strip()
    if key in _STORES:
        return _STORES[key]
    if ":" in key:
        mod, _, attr = key.partition(":")
        cls = getattr(importlib.import_module(mod), attr)
        if not (isinstance(cls, type) and issubclass(cls, VectorStore)):
            raise ValueError(f"ai.rag.store {name!r} is not a VectorStore subclass")
        return cls
    _load_entry_points()
    if key in _STORES:
        return _STORES[key]
    raise ValueError(f"unknown ai.rag.store {name!r}; registered: {', '.join(sorted(_STORES))}, auto "
                     f"(or give package.module:Class)")


def store_options(name: str, cls: Type[VectorStore], settings: Any = None,
                  environ: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """``cls.defaults`` < ``ai.rag.stores.<name>`` < ``SAJHA_AI_RAG_STORES_<NAME>_<KEY>``."""
    env = os.environ if environ is None else environ
    opts = dict(cls.defaults)
    configured = (getattr(settings, "stores", None) or {}) if settings is not None else {}
    opts.update(configured.get(name) or {})
    prefix = ENV_PREFIX + re.sub(r"[^A-Za-z0-9]", "_", name).upper() + "_"
    for var, value in env.items():
        if var.startswith(prefix) and len(var) > len(prefix):
            opts[var[len(prefix):].lower()] = value
    return opts


def _notice(title: str, detail: str, severity: str = "warning") -> None:
    try:
        from sajha.notices import raise_notice
        raise_notice(NOTICE_ID, severity=severity, source="ai.rag", title=title, detail=detail,
                     link="/help/guides/Intelligence%20Layer.md")
    except Exception:
        pass


def _clear_notice() -> None:
    try:
        from sajha.notices import clear_notice
        clear_notice(NOTICE_ID)
    except Exception:
        pass


def _memory(settings) -> VectorStore:
    cls = _STORES["memory"]
    return cls.create(store_options("memory", cls, settings), settings)


def select_store(settings: Any, engine: Any = None, environ: Optional[Dict[str, str]] = None
                 ) -> Tuple[VectorStore, Optional[str]]:
    """The store ``ai.rag.store`` names, and the reason for a fallback (None when it runs)."""
    wanted = (getattr(settings, "store", "") or "auto").strip()
    name = wanted
    if wanted == "auto":
        cls = _STORES["sqlite_vec"]
        reason = cls.probe(store_options("sqlite_vec", cls, settings, environ))
        if reason:
            msg = (f"ai.rag.store is auto and sqlite-vec is not usable here: {reason}. Document search uses the "
                   "in-memory store, which holds every passage and vector in RAM.")
            logger.warning(f"  RAG: {msg}")
            _notice("Document search is using the in-memory store", msg, severity="info")
            return _memory(settings), reason
        name = "sqlite_vec"
    try:
        cls = store_class(name)
        key = cls.name if cls.name not in ("", "base") else name
        store = cls.create(store_options(key, cls, settings, environ), settings, engine)
    except Exception as e:                 # unavailable, misconfigured, unreadable: never fatal
        if name == "memory":
            raise
        msg = (f"ai.rag.store {wanted!r} cannot run: {e}. Document search uses the in-memory store "
               "instead; fix the cause and restart.")
        logger.warning(f"  RAG: {msg}")
        _notice(f"Document search store '{wanted}' is unavailable", msg)
        return _memory(settings), str(e)
    _clear_notice()
    return store, None


def _register_shipped() -> None:
    from sajha.ai.rag.sqlite_vec import SqliteVecStore
    for c in (InProcessVectorStore, PgVectorStore, SqliteVecStore):
        register_store(c)


_register_shipped()
