"""
SAJHA MCP Server — Google Workspace tools that act as the caller (connected account ``google``).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Drive API v3 ``files.list`` (https://developers.google.com/drive/api/reference/rest/v3/files/list).
"""

from __future__ import annotations

from typing import Any, Dict

from sajha.accounts.tools.base import ConnectedAccountTool

API = 'https://www.googleapis.com/drive/v3'
FIELDS = 'files(id,name,mimeType,modifiedTime,webViewLink,owners(displayName,emailAddress)),nextPageToken'


def drive_query(text: str, mime_type: str = '') -> str:
    """A Drive ``q`` expression: full-text match, not trashed (quotes and backslashes escaped)."""
    esc = text.replace('\\', '\\\\').replace("'", "\\'")
    q = f"fullText contains '{esc}' and trashed = false"
    if mime_type:
        q += " and mimeType = '" + mime_type.replace('\\', '\\\\').replace("'", "\\'") + "'"
    return q


class GoogleDriveSearchTool(ConnectedAccountTool):
    default_provider = 'google'
    default_scopes = ('https://www.googleapis.com/auth/drive.readonly',)

    def run(self, a: Dict[str, Any]) -> Any:
        params = {'q': drive_query(str(a['query']), str(a.get('mime_type') or '')),
                  'pageSize': int(a.get('limit') or 10), 'fields': FIELDS, 'orderBy': 'modifiedTime desc',
                  'supportsAllDrives': True, 'includeItemsFromAllDrives': True}
        data = self.api_json('GET', f'{API}/files', params=params)
        files = [{'id': f.get('id'), 'name': f.get('name'), 'mime_type': f.get('mimeType'),
                  'modified': f.get('modifiedTime'), 'url': f.get('webViewLink'),
                  'owners': [o.get('displayName') or o.get('emailAddress') for o in f.get('owners') or []]}
                 for f in data.get('files') or []]
        return {'query': a['query'], 'count': len(files), 'files': files,
                'next_page_token': data.get('nextPageToken')}
