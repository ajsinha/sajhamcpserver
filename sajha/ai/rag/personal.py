"""
SAJHA MCP Server — RAG: the personal document index (sources read through connected accounts).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

``ai.rag.accounts.sources`` names document sources at services users link on
/account/connections (Google Drive, OneDrive, SharePoint, GitHub, Confluence;
account_sources.py). For each signed-in user with a usable link, the source is listed and
read **with that user's token**, so what is indexed for a user is exactly what that user may
read there. Isolation:

* the passages live in a store of their own (``ai.rag.accounts.store``: a sqlite_vec file or
  the memory store, never the shared index's store), so the shared ``sajha_search_docs``
  index never sees them;
* every passage's source is ``acct:<owner>:<source>``, where ``<owner>`` is a hash of the
  user id, and every search passes the caller's own source keys as the store's filter (and
  checks each hit again), so one user's query never reaches another user's passages; a
  document two users can both read is indexed once per user;
* a search covers only sources whose link is currently active; a link that is removed, or a
  source the user can no longer open (HTTP 403/404), removes that user's passages from it at
  the next sync.

Sync is incremental: each file's change token (account_sources.py) is the document's hash in
the store, so an unchanged file is not downloaded; files no longer listed are deleted. A
search starts a background sync of the caller's sources not synced within
``ai.rag.accounts.stale_after_seconds``; ``sync_interval_seconds`` (off by default) sweeps
every linked user. One document at a time is fetched, extracted, chunked and embedded with
no connection held, and only then written to the store in one short transaction.

Configuration: ``ai.rag.accounts`` (docs/getting-started/Configuration Reference.md); design:
docs/architecture/Intelligence Layer.md, "Document search (RAG)".
"""

from __future__ import annotations

import hashlib
import logging
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sajha.ai.rag import ocr
from sajha.ai.rag.account_sources import (AccessLost, AccountSource, FileTooLarge, ProviderSession, SourceError,
                                          client_for)
from sajha.ai.rag.chunking import SUPPORTED_TYPES, TEXT_TYPES, chunk_document, title_of
from sajha.ai.rag.stores import DimensionChanged, StoredChunk, VectorStore

logger = logging.getLogger(__name__)

PREFIX = "acct:"
_RRF_K = 60
STORES = ("auto", "sqlite_vec", "memory")


class PersonalDocsSettings(BaseModel):
    """``ai.rag.accounts``."""
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    sources: List[AccountSource] = Field(default_factory=list)
    store: str = "auto"                                  # auto (sqlite_vec, else memory) | sqlite_vec | memory
    path: str = "data/rag/personal.db"                   # the sqlite_vec file (local disk)
    index_path: str = "data/rag/personal_index.json"     # the memory store's file (storage backend)
    max_files_per_source: int = 2000
    max_file_bytes: int = 10_000_000
    stale_after_seconds: int = 3600                      # a search re-syncs sources older than this; 0: never
    sync_interval_seconds: int = 0                       # sweep every linked user this often; 0: off
    ocr_max_pages: int = 50                              # pages OCR'd per scanned PDF (ai.rag.ocr)

    @field_validator("store")
    @classmethod
    def _store(cls, v):
        if v not in STORES:
            raise ValueError(f"one of {', '.join(STORES)} (pgvector would share the shared index's table)")
        return v

    @field_validator("sources")
    @classmethod
    def _unique(cls, v):
        names = [s.name for s in v]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            raise ValueError(f"duplicate source names: {', '.join(dup)}")
        return v


def parse_settings(raw: Any) -> PersonalDocsSettings:
    if isinstance(raw, PersonalDocsSettings):
        return raw
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    return PersonalDocsSettings.model_validate(dict(raw or {}))


def owner_hash(user_id: str) -> str:
    return hashlib.sha256(f"sajha-rag-owner\x00{user_id}".encode("utf-8")).hexdigest()[:24]


def source_key(user_id: str, name: str) -> str:
    return f"{PREFIX}{owner_hash(user_id)}:{name}"


