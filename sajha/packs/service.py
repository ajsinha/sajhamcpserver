"""
SAJHA MCP Server — provider packs: review, install and uninstall.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A pack installs two things together: a connected-account *preset* (the provider users link,
sajha/accounts/presets.py) and an API Import of the service's bundled OpenAPI spec whose tools act
as the calling user (``auth.type: connected_account``). The flow is the review-and-approve gate of
Describe a tool (docs/architecture/Tool Generation.md §6), without a stored draft:

    plan(pack, inputs)      everything an install would do: the provider preset as it would be
                            built (validated by the provider registry's own rules), the redirect URI
                            to register with the service, every operation as API Import plans it
                            (tool name, annotations, conflicts, new/changed/unchanged), the policy
                            preview, and the review ``hash`` of all of it
    install(pack, inputs, hash, approve)
                            refused unless approve is true, the plan has no errors, the plan made
                            again has the same hash (nothing changed since the review: pack, spec,
                            inputs, names, existing tools), and the policy engine allows the pseudo
                            tool call ``studio.deploy`` with ``{"tool": "pack:<id>", "kind": "pack"}``
                            (``require_approval`` sends it to the Approvals page); then the preset is
                            saved and the operations are deployed by API Import's own ``deploy``.
                            A failed deploy restores the previous preset.
    uninstall(pack)         removes the pack's import (its tools) and the preset it created.

Install records live at ``config/packs/<id>.json`` through the storage backend.
Design: docs/architecture/Connected Accounts.md §11
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sajha.packs.manifest import INSTALL_FIELDS, Pack, PackError, discover

logger = logging.getLogger(__name__)

RECORDS_DIR = 'config/packs'
DEPLOY_ACTION = 'studio.deploy'          # the pseudo tool the policy engine sees, as for Describe a tool


# ── records ─────────────────────────────────────────────────────────

def _storage():
    from sajha.core.storage import get_storage
    return get_storage()


def _record_path(pack_id: str) -> str:
    from sajha.packs.manifest import PACK_ID
    if not PACK_ID.match(str(pack_id or '')):
        raise PackError(f'invalid pack id {pack_id!r}')
    return f'{RECORDS_DIR}/{pack_id}.json'


def load_record(pack_id: str) -> Optional[Dict[str, Any]]:
    try:
        path = _record_path(pack_id)
        st = _storage()
        if not st.exists(path):
            return None
        doc = st.read_json(path)
        return doc if isinstance(doc, dict) else None
    except PackError:
        return None
    except Exception as e:
        logger.error(f'pack record {pack_id} unreadable: {e}')
        return None


def _save_record(record: Dict[str, Any]) -> None:
    _storage().write_json(_record_path(record['pack']), record)


def _delete_record(pack_id: str) -> None:
    try:
        _storage().delete(_record_path(pack_id))
    except FileNotFoundError:
        pass


# ── catalog ─────────────────────────────────────────────────────────

def get_pack(pack_id: str, dirs: Optional[List[str]] = None) -> Pack:
    packs, problems = discover(dirs)
    if pack_id in packs:
        return packs[pack_id]
    if pack_id in problems:
        raise PackError(problems[pack_id], 409)
    raise PackError(f'no pack {pack_id!r}', 404)


def catalog(dirs: Optional[List[str]] = None) -> Dict[str, Any]:
    """Every pack with its install state, and the folders that are not valid packs."""
    packs, problems = discover(dirs)
    items = []
    for pid, pack in sorted(packs.items()):
        rec = load_record(pid)
        items.append({**pack.summary(),
                      'installed': ({k: rec.get(k) for k in ('version', 'installed_at', 'installed_by', 'api_id',
                                                             'tools', 'hash', 'approval')} if rec else None),
                      'upgrade': bool(rec and rec.get('version') != pack.version)})
    return {'success': True, 'packs': items, 'problems': problems}


def show(pack_id: str, dirs: Optional[List[str]] = None) -> Dict[str, Any]:
    pack = get_pack(pack_id, dirs)
    return {'success': True, 'pack': pack.summary(), 'provider': copy.deepcopy(pack.provider),
            'licence': pack.licence_text, 'installed': load_record(pack_id)}


# ── the plan ────────────────────────────────────────────────────────

def _inputs(pack: Pack, data: Dict[str, Any]) -> Dict[str, str]:
    """The administrator's install inputs: only the fields the pack asks for; secrets as references."""
    from sajha.accounts.providers import _is_ref
    raw = data.get('inputs') if isinstance(data.get('inputs'), dict) else data
    out: Dict[str, str] = {}
    for key in INSTALL_FIELDS:
        value = raw.get(key)
        if value in (None, ''):
            continue
        if key not in pack.install_fields:
            raise PackError(f'pack {pack.id} does not take {key}')
        out[key] = str(value).strip()
    if 'client_secret' in raw:
        raise PackError('give client_secret_ref (env:NAME, file:/path or db:...), never the secret itself')
    if out.get('client_secret_ref') and not _is_ref(out['client_secret_ref']):
        raise PackError('client_secret_ref must be a reference such as env:NAME, file:/path or db:table/key, '
                        'never the secret itself')
    return out


