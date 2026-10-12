"""
SAJHA MCP Server — RAG: document sources read through a user's connected account.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Each ``ai.rag.accounts.sources`` entry names a kind of source and where it is; a client of
that kind lists the files the *user* can see there and fetches one file at a time, always
with that user's own linked token (sajha/accounts/), so the index built from it holds only
what the user may read. The personal index (personal.py) does the indexing.

=================  ===========  ========================================================
kind               provider     where (fields of the source)
=================  ===========  ========================================================
``google_drive``   ``google``   ``folder``: a folder id, or ``root`` (My Drive); Google
                                Docs, Sheets and Slides are exported as text
``onedrive``       ``microsoft`` ``folder``: a path under the user's OneDrive root
``sharepoint``     ``microsoft`` ``drive_id`` (a document library) or ``site_id`` (its
                                default library), ``folder``: a path in it
``github``         ``github``   ``repo`` (owner/name), ``ref`` (default branch when
                                empty), ``path``: a folder prefix
``confluence``     ``atlassian`` ``cloud_id`` and ``space_id``; each page is a document
=================  ===========  ========================================================

Every file carries a *change token* (``version``): Drive's md5 or version, Graph's cTag,
the git blob sha, the Confluence page version. The index compares it with what it stored,
so an unchanged file is never downloaded again; a file no longer listed is deleted. A
GitHub source also has a cursor (the commit the ref points to): an unchanged commit skips
the listing altogether.

Requests go through the connected-accounts HTTP client (``sajha.accounts.http.client``,
which tests replace with an in-process transport) and only to the provider's ``api_hosts``
(``check_api_url``). A Graph download is a redirect to a pre-authenticated URL on another
host: it is fetched *without* the token, through the outbound fetch guard
(sajha/core/outbound.py). HTTP 401 refreshes the token once; a second 401 marks the link for
reconnection. HTTP 403 or 404 on the source itself means the user lost access to it
(:class:`AccessLost`), and the index removes that user's passages from it.
"""

from __future__ import annotations

import base64
import fnmatch
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Type
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

KINDS = ("google_drive", "onedrive", "sharepoint", "github", "confluence")
DEFAULT_PROVIDER = {"google_drive": "google", "onedrive": "microsoft", "sharepoint": "microsoft",
                    "github": "github", "confluence": "atlassian"}
DEFAULT_SCOPES = {"google_drive": ["https://www.googleapis.com/auth/drive.readonly"],
                  "onedrive": ["Files.Read"], "sharepoint": ["Sites.Read.All"],
                  "github": [], "confluence": []}
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_ID = re.compile(r"^[A-Za-z0-9_.!,~:-]{1,256}$")
MAX_FOLDERS = 2000                       # folders visited per listing (Drive, Graph)


class AccountSource(BaseModel):
    """One ``ai.rag.accounts.sources`` entry."""
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: str
    provider: str = ""                    # the connected-account provider id; default by kind
    title: str = ""
    pattern: str = "*"                    # fnmatch on the file name (case-insensitive)
    folder: str = ""                      # Drive: folder id or root; OneDrive/SharePoint: a path
    recursive: bool = True
    drive_id: str = ""                    # SharePoint document library
    site_id: str = ""                     # SharePoint site (its default library)
    repo: str = ""                        # GitHub owner/name
    ref: str = ""                         # GitHub branch, tag or commit; empty: the default branch
    path: str = ""                        # GitHub folder prefix
    cloud_id: str = ""                    # Confluence (Atlassian cloud id)
    space_id: str = ""                    # Confluence space id
    scopes: Optional[List[str]] = None    # scopes the link must grant; default by kind
    max_files: int = 0                    # 0: ai.rag.accounts.max_files_per_source

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        if not _NAME.match(v or ""):
            raise ValueError("a lower-case letter, then lower-case letters, digits or _ (40 at most)")
        return v

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in KINDS:
            raise ValueError(f"one of {', '.join(KINDS)}")
        return v

    @model_validator(mode="after")
    def _where(self):
        k = self.kind
        if not self.provider:
            self.provider = DEFAULT_PROVIDER[k]
        if self.scopes is None:
            self.scopes = list(DEFAULT_SCOPES[k])
        if k == "github" and not _REPO.match(self.repo or ""):
            raise ValueError(f"source {self.name}: repo must be owner/name")
        if k == "sharepoint" and not (self.drive_id or self.site_id):
            raise ValueError(f"source {self.name}: a sharepoint source needs drive_id or site_id")
        if k == "confluence" and not (self.cloud_id and self.space_id):
            raise ValueError(f"source {self.name}: a confluence source needs cloud_id and space_id")
        if k == "google_drive" and self.folder and self.folder != "root" and not _ID.match(self.folder):
            raise ValueError(f"source {self.name}: folder must be a Drive folder id or root")
        for f in ("drive_id", "site_id", "cloud_id", "space_id"):
            v = getattr(self, f)
            if v and not _ID.match(v):
                raise ValueError(f"source {self.name}: {f} has characters an id does not have")
        if ".." in (self.folder or "").split("/") or ".." in (self.path or "").split("/"):
            raise ValueError(f"source {self.name}: '..' is not allowed in a path")
        return self


