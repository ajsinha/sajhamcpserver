"""
SAJHA MCP Studio — the "LLM tool" creator: a form for the ``llm`` block, in and out of a config.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

    build_config(form)     the page's form -> a complete tool config (schemas generated per mode)
    form_from_config(cfg)  an existing LLM tool's config -> the form (to edit it)
    check(cfg)             the loader's own messages (parse_llm_block), lint, the live allow/deny
                           matching, the effective limits within the ai.llm_tools.* ceilings
    test_run(cfg, args)    one run against the mock model (ai.planners.dry_run_model); tools that
                           are not read-only are not run
    deploy(cfg, auth)      writes config/tools/<name>.json (a new tool, or an edit of one the
                           caller may change) and loads it into the live registry

The config is an ordinary LLM tool (docs/architecture/LLM Tools.md §5); nothing here is a
second validator: every rule comes from ``sajha.ai.llm_tools.config``. Guide:
docs/studio/MCP Studio LLM Tool Creator Guide.md.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

NAME_RE = re.compile(r'^[a-z][a-z0-9_]{2,63}$')
FIELD_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
FIELD_TYPES = ('string', 'number', 'integer', 'boolean', 'array', 'object')
INSTRUCTIONS = ('system_prompt', 'prompt', 'none')


class BuildError(ValueError):
    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


# ── small readers ────────────────────────────────────────────────────

def _registry():
    try:
        from sajha.app import tools_registry
        return tools_registry
    except Exception:
        return None


def _prompts_registry():
    try:
        from sajha.core.prompts_registry import PromptsRegistry
        return PromptsRegistry._instance
    except Exception:
        return None


def _gateway():
    """The running LLM factory (public ``sajha.ai.llm`` API), or None when the layer is off."""
    try:
        from sajha.ai.llm import llm_factory
        return llm_factory()
    except Exception:
        return None


def _str_list(v: Any) -> List[str]:
    if isinstance(v, str):
        v = re.split(r'[,\n]', v)
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()]


def _num(v: Any) -> Optional[float]:
    if v in (None, '') or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else f


def _bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, str):
        return v.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(v)


# ── what the form offers ─────────────────────────────────────────────

def options() -> Dict[str, Any]:
    """Everything the page's selects need: modes, model aliases, planners, prompts, ceilings."""
    from sajha.ai.llm_tools.config import KEYS, LIMIT_KEYS, MEMORY_MODES, MODES, settings
    s = settings()
    gw = _gateway()
    aliases = sorted((getattr(getattr(gw, 'settings', None), 'aliases', {}) or {}).keys()) if gw else []
    planners: List[Dict[str, Any]] = []
    try:
        from sajha.ai.planners_engine import get_registry
        reg = get_registry()
        for p in reg.describe():
            planners.append({'name': p['name'], 'versions': p.get('versions') or [], 'use_when': p.get('use_when') or ''})
        planner_default = reg.settings.default
    except Exception as e:
        logger.debug(f'llm creator: planners unavailable: {e}')
        planner_default = 'react'
    prompts = []
    preg = _prompts_registry()
    if preg is not None:
        try:
            prompts = sorted(getattr(preg, 'prompts', {}) or {})
        except Exception:
            prompts = []
    return {
        'modes': list(MODES),
        'mode_keys': {k: list(v) if v else None for k, v in KEYS.items()},
        'memory_modes': list(MEMORY_MODES),
        'aliases': aliases or ['default', 'fast', 'reasoning'],
        'default_model': s.default_model,
        'planners': planners,
        'planner_default': planner_default,
        'prompts': prompts,
        'limit_keys': list(LIMIT_KEYS),
        'ceilings': {k: getattr(s.limits, k) for k in LIMIT_KEYS},
        'field_types': list(FIELD_TYPES),
        'dry_run_model': _dry_run_model(),
    }