def _configured_raw() -> Dict[str, Dict[str, Any]]:
    from sajha.accounts.providers import _raw_provider_config
    try:
        return _raw_provider_config()
    except Exception:
        return {}


def _preset_fields(pack: Pack, inputs: Dict[str, str]) -> Dict[str, Any]:
    return {**pack.provider_fields, **inputs}


def _build_provider(pack: Pack, preset: Dict[str, Any]):
    """The Provider the registry would build after the install (the operator's YAML still wins)."""
    from sajha.accounts.presets import merge
    from sajha.accounts.providers import ProviderConfigError, build_provider
    configured = _configured_raw()
    merged = merge({pack.provider_id: preset}, {k: v for k, v in configured.items() if k == pack.provider_id})
    try:
        return build_provider(pack.provider_id, merged[pack.provider_id]), None
    except ProviderConfigError as e:
        return None, str(e)


def _host_ok(provider, url: str) -> Optional[str]:
    """None when an imported tool may send the user's token to ``url`` (https, on api_hosts)."""
    from sajha.accounts.http import TokenHostError, check_api_url
    try:
        check_api_url(provider, url)
        return None
    except TokenHostError as e:
        return str(e)


def _import_request(pack: Pack, with_auth: bool) -> Dict[str, Any]:
    api = pack.api
    scheme = str(api.get('security_scheme') or pack.provider_id)
    req: Dict[str, Any] = {
        'kind': 'openapi', 'text': pack.spec_text, 'url': '', 'prefix': api['prefix'],
        'base_url': api['base_url'], 'folder': str(api.get('folder') or api['prefix']),
        'selected': list(pack.operations), 'names': dict(api.get('names') or {}),
        'timeout_seconds': int(api.get('timeout_seconds') or 0),
        'rate_limit_per_minute': int(api.get('rate_limit_per_minute') or 0),
    }
    if with_auth:
        req['auth'] = {scheme: {'type': 'connected_account', 'provider': pack.provider_id,
                                'scopes': list(api.get('scopes') or [])}}
    return req


def _canonical_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def _redirect_uri(provider) -> str:
    try:
        from sajha.accounts.service import get_service
        return get_service().redirect_uri(provider)
    except Exception:
        return f'<public origin>/account/connections/{provider.id}/callback'


def _policy_preview(pack: Pack, user) -> Dict[str, Any]:
    try:
        from sajha.policy.engine import Call, get_engine
        from sajha.studio.describe import _caller
        d = get_engine().evaluate(Call(DEPLOY_ACTION, {'tool': f'pack:{pack.id}', 'kind': 'pack'}, _caller(user),
                                       'rest'))
        return {'deploy': d.to_dict()}
    except Exception as e:
        logger.debug(f'packs: policy preview failed: {e}')
        return {'error': str(e)}