@dataclass
class RemoteFile:
    id: str                               # the provider's id (unique within the source)
    name: str                             # file name with its extension (picks the reader)
    path: str                             # where it is within the source (shown to the user)
    version: str                          # the change token
    size: int = 0
    url: str = ""                         # a link to open it at the provider
    extra: Dict[str, Any] = field(default_factory=dict)


class SourceError(RuntimeError):
    """The provider answered with an error (the message never carries the token)."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class AccessLost(SourceError):
    """The user can no longer read the source itself (HTTP 403/404 on it)."""


class FileTooLarge(SourceError):
    """A file is larger than ai.rag.accounts.max_file_bytes."""


def matches(name: str, pattern: str) -> bool:
    return fnmatch.fnmatch((name or "").lower(), (pattern or "*").lower())


# ── HTTP as the user ────────────────────────────────────────────────────

class ProviderSession:
    """Requests to one provider with one user's token: api_hosts only, refresh once on 401."""

    def __init__(self, token, max_bytes: int, refresh: Optional[Callable] = None,
                 reject: Optional[Callable] = None, download: Optional[Callable] = None):
        self.token = token
        self.max_bytes = int(max_bytes)
        self._refresh = refresh
        self._reject = reject
        self._download = download

    @property
    def provider(self):
        return self.token.provider

    def _service(self):
        from sajha.accounts.service import get_service
        return get_service()

    def get(self, url: str, params: Optional[Dict[str, Any]] = None,
            headers: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, str], bytes]:
        """``(status, headers, body)``; 401 is retried once after a refresh, then refused. A
        redirect is returned as it is (no body), never followed with the token."""
        from sajha.accounts import http as ahttp
        p = self.provider
        ahttp.check_api_url(p, url)
        for attempt in range(2):
            hdrs = {"Accept": "application/json", **(p.api_headers or {}), **(headers or {}),
                    "Authorization": self.token.authorization()}
            with ahttp.client() as c:
                with c.stream("GET", url, params=params or None, headers=hdrs) as r:
                    status, rh = r.status_code, {k.lower(): v for k, v in r.headers.items()}
                    body = b"" if status == 401 or (300 <= status < 400) else self._read(r)
            if status != 401:
                return status, rh, body
            if attempt == 0:
                self.token = (self._refresh or self._service().refresh_after_rejection)(self.token)
                continue
            if self._reject is not None:
                self._reject(self.token)
            else:
                svc = self._service()
                svc.mark_rejected(self.token)
                raise svc.required(p.id, "reauth_required", self.token.user_id)
            raise SourceError(f"{p.title} rejected the linked token", 401)
        raise AssertionError("unreachable")

    def _read(self, r) -> bytes:
        size = r.headers.get("content-length")
        if size and size.isdigit() and int(size) > self.max_bytes:
            raise FileTooLarge(f"larger than {self.max_bytes} bytes")
        buf = bytearray()
        for part in r.iter_bytes():
            buf += part
            if len(buf) > self.max_bytes:
                raise FileTooLarge(f"larger than {self.max_bytes} bytes")
        return bytes(buf)

    def json(self, url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None,
             source_level: bool = False) -> Any:
        """The JSON at ``url``. 403/404 raise AccessLost when ``source_level`` (the source
        itself), SourceError otherwise."""
        import json as _json
        status, _h, body = self.get(url, params, headers)
        self._check(status, body, source_level)
        try:
            return _json.loads(body.decode("utf-8")) if body else {}
        except ValueError:
            raise SourceError(f"{self.provider.title}: the answer is not JSON", status) from None

    def _check(self, status: int, body: bytes, source_level: bool) -> None:
        if status < 400:
            return
        text = body[:300].decode("utf-8", "replace") if body else ""
        msg = f"{self.provider.title} answered HTTP {status}" + (f": {_short(text)}" if text else "")
        if status in (403, 404) and source_level:
            raise AccessLost(msg, status)
        raise SourceError(msg, status)

    def bytes(self, url: str, params: Optional[Dict[str, Any]] = None,
              headers: Optional[Dict[str, str]] = None) -> bytes:
        status, h, body = self.get(url, params, headers)
        if 300 <= status < 400 and h.get("location"):
            return self.download(h["location"])
        self._check(status, body, False)
        return body

    def download(self, url: str) -> bytes:
        """A pre-authenticated URL the provider redirected to: no token, through the outbound guard."""
        if not (url or "").lower().startswith("https://"):
            raise SourceError("a download link must be https")
        if self._download is not None:
            return self._download(url, self.max_bytes)
        from sajha.core import outbound
        try:
            r = outbound.request("GET", url, max_bytes=self.max_bytes + 1)
        except outbound.FetchError as e:
            raise SourceError(f"download failed: {e}") from None
        if r.status_code >= 400:
            raise SourceError(f"download failed: HTTP {r.status_code}", r.status_code)
        if len(r.content) > self.max_bytes:
            raise FileTooLarge(f"larger than {self.max_bytes} bytes")
        return r.content