def _dry_run_model() -> str:
    try:
        from sajha.ai.planners_engine.settings import planner_settings
        return planner_settings().dry_run_model
    except Exception:
        return 'mock/mock-planner'


# ── form -> config ───────────────────────────────────────────────────

def _field_schema(f: Dict[str, Any]) -> Dict[str, Any]:
    t = f.get('type') if f.get('type') in FIELD_TYPES else 'string'
    out: Dict[str, Any] = {'type': t}
    if t == 'array':
        out['items'] = {'type': 'string'}
    if f.get('description'):
        out['description'] = str(f['description'])[:500]
    if isinstance(f.get('enum'), list) and f['enum']:
        out['enum'] = [str(x) for x in f['enum']]
    return out


def _placeholders(text: str) -> List[str]:
    from sajha.ai.llm_tools.config import placeholders
    return placeholders(text or '')


def generated_schemas(form: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(inputSchema, outputSchema) for the form's mode: the fields the mode needs, the author's own
    input fields, and every ``{{input.x}}`` the template or prompt arguments use."""
    mode = str(form.get('mode') or 'answer')
    props: Dict[str, Any] = {}
    required: List[str] = []
    mem = form.get('memory') if isinstance(form.get('memory'), dict) else {}
    mem_mode = str(mem.get('mode') or 'none')
    if mode in ('answer', 'grounded'):
        props['question'] = {'type': 'string', 'description': 'The question, in plain words.'}
        required.append('question')
    for f in form.get('inputs') or []:
        if isinstance(f, dict) and FIELD_RE.match(str(f.get('name') or '')) and f['name'] not in props:
            props[f['name']] = _field_schema(f)
            if _bool(f.get('required'), True):
                required.append(f['name'])
    texts = [str(form.get('template') or '')]
    args = form.get('prompt_arguments') if isinstance(form.get('prompt_arguments'), dict) else {}
    texts += [str(v) for v in args.values()]
    src = form.get('source') if isinstance(form.get('source'), dict) else {}
    if isinstance(src.get('arguments'), dict):
        texts += [json.dumps(src['arguments'])]
    for t in texts:
        for ph in _placeholders(t):
            if ph not in props:
                props[ph] = {'type': 'string', 'description': f'Fills {{{{input.{ph}}}}}.'}
                required.append(ph)
    if mem_mode == 'conversation' and mode in ('answer', 'grounded'):
        props['conversation_id'] = {'type': 'string',
                                    'description': 'From a previous answer, to continue that conversation.'}
    if (mem_mode == 'client' or _bool(mem.get('accept_client_history'))) and mode in ('answer', 'grounded'):
        props['messages'] = {'type': 'array', 'items': {'type': 'object'},
                             'description': 'Earlier turns the client keeps ({role, content}).'}
    if mode == 'answer' and _str_list(form.get('tools_allow')) and str(form.get('confirm') or 'ask') == 'ask':
        props['confirm'] = {'type': 'array', 'items': {'type': 'string'},
                            'description': 'Fingerprints of destructive calls the user confirmed.'}
    in_schema = {'type': 'object', 'properties': props, 'required': list(dict.fromkeys(required))}

    out: Dict[str, Any] = {}
    out_req: List[str] = []
    if mode in ('answer', 'grounded'):
        out = {'answer': {'type': 'string'}, 'confidence': {'type': 'number'},
               'citations': {'type': 'array', 'items': {'type': 'string'}},
               'caveats': {'type': 'array', 'items': {'type': 'string'}}}
        if mem_mode == 'conversation':
            out['conversation_id'] = {'type': 'string'}
        if mode == 'answer':
            out['pending'] = {'type': 'array'}
            out['error'] = {'type': 'string'}
        out_req = ['answer']
    elif mode == 'complete':
        out, out_req = {'text': {'type': 'string'}}, ['text']
    elif mode == 'narrate':
        out, out_req = {'text': {'type': 'string'}, 'data': {}}, ['text']
    elif mode == 'classify':
        labels = _str_list(form.get('labels'))
        out = {'label': {'type': 'string', 'enum': labels}, 'reason': {'type': 'string'},
               'confidence': {'type': 'number'}}
        out_req = ['label']
    elif mode == 'extract':
        for f in form.get('fields') or []:
            if isinstance(f, dict) and FIELD_RE.match(str(f.get('name') or '')):
                out[f['name']] = _field_schema(f)
                if _bool(f.get('required'), False):
                    out_req.append(f['name'])
    elif mode == 'judge':
        out = {'scores': {'type': 'object'}, 'overall': {'type': 'number'}, 'verdict': {'type': 'string'},
               'reasons': {'type': 'object'}, 'summary': {'type': 'string'}}
        out_req = ['scores', 'verdict']
    out['stopped_by'] = {'type': 'string'}
    out_schema = {'type': 'object', 'properties': out, 'required': out_req + ['stopped_by']}
    return in_schema, out_schema


def build_config(form: Dict[str, Any], version: str = '1.0.0') -> Dict[str, Any]:
    """The tool config the form describes. Unset keys are left out, so the loader's defaults apply."""
    from sajha.ai.llm_tools.config import IMPLEMENTATION, KEYS, LIMIT_KEYS
    if not isinstance(form, dict):
        raise BuildError('the form must be a JSON object')
    mode = str(form.get('mode') or 'answer')
    llm: Dict[str, Any] = {'mode': mode}

    def applies(key: str) -> bool:
        allowed = KEYS.get(key)
        return allowed is None or mode in allowed

    if form.get('model'):
        llm['model'] = str(form['model']).strip()
    kind = str(form.get('instructions') or 'system_prompt')
    if kind == 'prompt' and form.get('prompt_name'):
        args = form.get('prompt_arguments') if isinstance(form.get('prompt_arguments'), dict) else {}
        llm['prompt'] = {'name': str(form['prompt_name']).strip(), 'arguments': {str(k): v for k, v in args.items()}}
    elif kind == 'system_prompt' and str(form.get('system_prompt') or '').strip():
        llm['system_prompt'] = str(form['system_prompt'])
    if applies('template') and str(form.get('template') or '').strip():
        llm['template'] = str(form['template'])
    if applies('tools'):
        allow, deny = _str_list(form.get('tools_allow')), _str_list(form.get('tools_deny'))
        if allow or deny:
            llm['tools'] = {'allow': allow, 'deny': deny}
        if str(form.get('confirm') or 'ask') == 'refuse':
            llm['confirm'] = 'refuse'
    if applies('planner') and str(form.get('planner') or '').strip():
        llm['planner'] = str(form['planner']).strip()
    if applies('planner_choices'):
        choices = _str_list(form.get('planner_choices'))
        if choices:
            llm['planner_choices'] = choices
    if applies('rag'):
        sources = _str_list(form.get('rag_sources'))
        top_k = _num(form.get('rag_top_k'))
        if sources or top_k:
            llm['rag'] = {**({'sources': sources} if sources else {}), **({'top_k': int(top_k)} if top_k else {})}
    if applies('source'):
        src = form.get('source') if isinstance(form.get('source'), dict) else {}
        kind_ = 'workflow' if src.get('workflow') else 'composite'
        target = str(src.get(kind_) or '').strip()
        if target:
            llm['source'] = {kind_: target}
            if isinstance(src.get('arguments'), dict) and src['arguments']:
                llm['source']['arguments'] = src['arguments']
    if applies('rubric'):
        rub = form.get('rubric') if isinstance(form.get('rubric'), dict) else {}
        crit = []
        for c in rub.get('criteria') or []:
            if not isinstance(c, dict) or not str(c.get('name') or '').strip():
                continue
            item: Dict[str, Any] = {'name': str(c['name']).strip()}
            if c.get('description'):
                item['description'] = str(c['description'])
            for k in ('min', 'max', 'weight'):
                n = _num(c.get(k))
                if n is not None:
                    item[k] = int(n) if k != 'weight' else n
            crit.append(item)
        if crit:
            llm['rubric'] = {'criteria': crit}
            ps = _num(rub.get('pass_score'))
            if ps is not None:
                llm['rubric']['pass_score'] = ps
    limits = {}
    for k in LIMIT_KEYS:
        n = _num((form.get('limits') or {}).get(k)) if isinstance(form.get('limits'), dict) else None
        if n is not None:
            limits[k] = n
    if limits:
        llm['limits'] = limits
    mem = form.get('memory') if isinstance(form.get('memory'), dict) else {}
    mm = str(mem.get('mode') or 'none')
    if mm != 'none' or _bool(mem.get('accept_client_history')):
        block: Dict[str, Any] = {'mode': mm}
        for k in ('ttl_minutes', 'max_turns'):
            n = _num(mem.get(k))
            if n is not None:
                block[k] = int(n)
        if _bool(mem.get('accept_client_history')):
            block['accept_client_history'] = True
        llm['memory'] = block
    sampling = str(form.get('sampling') or 'never')
    if sampling != 'never':
        llm['sampling'] = sampling
    out = form.get('output') if isinstance(form.get('output'), dict) else {}
    if out and (not _bool(out.get('citations'), True) or _bool(out.get('steps'))):
        llm['output'] = {'citations': _bool(out.get('citations'), True), 'steps': _bool(out.get('steps'))}
    if _bool(form.get('nesting_allow')):
        llm['nesting'] = {'allow': True}
    t = _num(form.get('temperature'))
    if t is not None:
        llm['temperature'] = t
    if applies('cache') and _bool(form.get('cache')):
        llm['cache'] = True

    in_schema, out_schema = generated_schemas(form)
    if isinstance(form.get('input_schema'), dict) and form['input_schema'].get('properties'):
        in_schema = copy.deepcopy(form['input_schema'])         # the author's own (edited) schema wins
    if isinstance(form.get('output_schema'), dict) and form['output_schema'].get('properties'):
        out_schema = copy.deepcopy(form['output_schema'])
    tags = _str_list(form.get('tags')) or ['llm-tool']
    config: Dict[str, Any] = {
        'name': str(form.get('name') or '').strip().lower(),
        'implementation': IMPLEMENTATION,
        'description': str(form.get('description') or '').strip(),
        'version': str(form.get('version') or version),
        'enabled': _bool(form.get('enabled'), True),
        'inputSchema': in_schema,
        'outputSchema': out_schema,
        'llm': llm,
        'metadata': {'category': str(form.get('category') or 'Intelligence').strip() or 'Intelligence',
                     'tags': tags, 'source': 'MCP Studio (LLM tool creator)'},
    }
    return config


def form_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """The form for an existing LLM tool (what the page shows to edit it)."""
    llm = dict(config.get('llm') or {})
    md = config.get('metadata') if isinstance(config.get('metadata'), dict) else {}
    tools = llm.get('tools') if isinstance(llm.get('tools'), dict) else {}
    prompt = llm.get('prompt') if isinstance(llm.get('prompt'), dict) else None
    mem = llm.get('memory') if isinstance(llm.get('memory'), dict) else {}
    rag = llm.get('rag') if isinstance(llm.get('rag'), dict) else {}
    ins = (config.get('inputSchema') or {}).get('properties') or {}
    req = set((config.get('inputSchema') or {}).get('required') or [])
    auto = {'question', 'conversation_id', 'messages', 'confirm', 'planner'}
    outs = (config.get('outputSchema') or {}).get('properties') or {}
    out_req = set((config.get('outputSchema') or {}).get('required') or [])
    from sajha.ai.llm_tools.config import META_FIELDS, label_enum
    return {
        'name': config.get('name', ''), 'description': config.get('description', ''),
        'version': config.get('version', '1.0.0'), 'enabled': config.get('enabled', True),
        'category': md.get('category', 'Intelligence'), 'tags': list(md.get('tags') or []),
        'mode': llm.get('mode', 'answer'), 'model': llm.get('model', ''),
        'instructions': 'prompt' if prompt else ('system_prompt' if llm.get('system_prompt') else 'none'),
        'system_prompt': llm.get('system_prompt', ''),
        'prompt_name': (prompt or {}).get('name', ''), 'prompt_arguments': (prompt or {}).get('arguments', {}),
        'template': llm.get('template', ''),
        'tools_allow': list(tools.get('allow') or []), 'tools_deny': list(tools.get('deny') or []),
        'confirm': llm.get('confirm', 'ask'), 'nesting_allow': bool((llm.get('nesting') or {}).get('allow')),
        'planner': llm.get('planner') if isinstance(llm.get('planner'), str) else '',
        'planner_object': llm.get('planner') if isinstance(llm.get('planner'), dict) else None,
        'planner_choices': list(llm.get('planner_choices') or []),
        'rag_sources': list(rag.get('sources') or []), 'rag_top_k': rag.get('top_k'),
        'source': llm.get('source') or {}, 'rubric': llm.get('rubric') or {},
        'limits': dict(llm.get('limits') or {}),
        'memory': {'mode': mem.get('mode', 'none'), 'ttl_minutes': mem.get('ttl_minutes'),
                   'max_turns': mem.get('max_turns'), 'accept_client_history': bool(mem.get('accept_client_history'))},
        'sampling': llm.get('sampling', 'never'),
        'output': {'citations': (llm.get('output') or {}).get('citations', True),
                   'steps': (llm.get('output') or {}).get('steps', False)},
        'temperature': llm.get('temperature'), 'cache': bool(llm.get('cache')),
        'labels': label_enum(config.get('outputSchema')),
        'inputs': [{'name': k, 'type': (v or {}).get('type', 'string') if isinstance(v, dict) else 'string',
                    'description': (v or {}).get('description', '') if isinstance(v, dict) else '',
                    'required': k in req} for k, v in ins.items() if k not in auto],
        'fields': [{'name': k, 'type': (v or {}).get('type', 'string') if isinstance(v, dict) else 'string',
                    'description': (v or {}).get('description', '') if isinstance(v, dict) else '',
                    'required': k in out_req} for k, v in outs.items() if k not in META_FIELDS and k != 'stopped_by'],
        'input_schema': config.get('inputSchema'), 'output_schema': config.get('outputSchema'),
    }


# ── checks ───────────────────────────────────────────────────────────

def match_preview(allow: List[str], deny: List[str], self_name: str = '', nesting_allow: bool = False,
                  confirm: str = 'ask', registry=None) -> Dict[str, Any]:
    """Live matching of ``tools.allow`` / ``tools.deny`` against the catalog: what the tool may call
    (before the caller's own access narrows it), and what each pattern matches."""
    from sajha.ai.llm_tools.config import LLMSpec, _matches, allowed_names, is_llm_tool
    reg = registry if registry is not None else _registry()
    tools = (getattr(reg, 'tools', {}) or {}) if reg is not None else {}
    spec = LLMSpec(mode='answer', allow=list(allow or []), deny=list(deny or []), nesting_allow=nesting_allow,
                   confirm=confirm if confirm in ('ask', 'refuse') else 'ask')
    allowed = allowed_names(spec, self_name, reg) if reg is not None else []
    patterns = []
    for p in spec.allow:
        names = sorted(n for n in tools if n != self_name and _matches(n, [p]))
        patterns.append({'pattern': p, 'kind': 'allow', 'matches': len(names), 'sample': names[:8]})
    for p in spec.deny:
        names = sorted(n for n in tools if _matches(n, [p]) and _matches(n, spec.allow))
        patterns.append({'pattern': p, 'kind': 'deny', 'matches': len(names), 'sample': names[:8]})
    excluded = []
    for n in sorted(tools):
        if n == self_name or not _matches(n, spec.allow) or n in allowed:
            continue
        why = 'denied' if _matches(n, spec.deny) else (
            'an LLM tool (nesting.allow is off)' if is_llm_tool(tools[n]) and not spec.nesting_allow else
            'destructive (confirm: refuse)')
        excluded.append({'name': n, 'why': why})
    return {'allowed': allowed, 'count': len(allowed), 'patterns': patterns, 'excluded': excluded[:50],
            'catalog': len(tools)}


def check(config: Dict[str, Any], registry=None, editing: bool = False) -> Dict[str, Any]:
    """Validate a config exactly as the loader will: {errors, warnings, lint, limits, annotations, matching}."""
    from sajha.ai.llm_tools.config import (LLMConfigError, derived_annotations, lint_findings, parse_llm_block,
                                           settings)
    reg = registry if registry is not None else _registry()
    errors: List[str] = []
    warnings: List[str] = []
    name = str(config.get('name') or '')
    from sajha.tools.naming import reserved_name_problem
    if not NAME_RE.match(name):
        errors.append('name must be 3-64 characters: a lowercase letter, then lowercase letters, digits or underscores')
    elif reserved_name_problem(name):
        errors.append(reserved_name_problem(name))
    elif not editing and _taken(name, reg):
        errors.append(f'a tool named {name} exists already')
    if not str(config.get('description') or '').strip():
        errors.append('description is empty: it is what callers and models read to choose the tool')
    spec = None
    try:
        spec = parse_llm_block(config, _prompts_registry())
    except LLMConfigError as e:
        errors.extend(e.problems)
    except Exception as e:                 # never a 500 for a bad form
        errors.append(f'{e.__class__.__name__}: {e}')
    out: Dict[str, Any] = {'errors': errors, 'warnings': warnings, 'lint': [], 'limits': None, 'annotations': None,
                           'matching': None, 'valid': False}
    if spec is not None:
        lim = spec.effective_limits(settings())
        asked = dict(spec.limits)
        out['limits'] = {'effective': lim.to_dict(), 'asked': asked,
                         'clamped': sorted(k for k, v in asked.items() if v > getattr(settings().limits, k))}
        for k in out['limits']['clamped']:
            warnings.append(f'llm.limits.{k} ({asked[k]}) is above the server ceiling '
                            f'ai.llm_tools.limits.{k} ({getattr(settings().limits, k)}); the ceiling applies')
        if reg is not None:
            out['annotations'] = derived_annotations(spec, name, reg)
            for level, rule, msg in lint_findings(name, config, reg):
                out['lint'].append({'level': level, 'rule': rule, 'message': msg})
                if level == 'error' and msg not in errors:
                    errors.append(msg)
        if spec.mode == 'answer':
            out['matching'] = match_preview(spec.allow, spec.deny, name, spec.nesting_allow, spec.confirm, reg)
    out['valid'] = not errors
    return out


def _taken(name: str, registry=None) -> bool:
    from pathlib import Path
    reg = registry if registry is not None else _registry()
    if reg is not None and (name in getattr(reg, 'tools', {}) or name in getattr(reg, 'tool_configs', {})):
        return True
    from sajha.routes.studio_routes import CONFIG_DIR
    return (Path(CONFIG_DIR) / f'{name}.json').exists()


# ── test run ─────────────────────────────────────────────────────────

def test_run(config: Dict[str, Any], arguments: Dict[str, Any], auth: Any = None, registry=None,
             run_all: bool = False) -> Dict[str, Any]:
    """One run of the (unsaved) tool against the mock model. Every tool the tool and the caller allow
    is offered; only read-only ones run (others answer "not run", as in the planner dry run) unless
    ``run_all``, which runs every allowed tool the caller may execute. Nothing is remembered or audited."""
    from sajha.ai.llm import RequestContext
    from sajha.ai.llm_tools import LLMConfigError, LLMTool
    from sajha.ai.planners_engine.dryrun import _DryRegistry
    reg = registry if registry is not None else _registry()
    try:
        tool = LLMTool(copy.deepcopy(config))
    except LLMConfigError as e:
        raise BuildError('the config does not load: ' + '; '.join(e.problems))
    if not isinstance(arguments, dict):
        raise BuildError('arguments must be a JSON object')
    try:
        import jsonschema
        jsonschema.validate(arguments, tool.get_input_schema())
    except ImportError:
        pass
    except Exception as e:
        raise BuildError(f'the arguments do not match the input schema: {str(e).splitlines()[0]}')
    if reg is not None:
        # as the planner dry run does: every allowed tool is offered, only read-only ones run
        run = [n for n in tool.allowed_tools() if auth is not None and auth.has_tool_access(n)] if run_all else []
        dry = _DryRegistry(reg, run)
        tool.registry = dry
        try:
            from sajha.ai.intelligence import IntelligenceService, get_intelligence
            svc = get_intelligence()
            if svc is not None:
                tool.service = IntelligenceService(svc.gateway, dry, settings=svc.settings, audit=lambda e: None,
                                                   memory=getattr(svc, '_memory', None))
        except Exception as e:
            logger.debug(f'llm creator: dry service unavailable: {e}')

    def can_use(name: str) -> bool:
        return bool(auth.has_tool_access(name)) if auth is not None else False

    ctx = RequestContext(user_id=str(getattr(auth, 'user_id', '') or ''), roles=list(getattr(auth, 'roles', None) or []),
                         is_admin=bool(getattr(auth, 'is_admin', False)), can_use_tool=can_use)
    model = _dry_run_model()
    t0 = time.time()
    try:
        info = tool.run(dict(arguments), ctx=ctx, model=model, remember=False, audit=False)
    except Exception as e:
        return {'ok': False, 'error': f'{e.__class__.__name__}: {e}'[:1000], 'model': model,
                'duration_ms': int((time.time() - t0) * 1000)}
    usage = info.usage
    return {
        'ok': not getattr(info.result, 'is_error', False),
        'result': json.loads(json.dumps(dict(info.result or {}), default=str)),
        'stopped_by': info.stopped_by, 'steps': [_step(s) for s in (info.steps or [])][:50],
        'planner': info.planner or None, 'planner_path': list(info.planner_path or []),
        'models': list(info.models or []), 'model': model, 'duration_ms': info.duration_ms,
        'usage': {k: getattr(usage, k, None) for k in ('input_tokens', 'output_tokens', 'cost_usd')} if usage else None,
    }


def _step(s: Any) -> Dict[str, Any]:
    if isinstance(s, str):
        return {'name': s, 'ok': True}
    return {'name': str(getattr(s, 'name', '') or s), 'ok': bool(getattr(s, 'ok', True)),
            'summary': str(getattr(s, 'summary', '') or '')[:300]}


# ── save ─────────────────────────────────────────────────────────────

def existing(name: str, registry=None) -> Optional[Dict[str, Any]]:
    """The config of an LLM tool by name (registry first, then the file), or None."""
    from pathlib import Path
    reg = registry if registry is not None else _registry()
    cfg = (getattr(reg, 'tool_configs', {}) or {}).get(name) if reg is not None else None
    if not cfg:
        from sajha.routes.studio_routes import CONFIG_DIR
        f = Path(CONFIG_DIR) / f'{name}.json'
        if f.exists():
            try:
                cfg = json.loads(f.read_text(encoding='utf-8'))
            except Exception:
                cfg = None
    if isinstance(cfg, dict) and isinstance(cfg.get('llm'), dict):
        return copy.deepcopy(cfg)
    return None


def list_tools(auth: Any = None, registry=None) -> List[Dict[str, Any]]:
    """Every LLM tool config the registry knows, with whether the caller may edit it."""
    from sajha.auth import is_owner
    from sajha.studio.ownership import creator_of
    reg = registry if registry is not None else _registry()
    out = []
    for name, cfg in sorted(((getattr(reg, 'tool_configs', {}) or {}) if reg is not None else {}).items()):
        if not isinstance(cfg, dict) or not isinstance(cfg.get('llm'), dict):
            continue
        by = creator_of(cfg)
        out.append({'name': name, 'mode': cfg['llm'].get('mode'), 'description': str(cfg.get('description') or '')[:160],
                    'created_by': by or None, 'loaded': name in getattr(reg, 'tools', {}),
                    'error': (getattr(reg, 'tool_errors', {}) or {}).get(name), 'enabled': cfg.get('enabled', True),
                    'editable': is_owner(auth, by)})
    return out


def deploy(config: Dict[str, Any], auth: Any, edit: bool = False, registry=None) -> Dict[str, Any]:
    """Write the config and load it. ``edit`` replaces an existing LLM tool the caller may change
    (its creator is kept; the old file comes back if the new one does not load)."""
    from pathlib import Path
    from sajha.core.storage import get_storage, write_tool_config
    from sajha.routes.studio_routes import CONFIG_DIR, _hot_load, _unload
    from sajha.studio.ownership import creator_of, refusal, stamp
    reg = registry if registry is not None else _registry()
    name = str(config.get('name') or '')
    previous = existing(name, reg) if NAME_RE.match(name) else None
    if edit:
        if previous is None:
            raise BuildError(f'no LLM tool named {name} to change', 404)
        refused = refusal(auth, creator_of(previous), name)
        if refused:
            raise BuildError(refused, 403)
        md = config.setdefault('metadata', {})
        for k in ('created_by', 'studio_creator', 'author', 'email', 'copyright'):
            if (previous.get('metadata') or {}).get(k) and not md.get(k):
                md[k] = previous['metadata'][k]
    result = check(config, reg, editing=edit)
    if result['errors']:
        raise BuildError('the tool has errors; fix them first', 400, check=result)
    stamp(config, str(getattr(auth, 'user_id', '') or ''), 'llm')
    config.setdefault('metadata', {})['updated_by'] = str(getattr(auth, 'user_id', '') or '')
    path = Path(CONFIG_DIR) / f'{name}.json'
    old_text = None
    if edit and path.exists():
        old_text = path.read_text(encoding='utf-8')
    write_tool_config(path, json.dumps(config, indent=2) + '\n')
    loaded, err = _hot_load(name)
    if not loaded:
        if old_text is not None:
            write_tool_config(path, old_text)
            _hot_load(name)
        else:
            try:
                get_storage().delete(f'config/tools/{name}.json')
            except Exception:
                pass
            if path.exists():
                path.unlink()
            _unload(name)
        raise BuildError(f'the tool was written but failed to load, so it was {"restored" if old_text else "removed"}: '
                         f'{err}', 500)
    _audit(auth, 'edit' if edit else 'deploy', {'name': name, 'mode': config['llm'].get('mode')})
    return {'name': name, 'file': f'config/tools/{name}.json', 'edited': edit, 'check': result,
            'message': f'{"Saved" if edit else "Deployed"} {name}; it is callable now.'}


def _audit(auth: Any, what: str, details: Dict[str, Any]) -> None:
    try:
        from sajha.core.audit import AuditLogger
        AuditLogger().config_changed(f'studio.llm.{what}', by_user=getattr(auth, 'user_id', None),
                                     details=json.dumps(details, default=str)[:2000])
    except Exception as e:
        logger.debug(f'llm creator audit: {e}')