def plan(pack_id: str, data: Optional[Dict[str, Any]] = None, registry=None, user=None,
         dirs: Optional[List[str]] = None) -> Dict[str, Any]:
    """Everything installing ``pack_id`` with these inputs would do, and the review hash."""
    from sajha.api_import import service as api_import
    data = dict(data or {})
    pack = get_pack(pack_id, dirs)
    inputs = _inputs(pack, data)
    errors: List[str] = []
    warnings: List[str] = []

    preset = _preset_fields(pack, inputs)
    provider, why = _build_provider(pack, preset)
    prov_view: Dict[str, Any] = {'id': pack.provider_id, 'fields': {k: v for k, v in preset.items()},
                                 'error': why or ''}
    if provider is None:
        errors.append(f'provider {pack.provider_id}: {why}')
    else:
        prov_view.update({'title': provider.title, 'configured': provider.configured,
                          'api_hosts': list(provider.api_hosts), 'scopes': list(provider.scopes),
                          'pkce': provider.pkce, 'authorize_url': provider.url('authorize_url'),
                          'token_url': provider.url('token_url'), 'redirect_uri': _redirect_uri(provider)})
        if not provider.configured:
            errors.append(f'provider {pack.provider_id} has no client id: give client_id (the OAuth app you '
                          f'registered with {provider.title}), or configure accounts.providers.{pack.provider_id}')
        bad_host = _host_ok(provider, pack.api['base_url'])
        if bad_host:
            errors.append(f"api.base_url: a user's token may not go there: {bad_host}")
        missing = [s for s in (pack.api.get('scopes') or []) if s not in provider.expand(provider.scopes)]
        if missing:
            warnings.append(f'the tools ask for scope(s) {", ".join(missing)} that the provider does not request '
                            f'by default; users are asked for them on first use (incremental consent)')
    configured = _configured_raw().get(pack.provider_id)
    if configured:
        warnings.append(f'accounts.providers.{pack.provider_id} is configured in application.yml; its fields '
                        f'override the pack preset')

    # the operations as API Import plans them (without the account binding: the provider may not exist yet)
    try:
        preview = api_import.plan(_import_request(pack, with_auth=False), registry)
    except api_import.APIImportError as e:
        raise PackError(f'pack {pack.id}: the bundled spec does not import: {e}', 409)
    ops = {o['key']: o for o in preview['operations']}
    rec = load_record(pack.id)
    operations = []
    for key in pack.operations:
        o = ops.get(key)
        if o is None:
            errors.append(f'operation {key} is not in the bundled spec')
            continue
        if o['unsupported']:
            errors.append(f"operation {key} cannot be imported: {o['unsupported']}")
        if o['conflict']:
            errors.append(f"tool name {o['name']} for {key} is already used by {o['conflict']}")
        operations.append({'key': key, 'name': o['name'], 'summary': o['summary'], 'status': o['status'],
                           'annotations': o['annotations'], 'conflict': o['conflict'],
                           'unsupported': o['unsupported'], 'input_schema': o['input_schema']})
    owner = (api_import.store.load(pack.api['prefix']) or {}) if not rec else {}
    if owner and not rec:
        errors.append(f"API Import prefix {pack.api['prefix']} is already used by an import that is not this pack")
    warnings += preview.get('warnings') or []
    request = _import_request(pack, with_auth=True)
    review = {
        'pack': pack.id, 'version': pack.version, 'spec_sha256': pack.spec_sha256,
        'provider': {'id': pack.provider_id, 'preset': preset},
        'import': {k: v for k, v in request.items() if k != 'text'},
        'operations': [(o['key'], o['name'], o['status']) for o in operations],
    }
    return {
        'success': True, 'pack': pack.summary(), 'provider': prov_view,
        'api': {'prefix': pack.api['prefix'], 'base_url': pack.api['base_url'], 'folder': request['folder'],
                'binding': request['auth'], 'operations': operations},
        'reinstall': rec is not None, 'installed': rec, 'licence': pack.source.get('licence'),
        'errors': errors, 'warnings': warnings, 'policy': _policy_preview(pack, user),
        'hash': _canonical_hash(review),
    }


# ── install / uninstall ─────────────────────────────────────────────

def _user_id(user) -> str:
    if isinstance(user, str):
        return user
    return str(getattr(user, 'user_id', '') or '')


def _policy_gate(pack: Pack, user) -> Optional[Dict[str, Any]]:
    """Describe a tool's deploy gate for ``pack:<id>`` of kind ``pack``; returns the grant used."""
    from sajha.studio.describe import DescribeError, _policy_gate as gate
    try:
        return gate({'name': f'pack:{pack.id}', 'kind': 'pack'}, user)
    except DescribeError as e:
        raise PackError(str(e), getattr(e, 'status', 403), **{k: v for k, v in (getattr(e, 'extra', {}) or {}).items()})


def _audit(user, what: str, details: Dict[str, Any]) -> None:
    try:
        from sajha.core.audit import AuditLogger
        AuditLogger().config_changed(f'packs.{what}', by_user=_user_id(user) or None,
                                     details=json.dumps(details, default=str)[:2000])
    except Exception as e:
        logger.debug(f'packs audit: {e}')


def _reload_providers() -> None:
    from sajha.accounts import presets
    from sajha.accounts.providers import set_registry
    presets.invalidate()
    set_registry(None)