def _short(text: str) -> str:
    try:
        import json as _json
        body = _json.loads(text)
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                return str(err.get("message") or err.get("code") or "")[:200]
            return str(body.get("message") or err or "")[:200]
    except ValueError:
        pass
    return text[:200]


# ── clients ─────────────────────────────────────────────────────────────

class SourceClient:
    """Lists and fetches the files of one source as one user."""

    kind = ""

    def __init__(self, source: AccountSource, session: ProviderSession, max_files: int,
                 accept: Callable[[str], bool]):
        self.source = source
        self.session = session
        self.max_files = max(1, int(max_files))
        self.accept = accept               # name -> index this file type?
        self.truncated = False

    def cursor(self) -> str:
        """A cheap token that changes whenever anything in the source may have ('' = none)."""
        return ""

    def files(self) -> Iterator[RemoteFile]:
        raise NotImplementedError

    def fetch(self, f: RemoteFile) -> Tuple[str, bytes]:
        """``(name to read it as, bytes)``."""
        raise NotImplementedError

    def _want(self, name: str) -> bool:
        return matches(name, self.source.pattern) and self.accept(name)


DRIVE = "https://www.googleapis.com/drive/v3"
_DRIVE_FOLDER = "application/vnd.google-apps.folder"
#: Google's own formats, exported as text (the export suffix decides the reader)
_DRIVE_EXPORT = {"application/vnd.google-apps.document": ("text/plain", ".txt"),
                 "application/vnd.google-apps.presentation": ("text/plain", ".txt"),
                 "application/vnd.google-apps.spreadsheet": ("text/csv", ".txt")}


