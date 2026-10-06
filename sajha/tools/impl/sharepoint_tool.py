"""
SAJHA MCP Server - SharePoint Tools
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

SharePoint Online through Microsoft Graph (https://graph.microsoft.com/v1.0): documents in
the site's default document library, lists and list items, site information and search.

One API, one token: the app registration's client-credentials token is requested for
``https://graph.microsoft.com/.default`` and used only against Graph. (The SharePoint REST
API, ``<site>/_api``, does not accept app-only tokens obtained with a client secret, so it
is not used.) The app needs Graph application permissions such as ``Sites.Read.All`` (read)
or ``Sites.ReadWrite.All`` (writes), or ``Sites.Selected`` granted on the site.

Configuration (``config/tools/sharepoint_*.json``): ``site_url`` and an ``authentication``
block (``type``, ``tenant_id``, ``client_id``, ``client_secret``), normally
``${sharepoint.site.url}``, ``${azure.tenant.id}``, ``${sharepoint.client.id}`` and
``${sharepoint.client.secret}`` resolved from ``config/application.yml`` / the environment.
"""

import base64
import logging
import threading
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

from sajha.tools.base_mcp_tool import BaseMCPTool

logger = logging.getLogger(__name__)

GRAPH_ROOT = 'https://graph.microsoft.com/v1.0'
GRAPH_SCOPE = 'https://graph.microsoft.com/.default'
LOGIN_ROOT = 'https://login.microsoftonline.com'
HTTP_TIMEOUT = 60
#: Library names a caller may put in front of a path (SharePoint's server-relative form);
#: Graph addresses the default library as the drive root, so they are dropped.
LIBRARY_PREFIXES = ('shared documents', 'documents')


class SharePointConfigError(ValueError):
    """The tool is not configured (site URL or app registration missing)."""


