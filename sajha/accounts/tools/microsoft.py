"""
SAJHA MCP Server — Microsoft 365 tools that act as the caller (connected account ``microsoft``).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Microsoft Graph ``GET /me/calendarView``
(https://learn.microsoft.com/en-us/graph/api/user-list-calendarview).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from sajha.accounts.tools.base import ConnectedAccountTool

API = 'https://graph.microsoft.com/v1.0'


def _iso(value: str, default: datetime) -> str:
    if not value:
        return default.strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError(f'not an ISO 8601 date or time: {value!r}')
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class MS365ListMyEventsTool(ConnectedAccountTool):
    default_provider = 'microsoft'
    default_scopes = ('Calendars.Read',)

    def run(self, a: Dict[str, Any]) -> Any:
        now = datetime.now(timezone.utc)
        start = _iso(str(a.get('start') or ''), now)
        end = _iso(str(a.get('end') or ''), now + timedelta(days=int(a.get('days') or 7)))
        params = {'startDateTime': start, 'endDateTime': end, '$top': int(a.get('limit') or 25),
                  '$orderby': 'start/dateTime',
                  '$select': 'subject,start,end,location,organizer,isOnlineMeeting,webLink'}
        data = self.api_json('GET', f'{API}/me/calendarView', params=params,
                             headers={'Prefer': 'outlook.timezone="UTC"'})
        events = [{'subject': e.get('subject'), 'start': (e.get('start') or {}).get('dateTime'),
                   'end': (e.get('end') or {}).get('dateTime'),
                   'location': (e.get('location') or {}).get('displayName'),
                   'organizer': ((e.get('organizer') or {}).get('emailAddress') or {}).get('name'),
                   'online': bool(e.get('isOnlineMeeting')), 'url': e.get('webLink')}
                  for e in data.get('value') or []]
        return {'from': start, 'to': end, 'count': len(events), 'events': events}
