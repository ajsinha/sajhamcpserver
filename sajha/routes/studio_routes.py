"""
SAJHA MCP Server v3 — Studio Routes (Tool Development)
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

``router`` combines two routers (app.py includes ``router``):

* ``pages`` (``/studio``) serves the Studio pages.
* ``actions`` (``/admin/studio``) serves the JSON endpoints those pages post to:
  analyze / preview / deploy for each creator, and delete.

Every route is admin only. A deploy writes the generated files (Python module
first, JSON config last) and then loads the new tool into the live registry, so
it is callable over MCP at once; if it fails to load, the files are removed and
the load error is returned. Delete removes only tools Studio generated.
"""

import importlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from sajha.app import render
from sajha.auth import AuthContext, require_admin

logger = logging.getLogger(__name__)

pages = APIRouter(prefix='/studio', tags=['studio'])
actions = APIRouter(prefix='/admin/studio', tags=['studio'])

#: Repository root (…/sajha/routes/studio_routes.py → three levels up)
BASE_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = BASE_DIR / 'config' / 'tools'
SCRIPTS_DIR = BASE_DIR / 'config' / 'scripts'
IMPL_DIR = BASE_DIR / 'sajha' / 'tools' / 'impl'
OLAP_DIR = BASE_DIR / 'config' / 'olap'

TOOL_NAME_RE = re.compile(r'^[a-z][a-z0-9_]{2,63}$')
#: Implementation module prefixes the Studio generators write (``<prefix><tool_name>``)
STUDIO_MODULE_PREFIXES = ('studio_', 'rest_', 'dbquery_', 'powerbi_', 'powerbidax_', 'livelink_')
STUDIO_MARKER = 'MCP Studio'


def _version() -> str:
    try:
        from sajha.core.config import get_settings
        return get_settings().app_version
    except Exception:
        return '6.0.0'


def _registry():
    from sajha.app import tools_registry
    return tools_registry


def _existing_tools() -> List[str]:
    reg = _registry()
    return list(reg.tools.keys()) if reg else []


def _ok(**kw) -> JSONResponse:
    return JSONResponse({'success': True, **kw})


def _fail(error: str, status: int = 400, **kw) -> JSONResponse:
    return JSONResponse({'success': False, 'error': error, **kw}, status_code=status)


