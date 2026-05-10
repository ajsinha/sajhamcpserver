"""
SAJHA MCP Server v3 — Monitoring, Help, About, Docs Routes
Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

import os
from pathlib import Path
from fastapi import APIRouter, Request, Depends
from sajha.auth import require_auth, require_admin, AuthContext
from sajha.app import render

router = APIRouter(tags=['misc'])


# ── Monitoring ───────────────────────────────────────────────────

@router.get('/monitoring/tools')
async def monitoring_tools(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.app import tools_registry
    metrics = tools_registry.get_tool_metrics() if tools_registry else []
    return render(request, 'monitoring/monitoring_tools.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'metrics': metrics,
        'is_admin': True,
    })


@router.get('/monitoring/users')
async def monitoring_users(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.db.engine import get_db_session
    from sajha.db.dao import UserDAO
    db = get_db_session()
    try:
        dao = UserDAO(db)
        users = dao.get_all_users()
        admin_count = sum(1 for u in users if u.is_admin)
        users_data = [
            {
                'user_id': u.user_id,
                'user_name': u.user_name,
                'roles': u.role_names,
                'enabled': u.enabled,
                'last_login': u.last_login.isoformat() if u.last_login else None,
            }
            for u in users
        ]
    finally:
        db.close()

    return render(request, 'monitoring/monitoring_users.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'users': users_data,
        'admin_count': admin_count,
        'is_admin': True,
    })


# ── Help & About ─────────────────────────────────────────────────

@router.get('/help')
async def help_page(request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.app import tools_registry
    total_tools = len(tools_registry.tools) if tools_registry else 0
    # Build tool groups from tool name prefixes
    group_map = {}
    if tools_registry:
        for name, tool in tools_registry.tools.items():
            prefix = name.split('_')[0] if '_' in name else name
            if prefix not in group_map:
                group_map[prefix] = {'count': 0, 'enabled': 0, 'descriptions': []}
            group_map[prefix]['count'] += 1
            cfg = getattr(tool, 'config', {}) or {}
            if cfg.get('enabled', True):
                group_map[prefix]['enabled'] += 1
            desc = cfg.get('description', '')
            if desc and len(group_map[prefix]['descriptions']) < 3:
                group_map[prefix]['descriptions'].append(desc[:80])

    # Color cycle for group cards
    colors = ['primary', 'success', 'info', 'warning', 'danger', 'secondary']
    icons = ['bi-tools', 'bi-graph-up', 'bi-database', 'bi-globe', 'bi-bank',
             'bi-search', 'bi-calculator', 'bi-file-text', 'bi-currency-exchange']
    tool_groups = []
    for i, (gname, gdata) in enumerate(sorted(group_map.items(), key=lambda x: -x[1]['count'])):
        tool_groups.append({
            'name': gname,
            'tool_count': gdata['count'],
            'enabled_count': gdata['enabled'],
            'color': colors[i % len(colors)],
            'icon': icons[i % len(icons)],
            'description': f"{gdata['count']} tools in the {gname} provider group",
            'categories': gdata['descriptions'],
        })

    return render(request, 'help/help.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
        'tool_stats': {'total_tools': total_tools, 'total_groups': len(group_map)},
        'tool_groups': tool_groups,
    })


@router.get('/about')
async def about_page(request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.app import tools_registry, prompts_registry, VERSION
    from sajha.core.config import get_settings
    settings = get_settings()

    return render(request, 'help/about.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
        'server_version': VERSION,
        'tools_count': len(tools_registry.tools) if tools_registry else 0,
        'prompts_count': len(prompts_registry.prompts) if prompts_registry else 0,
        'db_type': settings.db_type,
    })


# ── Docs ─────────────────────────────────────────────────────────

@router.get('/docs')
@router.get('/docs/')
async def docs_list(request: Request, auth: AuthContext = Depends(require_auth)):
    docs_dir = Path('docs')
    sections = {}  # folder_name -> list of docs
    top_level = []

    if docs_dir.is_dir():
        for f in sorted(docs_dir.rglob('*.md')):
            rel = f.relative_to(docs_dir)
            entry = {
                'name': f.stem.replace('_', ' ').replace('-', ' ').title(),
                'path': str(rel),
            }
            if len(rel.parts) > 1:
                folder = rel.parts[0].replace('_', ' ').title()
                sections.setdefault(folder, []).append(entry)
            else:
                top_level.append(entry)

    return render(request, 'docs/docs_list.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'docs': top_level,
        'sections': sections,
        'is_admin': auth.is_admin,
    })


@router.get('/docs/view/{doc_path:path}')
async def docs_view(doc_path: str, request: Request, auth: AuthContext = Depends(require_auth)):
    import base64
    docs_path = Path('docs') / doc_path
    if not docs_path.exists() or not docs_path.is_file():
        return render(request, 'common/error.html', {
            'error': 'Document Not Found',
            'message': f'Document "{doc_path}" does not exist',
        }, status_code=404)

    content = docs_path.read_text(encoding='utf-8')
    content_b64 = base64.b64encode(content.encode('utf-8')).decode('ascii')
    display_name = docs_path.stem.replace('_', ' ').replace('-', ' ').title()

    # Build breadcrumb from path parts
    parts = Path(doc_path).parts
    breadcrumb = [p.replace('_', ' ').title() for p in parts[:-1]]
    breadcrumb.append(display_name)

    return render(request, 'docs/docs_view.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'doc_name': display_name,
        'content_b64': content_b64,
        'breadcrumb': breadcrumb,
        'is_admin': auth.is_admin,
    })
