"""
SAJHA MCP Server — Help routes: the help catalog, the guides, the glossary, About.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Public, like the rest of the documentation (no login needed): /help, /help/c/{cid},
/help/guides, /help/guides/{name}, /glossary, /help/tools, /about, /comparison. What they
serve is the guides under docs/ (docs/archive/ excluded), GLOSSARY.md, the tool registry's
names and descriptions, which the public landing page already shows, and the comparison
data in sajha/web/competitive.py. Nothing here reads users, keys, configuration values or
secrets.

The help catalog is sajha/web/help_catalog.py, guides are found and rendered by
sajha/web/guides.py, and definitions come from GLOSSARY.md via sajha/web/glossary.py.
"""

import logging
from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from sajha.app import render
from sajha.auth import AuthContext, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=['help'])


def _user_ctx(auth: AuthContext) -> dict:
    return {
        'user': {'user_id': auth.user_id or 'guest', 'user_name': auth.user_name or 'Guest',
                 'roles': auth.roles or []},
        'is_admin': auth.is_admin,
    }


def _not_found(request: Request, what: str):
    return render(request, 'common/error.html', {
        'error': 'Not Found', 'message': f'{what} does not exist',
    }, status_code=404)


# ── The help landing page and its categories ────────────────────────────────

@router.get('/help', name='help_page')
async def help_page(request: Request, auth: AuthContext = Depends(get_current_user)):
    from sajha.web.help_catalog import CATALOG
    return render(request, 'help/index.html', {**_user_ctx(auth), 'catalog': CATALOG})


@router.get('/help/c/{cid}', name='help_category')
async def help_category(cid: str, request: Request, auth: AuthContext = Depends(get_current_user)):
    from sajha.web.help_catalog import CATALOG, category, grouped
    cat = category(cid)
    if cat is None:
        return _not_found(request, f'Help section "{cid}"')
    return render(request, 'help/category.html', {
        **_user_ctx(auth), 'cat': cat, 'groups': grouped(cat), 'catalog': CATALOG})


# ── Guides (docs/, by unique file name) ─────────────────────────────────────

@router.get('/help/guides', name='help_guides')
async def help_guides(request: Request, auth: AuthContext = Depends(get_current_user)):
    from sajha.web.guides import library
    from sajha.web.help_catalog import related_for
    folders = library()
    return render(request, 'help/guides.html', {
        **_user_ctx(auth), 'folders': folders,
        'guide_count': sum(len(f['guides']) for f in folders),
        'help_related': related_for('help_guides')})


@router.get('/help/guides/{name:path}', name='help_guide')
async def help_guide(name: str, request: Request, auth: AuthContext = Depends(get_current_user)):
    from sajha.core.config import get_settings
    from sajha.web.guides import FOLDERS, folder_of, read_guide, render_guide, title_of
    from sajha.web.help_catalog import related_for_guide
    found = read_guide(name)
    if found is None:
        return _not_found(request, f'Guide "{PurePosixPath(name).name}"')
    rel, text = found
    gname = rel.rsplit('/', 1)[-1]
    try:
        body, toc = render_guide(text, rel, get_settings().app_github_repo)
    except ImportError:
        # The guide is still readable as its source; the operator gets the fix in the log.
        logger.warning('Python-Markdown is not installed (pip install -r requirements.txt); '
                       'serving %s as plain text', rel)
        from markupsafe import escape
        body = ('<p class="small-muted">This server has no markdown renderer installed, so the '
                'guide is shown as its source. An administrator can fix this with '
                '<code>pip install -r requirements.txt</code>.</p>'
                f'<pre class="guide-source">{escape(text)}</pre>')
        toc = []
    folder = folder_of(rel)
    return render(request, 'help/guide_view.html', {
        **_user_ctx(auth),
        'title': title_of(text, gname), 'name': gname,
        'folder': folder, 'folder_label': FOLDERS.get(folder, folder),
        'body': body, 'toc': toc,
        'help_related': related_for_guide(gname),
    })


# ── Glossary (GLOSSARY.md) ──────────────────────────────────────────────────