async def _body(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _check_new_name(name: str) -> Optional[str]:
    """Error message for an invalid or taken tool name, else None."""
    if not TOOL_NAME_RE.match(name or ''):
        return ('Tool name must be 3-64 characters: a lowercase letter, then lowercase '
                'letters, digits or underscores')
    if name in _existing_tools() or (CONFIG_DIR / f'{name}.json').exists():
        return f'Tool "{name}" already exists'
    return None


# ── Registry hot-load / unload ───────────────────────────────────────────

def _impl_module(config: Dict[str, Any]) -> Optional[str]:
    impl = config.get('implementation')
    if isinstance(impl, str) and '.' in impl:
        return impl.rsplit('.', 1)[0]
    if isinstance(impl, dict):  # legacy script-tool config
        return f"sajha.tools.impl.{config.get('name')}_script_tool"
    return None


def _hot_load(tool_name: str) -> Tuple[bool, str]:
    """Load config/tools/<tool_name>.json into the live registry."""
    reg = _registry()
    if reg is None:
        return False, 'Tools registry is not initialised'
    importlib.invalidate_caches()
    try:
        cfg = json.loads((CONFIG_DIR / f'{tool_name}.json').read_text(encoding='utf-8'))
        mod = _impl_module(cfg)
        # A module of the same name may be cached from an earlier (deleted) deploy
        if mod and mod.rsplit('.', 1)[-1].startswith(STUDIO_MODULE_PREFIXES + (tool_name,)):
            sys.modules.pop(mod, None)
    except Exception:
        pass
    reg.load_tool_from_config(f'{tool_name}.json')
    if tool_name in reg.tools:
        return True, ''
    return False, reg.tool_errors.get(tool_name, 'Tool did not load')


def _unload(tool_name: str) -> None:
    reg = _registry()
    if reg is None:
        return
    cfg = reg.tool_configs.get(tool_name) or {}
    if tool_name in reg.tools:
        reg.unregister_tool(tool_name)
    with reg._tools_lock:
        reg.tool_configs.pop(tool_name, None)
        reg.tool_errors.pop(tool_name, None)
        reg._file_timestamps.pop(reg._config_rel(f'{tool_name}.json'), None)
    mod = _impl_module(cfg) if cfg else None
    if mod:
        sys.modules.pop(mod, None)


def _studio_files(tool_name: str, config: Dict[str, Any]) -> Optional[List[Path]]:
    """Files Studio generated for this tool, or None if Studio did not make it."""
    impl = config.get('implementation')
    files = [CONFIG_DIR / f'{tool_name}.json']
    if isinstance(impl, dict) or (isinstance(impl, str) and
                                  impl.startswith(f'sajha.tools.impl.{tool_name}_script_tool.')):
        files.append(IMPL_DIR / f'{tool_name}_script_tool.py')
        files += sorted(SCRIPTS_DIR.glob(f'{tool_name}.*'))
        return files
    if isinstance(impl, str):
        for prefix in STUDIO_MODULE_PREFIXES:
            if impl.startswith(f'sajha.tools.impl.{prefix}{tool_name}.'):
                return files + [IMPL_DIR / f'{prefix}{tool_name}.py']
        if impl.startswith('sajha.tools.impl.sharepoint_tool.') and \
                (config.get('metadata') or {}).get('generator_version'):
            return files  # SharePoint creator: config only, shared implementation
    return None


def _deploy_result(tool_name: str, written: List[str], message: str, **extra) -> JSONResponse:
    """Hot-load a freshly written tool; on failure remove its files."""
    loaded, err = _hot_load(tool_name)
    if not loaded:
        for f in written:
            try:
                if f and Path(f).exists():
                    Path(f).unlink()
            except OSError:
                pass
        _unload(tool_name)
        return _fail(f'Tool files were generated but the tool failed to load: {err}', 500)
    logger.info(f'Studio deployed tool {tool_name}: {written}')
    return _ok(message=message, tool_name=tool_name, **extra)


# ── Pages ────────────────────────────────────────────────────────────────

SAMPLE_CODE = '''from sajha.studio import sajhamcptool

@sajhamcptool(
    description="Calculate the factorial of a number",
    category="Mathematics",
    tags=["math", "factorial", "calculation"]
)
def calculate_factorial(n: int) -> dict:
    """Calculate factorial of n."""
    if n < 0:
        return {"error": "Factorial not defined for negative numbers"}

    result = 1
    for i in range(1, n + 1):
        result *= i

    return {
        "input": n,
        "factorial": result
    }
'''

CODE_EXAMPLES = [
    {
        'title': 'Simple Calculator',
        'description': 'Basic arithmetic calculator tool',
        'code': '''@sajhamcptool(
    description="Perform basic arithmetic operations",
    category="Mathematics",
    tags=["calculator", "math"]
)
def simple_calculator(
    a: float,
    b: float,
    operation: str = "add"
) -> dict:
    """Perform arithmetic operation on two numbers."""
    operations = {
        "add": a + b,
        "subtract": a - b,
        "multiply": a * b,
        "divide": a / b if b != 0 else None
    }

    result = operations.get(operation)
    if result is None:
        return {"error": f"Invalid operation: {operation}"}

    return {
        "a": a,
        "b": b,
        "operation": operation,
        "result": result
    }
''',
    },
    {
        'title': 'Text Analyzer',
        'description': 'Analyze text and return statistics',
        'code': '''@sajhamcptool(
    description="Analyze text and return word/character statistics",
    category="Text Processing",
    tags=["text", "analysis", "nlp"]
)
def analyze_text(
    text: str,
    include_details: bool = False
) -> dict:
    """Analyze text content."""
    words = text.split()

    result = {
        "character_count": len(text),
        "word_count": len(words),
        "sentence_count": text.count('.') + text.count('!') + text.count('?'),
        "average_word_length": sum(len(w) for w in words) / len(words) if words else 0
    }

    if include_details:
        result["word_frequency"] = {}
        for word in words:
            word_lower = word.lower().strip('.,!?')
            result["word_frequency"][word_lower] = result["word_frequency"].get(word_lower, 0) + 1

    return result
''',
    },
    {
        'title': 'Data Formatter',
        'description': 'Format data in different output formats',
        'code': '''@sajhamcptool(
    description="Format structured data into various output formats",
    category="Data Processing",
    tags=["format", "json", "csv"]
)
def format_data(
    data: dict,
    output_format: str = "json",
    pretty: bool = True
) -> dict:
    """Format data into specified output format."""
    import json

    if output_format == "json":
        formatted = json.dumps(data, indent=2 if pretty else None)
    elif output_format == "csv":
        headers = ','.join(str(k) for k in data.keys())
        values = ','.join(str(v) for v in data.values())
        formatted = f"{headers}\\n{values}"
    else:
        formatted = str(data)

    return {
        "original": data,
        "format": output_format,
        "formatted": formatted
    }
''',
    },
]


def _studio_ctx(auth: AuthContext) -> dict:
    return {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
        'sample_code': SAMPLE_CODE,
        'existing_tools': _existing_tools(),
        'examples': CODE_EXAMPLES,
        'sandbox': _sandbox_policy(),
    }


def _sandbox_policy() -> Optional[Dict[str, Any]]:
    """The sandbox policy a new Python code or script tool gets (shown on the creator pages)."""
    try:
        from sajha.sandbox import studio_policy
        return studio_policy()
    except Exception as e:
        logger.warning(f'Sandbox status unavailable: {e}')
        return None


@pages.get('')
@pages.get('/')
async def studio_home(request: Request, auth: AuthContext = Depends(require_admin)):
    return render(request, 'admin/studio/studio_home.html', _studio_ctx(auth))


@pages.get('/rest')
async def studio_rest(request: Request, auth: AuthContext = Depends(require_admin)):
    return render(request, 'admin/studio/studio_rest.html', _studio_ctx(auth))


@pages.get('/dbquery')
async def studio_dbquery(request: Request, auth: AuthContext = Depends(require_admin)):
    return render(request, 'admin/studio/studio_dbquery.html', _studio_ctx(auth))


@pages.get('/script')
async def studio_script(request: Request, auth: AuthContext = Depends(require_admin)):
    return render(request, 'admin/studio/studio_script.html', _studio_ctx(auth))


@pages.get('/livelink')
async def studio_livelink(request: Request, auth: AuthContext = Depends(require_admin)):
    return render(request, 'admin/studio/studio_livelink.html', _studio_ctx(auth))


@pages.get('/olap')
async def studio_olap(request: Request, auth: AuthContext = Depends(require_admin)):
    return render(request, 'admin/studio/studio_olap.html', _studio_ctx(auth))


@pages.get('/powerbi')
async def studio_powerbi(request: Request, auth: AuthContext = Depends(require_admin)):
    return render(request, 'admin/studio/studio_powerbi.html', _studio_ctx(auth))


@pages.get('/powerbidax')
async def studio_powerbidax(request: Request, auth: AuthContext = Depends(require_admin)):
    return render(request, 'admin/studio/studio_powerbidax.html', _studio_ctx(auth))


@pages.get('/sharepoint')
async def studio_sharepoint(request: Request, auth: AuthContext = Depends(require_admin)):
    return render(request, 'admin/studio/studio_sharepoint.html', _studio_ctx(auth))


@pages.get('/examples')
async def studio_examples(request: Request, auth: AuthContext = Depends(require_admin)):
    return render(request, 'admin/studio/studio_examples.html', _studio_ctx(auth))


# ── Python code creator ──────────────────────────────────────────────────

def _analyze_code(data: Dict[str, Any]):
    """(tool_name, tool_def, analyzer) or a JSONResponse error."""
    from sajha.studio import CodeAnalyzer
    source = data.get('code') or ''
    tool_name = (data.get('tool_name') or '').strip().lower()
    if not source.strip():
        return _fail('No code provided')
    err = _check_new_name(tool_name)
    if err:
        return _fail(err)
    analyzer = CodeAnalyzer()
    defs = analyzer.analyze(source)
    if analyzer.errors:
        return _fail('Code analysis errors: ' + '; '.join(map(str, analyzer.errors)),
                     errors=analyzer.errors)
    if not defs:
        return _fail('No @sajhamcptool decorated functions found in the code. '
                     'Make sure to use @sajhamcptool(description="...") decorator.')
    return tool_name, defs[0], analyzer


def _code_generator():
    from sajha.studio import ToolCodeGenerator
    return ToolCodeGenerator(tools_dir=str(CONFIG_DIR), impl_dir=str(IMPL_DIR))


@actions.post('/analyze')
async def studio_analyze(request: Request, auth: AuthContext = Depends(require_admin)):
    res = _analyze_code(await _body(request))
    if isinstance(res, JSONResponse):
        return res
    tool_name, tool_def, analyzer = res
    try:
        preview = _code_generator().preview_tool(tool_def, tool_name)
    except Exception as e:
        logger.error(f'Studio analyze failed: {e}', exc_info=True)
        return _fail(f'Analysis error: {e}', 500)
    if not preview.get('syntax_valid', True):
        return _fail(f"Generated Python has syntax error: {preview.get('syntax_error')}",
                     python_content=preview['python'])
    return _ok(
        tool_name=tool_name,
        function_name=tool_def.function_name,
        description=tool_def.description,
        category=tool_def.category,
        parameters=[{'name': p.name, 'type': p.type_hint, 'default': p.default_value,
                     'required': not p.has_default} for p in tool_def.parameters],
        json_content=preview['json'],
        python_content=preview['python'],
        json_filename=preview['json_filename'],
        python_filename=preview['python_filename'],
        syntax_valid=preview.get('syntax_valid', True),
        warnings=analyzer.warnings,
    )


@actions.post('/deploy')
async def studio_deploy(request: Request, auth: AuthContext = Depends(require_admin)):
    res = _analyze_code(await _body(request))
    if isinstance(res, JSONResponse):
        return res
    tool_name, tool_def, _ = res
    ok, message, json_path, python_path = _code_generator().save_tool(tool_def, tool_name, overwrite=False)
    if not ok:
        return _fail(message)
    return _deploy_result(tool_name, [json_path, python_path], f'Tool "{tool_name}" deployed successfully!',
                          json_path=json_path, python_path=python_path)


@actions.post('/validate-name')
async def studio_validate_name(request: Request, auth: AuthContext = Depends(require_admin)):
    name = ((await _body(request)).get('tool_name') or '').strip().lower()
    err = _check_new_name(name)
    return JSONResponse({'valid': err is None, 'error': err})


@actions.post('/delete')
async def studio_delete(request: Request, auth: AuthContext = Depends(require_admin)):
    """Delete a Studio-generated tool: unload it and remove its generated files."""
    tool_name = ((await _body(request)).get('tool_name') or '').strip().lower()
    if not TOOL_NAME_RE.match(tool_name):
        return _fail('Invalid tool name format')
    json_path = CONFIG_DIR / f'{tool_name}.json'
    reg = _registry()
    config = (reg.tool_configs.get(tool_name) if reg else None) or {}
    if not config and json_path.exists():
        try:
            config = json.loads(json_path.read_text(encoding='utf-8'))
        except Exception:
            config = {}
    if not config:
        # Nothing registered and no config: clean up any orphaned Studio module
        orphans = [IMPL_DIR / f'{p}{tool_name}.py' for p in STUDIO_MODULE_PREFIXES]
        orphans += [IMPL_DIR / f'{tool_name}_script_tool.py'] + sorted(SCRIPTS_DIR.glob(f'{tool_name}.*'))
        removed = []
        for f in orphans:
            if f.exists():
                f.unlink()
                removed.append(str(f))
        return _ok(message=(f'Deleted: {", ".join(Path(f).name for f in removed)}' if removed
                            else f'No files found for tool "{tool_name}"'),
                   deleted_files=removed, not_found_files=[])
    files = _studio_files(tool_name, config)
    if files is None:
        return _fail(f'"{tool_name}" was not created by MCP Studio; delete it from Admin > Tools instead', 403)

    _unload(tool_name)
    deleted, not_found = [], []
    from sajha.core.storage import get_storage
    for f in files:
        if f == json_path:
            try:
                existed = get_storage().delete(f'config/tools/{tool_name}.json')
            except Exception:
                existed = False
            if json_path.exists():
                json_path.unlink()
                existed = True
            (deleted if existed else not_found).append(str(f) if existed else f.name)
        elif f.exists():
            f.unlink()
            deleted.append(str(f))
        else:
            not_found.append(f.name)
    _unload(tool_name)  # the config watcher may have raced us
    message = (f'Deleted: {", ".join(Path(f).name for f in deleted)}' if deleted
               else f'No files found for tool "{tool_name}"')
    if deleted and not_found:
        message += f' (not found: {", ".join(not_found)})'
    logger.info(f'Studio deleted tool {tool_name}: {deleted}')
    return _ok(message=message, tool_name=tool_name, deleted_files=deleted, not_found_files=not_found)


# ── REST creator ─────────────────────────────────────────────────────────

def _rest_definition(data):
    from sajha.studio import RESTToolDefinition
    return RESTToolDefinition(
        name=(data.get('name') or '').strip().lower(),
        endpoint=data.get('endpoint') or '',
        method=(data.get('method') or 'GET').upper(),
        description=data.get('description') or '',
        request_schema=data.get('request_schema') or {},
        response_schema=data.get('response_schema') or {},
        category=data.get('category') or 'REST API',
        tags=data.get('tags') or [],
        api_key=data.get('api_key') or None,
        api_key_header=data.get('api_key_header') or 'X-API-Key',
        basic_auth_username=data.get('basic_auth_username') or None,
        basic_auth_password=data.get('basic_auth_password') or None,
        headers=data.get('headers') or {},
        timeout=int(data.get('timeout') or 30),
        content_type=data.get('content_type') or 'application/json',
        response_format=data.get('response_format') or 'json',
        csv_delimiter=data.get('csv_delimiter') or ',',
        csv_has_header=data.get('csv_has_header', True),
        csv_skip_rows=int(data.get('csv_skip_rows') or 0),
        version=_version(),
    )


def _rest_generator():
    from sajha.studio import RESTToolGenerator
    g = RESTToolGenerator()
    g.config_dir, g.impl_dir = CONFIG_DIR, IMPL_DIR
    return g


@actions.post('/rest/preview')
async def studio_rest_preview(request: Request, auth: AuthContext = Depends(require_admin)):
    try:
        definition = _rest_definition(await _body(request))
        err = _check_new_name(definition.name)
        if err:
            return _fail(err)
        preview = _rest_generator().preview_tool(definition)
        if not preview.get('success'):
            return _fail('Validation errors: ' + ', '.join(preview.get('errors', [])))
        return _ok(**{k: preview[k] for k in ('json_content', 'python_content', 'json_filename', 'python_filename')})
    except Exception as e:
        logger.error(f'Error previewing REST tool: {e}', exc_info=True)
        return _fail(f'Preview error: {e}', 500)


@actions.post('/rest/deploy')
async def studio_rest_deploy(request: Request, auth: AuthContext = Depends(require_admin)):
    try:
        definition = _rest_definition(await _body(request))
        err = _check_new_name(definition.name)
        if err:
            return _fail(err)
        ok, message, json_path, python_path = _rest_generator().save_tool(definition, overwrite=False)
        if not ok:
            return _fail(message)
        return _deploy_result(definition.name, [json_path, python_path],
                              f'REST Tool "{definition.name}" deployed successfully!',
                              json_path=json_path, python_path=python_path)
    except Exception as e:
        logger.error(f'Error deploying REST tool: {e}', exc_info=True)
        return _fail(f'Deployment error: {e}', 500)


# ── DB query creator ─────────────────────────────────────────────────────

def _dbquery_definition(data):
    from sajha.studio import DBQueryToolDefinition, DBQueryParameter
    params = [DBQueryParameter(
        name=(p.get('name') or '').strip(),
        param_type=p.get('param_type') or 'string',
        description=p.get('description') or '',
        required=p.get('required', True),
        default=p.get('default') if p.get('default') not in ('', None) else None,
        enum=p.get('enum') or None,
    ) for p in (data.get('parameters') or [])]
    return DBQueryToolDefinition(
        name=(data.get('name') or '').strip().lower(),
        description=data.get('description') or '',
        db_type=data.get('db_type') or 'duckdb',
        connection_string=data.get('connection_string') or '',
        query_template=data.get('query_template') or '',
        parameters=params,
        category=data.get('category') or 'Database',
        tags=data.get('tags') or ['database', 'query', 'sql'],
        literature=data.get('literature') or '',
        timeout=int(data.get('timeout') or 30),
        max_rows=int(data.get('max_rows') or 1000),
        version=_version(),
    )


def _dbquery_generator():
    from sajha.studio import DBQueryToolGenerator
    g = DBQueryToolGenerator()
    g.config_dir, g.impl_dir = CONFIG_DIR, IMPL_DIR
    return g


@actions.post('/dbquery/preview')
async def studio_dbquery_preview(request: Request, auth: AuthContext = Depends(require_admin)):
    try:
        definition = _dbquery_definition(await _body(request))
        err = _check_new_name(definition.name)
        if err:
            return _fail(err)
        preview = _dbquery_generator().preview_tool(definition)
        if not preview.get('success'):
            return _fail('Validation errors: ' + ', '.join(preview.get('errors', [])))
        return _ok(**{k: preview[k] for k in ('json_content', 'python_content', 'json_filename',
                                              'python_filename', 'input_schema', 'output_schema')})
    except Exception as e:
        logger.error(f'Error previewing DB Query tool: {e}', exc_info=True)
        return _fail(f'Preview error: {e}', 500)


@actions.post('/dbquery/deploy')
async def studio_dbquery_deploy(request: Request, auth: AuthContext = Depends(require_admin)):
    try:
        definition = _dbquery_definition(await _body(request))
        err = _check_new_name(definition.name)
        if err:
            return _fail(err)
        ok, message, json_path, python_path = _dbquery_generator().save_tool(definition, overwrite=False)
        if not ok:
            return _fail(message)
        return _deploy_result(definition.name, [json_path, python_path],
                              f'DB Query Tool "{definition.name}" deployed successfully!',
                              json_path=json_path, python_path=python_path)
    except Exception as e:
        logger.error(f'Error deploying DB Query tool: {e}', exc_info=True)
        return _fail(f'Deployment error: {e}', 500)


# ── Script creator ───────────────────────────────────────────────────────

def _script_config(data):
    from sajha.studio import ScriptToolConfig
    return ScriptToolConfig(
        tool_name=(data.get('tool_name') or '').strip().lower(),
        description=data.get('description') or '',
        script_type=data.get('script_type') or 'bash',
        script_content=data.get('script_content') or '',
        version=_version(),
        author=data.get('author') or '',
        tags=data.get('tags') or [],
        timeout_seconds=int(data.get('timeout_seconds') or 30),
        working_directory=data.get('working_directory') or '',
        environment_vars=data.get('environment_vars') or {},
        max_args=int(data.get('max_args') or 10),
        arg_descriptions=data.get('arg_descriptions') or [],
        allow_stdin=bool(data.get('allow_stdin', False)),
        capture_stderr=bool(data.get('capture_stderr', True)),
        literature=data.get('literature') or '',
    )


def _script_generator():
    from sajha.studio import ScriptToolGenerator
    return ScriptToolGenerator(config_dir=str(CONFIG_DIR), scripts_dir=str(SCRIPTS_DIR), impl_dir=str(IMPL_DIR))


@actions.post('/script/preview')
async def studio_script_preview(request: Request, auth: AuthContext = Depends(require_admin)):
    try:
        config = _script_config(await _body(request))
        err = _check_new_name(config.tool_name)
        if err:
            return _fail(err)
        gen = _script_generator()
        errors = gen.validate_config(config)
        if errors:
            return _fail('Validation errors: ' + ', '.join(errors))
        return _ok(json_content=json.dumps(gen.generate_tool_config(config), indent=2),
                   python_content=gen.generate_python_wrapper(config),
                   script_type=config.script_type)
    except Exception as e:
        logger.error(f'Error previewing script tool: {e}', exc_info=True)
        return _fail(f'Preview error: {e}', 500)


@actions.post('/script/deploy')
async def studio_script_deploy(request: Request, auth: AuthContext = Depends(require_admin)):
    try:
        config = _script_config(await _body(request))
        err = _check_new_name(config.tool_name)
        if err:
            return _fail(err)
        result = _script_generator().generate_tool(config)
        if not result.get('success'):
            return _fail('Errors: ' + ', '.join(result.get('errors', ['Unknown error'])))
        files = [result.get('config_path'), result.get('wrapper_path'), result.get('script_path')]
        return _deploy_result(config.tool_name, files,
                              result.get('message') or f'Script Tool "{config.tool_name}" deployed successfully!',
                              config_path=result.get('config_path'), script_path=result.get('script_path'),
                              wrapper_path=result.get('wrapper_path'))
    except Exception as e:
        logger.error(f'Error deploying script tool: {e}', exc_info=True)
        return _fail(f'Deployment error: {e}', 500)


# ── PowerBI report / PowerBI DAX / LiveLink creators ─────────────────────

def _powerbi(data):
    from sajha.studio import PowerBIToolConfig, PowerBIToolGenerator
    config = PowerBIToolConfig(
        tool_name=(data.get('tool_name') or '').strip().lower(),
        description=data.get('description') or '',
        report_name=data.get('report_name') or '',
        workspace_id=data.get('workspace_id') or '',
        report_id=data.get('report_id') or '',
        tenant_id=data.get('tenant_id') or '',
        client_id=data.get('client_id') or '',
        client_secret_env=data.get('client_secret_env') or 'POWERBI_CLIENT_SECRET',
        version=_version(),
        author=data.get('author') or '',
        tags=data.get('tags') or [],
        page_name=data.get('page_name') or '',
        export_format=data.get('export_format') or 'PDF',
        timeout_seconds=int(data.get('timeout_seconds') or 120),
    )
    return config, PowerBIToolGenerator(config_dir=str(CONFIG_DIR), impl_dir=str(IMPL_DIR))


def _powerbidax(data):
    from sajha.studio import PowerBIDAXToolConfig, PowerBIDAXToolGenerator
    config = PowerBIDAXToolConfig(
        tool_name=(data.get('tool_name') or '').strip().lower(),
        description=data.get('description') or '',
        dataset_name=data.get('dataset_name') or '',
        workspace_id=data.get('workspace_id') or '',
        dataset_id=data.get('dataset_id') or '',
        dax_query=data.get('dax_query') or '',
        tenant_id=data.get('tenant_id') or '',
        client_id=data.get('client_id') or '',
        client_secret_env=data.get('client_secret_env') or 'POWERBI_CLIENT_SECRET',
        version=_version(),
        author=data.get('author') or '',
        tags=data.get('tags') or [],
        timeout_seconds=int(data.get('timeout_seconds') or 60),
        max_rows=int(data.get('max_rows') or 10000),
        parameters=data.get('parameters') or [],
    )
    return config, PowerBIDAXToolGenerator(config_dir=str(CONFIG_DIR), impl_dir=str(IMPL_DIR))


def _livelink(data):
    from sajha.studio import LiveLinkToolConfig, LiveLinkToolGenerator
    config = LiveLinkToolConfig(
        tool_name=(data.get('tool_name') or '').strip().lower(),
        description=data.get('description') or '',
        server_url=data.get('server_url') or '',
        auth_type=data.get('auth_type') or 'basic',
        username_env=data.get('username_env') or 'LIVELINK_USERNAME',
        password_env=data.get('password_env') or 'LIVELINK_PASSWORD',
        oauth_token_env=data.get('oauth_token_env') or 'LIVELINK_OAUTH_TOKEN',
        default_parent_id=data.get('default_parent_id') or '',
        document_types=data.get('document_types') or [],
        version=_version(),
        author=data.get('author') or '',
        tags=data.get('tags') or [],
        timeout_seconds=int(data.get('timeout_seconds') or 60),
        max_file_size_mb=int(data.get('max_file_size_mb') or 50),
        api_version=data.get('api_version') or 'v2',
    )
    return config, LiveLinkToolGenerator(config_dir=str(CONFIG_DIR), impl_dir=str(IMPL_DIR))


_CONFIG_CREATORS = {'powerbi': ('PowerBI', _powerbi), 'powerbidax': ('PowerBI DAX', _powerbidax),
                    'livelink': ('LiveLink', _livelink)}


async def _config_creator_preview(kind: str, request: Request) -> JSONResponse:
    label, build = _CONFIG_CREATORS[kind]
    try:
        config, gen = build(await _body(request))
        err = _check_new_name(config.tool_name)
        errors = ([err] if err else []) + gen.validate_config(config)
        if errors:
            return _fail('; '.join(errors))
        return _ok(config=gen.generate_tool_config(config),
                   python_content=gen.generate_python_wrapper(config))
    except Exception as e:
        logger.error(f'Error previewing {label} tool: {e}', exc_info=True)
        return _fail(str(e), 500)


async def _config_creator_deploy(kind: str, request: Request) -> JSONResponse:
    label, build = _CONFIG_CREATORS[kind]
    try:
        config, gen = build(await _body(request))
        err = _check_new_name(config.tool_name)
        if err:
            return _fail(err)
        result = gen.generate_tool(config)
        if not result.get('success'):
            return _fail(result.get('message') or 'Deployment failed')
        files = list((result.get('files') or {}).values())
        return _deploy_result(config.tool_name, files, result.get('message') or f'{label} tool deployed',
                              files=result.get('files'), config=gen.generate_tool_config(config))
    except Exception as e:
        logger.error(f'Error deploying {label} tool: {e}', exc_info=True)
        return _fail(str(e), 500)


@actions.post('/powerbi/preview')
async def studio_powerbi_preview(request: Request, auth: AuthContext = Depends(require_admin)):
    return await _config_creator_preview('powerbi', request)


@actions.post('/powerbi/deploy')
async def studio_powerbi_deploy(request: Request, auth: AuthContext = Depends(require_admin)):
    return await _config_creator_deploy('powerbi', request)


@actions.post('/powerbidax/preview')
async def studio_powerbidax_preview(request: Request, auth: AuthContext = Depends(require_admin)):
    return await _config_creator_preview('powerbidax', request)


@actions.post('/powerbidax/deploy')
async def studio_powerbidax_deploy(request: Request, auth: AuthContext = Depends(require_admin)):
    return await _config_creator_deploy('powerbidax', request)


@actions.post('/livelink/preview')
async def studio_livelink_preview(request: Request, auth: AuthContext = Depends(require_admin)):
    return await _config_creator_preview('livelink', request)


@actions.post('/livelink/deploy')
async def studio_livelink_deploy(request: Request, auth: AuthContext = Depends(require_admin)):
    return await _config_creator_deploy('livelink', request)


# ── SharePoint creator ───────────────────────────────────────────────────

def _sharepoint(data):
    from sajha.studio.sharepoint_tool_generator import SharePointToolConfig, SharePointToolGenerator

    def _int(key, default):
        try:
            return int(data.get(key))
        except (TypeError, ValueError):
            return default

    config = SharePointToolConfig(
        name=(data.get('name') or '').strip().lower(),
        description=data.get('description') or '',
        tool_type=data.get('tool_type') or 'documents',
        site_url=data.get('site_url') or '',
        version=data.get('version') or _version(),
        auth_type=data.get('auth_type') or 'client_credentials',
        tenant_id=data.get('tenant_id') or '',
        client_id=data.get('client_id') or '',
        client_secret=data.get('client_secret') or '',
        default_folder=data.get('default_folder') or '/Shared Documents',
        default_list=data.get('default_list') or '',
        allowed_operations=data.get('allowed_operations') or [],
        max_file_size_mb=_int('max_file_size_mb', 100),
        cache_ttl_seconds=_int('cache_ttl_seconds', 300),
        allowed_file_types=data.get('allowed_file_types') or [],
        enable_version_control=bool(data.get('enable_version_control', True)),
        enable_metadata=bool(data.get('enable_metadata', True)),
        cache_enabled=bool(data.get('cache_enabled', True)),
        category=data.get('category') or 'Document Management',
        tags=data.get('tags') or ['sharepoint', 'microsoft', 'documents'],
    )
    return config, SharePointToolGenerator(output_dir=str(CONFIG_DIR))


@actions.post('/sharepoint/preview')
async def studio_sharepoint_preview(request: Request, auth: AuthContext = Depends(require_admin)):
    try:
        config, gen = _sharepoint(await _body(request))
        err = _check_new_name(config.name)
        errors = ([err] if err else []) + gen.validate(config)
        if errors:
            return _fail('; '.join(errors), errors=errors)
        tool_config = gen.generate(config)
        if (tool_config.get('authentication') or {}).get('client_secret'):
            tool_config['authentication']['client_secret'] = '***hidden***'
        return _ok(config=tool_config)
    except Exception as e:
        logger.error(f'Error previewing SharePoint tool: {e}', exc_info=True)
        return _fail(str(e), 500)


@actions.post('/sharepoint/deploy')
async def deploy_sharepoint_tool(request: Request, auth: AuthContext = Depends(require_admin)):
    try:
        config, gen = _sharepoint(await _body(request))
        err = _check_new_name(config.name)
        errors = ([err] if err else []) + gen.validate(config)
        if errors:
            return _fail('; '.join(errors))
        output_path = gen.save(config)
        return _deploy_result(config.name, [str(output_path)],
                              f'SharePoint tool "{config.name}" deployed successfully!',
                              config_file=str(output_path))
    except Exception as e:
        logger.error(f'Error deploying SharePoint tool: {e}', exc_info=True)
        return _fail(str(e), 500)


# ── OLAP dataset creator ─────────────────────────────────────────────────

def _olap_datasets_file() -> Path:
    return OLAP_DIR / 'datasets.json'


def _reload_olap_tools() -> List[str]:
    """Re-create the OLAP tools so they read the updated semantic layer."""
    reg = _registry()
    reloaded = []
    if reg is None:
        return reloaded
    for name, cfg in list(reg.tool_configs.items()):
        if str(cfg.get('implementation', '')).startswith('sajha.tools.impl.duckdb_olap_advanced.'):
            reg.load_tool_from_config(f'{name}.json')
            reloaded.append(name)
    return reloaded


def _add_olap_definitions(data: Dict[str, Any]) -> Dict[str, List[str]]:
    """Add the page's dimension/measure definitions that dimensions.json / measures.json
    do not have yet. Returns the names added (removed again when the dataset is deleted)."""
    added: Dict[str, List[str]] = {'dimensions': [], 'measures': []}
    for kind, key, build in (
        ('dimensions', 'dimension_definitions',
         lambda d: {'name': d['name'], 'column': d.get('column') or d['name'],
                    'type': 'time' if d.get('type') == 'time' else 'standard',
                    'description': d.get('description') or '', 'created_by': STUDIO_MARKER}),
        ('measures', 'measure_definitions',
         lambda d: {'name': d['name'], 'expression': d['expression'], 'format': d.get('format') or 'number',
                    'description': d.get('description') or '', 'created_by': STUDIO_MARKER}),
    ):
        defs = [d for d in (data.get(key) or []) if isinstance(d, dict) and d.get('name')
                and (kind == 'dimensions' or d.get('expression'))]
        if not defs:
            continue
        f = OLAP_DIR / f'{kind}.json'
        doc = json.loads(f.read_text(encoding='utf-8')) if f.exists() else {kind: {}}
        doc.setdefault(kind, {})
        for d in defs:
            if d['name'] not in doc[kind]:
                doc[kind][d['name']] = build(d)
                added[kind].append(d['name'])
        if added[kind]:
            f.write_text(json.dumps(doc, indent=4) + '\n', encoding='utf-8')
    return added


def _remove_olap_definitions(added: Dict[str, List[str]], still_used: Dict[str, set]) -> None:
    for kind in ('dimensions', 'measures'):
        names = [n for n in (added or {}).get(kind, []) if n not in still_used.get(kind, set())]
        f = OLAP_DIR / f'{kind}.json'
        if not names or not f.exists():
            continue
        doc = json.loads(f.read_text(encoding='utf-8'))
        for n in names:
            if (doc.get(kind, {}).get(n) or {}).get('created_by') == STUDIO_MARKER:
                del doc[kind][n]
        f.write_text(json.dumps(doc, indent=4) + '\n', encoding='utf-8')


@actions.post('/olap/deploy')
async def studio_olap_deploy(request: Request, auth: AuthContext = Depends(require_admin)):
    data = await _body(request)
    name = (data.get('name') or '').strip()
    if not name:
        return _fail('Dataset name is required')
    if not re.match(r'^[A-Za-z][A-Za-z0-9_]{0,63}$', name):
        return _fail('Dataset name must start with a letter and contain only letters, digits and underscores')
    for key, label in (('source_table', 'Source table'),):
        if not data.get(key):
            return _fail(f'{label} is required')
    if not data.get('dimensions'):
        return _fail('At least one dimension is required')
    if not data.get('measures'):
        return _fail('At least one measure is required')
    try:
        path = _olap_datasets_file()
        doc = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {
            'version': _version(), 'description': 'OLAP Dataset Definitions for Semantic Layer', 'datasets': {}}
        doc.setdefault('datasets', {})
        if name in doc['datasets']:
            return _fail(f'Dataset "{name}" already exists')
        doc['datasets'][name] = {
            'name': name,
            'display_name': data.get('display_name') or name,
            'description': data.get('description') or '',
            'source_table': data['source_table'],
            'joins': data.get('joins') or [],
            'dimensions': data['dimensions'],
            'measures': data['measures'],
            'default_time_dimension': data.get('default_time_dimension'),
            'default_grain': data.get('default_grain') or 'month',
            'cache_ttl_seconds': 300,
            'tags': [],
            'created_by': STUDIO_MARKER,
        }
        added = _add_olap_definitions(data)
        doc['datasets'][name]['studio_added'] = added
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=4) + '\n', encoding='utf-8')
        reloaded = _reload_olap_tools()
        return _ok(message=f'Dataset "{name}" deployed successfully!', dataset=name, reloaded_tools=reloaded)
    except Exception as e:
        logger.error(f'Error deploying OLAP dataset: {e}', exc_info=True)
        return _fail(str(e), 500)