def _unset(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip() or value.strip().startswith('${')


def odata_string(value: Any) -> str:
    """An OData string literal body: single quotes doubled (``O'Brien`` -> ``O''Brien``)."""
    return str(value).replace("'", "''")


def _kql_phrase(value: Any) -> str:
    """A KQL phrase in double quotes (quotes inside dropped)."""
    return '"' + str(value).replace('"', ' ') + '"'


class SharePointAuthenticator:
    """Client-credentials tokens for Microsoft Graph, cached until shortly before expiry."""

    #: Refresh this many seconds before the token's stated expiry.
    EXPIRY_MARGIN = 60

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.access_token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None
        self._lock = threading.Lock()

    @property
    def auth_type(self) -> str:
        return self.config.get('type') or self.config.get('auth_type') or 'client_credentials'

    def get_access_token(self) -> str:
        """A valid access token, requested again when the cached one is about to expire."""
        with self._lock:
            if self.access_token and self.token_expiry and datetime.now() < self.token_expiry:
                return self.access_token
            if self.auth_type != 'client_credentials':
                raise SharePointConfigError(
                    f"Unsupported SharePoint authentication type '{self.auth_type}': "
                    "only 'client_credentials' is implemented")
            return self._get_client_credentials_token()

    def _get_client_credentials_token(self) -> str:
        tenant_id = self.config.get('tenant_id')
        client_id = self.config.get('client_id')
        client_secret = self.config.get('client_secret')
        missing = [k for k, v in (('tenant_id', tenant_id), ('client_id', client_id),
                                  ('client_secret', client_secret)) if _unset(v)]
        if missing:
            raise SharePointConfigError(
                'SharePoint is not configured: set ' + ', '.join(missing) + ' (AZURE_TENANT_ID, '
                'SHAREPOINT_CLIENT_ID, SHAREPOINT_CLIENT_SECRET; see the SharePoint Tool Reference Guide)')
        response = requests.post(
            f"{LOGIN_ROOT}/{urllib.parse.quote(tenant_id.strip(), safe='')}/oauth2/v2.0/token",
            data={'grant_type': 'client_credentials', 'client_id': client_id,
                  'client_secret': client_secret, 'scope': GRAPH_SCOPE},
            timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        token_data = response.json()
        self.access_token = token_data['access_token']
        try:
            expires_in = int(token_data.get('expires_in', 3600))
        except (TypeError, ValueError):
            expires_in = 3600
        self.token_expiry = datetime.now() + timedelta(seconds=max(0, expires_in - self.EXPIRY_MARGIN))
        return self.access_token


class SharePointBaseTool(BaseMCPTool):
    """Shared Graph plumbing: configuration, token, site lookup, paths, requests."""

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.config = config or {}
        self.site_url = (self.config.get('site_url') or '').strip()
        self.authenticator: Optional[SharePointAuthenticator] = None
        self._site_id: Optional[str] = None
        self._init_auth()

    def _init_auth(self):
        auth_config = self.config.get('authentication', {})
        if auth_config:
            self.authenticator = SharePointAuthenticator(auth_config)

    def get_input_schema(self) -> Dict:
        """JSON schema for tool inputs (from the tool's config 'inputSchema')."""
        return self._input_schema

    def get_output_schema(self) -> Dict:
        """JSON schema for tool outputs (from the tool's config 'outputSchema')."""
        return self._output_schema

    # -- configuration --------------------------------------------------------

    def _site_parts(self) -> Tuple[str, str]:
        """(hostname, server-relative site path) of the configured site URL."""
        if _unset(self.site_url):
            raise SharePointConfigError(
                'SharePoint is not configured: set sharepoint.site.url (SHAREPOINT_SITE_URL), '
                'e.g. https://contoso.sharepoint.com/sites/team')
        parts = urllib.parse.urlsplit(self.site_url)
        if parts.scheme != 'https' or not parts.hostname:
            raise SharePointConfigError(f'Invalid SharePoint site URL: {self.site_url!r}')
        return parts.hostname, parts.path.rstrip('/')

    # -- HTTP -----------------------------------------------------------------

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        if not self.authenticator:
            raise SharePointConfigError('SharePoint is not configured: the tool config has no '
                                        "'authentication' block")
        headers = {'Authorization': f'Bearer {self.authenticator.get_access_token()}',
                   'Accept': 'application/json'}
        headers.update(extra or {})
        return headers

    def _graph(self, method: str, path: str, params: Optional[Dict[str, Any]] = None,
               json_body: Any = None, data: Optional[bytes] = None,
               headers: Optional[Dict[str, str]] = None, raw: bool = False):
        """One Graph call. ``path`` is already URL-encoded; ``params`` are encoded here."""
        url = path if path.startswith('https://') else f'{GRAPH_ROOT}{path}'
        response = requests.request(method, url, params=params, json=json_body, data=data,
                                    headers=self._headers(headers), timeout=HTTP_TIMEOUT)
        if response.status_code >= 400:
            detail = ''
            try:
                detail = (response.json().get('error') or {}).get('message', '')
            except Exception:
                detail = (response.text or '')[:200]
            raise RuntimeError(f'Microsoft Graph {method} {path.split("?")[0]} failed: '
                               f'HTTP {response.status_code} {detail}'.rstrip())
        if raw:
            return response
        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {}

    # -- addressing -----------------------------------------------------------

    def site_id(self) -> str:
        """The Graph id of the configured site (looked up once)."""
        if self._site_id is None:
            host, path = self._site_parts()
            target = f'/sites/{host}:{urllib.parse.quote(path)}' if path else f'/sites/{host}'
            self._site_id = self._graph('GET', target)['id']
        return self._site_id

    def _site(self) -> str:
        return f'/sites/{urllib.parse.quote(self.site_id(), safe="")}'

    def drive_path(self, path: Optional[str]) -> str:
        """A path inside the default document library, from either form a caller may use:
        library-relative (``/Project/plan.docx``) or SharePoint server-relative
        (``/sites/team/Shared Documents/Project/plan.docx``)."""
        p = (path or '').strip().replace('\\', '/')
        try:
            _, site_path = self._site_parts()
        except SharePointConfigError:
            site_path = ''
        if site_path and p.lower().startswith(site_path.lower() + '/'):
            p = p[len(site_path):]
        segments = [s for s in p.split('/') if s and s != '.']
        if '..' in segments:
            raise ValueError("'..' is not allowed in a SharePoint path")
        if segments and segments[0].lower() in LIBRARY_PREFIXES:
            segments = segments[1:]
        return '/'.join(segments)

    def item_ref(self, path: Optional[str]) -> str:
        """The Graph address of a drive item by path (the library root for an empty path)."""
        rel = self.drive_path(path)
        if not rel:
            return f'{self._site()}/drive/root'
        return f'{self._site()}/drive/root:/{urllib.parse.quote(rel)}:'

    def list_ref(self, list_name: Optional[str]) -> str:
        """A list addressed by its title or id (Graph accepts either)."""
        if not list_name or not str(list_name).strip():
            raise ValueError("'list_name' is required for this operation")
        return f'{self._site()}/lists/{urllib.parse.quote(str(list_name).strip(), safe="")}'

    # -- running --------------------------------------------------------------

    def _run(self, label: str, fn, arguments: Dict[str, Any]) -> Dict[str, Any]:
        start = time.time()
        try:
            result = fn(arguments)
            result['execution_time_ms'] = round((time.time() - start) * 1000, 2)
            result['success'] = True
            return result
        except Exception as e:
            logger.error(f'{label} error: {e}', exc_info=not isinstance(e, SharePointConfigError))
            return {'success': False, 'error': str(e)}


def _item_summary(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'name': item.get('name'),
        'id': item.get('id'),
        'url': item.get('webUrl'),
        'path': ((item.get('parentReference') or {}).get('path', '').split('root:', 1)[-1] + '/'
                 + (item.get('name') or '')).replace('//', '/'),
        'size': item.get('size'),
        'is_folder': 'folder' in item,
        'created': item.get('createdDateTime'),
        'modified': item.get('lastModifiedDateTime'),
        'author': ((item.get('createdBy') or {}).get('user') or {}).get('displayName'),
    }


class SharePointDocumentTool(SharePointBaseTool):
    """
    Documents in the site's default document library.

    Operations: list_files, get_file, download, upload, search, get_metadata,
    update_metadata, check_out, check_in, get_versions, delete, move, copy
    """

    #: Upper bound on items walked by list_files with recursive=true.
    MAX_RECURSIVE_ITEMS = 1000
    #: Graph's simple upload (PUT .../content) takes files up to 250 MB; keep it modest.
    MAX_UPLOAD_BYTES = 4 * 1024 * 1024

    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        operation = arguments.get('operation', 'list_files')
        handler = {
            'list_files': self._list_files, 'get_file': self._get_file,
            'download': self._download_file, 'upload': self._upload_file,
            'search': self._search_documents, 'get_metadata': self._get_metadata,
            'update_metadata': self._update_metadata, 'check_out': self._check_out,
            'check_in': self._check_in, 'get_versions': self._get_versions,
            'delete': self._delete_file, 'move': self._move_file, 'copy': self._copy_file,
        }.get(operation)
        if handler is None:
            return {'success': False, 'error': f'Unknown operation: {operation}'}
        return self._run('SharePointDocumentTool', handler, arguments)

    @staticmethod
    def _need(args: Dict, key: str) -> str:
        value = args.get(key)
        if not value:
            raise ValueError(f"'{key}' is required for this operation")
        return value

    def _children(self, ref: str) -> List[Dict]:
        out, url = [], f'{ref}/children'
        params = {'$top': 200}
        while url:
            page = self._graph('GET', url, params=params)
            out.extend(page.get('value', []))
            url, params = page.get('@odata.nextLink'), None
            if len(out) >= self.MAX_RECURSIVE_ITEMS:
                break
        return out

    def _list_files(self, args: Dict) -> Dict:
        folder_path = args.get('folder_path', '')
        recursive = bool(args.get('recursive', False))
        items, queue, truncated = [], [self.item_ref(folder_path)], False
        while queue:
            for child in self._children(queue.pop(0)):
                items.append(_item_summary(child))
                if recursive and 'folder' in child:
                    queue.append(f"{self._site()}/drive/items/{urllib.parse.quote(child['id'], safe='')}")
            if len(items) >= self.MAX_RECURSIVE_ITEMS:
                truncated = bool(queue) or len(items) > self.MAX_RECURSIVE_ITEMS
                items = items[:self.MAX_RECURSIVE_ITEMS]
                break
        files = [i for i in items if not i['is_folder']]
        return {'folder_path': folder_path or '/', 'file_count': len(files),
                'folder_count': len(items) - len(files), 'files': files,
                'folders': [i for i in items if i['is_folder']], 'truncated': truncated}

    def _get_file(self, args: Dict) -> Dict:
        item = self._graph('GET', self.item_ref(self._need(args, 'file_url')))
        out = _item_summary(item)
        out.update({'etag': item.get('eTag'), 'ctag': item.get('cTag'),
                    'mime_type': (item.get('file') or {}).get('mimeType')})
        return out

    def _download_file(self, args: Dict) -> Dict:
        file_url = self._need(args, 'file_url')
        response = self._graph('GET', f'{self.item_ref(file_url)}/content', raw=True)
        out = {'file_url': file_url, 'content_type': response.headers.get('Content-Type'),
               'size': len(response.content)}
        if args.get('return_content', False):
            out['content_base64'] = base64.b64encode(response.content).decode('ascii')
        else:
            out['download_ready'] = True
        return out

    def _upload_file(self, args: Dict) -> Dict:
        file_name = self._need(args, 'file_name')
        if '/' in file_name or '\\' in file_name:
            raise ValueError("'file_name' must be a plain file name; put the folder in 'folder_path'")
        try:
            content = base64.b64decode(self._need(args, 'content_base64'), validate=True)
        except Exception:
            raise ValueError("'content_base64' is not valid base64")
        if len(content) > self.MAX_UPLOAD_BYTES:
            raise ValueError(f'File too large for a simple upload ({len(content)} bytes; '
                             f'limit {self.MAX_UPLOAD_BYTES})')
        folder = self.drive_path(args.get('folder_path', ''))
        target = f'{folder}/{file_name}' if folder else file_name
        conflict = 'replace' if args.get('overwrite', False) else 'fail'
        item = self._graph('PUT', f'{self.item_ref(target)}/content',
                           params={'@microsoft.graph.conflictBehavior': conflict}, data=content,
                           headers={'Content-Type': 'application/octet-stream'})
        return {'uploaded': True, 'file_name': file_name, 'file_url': item.get('webUrl'),
                'id': item.get('id'), 'size': item.get('size')}

    def _search_documents(self, args: Dict) -> Dict:
        query = args.get('query') or '*'
        ref = self.item_ref(args.get('folder_path', ''))
        page = self._graph('GET', f"{ref}/search(q='{urllib.parse.quote(odata_string(query), safe='')}')",
                           params={'$top': int(args.get('max_results', 50) or 50)})
        results = [_item_summary(i) for i in page.get('value', [])]
        types = {t.lower().lstrip('.') for t in (args.get('file_types') or [])}
        if types:
            results = [r for r in results if (r['name'] or '').lower().rsplit('.', 1)[-1] in types]
        return {'query': query, 'result_count': len(results), 'results': results}

    def _get_metadata(self, args: Dict) -> Dict:
        file_url = self._need(args, 'file_url')
        item = self._graph('GET', f'{self.item_ref(file_url)}/listItem', params={'$expand': 'fields'})
        return {'file_url': file_url, 'list_item_id': item.get('id'), 'metadata': item.get('fields', {})}

    def _update_metadata(self, args: Dict) -> Dict:
        file_url = self._need(args, 'file_url')
        metadata = args.get('metadata') or {}
        if not isinstance(metadata, dict) or not metadata:
            raise ValueError("'metadata' must be a non-empty object of column values")
        fields = self._graph('PATCH', f'{self.item_ref(file_url)}/listItem/fields', json_body=metadata)
        return {'file_url': file_url, 'updated': True, 'metadata': fields or metadata}

    def _check_out(self, args: Dict) -> Dict:
        file_url = self._need(args, 'file_url')
        self._graph('POST', f'{self.item_ref(file_url)}/checkout')
        return {'file_url': file_url, 'checked_out': True}

    def _check_in(self, args: Dict) -> Dict:
        file_url = self._need(args, 'file_url')
        comment = args.get('comment', '')
        body = {'comment': comment}
        if args.get('publish'):
            body['checkInAs'] = 'published'
        self._graph('POST', f'{self.item_ref(file_url)}/checkin', json_body=body)
        return {'file_url': file_url, 'checked_in': True, 'comment': comment}

    def _get_versions(self, args: Dict) -> Dict:
        file_url = self._need(args, 'file_url')
        page = self._graph('GET', f'{self.item_ref(file_url)}/versions')
        versions = [{'version_id': v.get('id'),
                     'modified': v.get('lastModifiedDateTime'),
                     'modified_by': ((v.get('lastModifiedBy') or {}).get('user') or {}).get('displayName'),
                     'size': v.get('size')} for v in page.get('value', [])]
        return {'file_url': file_url, 'version_count': len(versions), 'versions': versions}

    def _delete_file(self, args: Dict) -> Dict:
        file_url = self._need(args, 'file_url')
        recycle = args.get('recycle', True)
        if recycle:
            self._graph('DELETE', self.item_ref(file_url))          # to the site recycle bin
        else:
            self._graph('POST', f'{self.item_ref(file_url)}/permanentDelete')
        return {'file_url': file_url, 'deleted': True, 'recycled': bool(recycle)}

    def _destination(self, args: Dict) -> Tuple[str, str]:
        """(parent folder path, new name) of 'destination_url'."""
        dest = self.drive_path(self._need(args, 'destination_url'))
        if not dest:
            raise ValueError("'destination_url' must name the destination file")
        parent, _, name = dest.rpartition('/')
        return parent, name

    def _parent_reference(self, parent: str) -> Dict[str, Any]:
        root = self._graph('GET', f'{self._site()}/drive/root', params={'$select': 'id,parentReference'})
        drive_id = (root.get('parentReference') or {}).get('driveId')
        ref = {'path': '/drive/root:' + (f'/{parent}' if parent else '')}
        if drive_id:
            ref['driveId'] = drive_id
        return ref

    def _move_file(self, args: Dict) -> Dict:
        source = self._need(args, 'source_url') if args.get('source_url') else self._need(args, 'file_url')
        parent, name = self._destination(args)
        params = {'@microsoft.graph.conflictBehavior': 'replace' if args.get('overwrite') else 'fail'}
        item = self._graph('PATCH', self.item_ref(source), params=params,
                           json_body={'parentReference': {'path': '/drive/root:' + (f'/{parent}' if parent else '')},
                                      'name': name})
        return {'source_url': source, 'destination_url': args.get('destination_url'),
                'moved': True, 'url': item.get('webUrl')}

    def _copy_file(self, args: Dict) -> Dict:
        source = self._need(args, 'source_url') if args.get('source_url') else self._need(args, 'file_url')
        parent, name = self._destination(args)
        params = {'@microsoft.graph.conflictBehavior': 'replace' if args.get('overwrite') else 'fail'}
        response = self._graph('POST', f'{self.item_ref(source)}/copy', params=params,
                               json_body={'parentReference': self._parent_reference(parent), 'name': name},
                               raw=True)
        # Graph copies asynchronously: 202 Accepted with a monitor URL in Location
        return {'source_url': source, 'destination_url': args.get('destination_url'),
                'copied': True, 'status': 'accepted', 'monitor_url': response.headers.get('Location')}


class SharePointListTool(SharePointBaseTool):
    """
    SharePoint lists and list items.

    Operations: get_lists, get_list_items, get_item, create_item, update_item,
    delete_item, get_list_schema, query_items
    """

    #: Graph pages list items; skip is applied client-side, so top + skip is bounded.
    MAX_ITEMS = 5000
    #: Lets $filter / $orderby use columns that are not indexed (Graph refuses otherwise).
    NON_INDEXED = {'Prefer': 'HonorNonIndexedQueriesWarningMayFailRandomly'}

    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        operation = arguments.get('operation', 'get_lists')
        handler = {
            'get_lists': self._get_lists, 'get_list_items': self._get_list_items,
            'get_item': self._get_item, 'create_item': self._create_item,
            'update_item': self._update_item, 'delete_item': self._delete_item,
            'get_list_schema': self._get_list_schema, 'query_items': self._query_items,
        }.get(operation)
        if handler is None:
            return {'success': False, 'error': f'Unknown operation: {operation}'}
        return self._run('SharePointListTool', handler, arguments)

    @staticmethod
    def _item_id(args: Dict) -> str:
        item_id = args.get('item_id')
        if item_id is None or str(item_id).strip() == '':
            raise ValueError("'item_id' is required for this operation")
        return urllib.parse.quote(str(item_id), safe='')

    def _get_lists(self, args: Dict) -> Dict:
        page = self._graph('GET', f'{self._site()}/lists',
                           params={'$select': 'id,displayName,description,createdDateTime,list,webUrl'})
        lists = [{'id': l.get('id'), 'title': l.get('displayName'), 'description': l.get('description'),
                  'created': l.get('createdDateTime'), 'url': l.get('webUrl'),
                  'template': (l.get('list') or {}).get('template')}
                 for l in page.get('value', []) if not (l.get('list') or {}).get('hidden')]
        return {'list_count': len(lists), 'lists': lists}

    def _fetch_items(self, args: Dict, filter_query: Optional[str] = None) -> List[Dict]:
        top = max(0, int(args.get('top', 100) or 100))
        skip = max(0, int(args.get('skip', 0) or 0))
        wanted = min(top + skip, self.MAX_ITEMS)
        select = args.get('select_fields') or []
        expand = f"fields($select={','.join(select)})" if select else 'fields'
        params = {'$expand': expand, '$top': min(wanted, 999)}
        if filter_query:
            params['$filter'] = filter_query
        if args.get('order_by'):
            params['$orderby'] = args['order_by']
        items, url = [], f"{self.list_ref(args.get('list_name'))}/items"
        while url and len(items) < wanted:
            page = self._graph('GET', url, params=params, headers=self.NON_INDEXED)
            items.extend(page.get('value', []))
            url, params = page.get('@odata.nextLink'), None
        return [{'id': i.get('id'), 'fields': i.get('fields', {}), 'url': i.get('webUrl'),
                 'modified': i.get('lastModifiedDateTime')} for i in items[skip:skip + top]]

    def _get_list_items(self, args: Dict) -> Dict:
        items = self._fetch_items(args)
        return {'list_name': args.get('list_name'), 'item_count': len(items), 'items': items}

    def _get_item(self, args: Dict) -> Dict:
        item = self._graph('GET', f"{self.list_ref(args.get('list_name'))}/items/{self._item_id(args)}",
                           params={'$expand': 'fields'})
        return {'list_name': args.get('list_name'), 'item_id': args.get('item_id'),
                'item': item.get('fields', {})}

    def _create_item(self, args: Dict) -> Dict:
        data = args.get('item_data') or {}
        if not isinstance(data, dict) or not data:
            raise ValueError("'item_data' must be a non-empty object of column values")
        item = self._graph('POST', f"{self.list_ref(args.get('list_name'))}/items", json_body={'fields': data})
        return {'list_name': args.get('list_name'), 'created': True, 'item_id': item.get('id'),
                'item': item.get('fields', {})}

    def _update_item(self, args: Dict) -> Dict:
        data = args.get('item_data') or {}
        if not isinstance(data, dict) or not data:
            raise ValueError("'item_data' must be a non-empty object of column values")
        fields = self._graph('PATCH', f"{self.list_ref(args.get('list_name'))}/items/{self._item_id(args)}/fields",
                             json_body=data)
        return {'list_name': args.get('list_name'), 'item_id': args.get('item_id'), 'updated': True,
                'item': fields}

    def _delete_item(self, args: Dict) -> Dict:
        self._graph('DELETE', f"{self.list_ref(args.get('list_name'))}/items/{self._item_id(args)}")
        # Graph has one delete for list items: the item goes to the site recycle bin
        return {'list_name': args.get('list_name'), 'item_id': args.get('item_id'), 'deleted': True,
                'recycled': True}

    _COLUMN_TYPES = ('text', 'number', 'dateTime', 'choice', 'boolean', 'currency', 'lookup',
                     'personOrGroup', 'calculated', 'hyperlinkOrPicture', 'geolocation', 'term',
                     'thumbnail', 'contentApprovalStatus')

    def _get_list_schema(self, args: Dict) -> Dict:
        page = self._graph('GET', f"{self.list_ref(args.get('list_name'))}/columns")
        fields = []
        for c in page.get('value', []):
            if c.get('hidden'):
                continue
            fields.append({'name': c.get('name'), 'display_name': c.get('displayName'),
                           'type': next((t for t in self._COLUMN_TYPES if t in c), 'unknown'),
                           'required': c.get('required'), 'read_only': c.get('readOnly'),
                           'default_value': (c.get('defaultValue') or {}).get('value')})
        return {'list_name': args.get('list_name'), 'field_count': len(fields), 'fields': fields}

    def _query_items(self, args: Dict) -> Dict:
        filter_query = args.get('filter')
        items = self._fetch_items(args, filter_query)
        return {'list_name': args.get('list_name'), 'filter': filter_query,
                'item_count': len(items), 'items': items}


class SharePointSiteTool(SharePointBaseTool):
    """
    Site information.

    Operations: get_site_info, get_subsites, get_users, get_groups, get_permissions,
    get_content_types. ``get_groups`` (SharePoint site groups) has no Microsoft Graph API
    and answers with an error saying so.
    """

    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        operation = arguments.get('operation', 'get_site_info')
        handler = {
            'get_site_info': self._get_site_info, 'get_subsites': self._get_subsites,
            'get_users': self._get_users, 'get_groups': self._get_groups,
            'get_permissions': self._get_permissions, 'get_content_types': self._get_content_types,
        }.get(operation)
        if handler is None:
            return {'success': False, 'error': f'Unknown operation: {operation}'}
        return self._run('SharePointSiteTool', handler, arguments)

    def _get_site_info(self, args: Dict) -> Dict:
        site = self._graph('GET', self._site())
        return {'id': site.get('id'), 'title': site.get('displayName'),
                'description': site.get('description'), 'url': site.get('webUrl'),
                'created': site.get('createdDateTime'), 'modified': site.get('lastModifiedDateTime')}

    def _get_subsites(self, args: Dict) -> Dict:
        page = self._graph('GET', f'{self._site()}/sites')
        subsites = [{'id': s.get('id'), 'title': s.get('displayName'), 'url': s.get('webUrl'),
                     'created': s.get('createdDateTime')} for s in page.get('value', [])]
        return {'subsite_count': len(subsites), 'subsites': subsites}

    def _get_users(self, args: Dict) -> Dict:
        # The site's hidden "User Information List" holds the people known to the site
        page = self._graph('GET', f"{self.list_ref('User Information List')}/items",
                           params={'$expand': 'fields', '$top': 999})
        users = []
        for item in page.get('value', []):
            f = item.get('fields', {})
            users.append({'id': item.get('id'), 'title': f.get('Title'), 'email': f.get('EMail'),
                          'login_name': f.get('Name'), 'is_site_admin': f.get('IsSiteAdmin')})
        return {'user_count': len(users), 'users': users}

    def _get_groups(self, args: Dict) -> Dict:
        raise RuntimeError('SharePoint site groups are not exposed by Microsoft Graph; '
                           'manage membership through the Microsoft 365 group or the site UI')

    def _get_permissions(self, args: Dict) -> Dict:
        object_url = args.get('object_url', '')
        ref = f'{self.item_ref(object_url)}/permissions' if object_url else f'{self._site()}/permissions'
        page = self._graph('GET', ref)
        permissions = [{'id': p.get('id'), 'roles': p.get('roles', []),
                        'granted_to': p.get('grantedToV2') or p.get('grantedTo')
                        or p.get('grantedToIdentitiesV2') or p.get('grantedToIdentities')}
                       for p in page.get('value', [])]
        return {'permission_count': len(permissions), 'permissions': permissions}

    def _get_content_types(self, args: Dict) -> Dict:
        page = self._graph('GET', f'{self._site()}/contentTypes')
        types = [{'id': c.get('id'), 'name': c.get('name'), 'description': c.get('description'),
                  'group': c.get('group')} for c in page.get('value', [])]
        return {'content_type_count': len(types), 'content_types': types}


class SharePointSearchTool(SharePointBaseTool):
    """
    Search within the configured site through the Microsoft Graph search API
    (``POST /search/query``), or people through the directory.

    With application permissions Graph needs a ``region`` for SharePoint searches; set
    ``search_region`` in the tool config (e.g. ``NAM``, ``EUR``) when the tenant asks for it.
    """

    ENTITY_TYPES = {'all': ['driveItem', 'listItem', 'site'], 'documents': ['driveItem'],
                    'sites': ['site']}

    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        search_type = arguments.get('search_type', 'all')
        if search_type == 'people':
            return self._run('SharePointSearchTool', self._search_people, arguments)
        if search_type not in self.ENTITY_TYPES:
            return {'success': False, 'error': f'Unknown search type: {search_type}'}
        return self._run('SharePointSearchTool', self._search, arguments)

    def _query_string(self, args: Dict) -> str:
        query = str(args.get('query') or '*').strip() or '*'
        parts = [f'({query})']
        types = [t.lower().lstrip('.') for t in (args.get('file_types') or []) if str(t).strip()]
        bad = [t for t in types if not t.isalnum()]
        if bad:
            raise ValueError(f'Invalid file type(s): {", ".join(bad)}')
        if types:
            parts.append('(' + ' OR '.join(f'filetype:{t}' for t in types) + ')')
        if not _unset(self.site_url):
            parts.append(f'path:{_kql_phrase(self.site_url)}')       # this site only
        return ' AND '.join(parts)

    def _search(self, args: Dict) -> Dict:
        query = args.get('query') or '*'
        request = {'entityTypes': self.ENTITY_TYPES[args.get('search_type', 'all')],
                   'query': {'queryString': self._query_string(args)},
                   'from': int(args.get('start_row', 0) or 0),
                   'size': int(args.get('max_results', 50) or 50)}
        region = self.config.get('search_region')
        if not _unset(region):
            request['region'] = region
        page = self._graph('POST', '/search/query', json_body={'requests': [request]})
        containers = [c for r in page.get('value', []) for c in r.get('hitsContainers', [])]
        results, total = [], 0
        for c in containers:
            total += int(c.get('total') or 0)
            for hit in c.get('hits', []):
                res = hit.get('resource') or {}
                results.append({
                    'title': res.get('name') or res.get('displayName') or (res.get('fields') or {}).get('title'),
                    'path': res.get('webUrl'),
                    'author': ((res.get('createdBy') or {}).get('user') or {}).get('displayName'),
                    'modified': res.get('lastModifiedDateTime'),
                    'size': res.get('size'),
                    'summary': hit.get('summary'),
                    'content_class': (res.get('@odata.type') or '').rsplit('.', 1)[-1],
                })
        return {'query': query, 'total_results': total, 'result_count': len(results), 'results': results}

    def _search_people(self, args: Dict) -> Dict:
        query = str(args.get('query') or '').strip()
        if not query or query == '*':
            raise ValueError("'query' must name the person to look for")
        term = query.replace('"', ' ')
        page = self._graph('GET', '/users', headers={'ConsistencyLevel': 'eventual'},
                           params={'$search': f'"displayName:{term}" OR "mail:{term}"',
                                   '$top': min(int(args.get('max_results', 50) or 50), 999),
                                   '$select': 'id,displayName,mail,jobTitle,department'})
        results = [{'title': u.get('displayName'), 'email': u.get('mail'), 'job_title': u.get('jobTitle'),
                    'department': u.get('department'), 'id': u.get('id')} for u in page.get('value', [])]
        return {'query': query, 'total_results': len(results), 'result_count': len(results),
                'results': results}