def install(pack_id: str, data: Optional[Dict[str, Any]], reviewed_hash: str, approve: bool, registry=None,
            user=None, dirs: Optional[List[str]] = None) -> Dict[str, Any]:
    """Install exactly the reviewed plan. Every precondition is checked here, server side."""
    from sajha.accounts import presets
    from sajha.api_import import service as api_import
    if not approve:
        raise PackError('an install needs explicit approval (approve: true) after you have reviewed the plan')
    p = plan(pack_id, data, registry, user, dirs)
    if p['errors']:
        raise PackError('the plan has errors: ' + '; '.join(p['errors']), 409, plan=p)
    if str(reviewed_hash or '') != p['hash']:
        raise PackError('the plan changed since you reviewed it (the pack, its inputs or the tools it would '
                        'replace); review the current plan and install again', 409, hash=p['hash'])
    pack = get_pack(pack_id, dirs)
    grant = _policy_gate(pack, user)
    uid = _user_id(user)
    previous = presets.load(pack.provider_id)
    rec = load_record(pack.id)
    presets.save(pack.provider_id, p['provider']['fields'], pack=pack.id, user=uid)
    _reload_providers()
    try:
        result = api_import.deploy(_import_request(pack, with_auth=True), registry, uid)
    except Exception as e:
        _restore(pack, previous)
        _audit(user, 'install_failed', {'pack': pack.id, 'error': str(e)})
        if isinstance(e, api_import.APIImportError):
            raise PackError(f'the import failed, nothing was installed: {e}', 409)
        raise
    if not result.get('success'):
        if not result.get('deployed') and not result.get('updated'):
            _restore(pack, previous)
        _audit(user, 'install_failed', {'pack': pack.id, 'failed': result.get('failed')})
        raise PackError('some tools did not load: ' + '; '.join(f"{f['name']}: {f['error']}"
                                                                for f in result.get('failed') or []),
                        409, result=result)
    now = datetime.now(timezone.utc).isoformat()
    record = {'pack': pack.id, 'version': pack.version, 'hash': p['hash'], 'spec_sha256': pack.spec_sha256,
              'provider': pack.provider_id,
              'preset_created': (rec or {}).get('preset_created', previous is None),
              'api_id': pack.api['prefix'], 'tools': sorted(o['name'] for o in p['api']['operations']),
              'installed_at': now, 'installed_by': uid, 'approval': (grant or {}).get('id'),
              'first_installed_at': (rec or {}).get('first_installed_at') or now}
    _save_record(record)
    _audit(user, 'install', {'pack': pack.id, 'version': pack.version, 'hash': p['hash'], 'provider': pack.provider_id,
                             'tools': record['tools'], 'approval': record['approval']})
    return {'success': True, 'pack': pack.id, 'record': record, 'import': result,
            'message': f"Installed {pack.title}: provider {pack.provider_id} and {len(record['tools'])} tool(s). "
                       f"Users link their account on Connected accounts; register "
                       f"{p['provider'].get('redirect_uri', 'the redirect URI')} with {pack.title}."}


def _restore(pack: Pack, previous: Optional[Dict[str, Any]]) -> None:
    from sajha.accounts import presets
    try:
        if previous is None:
            presets.delete(pack.provider_id)
        else:
            presets.save(pack.provider_id, previous.get('fields') or {}, pack=previous.get('pack') or '',
                         user=previous.get('installed_by') or '')
    finally:
        _reload_providers()


def uninstall(pack_id: str, registry=None, user=None) -> Dict[str, Any]:
    """Remove an installed pack's tools (its API Import) and the provider preset it created.
    Users' linked accounts stay in the vault until they or an administrator unlink them."""
    from sajha.accounts import presets
    from sajha.api_import import service as api_import
    rec = load_record(pack_id)
    if not rec:
        raise PackError(f'pack {pack_id!r} is not installed', 404)
    removed: List[str] = []
    if api_import.store.load(rec.get('api_id') or ''):
        removed = api_import.delete_api(rec['api_id'], registry).get('removed') or []
    preset_removed = False
    pid = rec.get('provider') or ''
    doc = presets.load(pid) if pid else None
    if doc and doc.get('pack') == pack_id and rec.get('preset_created', True):
        preset_removed = presets.delete(pid)
        _reload_providers()
    _delete_record(pack_id)
    _audit(user, 'uninstall', {'pack': pack_id, 'removed': removed, 'preset_removed': preset_removed})
    return {'success': True, 'pack': pack_id, 'removed': removed, 'preset_removed': preset_removed,
            'message': f'{pack_id}: removed {len(removed)} tool(s)' + (' and the provider preset' if preset_removed else '')}