class GoogleDriveClient(SourceClient):
    kind = "google_drive"

    def files(self):
        root = self.source.folder or "root"
        queue: List[Tuple[str, str]] = [(root, "")]
        seen_folders, n = 0, 0
        first = True
        while queue:
            fid, prefix = queue.pop(0)
            seen_folders += 1
            if seen_folders > MAX_FOLDERS:
                self.truncated = True
                return
            token = None
            while True:
                params = {"q": f"'{fid}' in parents and trashed = false", "pageSize": 200,
                          "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,md5Checksum,version,size,"
                                    "webViewLink)",
                          "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
                if token:
                    params["pageToken"] = token
                data = self.session.json(f"{DRIVE}/files", params, source_level=first)
                first = False
                for it in data.get("files") or []:
                    mime, name, iid = str(it.get("mimeType") or ""), str(it.get("name") or ""), str(it.get("id") or "")
                    if not iid:
                        continue
                    if mime == _DRIVE_FOLDER:
                        if self.source.recursive:
                            queue.append((iid, f"{prefix}{name}/"))
                        continue
                    export = _DRIVE_EXPORT.get(mime)
                    read_as = name + export[1] if export else name
                    if mime.startswith("application/vnd.google-apps.") and not export:
                        continue                       # forms, drawings, shortcuts: no text to read
                    if not self._want(read_as):
                        continue
                    n += 1
                    if n > self.max_files:
                        self.truncated = True
                        return
                    yield RemoteFile(iid, read_as, prefix + name,
                                     str(it.get("md5Checksum") or it.get("version") or it.get("modifiedTime") or ""),
                                     int(it.get("size") or 0), str(it.get("webViewLink") or ""),
                                     {"export": export[0] if export else ""})
                token = data.get("nextPageToken")
                if not token:
                    break

    def fetch(self, f):
        if f.extra.get("export"):
            return f.name, self.session.bytes(f"{DRIVE}/files/{quote(f.id, safe='')}/export",
                                              {"mimeType": f.extra["export"]})
        return f.name, self.session.bytes(f"{DRIVE}/files/{quote(f.id, safe='')}", {"alt": "media",
                                                                                     "supportsAllDrives": "true"})


GRAPH = "https://graph.microsoft.com/v1.0"


class GraphDriveClient(SourceClient):
    """OneDrive (the user's own drive) and SharePoint document libraries."""
    kind = "onedrive"

    def _base(self) -> str:
        s = self.source
        if s.kind == "sharepoint":
            return f"{GRAPH}/drives/{quote(s.drive_id, safe='')}" if s.drive_id else \
                f"{GRAPH}/sites/{quote(s.site_id, safe='')}/drive"
        return f"{GRAPH}/me/drive"

    def files(self):
        base = self._base()
        folder = (self.source.folder or "").strip("/")
        start = f"{base}/root:/{quote(folder)}:/children" if folder else f"{base}/root/children"
        queue: List[Tuple[str, str]] = [(start, folder + "/" if folder else "")]
        seen_folders, n, first = 0, 0, True
        while queue:
            url, prefix = queue.pop(0)
            seen_folders += 1
            if seen_folders > MAX_FOLDERS:
                self.truncated = True
                return
            params: Optional[Dict[str, Any]] = {"$top": 200}
            while url:
                data = self.session.json(url, params, source_level=first)
                first, params = False, None
                for it in data.get("value") or []:
                    name, iid = str(it.get("name") or ""), str(it.get("id") or "")
                    if not iid:
                        continue
                    if "folder" in it:
                        if self.source.recursive:
                            queue.append((f"{base}/items/{quote(iid, safe='')}/children", f"{prefix}{name}/"))
                        continue
                    if "file" not in it or not self._want(name):
                        continue
                    n += 1
                    if n > self.max_files:
                        self.truncated = True
                        return
                    yield RemoteFile(iid, name, prefix + name,
                                     str(it.get("cTag") or it.get("eTag") or it.get("lastModifiedDateTime") or ""),
                                     int(it.get("size") or 0), str(it.get("webUrl") or ""))
                url = data.get("@odata.nextLink") or ""

    def fetch(self, f):
        return f.name, self.session.bytes(f"{self._base()}/items/{quote(f.id, safe='')}/content")


GITHUB = "https://api.github.com"


class GitHubClient(SourceClient):
    kind = "github"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._commit = ""
        self._ref = ""

    def _resolve(self) -> None:
        if self._commit:
            return
        repo = self.source.repo
        ref = self.source.ref
        if not ref:
            ref = str(self.session.json(f"{GITHUB}/repos/{repo}", source_level=True).get("default_branch") or "main")
        data = self.session.json(f"{GITHUB}/repos/{repo}/commits/{quote(ref, safe='')}", source_level=True)
        self._ref, self._commit = ref, str(data.get("sha") or "")
        if not self._commit:
            raise SourceError(f"GitHub: {repo}@{ref} has no commit")

    def cursor(self):
        self._resolve()
        return self._commit

    def files(self):
        self._resolve()
        repo = self.source.repo
        data = self.session.json(f"{GITHUB}/repos/{repo}/git/trees/{self._commit}", {"recursive": "1"},
                                 source_level=True)
        self.truncated = bool(data.get("truncated"))
        prefix = (self.source.path or "").strip("/")
        n = 0
        for it in data.get("tree") or []:
            if it.get("type") != "blob":
                continue
            path = str(it.get("path") or "")
            if prefix and not (path == prefix or path.startswith(prefix + "/")):
                continue
            if not self.source.recursive and "/" in path[len(prefix):].strip("/"):
                continue
            name = path.rsplit("/", 1)[-1]
            if not self._want(name):
                continue
            n += 1
            if n > self.max_files:
                self.truncated = True
                return
            yield RemoteFile(path, name, path, str(it.get("sha") or ""), int(it.get("size") or 0),
                             f"https://github.com/{repo}/blob/{quote(self._ref)}/{quote(path)}",
                             {"sha": str(it.get("sha") or "")})

    def fetch(self, f):
        data = self.session.json(f"{GITHUB}/repos/{self.source.repo}/git/blobs/{f.extra['sha']}")
        if int(data.get("size") or 0) > self.session.max_bytes:
            raise FileTooLarge(f"larger than {self.session.max_bytes} bytes")
        if data.get("encoding") != "base64":
            raise SourceError("GitHub: the blob is not base64-encoded")
        return f.name, base64.b64decode(str(data.get("content") or ""))


class ConfluenceClient(SourceClient):
    kind = "confluence"

    def _site(self) -> str:
        return f"https://api.atlassian.com/ex/confluence/{quote(self.source.cloud_id, safe='')}"

    def files(self):
        site = self._site()
        url = f"{site}/wiki/api/v2/spaces/{quote(self.source.space_id, safe='')}/pages"
        params: Optional[Dict[str, Any]] = {"limit": 100}
        n, first = 0, True
        while url:
            data = self.session.json(url, params, source_level=first)
            first, params = False, None
            base = str((data.get("_links") or {}).get("base") or "")
            for it in data.get("results") or []:
                pid, title = str(it.get("id") or ""), str(it.get("title") or "")
                if not pid or str(it.get("status") or "current") != "current":
                    continue
                name = re.sub(r"[/\\]+", "-", title or pid) + ".html"
                if not self._want(name):
                    continue
                n += 1
                if n > self.max_files:
                    self.truncated = True
                    return
                webui = str((it.get("_links") or {}).get("webui") or "")
                yield RemoteFile(pid, name, title or pid, str((it.get("version") or {}).get("number") or ""), 0,
                                 base + webui if webui else "")
            nxt = str((data.get("_links") or {}).get("next") or "")
            url = site + nxt if nxt.startswith("/") else ""

    def fetch(self, f):
        data = self.session.json(f"{self._site()}/wiki/api/v2/pages/{quote(f.id, safe='')}",
                                 {"body-format": "storage"})
        body = str(((data.get("body") or {}).get("storage") or {}).get("value") or "")
        title = str(data.get("title") or f.path)
        html = f"<h1>{_esc(title)}</h1>\n{body}"
        return f.name, html.encode("utf-8")


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


CLIENTS: Dict[str, Type[SourceClient]] = {"google_drive": GoogleDriveClient, "onedrive": GraphDriveClient,
                                          "sharepoint": GraphDriveClient, "github": GitHubClient,
                                          "confluence": ConfluenceClient}


def client_for(source: AccountSource, session: ProviderSession, max_files: int,
               accept: Callable[[str], bool]) -> SourceClient:
    return CLIENTS[source.kind](source, session, max_files, accept)
