"""
SAJHA MCP Server — GitHub tools that act as the caller (connected account ``github``).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

REST API v3 (https://docs.github.com/en/rest): ``GET /user/repos`` and
``POST /repos/{owner}/{repo}/issues``.
"""

from __future__ import annotations

import re
from typing import Any, Dict

from sajha.accounts.tools.base import ConnectedAccountTool

API = 'https://api.github.com'
_NAME = re.compile(r'^[A-Za-z0-9_.-]{1,100}$')


class GithubListMyReposTool(ConnectedAccountTool):
    default_provider = 'github'

    def run(self, a: Dict[str, Any]) -> Any:
        params = {'per_page': int(a.get('limit') or 30), 'sort': a.get('sort') or 'updated',
                  'visibility': a.get('visibility') or 'all',
                  'affiliation': a.get('affiliation') or 'owner,collaborator,organization_member'}
        repos = self.api_json('GET', f'{API}/user/repos', params=params)
        out = [{'full_name': r.get('full_name'), 'private': bool(r.get('private')),
                'description': r.get('description') or '', 'url': r.get('html_url'),
                'default_branch': r.get('default_branch'), 'language': r.get('language'),
                'stars': r.get('stargazers_count', 0), 'open_issues': r.get('open_issues_count', 0),
                'updated_at': r.get('updated_at')}
               for r in (repos if isinstance(repos, list) else [])]
        return {'account': self.token().connection.account_login, 'count': len(out), 'repositories': out}


class GithubCreateIssueTool(ConnectedAccountTool):
    default_provider = 'github'
    default_scopes = ('repo',)

    def run(self, a: Dict[str, Any]) -> Any:
        owner, repo = str(a['owner']), str(a['repo'])
        if not (_NAME.match(owner) and _NAME.match(repo)):
            raise ValueError('owner and repo must be GitHub names (letters, digits, -, _ and .)')
        body: Dict[str, Any] = {'title': a['title']}
        if a.get('body'):
            body['body'] = a['body']
        if a.get('labels'):
            body['labels'] = list(a['labels'])
        issue = self.api_json('POST', f'{API}/repos/{owner}/{repo}/issues', json_body=body)
        return {'number': issue.get('number'), 'url': issue.get('html_url'), 'title': issue.get('title'),
                'state': issue.get('state'), 'created_by': (issue.get('user') or {}).get('login')}
