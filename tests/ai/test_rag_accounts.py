# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Documents from connected accounts as RAG sources (sajha/ai/rag/personal.py, account_sources.py,
ocr.py, personal_tool.py): per-user isolation (a user's search never reaches another user's passages),
incremental sync by change token (unchanged files are not fetched, deletions are removed), access loss
and disconnection purging a user's passages, the Drive, Graph, GitHub and Confluence clients against
in-process HTTP fakes (the user's token only to the provider's hosts, refresh on 401, Graph downloads
without the token), optional OCR refused clearly without an engine, and the sajha_search_my_docs tool.
No live calls; mock embeddings."""

from __future__ import annotations

import base64
import io
import json
import types

import httpx
import pytest

from sajha.accounts import http as ahttp
from sajha.accounts.errors import ConnectedAccountRequired
from sajha.ai.llm.settings import RagSettings
from sajha.ai.rag import ocr, personal
from sajha.ai.rag.account_sources import (AccessLost, AccountSource, ProviderSession, RemoteFile, SourceClient,
                                          client_for)
from sajha.ai.rag.personal import PersonalDocIndex, PersonalDocsSettings, owner_hash, source_key
from sajha.ai.rag.stores import InProcessVectorStore
from sajha.observability.caller import Caller, reset, set_caller
from tests.ai.conftest import make_gateway


# ── helpers ─────────────────────────────────────────────────────────────

def rag_settings(accounts, ocr_on=False, **kw):
    """RagSettings with ai.rag.accounts and ai.rag.ocr."""
    return RagSettings(accounts=accounts, ocr=ocr_on, index_sajha_docs=False, persist=False, store="memory", **kw)


def provider(pid="google", hosts=("www.googleapis.com", "*.googleapis.com")):
    return types.SimpleNamespace(id=pid, title=pid.title(), api_hosts=list(hosts), api_headers={})


class Token:
    def __init__(self, user, prov, value=None):
        self.provider, self.user_id, self.access_token = prov, user, value or f"tok-{user}"

    def authorization(self):
        return f"Bearer {self.access_token}"


class World:
    """What each user can see at the fake service, and which users have a link."""

    def __init__(self):
        self.files = {}          # user -> {id: (name, version, text)}
        self.linked = set()
        self.lost = set()        # users who lost access to the source
        self.fetches = []        # (user, id)
        self.listings = 0

    def token_for(self, user, pid, scopes):
        if user not in self.linked:
            raise ConnectedAccountRequired(pid, reason="not_connected", user_id=user)
        return Token(user, provider(pid))

    def link_active(self, user, pid):
        return user in self.linked and pid == "google"


def docs(idx, user, query):
    """The documents a user's search returns (the user's own, whatever the query)."""
    return {h["document"] for h in idx.search(user, query, 20)}


def fake_client(world):
    class Fake(SourceClient):
        kind = "google_drive"

        def files(self):
            world.listings += 1
            user = self.session.token.user_id
            if user in world.lost:
                raise AccessLost("Google answered HTTP 404", 404)
            for fid, (name, version, _t) in sorted(world.files.get(user, {}).items()):
                if self._want(name):
                    yield RemoteFile(fid, name, name, version, url=f"https://drive.example/{fid}")

        def fetch(self, f):
            user = self.session.token.user_id
            world.fetches.append((user, f.id))
            return f.name, world.files[user][f.id][2].encode()
    return Fake


SRC = {"name": "drive", "kind": "google_drive", "folder": "root"}


@pytest.fixture
def world(monkeypatch):
    w = World()
    monkeypatch.setattr(personal, "client_for", lambda src, session, n, accept: fake_client(w)(src, session, n, accept))
    return w


def make_index(world, sources=None, store=None, **acct):
    cfg = {"sources": sources or [SRC], **acct}
    return PersonalDocIndex(rag_settings(cfg), make_gateway(), store=store or InProcessVectorStore(None),
                            token_for=world.token_for, link_active=world.link_active, users_for=lambda p: sorted(world.linked))


# ── isolation ───────────────────────────────────────────────────────────

def test_each_user_searches_only_their_own_documents(world):
    world.linked = {"alice", "bob"}
    world.files["alice"] = {"a1": ("plan.md", "v1", "# Plan\n\nThe zebra migration finishes in March."),
                            "s1": ("shared.md", "v1", "# Shared\n\nThe handbook explains the okapi rules.")}
    world.files["bob"] = {"b1": ("notes.txt", "v1", "Bob's secret: the giraffe budget is 42."),
                          "s1": ("shared.md", "v1", "# Shared\n\nThe handbook explains the okapi rules.")}
    idx = make_index(world)
    assert idx.sync_user("alice")["drive"]["indexed"] == 2
    assert idx.sync_user("bob")["drive"]["indexed"] == 2
    hit = idx.search("alice", "zebra migration", 3)
    assert hit and hit[0]["title"] == "Plan" and hit[0]["source"] == "drive" and hit[0]["url"] == "https://drive.example/a1"
    assert "a1" not in docs(idx, "bob", "zebra migration")         # alice's passage is not bob's
    assert "b1" not in docs(idx, "alice", "giraffe budget")         # nor bob's alice's
    assert docs(idx, "bob", "zebra migration") <= {"b1", "s1"}
    assert idx.search("bob", "giraffe budget", 1)[0]["document"] == "b1"
    # a document both can read is held once per user, under each user's own source key
    stored = idx.store.documents()
    assert (source_key("alice", "drive"), "s1") in stored and (source_key("bob", "drive"), "s1") in stored
    assert source_key("alice", "drive") != source_key("bob", "drive") and "alice" not in source_key("alice", "drive")
    # every hit is checked against the caller's keys even if a store ignored the filter
    idx.store.search = lambda v, k, sources=None: [(c, 1.0) for c in idx.store.chunks()]
    idx.store.keyword_search = lambda q, k, sources=None: [(c, 1.0) for c in idx.store.chunks()]
    assert {h["document"] for h in idx.search("bob", "anything at all", 20)} == {"b1", "s1"}
    assert all(h["text"] != world.files["alice"]["a1"][2] for h in idx.search("bob", "zebra", 20))


def test_non_users_and_unlinked_sources_get_nothing(world):
    world.linked = {"alice"}
    world.files["alice"] = {"a1": ("plan.md", "v1", "# Plan\n\nThe zebra plan is written down here.")}
    idx = make_index(world)
    idx.sync_user("alice")
    for who in ("anonymous", "apikey:ci", ""):
        assert idx.search(who, "zebra") == []
        with pytest.raises(PermissionError):
            idx.sync_user(who)
    world.linked = set()                              # link no longer active: its source is not searched
    assert idx.search("alice", "zebra") == []


def test_disconnecting_removes_the_users_passages(world):
    world.linked = {"alice"}
    world.files["alice"] = {"a1": ("plan.md", "v1", "# Plan\n\nThe zebra plan is written down here.")}
    idx = make_index(world)
    idx.sync_user("alice")
    world.linked = set()
    out = idx.sync_user("alice")["drive"]
    assert out["status"] == "needs_connection" and out["removed"] == 1
    assert not any(s.startswith("acct:") for s, _ in idx.store.documents())


def test_losing_access_to_the_source_purges_it(world):
    world.linked = {"alice", "bob"}
    world.files["alice"] = {"a1": ("plan.md", "v1", "# Plan\n\nThe zebra plan is written down here.")}
    world.files["bob"] = {"b1": ("plan.md", "v1", "# Plan\n\nBob keeps a zebra plan of his own.")}
    idx = make_index(world)
    idx.sync_user("alice"), idx.sync_user("bob")
    world.lost = {"alice"}
    out = idx.sync_user("alice")["drive"]
    assert out["status"] == "access_lost" and out["removed"] == 1
    assert idx.search("alice", "zebra") == [] and idx.search("bob", "zebra")      # bob is untouched


# ── incremental sync ────────────────────────────────────────────────────

def test_sync_is_incremental_by_change_token(world):
    world.linked = {"alice"}
    world.files["alice"] = {"a1": ("plan.md", "v1", "# Plan\n\nThe zebra migration."),
                            "a2": ("notes.txt", "v1", "Quarterly notes about okapis."),
                            "a3": ("photo.png", "v1", "not indexed: an image without OCR")}
    idx = make_index(world)
    first = idx.sync_user("alice")["drive"]
    assert (first["documents"], first["indexed"]) == (2, 2)
    world.fetches.clear()
    again = idx.sync_user("alice")["drive"]
    assert (again["unchanged"], again["indexed"], world.fetches) == (2, 0, [])     # nothing downloaded
    world.files["alice"]["a2"] = ("notes.txt", "v2", "Quarterly notes about narwhals.")
    del world.files["alice"]["a1"]
    third = idx.sync_user("alice")["drive"]
    assert (third["indexed"], third["unchanged"], third["removed"]) == (1, 0, 1) and world.fetches == [("alice", "a2")]
    assert idx.search("alice", "narwhals")[0]["document"] == "a2"
    assert all("okapis" not in h["text"] and "zebra" not in h["text"] for h in idx.search("alice", "okapis zebra"))
    assert docs(idx, "alice", "zebra migration") == {"a2"}


def test_the_document_is_embedded_before_the_store_is_written(world):
    """The DB rule: no store transaction is open while fetching or embedding."""
    world.linked = {"alice"}
    world.files["alice"] = {"a1": ("plan.md", "v1", "# Plan\n\n" + "zebra words. " * 400)}
    store = InProcessVectorStore(None)
    got = []
    real = store.replace_document

    def spy(source, document, h, embedder, chunks):
        got.append(type(chunks))
        assert all(len(c.vector) for c in chunks)                  # already embedded
        return real(source, document, h, embedder, chunks)
    store.replace_document = spy
    idx = make_index(world, store=store)
    idx.sync_user("alice")
    assert got == [list]


def test_github_cursor_skips_the_listing_when_the_commit_is_unchanged(world, monkeypatch):
    world.linked = {"alice"}
    world.files["alice"] = {"README.md": ("README.md", "sha1", "# Readme\n\nThe zebra readme is written down here.")}
    head = {"sha": "c1"}

    class WithCursor(fake_client(world)):
        def cursor(self):
            return head["sha"]
    monkeypatch.setattr(personal, "client_for", lambda s, se, n, a: WithCursor(s, se, n, a))
    idx = make_index(world, sources=[{"name": "repo", "kind": "github", "repo": "acme/handbook"}])
    idx.sync_user("alice")
    assert world.listings == 1
    assert idx.sync_user("alice")["repo"]["status"] == "unchanged" and world.listings == 1
    head["sha"] = "c2"
    idx.sync_user("alice")
    assert world.listings == 2


def test_search_starts_a_background_sync_of_stale_sources(world):
    world.linked = {"alice"}
    world.files["alice"] = {"a1": ("plan.md", "v1", "# Plan\n\nThe zebra plan is written down here.")}
    idx = make_index(world)
    assert idx.refresh_in_background("alice") == ["drive"]
    idx._pool.shutdown(wait=True)
    assert idx.search("alice", "zebra")
    assert idx.refresh_in_background("alice") == []               # fresh now
    assert idx.refresh_in_background("bob") == []                  # no link
    assert idx.sync_all() == {"synced": 1}


# ── settings ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,msg", [
    ({"sources": [{"name": "x", "kind": "dropbox"}]}, "one of"),
    ({"sources": [{"name": "x", "kind": "github", "repo": "nope"}]}, "owner/name"),
    ({"sources": [{"name": "x", "kind": "sharepoint"}]}, "drive_id or site_id"),
    ({"sources": [{"name": "x", "kind": "confluence", "cloud_id": "c"}]}, "cloud_id and space_id"),
    ({"sources": [{"name": "x", "kind": "google_drive", "folder": "a'b"}]}, "folder"),
    ({"sources": [SRC, SRC]}, "duplicate"),
    ({"store": "pgvector"}, "shared index"),
    ({"sources": [{"name": "Bad", "kind": "github", "repo": "a/b"}]}, "lower-case"),
    ({"surprise": 1}, "xtra"),
])
def test_bad_settings_are_refused(raw, msg):
    with pytest.raises(Exception, match=msg):
        PersonalDocsSettings.model_validate(raw)


def test_defaults_by_kind():
    s = AccountSource(name="m", kind="sharepoint", site_id="contoso.sharepoint.com,1,2")
    assert (s.provider, s.scopes) == ("microsoft", ["Sites.Read.All"])
    assert AccountSource(name="g", kind="github", repo="a/b").provider == "github"


def test_init_is_off_without_sources_and_reports_bad_config():
    assert personal.init_personal_index(rag_settings({})) is None and personal.personal_error() == ""
    assert personal.init_personal_index(rag_settings({"sources": [{"name": "x", "kind": "?"}]})) is None
    assert "kind" in personal.personal_error()
    personal.set_personal_index(None)


# ── the clients, over HTTP fakes ────────────────────────────────────────

class HTTP:
    def __init__(self, routes):
        self.routes, self.seen = routes, []

    def __call__(self, request):
        self.seen.append(request)
        for (host, path), answer in self.routes.items():
            if request.url.host == host and request.url.path == path:
                return answer(request) if callable(answer) else answer
        return httpx.Response(404, json={"error": {"message": "not found"}})


@pytest.fixture
def transport():
    holder = {}

    def install(routes):
        h = HTTP(routes)
        ahttp.set_transport(httpx.MockTransport(h))
        holder["h"] = h
        return h
    yield install
    ahttp.set_transport(None)


def session(user="alice", pid="google", hosts=("www.googleapis.com",), **kw):
    return ProviderSession(Token(user, provider(pid, hosts)), 1_000_000, **kw)


def accept_all(name):
    return True


def test_google_drive_lists_recursively_exports_docs_and_downloads(transport):
    def listing(req):
        q = req.url.params["q"]
        if q.startswith("'root'"):
            return httpx.Response(200, json={"files": [
                {"id": "f1", "name": "Sub", "mimeType": "application/vnd.google-apps.folder"},
                {"id": "d1", "name": "Policy", "mimeType": "application/vnd.google-apps.document", "version": "7",
                 "webViewLink": "https://docs.google.com/d1"},
                {"id": "x1", "name": "Form", "mimeType": "application/vnd.google-apps.form"}]})
        assert q == "'f1' in parents and trashed = false"
        return httpx.Response(200, json={"files": [{"id": "p1", "name": "a.md", "mimeType": "text/markdown",
                                                    "md5Checksum": "abc", "size": "12"}]})
    h = transport({("www.googleapis.com", "/drive/v3/files"): listing,
                   ("www.googleapis.com", "/drive/v3/files/d1/export"): httpx.Response(200, text="Policy text"),
                   ("www.googleapis.com", "/drive/v3/files/p1"): httpx.Response(200, text="# A\n\nbody")})
    c = client_for(AccountSource(**SRC), session(), 100, accept_all)
    files = list(c.files())
    assert [(f.id, f.name, f.path, f.version) for f in files] == [("d1", "Policy.txt", "Policy", "7"),
                                                                  ("p1", "a.md", "Sub/a.md", "abc")]
    assert c.fetch(files[0]) == ("Policy.txt", b"Policy text")
    assert h.seen[-1].url.params["mimeType"] == "text/plain"
    assert c.fetch(files[1])[1] == b"# A\n\nbody" and h.seen[-1].url.params["alt"] == "media"
    assert all(r.headers["authorization"] == "Bearer tok-alice" for r in h.seen)


def test_no_access_to_the_source_is_access_lost(transport):
    transport({("www.googleapis.com", "/drive/v3/files"): httpx.Response(404, json={"error": {"message": "gone"}})})
    with pytest.raises(AccessLost, match="404"):
        list(client_for(AccountSource(**SRC), session(), 100, accept_all).files())


def test_401_refreshes_once_and_retries(transport):
    calls = []

    def listing(req):
        calls.append(req.headers["authorization"])
        if req.headers["authorization"] == "Bearer old":
            return httpx.Response(401)
        return httpx.Response(200, json={"files": []})
    transport({("www.googleapis.com", "/drive/v3/files"): listing})
    s = ProviderSession(Token("alice", provider(), "old"), 1000,
                        refresh=lambda t: Token("alice", t.provider, "new"))
    assert list(client_for(AccountSource(**SRC), s, 10, accept_all).files()) == []
    assert calls == ["Bearer old", "Bearer new"]
    rejected = []
    transport({("www.googleapis.com", "/drive/v3/files"): httpx.Response(401)})
    s = ProviderSession(Token("alice", provider(), "old"), 1000, refresh=lambda t: t, reject=rejected.append)
    with pytest.raises(Exception, match="rejected"):
        list(client_for(AccountSource(**SRC), s, 10, accept_all).files())
    assert len(rejected) == 1


def test_the_token_never_goes_to_another_host():
    s = session()
    with pytest.raises(PermissionError, match="not one of the hosts"):
        s.get("https://evil.example/x")


def test_graph_follows_the_download_redirect_without_the_token(transport):
    base = "/v1.0/drives/lib1"
    transport({("graph.microsoft.com", f"{base}/root:/Policies:/children"): httpx.Response(200, json={"value": [
                   {"id": "i1", "name": "travel.md", "file": {}, "cTag": "c1", "webUrl": "https://sp/x"},
                   {"id": "f2", "name": "Old", "folder": {}}],
                   "@odata.nextLink": "https://graph.microsoft.com/v1.0/drives/lib1/root:/Policies:/children2"}),
               ("graph.microsoft.com", f"{base}/root:/Policies:/children2"): httpx.Response(200, json={"value": []}),
               ("graph.microsoft.com", f"{base}/items/f2/children"): httpx.Response(200, json={"value": [
                   {"id": "i2", "name": "old.pdf", "file": {}, "eTag": "e2"}]}),
               ("graph.microsoft.com", f"{base}/items/i1/content"):
                   httpx.Response(302, headers={"location": "https://contoso.sharepoint.com/dl?sig=1"})})
    downloads = []
    s = session(pid="microsoft", hosts=("graph.microsoft.com",),
                download=lambda url, limit: downloads.append(url) or b"# Travel\n\nfly economy")
    src = AccountSource(name="sp", kind="sharepoint", drive_id="lib1", folder="Policies")
    c = client_for(src, s, 100, lambda n: n.endswith((".md", ".pdf")))
    files = list(c.files())
    assert [(f.id, f.path, f.version) for f in files] == [("i1", "Policies/travel.md", "c1"),
                                                          ("i2", "Policies/Old/old.pdf", "e2")]
    assert c.fetch(files[0]) == ("travel.md", b"# Travel\n\nfly economy")
    assert downloads == ["https://contoso.sharepoint.com/dl?sig=1"]


def test_github_lists_the_tree_under_a_path_and_reads_blobs(transport):
    blob = base64.b64encode(b"# Guide\n\nzebra").decode()
    transport({("api.github.com", "/repos/acme/kb"): httpx.Response(200, json={"default_branch": "main"}),
               ("api.github.com", "/repos/acme/kb/commits/main"): httpx.Response(200, json={"sha": "c0ffee"}),
               ("api.github.com", "/repos/acme/kb/git/trees/c0ffee"): httpx.Response(200, json={"tree": [
                   {"type": "blob", "path": "docs/guide.md", "sha": "b1", "size": 10},
                   {"type": "blob", "path": "docs/img.bin", "sha": "b2"},
                   {"type": "tree", "path": "docs/sub"},
                   {"type": "blob", "path": "src/app.md", "sha": "b3"}]}),
               ("api.github.com", "/repos/acme/kb/git/blobs/b1"): httpx.Response(200, json={
                   "encoding": "base64", "content": blob, "size": 14})})
    src = AccountSource(name="kb", kind="github", repo="acme/kb", path="docs", pattern="*.md")
    c = client_for(src, session(pid="github", hosts=("api.github.com",)), 100, lambda n: n.endswith(".md"))
    assert c.cursor() == "c0ffee"
    files = list(c.files())
    assert [(f.id, f.version, f.url) for f in files] == [("docs/guide.md", "b1",
                                                          "https://github.com/acme/kb/blob/main/docs/guide.md")]
    assert c.fetch(files[0]) == ("guide.md", b"# Guide\n\nzebra")


def test_confluence_pages_become_html_documents(transport):
    site = "/ex/confluence/cl1/wiki/api/v2"
    transport({("api.atlassian.com", f"{site}/spaces/42/pages"): httpx.Response(200, json={
                   "results": [{"id": "p1", "title": "On/boarding", "status": "current", "version": {"number": 3},
                                "_links": {"webui": "/spaces/HR/pages/p1"}},
                               {"id": "p2", "title": "Draft", "status": "draft"}],
                   "_links": {"base": "https://acme.atlassian.net/wiki"}}),
               ("api.atlassian.com", f"{site}/pages/p1"): httpx.Response(200, json={
                   "title": "On/boarding", "body": {"storage": {"value": "<p>Badge &amp; laptop</p>"}}})})
    src = AccountSource(name="hr", kind="confluence", cloud_id="cl1", space_id="42")
    c = client_for(src, session(pid="atlassian", hosts=("api.atlassian.com",)), 100, accept_all)
    files = list(c.files())
    assert [(f.id, f.name, f.version, f.url) for f in files] == [
        ("p1", "On-boarding.html", "3", "https://acme.atlassian.net/wiki/spaces/HR/pages/p1")]
    name, data = c.fetch(files[0])
    assert name == "On-boarding.html" and b"<p>Badge &amp; laptop</p>" in data


def test_end_to_end_with_the_real_accounts_service(tmp_path, transport):
    """Tokens come from the vault through ConnectedAccountsService.resolve, per user."""
    from sqlalchemy import create_engine
    from sajha.accounts.providers import ProviderRegistry, set_registry
    from sajha.accounts.service import ConnectedAccountsService, set_service
    from sajha.accounts.settings import AccountsSettings, set_accounts_settings
    from sajha.accounts.vault import LocalKeyProvider, TokenVault, set_vault
    from sajha.core.state.memory import MemoryStateStore
    set_accounts_settings(AccountsSettings(public_url="https://sajha.test"))
    reg = ProviderRegistry.load(raw={"google": {"client_id": "cid", "token_url": "https://oauth2.googleapis.com/token"}},
                                use_env=False)
    set_registry(reg)
    vault = TokenVault(engine=create_engine(f"sqlite:///{tmp_path / 'v.db'}"),
                       key_provider=LocalKeyProvider("k" * 40))
    set_vault(vault)
    set_service(ConnectedAccountsService(reg, vault, MemoryStateStore("t:")))
    try:
        scope = ["https://www.googleapis.com/auth/drive.readonly"]
        vault.save("alice", "google", {"access_token": "tok-alice"}, scopes=scope, expires_at=None)
        vault.save("bob", "google", {"access_token": "tok-bob"}, scopes=scope, expires_at=None)

        def listing(req):
            who = req.headers["authorization"].split("-", 1)[1]
            return httpx.Response(200, json={"files": [{"id": f"{who}1", "name": f"{who}.md", "mimeType": "text/markdown",
                                                        "md5Checksum": "m"}]})

        def content(req):
            who = req.headers["authorization"].split("-", 1)[1]
            return httpx.Response(200, text=f"# {who}\n\nonly {who} has the {who}word")
        routes = {("www.googleapis.com", "/drive/v3/files"): listing}
        for who in ("alice", "bob"):
            routes[("www.googleapis.com", f"/drive/v3/files/{who}1")] = content
        transport(routes)
        idx = PersonalDocIndex(rag_settings({"sources": [SRC]}), make_gateway(), store=InProcessVectorStore(None))
        assert idx.sync_user("alice")["drive"]["indexed"] == 1 and idx.sync_user("bob")["drive"]["indexed"] == 1
        assert idx.search("alice", "aliceword")[0]["document"] == "alice1"
        assert docs(idx, "alice", "bobword") == {"alice1"} and docs(idx, "bob", "aliceword") == {"bob1"}
        assert idx.sync_user("carol")["drive"]["status"] == "needs_connection"
        assert idx.status("bob")["sources"][0]["documents"] == 1 and idx.status("bob")["sources"][0]["linked"]
    finally:
        set_service(None), set_vault(None), set_registry(None), set_accounts_settings(None)


# ── OCR ─────────────────────────────────────────────────────────────────

def _scanned_pdf() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (60, 30), "white").save(buf, "PDF")
    return buf.getvalue()


def _png() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, "PNG")
    return buf.getvalue()


def test_ocr_off_or_missing_is_refused_with_a_clear_message(monkeypatch):
    pytest.importorskip("pypdf")
    monkeypatch.setattr(ocr, "engine", lambda: None)
    with pytest.raises(ValueError, match="set ai.rag.ocr to true"):
        ocr.extract_document("scan.pdf", _scanned_pdf(), ocr=False)
    with pytest.raises(ocr.OCRUnavailable, match="pip install rapidocr-onnxruntime"):
        ocr.extract_document("scan.pdf", _scanned_pdf(), ocr=True)
    with pytest.raises(ValueError, match="is an image"):
        ocr.extract_document("photo.png", _png(), ocr=False)
    assert ocr.available()["installed"] is False and "pytesseract" in ocr.available()["hint"]


def test_ocr_reads_scanned_pdfs_and_images_when_an_engine_is_there(world):
    pytest.importorskip("pypdf")
    ocr.set_engine(lambda data: "Scanned invoice number 7781")
    try:
        assert ocr.extract_document("scan.pdf", _scanned_pdf(), ocr=True)[0] == "Scanned invoice number 7781"
        world.linked = {"alice"}
        world.files["alice"] = {"i1": ("receipt.png", "v1", "")}
        world_png = _png()

        idx = PersonalDocIndex(rag_settings({"sources": [SRC]}, ocr_on=True), make_gateway(),
                               store=InProcessVectorStore(None), token_for=world.token_for,
                               link_active=world.link_active)
        orig = idx._text
        idx._text = lambda name, data: orig(name, world_png)
        assert idx.sync_user("alice")["drive"]["indexed"] == 1
        assert idx.search("alice", "invoice 7781")[0]["document"] == "i1"
    finally:
        ocr.set_engine(None)


# ── the tool ────────────────────────────────────────────────────────────

def test_the_tool_searches_as_the_caller(world):
    from sajha.ai.rag.personal_tool import SajhaSearchMyDocsTool
    world.linked = {"alice"}
    world.files["alice"] = {"a1": ("plan.md", "v1", "# Plan\n\nThe zebra migration finishes in March.")}
    idx = make_index(world, sources=[SRC, {"name": "repo", "kind": "github", "repo": "acme/kb"}])
    idx.sync_user("alice", ["drive"])
    tool = SajhaSearchMyDocsTool()
    personal.set_personal_index(None)
    assert tool.enabled is False
    personal.set_personal_index(idx)
    try:
        assert tool.enabled is True
        t = set_caller(Caller("alice"))
        try:
            out = tool.execute({"query": "zebra migration", "source": "drive"})
            assert out["count"] == 1 and out["results"][0]["source"] == "drive" and out["not_linked"] == []
            out = tool.execute({"query": "zebra"})
            assert out["not_linked"] == [{"source": "repo", "provider": "github",
                                          "connect": "/account/connections?connect=github"}]
            with pytest.raises(ValueError, match="no such source"):
                tool.execute({"query": "x", "source": "nope"})
        finally:
            reset(t)
        t = set_caller(Caller("bob"))
        try:
            assert tool.execute({"query": "zebra migration"})["count"] == 0
        finally:
            reset(t)
        t = set_caller(Caller("apikey:ci"))
        try:
            with pytest.raises(PermissionError):
                tool.execute({"query": "zebra"})
        finally:
            reset(t)
        t = set_caller(Caller("alice", auth_type="apikey"))      # a key bound to alice: still nothing
        try:
            with pytest.raises(PermissionError):
                tool.execute({"query": "zebra"})
        finally:
            reset(t)
    finally:
        personal.set_personal_index(None)


def test_owner_hash_is_stable_and_not_the_user_id():
    assert owner_hash("alice") == owner_hash("alice") != owner_hash("bob")
    assert len(owner_hash("alice")) == 24 and "alice" not in owner_hash("alice")
    assert json.dumps(source_key("a", "drive")).count(":") == 2


def test_isolation_holds_on_the_sqlite_vec_store(world, tmp_path):
    from sajha.ai.rag.sqlite_vec import SqliteVecStore
    if SqliteVecStore.probe({}):
        pytest.skip("sqlite-vec is not usable here")
    store = SqliteVecStore(str(tmp_path / "personal.db"))
    world.linked = {"alice", "bob"}
    world.files["alice"] = {"a1": ("plan.md", "v1", "# Plan\n\nThe zebra migration finishes in March.")}
    world.files["bob"] = {"b1": ("notes.md", "v1", "# Notes\n\nBob's giraffe budget is forty two.")}
    idx = make_index(world, store=store)
    try:
        idx.sync_user("alice"), idx.sync_user("bob")
        assert docs(idx, "alice", "giraffe budget zebra") == {"a1"}
        assert docs(idx, "bob", "giraffe budget zebra") == {"b1"}
        world.files["alice"] = {}
        assert idx.sync_user("alice")["drive"]["removed"] == 1
        assert docs(idx, "alice", "zebra") == set() and docs(idx, "bob", "giraffe") == {"b1"}
    finally:
        idx.close()


def test_the_personal_store_never_shares_the_shared_index_file(world):
    with pytest.raises(ValueError, match="must differ"):
        PersonalDocIndex(rag_settings({"sources": [SRC], "store": "sqlite_vec", "path": "data/rag/vectors.db"}),
                         make_gateway(), token_for=world.token_for, link_active=world.link_active)


def test_my_docs_routes(world):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sajha.auth import AuthContext, require_auth
    from sajha.routes.ai_routes import router
    app = FastAPI()
    app.include_router(router)
    who = {"u": AuthContext(authenticated=True, user_id="alice", roles=["user"], is_admin=False)}
    app.dependency_overrides[require_auth] = lambda: who["u"]
    c = TestClient(app)
    personal.set_personal_index(None)
    assert c.get("/api/ai/docs/mine").status_code == 503
    world.linked = {"alice"}
    world.files["alice"] = {"a1": ("plan.md", "v1", "# Plan\n\nThe zebra migration finishes in March.")}
    idx = make_index(world)
    personal.set_personal_index(idx)
    try:
        assert c.post("/api/ai/docs/mine/sync", json={"sources": ["nope"]}).status_code == 400
        r = c.post("/api/ai/docs/mine/sync", json={})
        assert r.status_code == 202 and r.json() == {"syncing": ["drive"]}
        idx._pool.shutdown(wait=True)
        status = c.get("/api/ai/docs/mine").json()
        assert status["sources"][0]["documents"] == 1 and status["sources"][0]["linked"] is True
        body = c.post("/api/ai/docs/mine/search", json={"query": "zebra migration"}).json()
        assert body["count"] == 1 and body["results"][0]["document"] == "a1"
        assert c.post("/api/ai/docs/mine/search", json={}).status_code == 400
        assert c.post("/api/ai/docs/mine/search", json={"query": "x", "source": "nope"}).status_code == 400
        who["u"] = AuthContext(authenticated=True, user_id="bob", roles=["user"], is_admin=False)
        assert all(h["document"] != "a1" for h in c.post("/api/ai/docs/mine/search", json={"query": "zebra"}).json()["results"])
        who["u"] = AuthContext(authenticated=True, user_id="apikey:ci", roles=["api_consumer"], is_admin=False)
        assert c.get("/api/ai/docs/mine").status_code == 403
        # a key bound to a real user gets nothing either (Intelligence Layer: keys have no connected accounts)
        who["u"] = AuthContext(authenticated=True, user_id="alice", roles=["user"], is_admin=False, auth_type="apikey")
        assert c.get("/api/ai/docs/mine").status_code == 403
        assert c.post("/api/ai/docs/mine/search", json={"query": "zebra"}).status_code == 403
    finally:
        personal.set_personal_index(None)


def test_my_docs_post_routes_need_the_csrf_token_with_a_session_cookie(world):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sajha.auth import AuthContext, require_auth
    from sajha.routes.ai_routes import router
    from sajha.routes.accounts_routes import csrf_token
    app = FastAPI()
    app.include_router(router)
    who = {"u": AuthContext(authenticated=True, user_id="alice", roles=["user"], is_admin=False, auth_type="session")}
    app.dependency_overrides[require_auth] = lambda: who["u"]
    c = TestClient(app)
    world.linked = {"alice"}
    world.files["alice"] = {"a1": ("plan.md", "v1", "# Plan\n\nThe zebra migration finishes in March.")}
    idx = make_index(world)
    personal.set_personal_index(idx)
    try:
        c.cookies.set("sajha_token", "cookie-value")
        for path, body in (("/api/ai/docs/mine/sync", {}), ("/api/ai/docs/mine/search", {"query": "zebra"})):
            assert c.post(path, json=body).status_code == 403
            assert c.post(path, json=body, headers={"X-CSRF-Token": "wrong"}).status_code == 403

        class _Req:
            cookies = {"sajha_token": "cookie-value"}
        token = csrf_token(_Req(), who["u"])
        assert c.post("/api/ai/docs/mine/sync", json={}, headers={"X-CSRF-Token": token}).status_code == 202
        idx._pool.shutdown(wait=True)
        assert c.post("/api/ai/docs/mine/search", json={"query": "zebra"},
                      headers={"X-CSRF-Token": token}).status_code == 200
        who["u"] = AuthContext(authenticated=True, user_id="alice", roles=["user"], is_admin=False, auth_type="jwt")
        assert c.post("/api/ai/docs/mine/search", json={"query": "zebra"}).status_code == 200   # a bearer JWT
    finally:
        personal.set_personal_index(None)