def is_user(user_id: Optional[str], auth_type: Optional[str] = None) -> bool:
    """Signed-in users only: API keys and anonymous callers have no connected accounts. A key bound to a
    user calls as that user (``user_id`` is the owner), so the entry points pass ``auth_type`` too and a
    key (``apikey``) gets nothing, as on Connected accounts (sajha/routes/accounts_routes.py)."""
    if auth_type == "apikey":
        return False
    return bool(user_id) and user_id != "anonymous" and not str(user_id).startswith("apikey:")


# ── collaborators (replaced in tests) ───────────────────────────────────

def _default_token(user_id: str, provider: str, scopes: List[str]):
    from sajha.accounts.service import get_service
    return get_service().resolve(user_id, provider, scopes, tool="rag:accounts")


def _default_link_active(user_id: str, provider: str) -> bool:
    try:
        from sajha.accounts.settings import get_accounts_settings
        from sajha.accounts.vault import get_vault
        from sajha.accounts.providers import get_registry
        if not get_accounts_settings().enabled:
            return False
        p = get_registry().get(provider)
        if p is None or not p.configured:
            return False
        conn = get_vault().get(user_id, provider)
        return conn is not None and conn.status == "active"
    except Exception as e:
        logger.debug(f"rag accounts: link check for {provider}: {e}")
        return False


def _default_users(provider: str) -> List[str]:
    from sajha.accounts.vault import get_vault
    return sorted({c.user_id for c in get_vault().list_all(provider=provider, limit=100000) if c.status == "active"})


