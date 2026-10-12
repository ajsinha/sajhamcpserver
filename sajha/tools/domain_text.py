"""
SAJHA MCP Server — domain descriptions: what a tool folder as a whole is for, said once.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

An optional ``<tools dir>/<folder>/domain.txt`` (plain UTF-8 text, read through the storage backend
like the tool configs beside it) is appended to the description of every tool filed in that folder
wherever a description is served: the tool's own description, a blank line, then the domain text.
The text is never written into a tool's JSON; the registry's configs and the editors keep the tool's
own description only. Design: docs/architecture/Architecture.md §5 ("Domain descriptions").

- At most ``tools.domain_description_max_chars`` (600) characters after trimming. A longer file is
  refused, never truncated, with the warning notice ``tools.domain_description:<folder>``; the
  folder's tools are served without it until the file is fixed.
- A ``domain.txt`` at the root of the tools directory is ignored with the info notice
  ``tools.domain_description_root``: unfiled tools have no domain. Deeper files are ignored.
- Only tools with a config file in a folder get it: proxied MCP server tools and remote SAJHA Net
  tools have no folder here.
- The registry's file monitor rescans these files with the tool configs (hot reload).
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

FILE_NAME = 'domain.txt'
DEFAULT_MAX_CHARS = 600
ROOT_NOTICE = 'tools.domain_description_root'
NOTICE_PREFIX = 'tools.domain_description:'


def max_chars() -> int:
    """``tools.domain_description_max_chars`` (default 600)."""
    try:
        from sajha.core.config import _get
        return max(1, int(float(_get('tools.domain_description_max_chars', DEFAULT_MAX_CHARS) or DEFAULT_MAX_CHARS)))
    except (TypeError, ValueError):
        return DEFAULT_MAX_CHARS
    except Exception:
        return DEFAULT_MAX_CHARS


def compose(own: str, domain: str) -> str:
    """The served description: the tool's own description, a blank line, the domain description."""
    own = own or ''
    if not domain:
        return own
    if not own.strip():
        return domain
    return own.rstrip() + '\n\n' + domain


def first_sentence(text: str) -> Tuple[str, str]:
    """(first sentence, the rest) of a domain description, for the Domains page."""
    text = (text or '').strip()
    for i, ch in enumerate(text):
        if ch in '.!?' and (i + 1 == len(text) or text[i + 1] in ' \n\t'):
            return text[:i + 1], text[i + 1:].strip()
    return text, ''


class DomainTexts:
    """The domain descriptions of one tools directory on one storage backend."""

    def __init__(self, prefix: str, storage=None):
        self.prefix = prefix.strip('/')
        self._st = storage
        self._lock = threading.RLock()
        self._texts: Dict[str, str] = {}          # folder -> accepted text
        self._refused: Dict[str, str] = {}        # folder -> why
        self._stamps: Dict[str, float] = {}       # rel -> modified time
        self._root = False
        self.loaded = False

    def storage(self):
        if self._st is not None:
            return self._st
        from sajha.core.storage import get_storage
        return get_storage()

    def _listing(self) -> Dict[str, float]:
        st = self.storage()
        out = {}
        for rel in st.list_files(self.prefix, FILE_NAME):
            rel = rel.replace('\\', '/')
            try:
                out[rel] = st.get_modified_time(rel)
            except FileNotFoundError:
                continue
        return out

    def _folder(self, rel: str) -> Optional[str]:
        """'' for the root file, the folder one level down, None for anything else."""
        if not rel.startswith(self.prefix + '/'):
            return None
        parts = rel[len(self.prefix) + 1:].split('/')
        if parts == [FILE_NAME]:
            return ''
        if len(parts) == 2 and parts[1] == FILE_NAME:
            from sajha.tools.tool_files import valid_folder_name
            return parts[0] if valid_folder_name(parts[0]) else None
        return None

    def load(self) -> bool:
        """Read every domain.txt again; True when the served texts changed."""
        try:
            listing = self._listing()
        except Exception as e:
            logger.warning(f'Domain descriptions: cannot list {self.prefix}: {e}')
            listing = {}
        limit = max_chars()
        texts, refused, root = {}, {}, False
        st = self.storage()
        for rel in sorted(listing):
            folder = self._folder(rel)
            if folder is None:
                continue
            if folder == '':
                root = True
                continue
            try:
                text = st.read_bytes(rel).decode('utf-8').strip()
            except UnicodeDecodeError:
                refused[folder] = f'{rel} is not UTF-8 text'
                continue
            except Exception as e:
                logger.warning(f'Domain description {rel} unreadable: {e}')
                continue
            if not text:
                continue
            if len(text) > limit:
                refused[folder] = (f'{rel} has {len(text)} characters; at most {limit} '
                                   f'(tools.domain_description_max_chars) are allowed')
                continue
            texts[folder] = text
        with self._lock:
            changed = texts != self._texts
            self._texts, self._refused, self._root, self._stamps = texts, refused, root, listing
            self.loaded = True
        self._report(refused, root)
        return changed

    def scan(self) -> bool:
        """Reload when a domain.txt was added, changed or removed; True when the served texts changed."""
        try:
            listing = self._listing()
        except Exception:
            return False
        with self._lock:
            same = listing == self._stamps and self.loaded
        return False if same else self.load()

    def _report(self, refused: Dict[str, str], root: bool) -> None:
        try:
            from sajha import notices
            for n in notices.list_notices(state='open', source='tools'):
                nid = str(n.get('id') or '')
                if nid.startswith(NOTICE_PREFIX) and nid[len(NOTICE_PREFIX):] not in refused:
                    notices.clear_notice(nid)
            for folder, why in sorted(refused.items()):
                logger.warning(f'Domain description of {folder} refused: {why}')
                notices.raise_notice(
                    NOTICE_PREFIX + folder, severity='warning', source='tools',
                    title=f'The domain description of tool folder {folder} is refused',
                    detail=why + '. A domain description is never cut, because a cut sentence can change '
                                 'its meaning: the folder\'s tools are served without it until the file '
                                 'is shortened.',
                    link='/help/guides/Architecture.md', ttl_minutes=0)
            if root:
                notices.raise_notice(
                    ROOT_NOTICE, severity='info', source='tools',
                    title=f'{self.prefix}/{FILE_NAME} is ignored',
                    detail='A domain description belongs in a tool folder (<tools dir>/<folder>/domain.txt). '
                           'Tools at the root of the tools directory are Unfiled and have no domain.',
                    link='/help/guides/Architecture.md', ttl_minutes=0)
            else:
                notices.clear_notice(ROOT_NOTICE)
        except Exception:
            pass

    def ensure(self) -> 'DomainTexts':
        if not self.loaded:
            self.load()
        return self

    def text(self, folder: Optional[str]) -> str:
        if not folder:
            return ''
        self.ensure()
        with self._lock:
            return self._texts.get(folder, '')

    def refused(self, folder: Optional[str]) -> str:
        if not folder:
            return ''
        self.ensure()
        with self._lock:
            return self._refused.get(folder, '')

    def all(self) -> Dict[str, str]:
        self.ensure()
        with self._lock:
            return dict(self._texts)