@actions.post('/olap/delete')
async def studio_olap_delete(request: Request, auth: AuthContext = Depends(require_admin)):
    name = ((await _body(request)).get('name') or '').strip()
    path = _olap_datasets_file()
    try:
        doc = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except Exception as e:
        return _fail(f'Cannot read {path.name}: {e}', 500)
    ds = (doc.get('datasets') or {}).get(name)
    if ds is None:
        return _fail(f'Dataset "{name}" not found', 404)
    if ds.get('created_by') != STUDIO_MARKER:
        return _fail(f'Dataset "{name}" was not created by MCP Studio', 403)
    del doc['datasets'][name]
    path.write_text(json.dumps(doc, indent=4) + '\n', encoding='utf-8')
    still_used = {'dimensions': set(), 'measures': set()}
    for other in doc['datasets'].values():
        for kind in still_used:
            still_used[kind].update(x if isinstance(x, str) else (x or {}).get('name')
                                    for x in other.get(kind, []))
    _remove_olap_definitions(ds.get('studio_added') or {}, still_used)
    reloaded = _reload_olap_tools()
    return _ok(message=f'Dataset "{name}" deleted', dataset=name, reloaded_tools=reloaded)


# Both routers are served through the one ``router`` app.py includes.
# (include_router copies routes, so this must stay at the end of the module.)
router = APIRouter()
router.include_router(pages)
router.include_router(actions)