@router.get('/glossary', name='glossary')
async def glossary(request: Request, auth: AuthContext = Depends(get_current_user)):
    from sajha.web.glossary import load_glossary
    from sajha.web.help_catalog import related_for
    sections = load_glossary()
    return render(request, 'help/glossary.html', {
        **_user_ctx(auth), 'glossary': sections,
        'term_count': sum(len(s['terms']) for s in sections),
        'help_related': related_for('glossary')})


# ── The live tool catalog ───────────────────────────────────────────────────

def _can_see(auth: AuthContext):
    """The viewer's tools/list visibility: the help pages name no tool it would hide."""
    from sajha.auth.access import policy_for
    return policy_for(auth).can_see


@router.get('/help/tools', name='help_tools_page')
async def help_tools_page(request: Request, auth: AuthContext = Depends(get_current_user)):
    from sajha.web.help_catalog import live_tool_groups, related_for
    return render(request, 'help/help_tools.html', {
        **_user_ctx(auth), 'catalog_live': live_tool_groups(visible=_can_see(auth)),
        'help_related': related_for('help_tools_page')})


# ── About ───────────────────────────────────────────────────────────────────

@router.get('/about', name='about_page')
async def about_page(request: Request, auth: AuthContext = Depends(get_current_user)):
    from sajha.app import prompts_registry
    from sajha.core.mcp_modern import HANDSHAKE_PROTOCOL_VERSIONS, MODERN_PROTOCOL_VERSIONS
    from sajha.web.help_catalog import live_tool_groups, related_for
    ctx = {
        **_user_ctx(auth),
        'catalog_live': live_tool_groups(visible=_can_see(auth)),
        'prompts_count': len(prompts_registry.prompts) if prompts_registry else 0,
        'modern_versions': MODERN_PROTOCOL_VERSIONS,
        'handshake_versions': HANDSHAKE_PROTOCOL_VERSIONS,
        'help_related': related_for('about_page'),
    }
    if auth.is_admin:   # the running configuration is for administrators only
        from sajha.auth.oauth import settings as oauth_settings
        from sajha.core.config import get_settings
        ctx['oauth_mode'] = oauth_settings.auth_mode()
        ctx['oauth_builtin'] = oauth_settings.is_builtin()
        ctx['db_type'] = get_settings().db_type
    return render(request, 'help/about.html', ctx)


# ── How SAJHA compares (sajha/web/competitive.py) ───────────────────────────

@router.get('/comparison', name='comparison_page')
async def comparison_page(request: Request, auth: AuthContext = Depends(get_current_user)):
    from sajha.web.competitive import page_context
    from sajha.web.help_catalog import related_for
    return render(request, 'help/comparison.html', {
        **_user_ctx(auth), **page_context(), 'help_related': related_for('comparison_page')})


# ── Superseded pages: 301 to their owners ───────────────────────────────────

def _redirect_to(target: str):
    async def handler():
        return RedirectResponse(url=target, status_code=301)
    return handler


def _register_redirects():
    from sajha.web.help_catalog import REDIRECTS
    for endpoint, (path, target) in REDIRECTS.items():
        router.add_api_route(path, _redirect_to(target), methods=['GET'], name=endpoint,
                             include_in_schema=False)


_register_redirects()


# The old /docs viewer served docs/ (archive included) as client-rendered markdown. The
# guide pages replace it; its URLs redirect so links and bookmarks keep working.
@router.get('/docs', name='docs_list', include_in_schema=False)
@router.get('/docs/', include_in_schema=False)
async def docs_list():
    return RedirectResponse(url='/help/guides', status_code=301)


@router.get('/docs/view/{doc_path:path}', name='docs_view', include_in_schema=False)
async def docs_view(doc_path: str):
    from sajha.web.guides import find_guide
    name = PurePosixPath(doc_path).name
    if '..' not in PurePosixPath(doc_path).parts and find_guide(name):
        return RedirectResponse(url='/help/guides/' + quote(name), status_code=301)
    return RedirectResponse(url='/help/guides', status_code=301)