_held: Dict[str, Tuple[object, DomainTexts]] = {}
_held_lock = threading.Lock()


def get_domain_texts(prefix: Optional[str] = None) -> DomainTexts:
    """The shared domain descriptions of a tools directory on the current storage backend."""
    from sajha.core.storage import get_storage
    from sajha.tools.tool_files import default_prefix
    prefix = (prefix or default_prefix()).strip('/')
    st = get_storage()
    with _held_lock:
        held = _held.get(prefix)
        if held is None or held[0] is not st:
            held = (st, DomainTexts(prefix))
            _held[prefix] = held
        return held[1]


def _registry_of(tool):
    """The registry serving ``tool`` (the one that registered it, else the process registry)."""
    ref = getattr(tool, '_served_by', None)
    reg = ref() if callable(ref) else None
    if reg is not None:
        return reg
    try:
        from sajha.tools.tools_registry import ToolsRegistry
        return ToolsRegistry._instance
    except Exception:
        return None


def folder_of_tool(tool) -> Optional[str]:
    """The tool folder a served tool is filed in ('' or None: none). Only file-backed tools of the
    registry serving them have one; proxies of other servers never do."""
    if getattr(tool, 'namespaced_name', False):
        return None
    reg = _registry_of(tool)
    if reg is None or not hasattr(reg, '_config_prefix'):
        return None
    name = getattr(tool, 'name', None)
    tools = getattr(reg, 'tools', None) or {}
    if not name or name not in tools:
        return None
    try:
        return reg.tool_folder(name)
    except Exception:
        return None


def domain_description_of(tool) -> str:
    """The domain description appended to ``tool``'s description ('' when it has none)."""
    folder = folder_of_tool(tool)
    if not folder:
        return ''
    reg = _registry_of(tool)
    try:
        return get_domain_texts(getattr(reg, '_config_prefix', None)).text(folder)
    except Exception as e:
        logger.debug(f'domain description of {getattr(tool, "name", "?")}: {e}')
        return ''


def served_description(tool) -> str:
    """The description ``tool`` is served with: its own, then its folder's domain description."""
    own = getattr(tool, 'description', '') or ''
    return compose(own, domain_description_of(tool))


def studio_view(folder: Optional[str] = None, description: str = '', tool=None) -> dict:
    """What MCP Studio shows beside a tool's description (Architecture §5): ``{folder,
    domain_description, served_description}``. For a served ``tool``, its folder and
    :func:`served_description`; for a new tool (a creator's preview), the folder it is filed in
    (``folder``, "Unfiled" or empty: the root, no domain) and ``description`` composed with that
    folder's domain text, as SAJHA will serve it once it is deployed."""
    if tool is not None:
        f = folder_of_tool(tool) or ''
        domain = domain_description_of(tool)
        return {'folder': f, 'domain_description': domain, 'served_description': served_description(tool)}
    from sajha.tools.tool_files import clean_folder
    f = clean_folder(folder)
    domain = ''
    if f:
        try:
            domain = get_domain_texts().text(f)
        except Exception as e:
            logger.debug(f'domain description of folder {f}: {e}')
    return {'folder': f, 'domain_description': domain, 'served_description': compose(description or '', domain)}


def studio_domain_texts() -> dict:
    """folder -> served domain text, for the Studio creators' Folder field."""
    try:
        return get_domain_texts().all()
    except Exception:
        return {}


def export_description(tool, served: str, limit: int) -> str:
    """The description offered to a SAJHA Net catalog: ``served`` unless it is longer than ``limit``
    while carrying domain text, in which case the domain text is left out entirely, so the tool's own
    words are never cut (Architecture §5)."""
    if len(served or '') <= limit:
        return served
    own = getattr(tool, 'description', '') or ''
    return own if own != served else served