class PersonalDocIndex:
    def __init__(self, rag_settings: Any = None, gateway: Any = None, store: Optional[VectorStore] = None,
                 token_for: Optional[Callable] = None, link_active: Optional[Callable] = None,
                 users_for: Optional[Callable] = None, session_options: Optional[Dict[str, Any]] = None):
        from sajha.ai.llm.settings import RagSettings
        self.rag = rag_settings or RagSettings()
        self.cfg = parse_settings(getattr(self.rag, "accounts", None) or {})
        self.ocr = bool(getattr(self.rag, "ocr", False))
        self.gateway = gateway
        self._token_for = token_for or _default_token
        self._link_active = link_active or _default_link_active
        self._users_for = users_for or _default_users
        self._session_options = dict(session_options or {})
        self.store = store or self._choose_store()
        from sajha.ai.rag.index import DocIndex          # embedding helpers only (no build, no discovery)
        self._embedder = DocIndex(self.rag, gateway, store=self.store)
        self._state: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._running: set = set()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rag-accounts")
        self._stop = threading.Event()
        self._sweeper: Optional[threading.Thread] = None
        self._scope = self._claim_scope()

    # ── setup ───────────────────────────────────────────────────
    def _choose_store(self) -> VectorStore:
        from sajha.ai.rag.sqlite_vec import SqliteVecStore
        from sajha.ai.rag.stores import InProcessVectorStore
        want = self.cfg.store
        if want in ("auto", "sqlite_vec"):
            shared = str(((getattr(self.rag, "stores", None) or {}).get("sqlite_vec") or {}).get("path")
                         or SqliteVecStore.defaults["path"])
            if os.path.abspath(self.cfg.path) == os.path.abspath(shared):
                raise ValueError("ai.rag.accounts.path must differ from the shared index's sqlite_vec path")
            reason = SqliteVecStore.probe({})
            if reason is None:
                return SqliteVecStore.create({"path": self.cfg.path}, self.rag)
            if want == "sqlite_vec":
                raise ValueError(f"ai.rag.accounts.store is sqlite_vec and it cannot run here: {reason}")
            logger.info(f"  RAG accounts: sqlite-vec is not usable ({reason}); using the memory store")
        if self.cfg.index_path == getattr(self.rag, "index_path", None):
            raise ValueError("ai.rag.accounts.index_path must differ from ai.rag.index_path")
        return InProcessVectorStore(self.cfg.index_path if getattr(self.rag, "persist", True) else None)

    def _claim_scope(self) -> str:
        """Workers that share this store (one sqlite file on one host) share sync claims."""
        path = getattr(self.store, "path", None)
        if path and not getattr(self.store, "temporary", False):
            return f"{socket.gethostname()}:{path}"
        from sajha.core.state import WORKER_ID
        return WORKER_ID

    def close(self) -> None:
        self._stop.set()
        self._pool.shutdown(wait=False, cancel_futures=True)
        try:
            self.store.close()
        except Exception as e:
            logger.debug(f"rag accounts: closing the store: {e}")

    def source(self, name: str) -> Optional[AccountSource]:
        return next((s for s in self.cfg.sources if s.name == name), None)

    # ── files ───────────────────────────────────────────────────
    def accepts(self, name: str) -> bool:
        low = (name or "").lower()
        return low.endswith(SUPPORTED_TYPES) or (self.ocr and ocr.is_image(low))

    def _text(self, name: str, data: bytes) -> Tuple[str, str]:
        if name.lower().endswith(TEXT_TYPES):
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise ValueError("not UTF-8 text") from None
            return text, title_of(name, text)
        text, title = ocr.extract_document(name, data, self.ocr, self.cfg.ocr_max_pages)
        return text, title or title_of(name, text if name.lower().endswith(".docx") else "")

    def _doc_hash(self, f) -> str:
        s = self.rag
        return hashlib.sha256(f"{s.chunk_chars}\x00{s.chunk_overlap}\x00{int(self.ocr)}\x00{f.name}\x00{f.version}"
                              .encode("utf-8")).hexdigest()

    # ── syncing ─────────────────────────────────────────────────
    def sync_user(self, user_id: str, names: Optional[Iterable[str]] = None, force: bool = False
                  ) -> Dict[str, Any]:
        """Sync the user's sources now (all, or ``names``); {source name: stats}."""
        if not is_user(user_id):
            raise PermissionError("documents from connected accounts belong to signed-in users")
        wanted = set(names or [])
        out = {}
        for src in self.cfg.sources:
            if wanted and src.name not in wanted:
                continue
            out[src.name] = self.sync_source(user_id, src, force=force)
        return out

    def sync_source(self, user_id: str, src: AccountSource, force: bool = False) -> Dict[str, Any]:
        key = (user_id, src.name)
        with self._lock:
            if key in self._running:
                return {"status": "already syncing"}
            self._running.add(key)
        lease = f"rag:accounts:sync:{self._scope}:{owner_hash(user_id)}:{src.name}"
        claimed = self._claim(lease)
        try:
            if not claimed:
                return {"status": "syncing on another worker"}
            try:
                stats = self._sync(user_id, src, force)
            except DimensionChanged as e:
                logger.info(f"  RAG accounts: the embedding dimension changed ({e}); clearing the personal index")
                self.store.clear()
                with self._lock:
                    self._state.clear()
                stats = self._sync(user_id, src, True)
        except Exception as e:                        # never fatal for a background sync
            logger.warning(f"rag accounts: {src.name}: sync failed: {e}")
            stats = {"status": "error", "error": str(e)[:300]}
        finally:
            if claimed:
                self._release(lease)
            with self._lock:
                self._running.discard(key)
        with self._lock:
            prev = self._state.get(key, {})
            self._state[key] = {**prev, "at": time.time(), "last": stats,
                                **({"cursor": stats.pop("_cursor")} if "_cursor" in stats else {})}
        return stats

    def _claim(self, lease: str) -> bool:
        try:
            from sajha.core.state import WORKER_ID, get_state_store
            return get_state_store().lease_claim(lease, WORKER_ID, ttl=900)
        except Exception as e:
            logger.debug(f"rag accounts: no sync claim ({e}); syncing")
            return True

    def _release(self, lease: str) -> None:
        try:
            from sajha.core.state import WORKER_ID, get_state_store
            get_state_store().lease_release(lease, WORKER_ID)
        except Exception:
            pass

    def _sync(self, user_id: str, src: AccountSource, force: bool) -> Dict[str, Any]:
        from sajha.accounts.errors import ConnectedAccountRequired, ProviderNotConfigured
        t0 = time.time()
        skey = source_key(user_id, src.name)
        stats: Dict[str, Any] = {"status": "ok", "documents": 0, "indexed": 0, "unchanged": 0, "removed": 0,
                                 "skipped": 0, "chunks": 0, "errors": [], "truncated": False}
        try:
            token = self._token_for(user_id, src.provider, list(src.scopes or []))
        except ConnectedAccountRequired as e:
            if e.reason in ("not_connected", "sign_in_required"):
                stats["removed"] = self.purge(user_id, src.name)
            return {**stats, "status": "needs_connection", "reason": e.reason, "error": e.message}
        except ProviderNotConfigured as e:
            return {**stats, "status": "unavailable", "error": str(e)}
        session = ProviderSession(token, self.cfg.max_file_bytes, **self._session_options)
        client = client_for(src, session, src.max_files or self.cfg.max_files_per_source, self.accepts)
        have = {doc: h for (s, doc), h in self.store.documents().items() if s == skey}
        try:
            cursor = client.cursor()
            prev = self._state.get((user_id, src.name), {})
            if cursor and not force and have and prev.get("cursor") == cursor:
                return {**stats, "status": "unchanged", "documents": len(have), "unchanged": len(have),
                        "_cursor": cursor}
            embedder = self._embedder.embedder_name()
            if force or self.store.embedder() not in ("", embedder):
                have = {}
            seen = set()
            for f in client.files():
                stats["documents"] += 1
                seen.add(f.id)
                h = self._doc_hash(f)
                if have.get(f.id) == h:
                    stats["unchanged"] += 1
                    continue
                try:
                    stats["chunks"] += self._index_file(skey, src, client, f, h, embedder)
                    stats["indexed"] += 1
                except DimensionChanged:
                    raise
                except AccessLost:
                    raise
                except (SourceError, ValueError, ocr.OCRUnavailable, FileTooLarge) as e:
                    stats["skipped"] += 1
                    stats["errors"].append(f"{f.path}: {e}"[:300])
                    if f.id in have:                     # it was readable before; it is not now
                        self.store.delete_document(skey, f.id)
                except Exception as e:                   # an extractor missing, a reader bug
                    stats["skipped"] += 1
                    stats["errors"].append(f"{f.path}: {e.__class__.__name__}: {e}"[:300])
            stats["truncated"] = client.truncated
            for doc in set(have) - seen:
                self.store.delete_document(skey, doc)
                stats["removed"] += 1
            if cursor and not stats["errors"]:       # a file that failed is tried again next time
                stats["_cursor"] = cursor
        except AccessLost as e:
            n = self.purge(user_id, src.name)
            return {**stats, "status": "access_lost", "removed": n, "error": str(e)}
        except ConnectedAccountRequired as e:
            return {**stats, "status": "needs_connection", "reason": e.reason, "error": e.message}
        finally:
            self.store.save()
        stats["errors"] = stats["errors"][:20]
        stats["duration_ms"] = int((time.time() - t0) * 1000)
        logger.info(f"  RAG accounts: {src.name} for one user: {stats['documents']} documents "
                    f"({stats['indexed']} indexed, {stats['unchanged']} unchanged, {stats['removed']} removed, "
                    f"{stats['skipped']} skipped) in {stats['duration_ms']} ms")
        return stats

    def _index_file(self, skey: str, src: AccountSource, client, f, doc_hash: str, embedder: str) -> int:
        """Fetch, extract, chunk and embed one file with no store connection held, then write it."""
        name, data = client.fetch(f)
        text, title = self._text(name, data)
        del data
        s = self.rag
        pieces = chunk_document(name, text, s.chunk_chars, s.chunk_overlap)
        chunks = []
        for p in pieces:
            cid = hashlib.sha1(f"{skey}\x00{f.id}\x00{p.ordinal}\x00{doc_hash}".encode()).hexdigest()[:32]
            chunks.append(StoredChunk(cid, skey, f.id, title or f.path, p.heading, p.anchor, f.url, p.text,
                                      p.ordinal))
        if embedder and chunks:
            vecs = self._embedder._embed([f"{c.title} — {c.heading}\n{c.text}" for c in chunks], "document")
            for c, v in zip(chunks, vecs):
                c.vector = v
        return self.store.replace_document(skey, f.id, doc_hash, embedder, chunks)

    def purge(self, user_id: str, name: Optional[str] = None) -> int:
        """Remove the user's passages (from one source, or all); the number of documents removed."""
        keys = {source_key(user_id, s.name) for s in self.cfg.sources if name in (None, s.name)}
        if name is None:                                  # also sources no longer configured
            prefix = f"{PREFIX}{owner_hash(user_id)}:"
            keys |= {s for s, _ in self.store.documents() if s.startswith(prefix)}
        n = 0
        for s, doc in list(self.store.documents()):
            if s in keys:
                self.store.delete_document(s, doc)
                n += 1
        if n:
            self.store.save()
        with self._lock:
            for k in [k for k in self._state if k[0] == user_id and name in (None, k[1])]:
                self._state.pop(k, None)
        return n

    # ── background ──────────────────────────────────────────────
    def linked(self, user_id: str, provider: str) -> bool:
        """Whether the user's link to ``provider`` is usable now."""
        return bool(is_user(user_id) and self._link_active(user_id, provider))

    def sync_in_background(self, user_id: str, names: Optional[Iterable[str]] = None,
                           force: bool = False) -> List[str]:
        """Start syncs of the user's sources (all, or ``names``) now; the names started."""
        if not is_user(user_id):
            raise PermissionError("documents from connected accounts belong to signed-in users")
        wanted = set(names or [])
        started = []
        for src in self.cfg.sources:
            if not wanted or src.name in wanted:
                self._pool.submit(self.sync_source, user_id, src, force)
                started.append(src.name)
        return started

    def stale(self, user_id: str, src: AccountSource) -> bool:
        st = self._state.get((user_id, src.name))
        if st is None:
            return True
        age = self.cfg.stale_after_seconds
        return bool(age) and time.time() - st.get("at", 0) > age

    def refresh_in_background(self, user_id: str, names: Optional[Iterable[str]] = None) -> List[str]:
        """Start syncs of the user's stale sources with an active link; the names started."""
        if not is_user(user_id):
            return []
        started = []
        wanted = set(names or [])
        for src in self.cfg.sources:
            if wanted and src.name not in wanted:
                continue
            with self._lock:
                busy = (user_id, src.name) in self._running
            if busy or not self.stale(user_id, src) or not self._link_active(user_id, src.provider):
                continue
            with self._lock:                   # mark now so a burst of searches starts one sync
                self._state.setdefault((user_id, src.name), {})["at"] = time.time()
            self._pool.submit(self.sync_source, user_id, src)
            started.append(src.name)
        return started

    def sync_all(self) -> Dict[str, int]:
        """Sync every source for every user with an active link to its provider."""
        done = 0
        for src in self.cfg.sources:
            try:
                users = self._users_for(src.provider)
            except Exception as e:
                logger.warning(f"rag accounts: cannot list linked users for {src.provider}: {e}")
                continue
            for uid in users:
                if self._stop.is_set():
                    return {"synced": done}
                if is_user(uid):
                    self.sync_source(uid, src)
                    done += 1
        return {"synced": done}

    def start_sweeper(self) -> bool:
        every = int(self.cfg.sync_interval_seconds or 0)
        if every <= 0 or self._sweeper is not None:
            return False

        def loop():
            while not self._stop.wait(every):
                try:
                    self.sync_all()
                except Exception as e:
                    logger.warning(f"rag accounts: sweep failed: {e}")
        self._sweeper = threading.Thread(target=loop, name="rag-accounts-sweep", daemon=True)
        self._sweeper.start()
        return True

    # ── searching ───────────────────────────────────────────────
    def search(self, user_id: str, query: str, top_k: Optional[int] = None,
               sources: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """The caller's own passages that best answer ``query``, best first, with citations."""
        query = (query or "").strip()
        if not query or not is_user(user_id):
            return []
        names = {source_key(user_id, s.name): s.name for s in self.cfg.sources
                 if (not sources or s.name in sources) and self._link_active(user_id, s.provider)}
        if not names:
            return []
        keys = sorted(names)
        k = max(1, min(int(top_k or self.rag.top_k), 20))
        pool = k * 4
        ranked: Dict[str, float] = {}
        found: Dict[str, StoredChunk] = {}
        if self.store.embedder() and self.gateway is not None:
            try:
                qv = self._embedder._embed([query], "query")[0]
                w = max(0.0, float(self.rag.vector_weight))
                for rank, (c, _s) in enumerate(self.store.search(qv, pool, keys)):
                    ranked[c.id] = ranked.get(c.id, 0.0) + w / (_RRF_K + rank + 1)
                    found[c.id] = c
            except Exception as e:
                logger.info(f"rag accounts: vector search failed ({e}); lexical only")
        try:
            hits = self.store.keyword_search(query, pool, keys)
        except Exception as e:
            logger.info(f"rag accounts: keyword search failed ({e})")
            hits = []
        for rank, (c, _s) in enumerate(hits):
            ranked[c.id] = ranked.get(c.id, 0.0) + 1.0 / (_RRF_K + rank + 1)
            found.setdefault(c.id, c)
        # the store filtered by source; check again, so a store bug cannot cross users
        best = sorted((cid for cid in ranked if cid in found and found[cid].source in names),
                      key=lambda c: -ranked[c])[:k]
        top = ranked[best[0]] if best else 1.0
        out = []
        for i, cid in enumerate(best):
            c = found[cid]
            out.append({"citation": i + 1, "source": names[c.source], "document": c.document, "title": c.title,
                        "section": c.heading, "url": c.url or None, "score": round(ranked[cid] / top, 4),
                        "text": c.text if len(c.text) <= 1500 else c.text[:1499] + "…"})
        return out

    # ── status ──────────────────────────────────────────────────
    def status(self, user_id: str) -> Dict[str, Any]:
        """The user's sources: linked or not, documents indexed, the last sync."""
        counts: Dict[str, int] = {}
        for s, _d in self.store.documents():
            counts[s] = counts.get(s, 0) + 1
        rows = []
        for src in self.cfg.sources:
            st = self._state.get((user_id, src.name), {})
            with self._lock:
                busy = (user_id, src.name) in self._running
            rows.append({"name": src.name, "title": src.title or src.name, "kind": src.kind,
                         "provider": src.provider, "linked": self._link_active(user_id, src.provider),
                         "documents": counts.get(source_key(user_id, src.name), 0), "syncing": busy,
                         "last_sync_at": st.get("at"), "last_sync": st.get("last")})
        return {"enabled": True, "store": self.store.name, "ocr": {"enabled": self.ocr, **ocr.available()},
                "sources": rows}


# ── singleton ─────────────────────────────────────────────────────

_index: Optional[PersonalDocIndex] = None
_error: str = ""


def init_personal_index(rag_settings: Any = None, gateway: Any = None) -> Optional[PersonalDocIndex]:
    """Start the personal index when ``ai.rag.accounts`` names sources (else None). A bad
    configuration is logged and leaves it off; ``personal_error()`` says why."""
    global _index, _error
    if _index is not None:
        _index.close()
    _index, _error = None, ""
    if rag_settings is not None and not getattr(rag_settings, "enabled", True):
        return None
    try:
        cfg = parse_settings(getattr(rag_settings, "accounts", None) or {})
        if not cfg.enabled or not cfg.sources:
            return None
        _index = PersonalDocIndex(rag_settings, gateway)
        _index.start_sweeper()
    except Exception as e:
        _error = f"{e.__class__.__name__}: {e}"[:500]
        logger.warning(f"  RAG accounts: off ({_error})")
        _index = None
    return _index


def get_personal_index() -> Optional[PersonalDocIndex]:
    return _index


def set_personal_index(index: Optional[PersonalDocIndex]) -> None:
    global _index
    _index = index


def personal_error() -> str:
    return _error
