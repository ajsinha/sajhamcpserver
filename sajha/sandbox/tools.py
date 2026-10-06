"""
SAJHA sandbox — tools whose code runs in a sandbox.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

The registry asks :func:`build_sandboxed_tool` before importing a tool's module.
For user code — a Studio Python code tool (``sajha.tools.impl.studio_*``), a
Studio script tool, or any tool whose config says ``"sandbox": {"enabled": true}``
— it returns a stand-in that never imports that module into the server. The
stand-in reads the module source (or the script) at call time and runs it
through a sandbox backend. Built-in tools are trusted and stay in-process.

Callers (MCP, REST, A2A, Ask SAJHA) see the same tool contract: same name,
schemas and result shape; a tool error is still an exception.
"""

import ast
import importlib.util
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from sajha.tools.base_mcp_tool import BaseMCPTool

from .backends import (PROJECT_ROOT, SandboxError, SandboxOutputLimit, SandboxTimeout,
                       SandboxToolError, get_backend)
from .policy import PolicyError, SandboxPolicy, policy_from_config
from .settings import load_settings

logger = logging.getLogger(__name__)

SCRIPTS_DIR = PROJECT_ROOT / 'config' / 'scripts'
#: Interpreters for script tools; '{python}' is the backend's Python.
SCRIPT_INTERPRETERS = {
    'shell': ['/bin/sh'], 'bash': ['/bin/bash'], 'python': ['{python}', '-I', '-B'],
    'powershell': ['pwsh', '-File'], 'node': ['node'], 'perl': ['perl'], 'ruby': ['ruby'],
}
SCRIPT_EXTENSIONS = {'shell': '.sh', 'bash': '.sh', 'python': '.py', 'powershell': '.ps1',
                     'node': '.js', 'perl': '.pl', 'ruby': '.rb'}
#: Only these config keys travel into the sandbox (a config may hold substituted secrets)
SAFE_CONFIG_KEYS = ('name', 'description', 'version', 'enabled', 'inputSchema', 'outputSchema')


# ── Classification ─────────────────────────────────────────────────────────

def classify(config: Dict[str, Any]) -> Optional[str]:
    """'script', 'python', or None for a trusted (in-process) tool."""
    impl = config.get('implementation')
    if isinstance(config.get('script'), dict) or isinstance(impl, dict):
        return 'script'
    if not isinstance(impl, str) or '.' not in impl:
        return None
    module = impl.rsplit('.', 1)[0]
    if module.startswith('sajha.tools.impl.') and module.endswith('_script_tool'):
        return 'script'
    if module.startswith('sajha.tools.impl.studio_'):
        return 'python'
    if (config.get('sandbox') or {}).get('enabled') is True:
        return 'python'
    return None


def should_sandbox(config: Dict[str, Any]) -> Optional[str]:
    kind = classify(config)
    if kind is None:
        return None
    block = config.get('sandbox') or {}
    settings = load_settings()
    if settings.enforce_for_generated_tools:
        if block.get('enabled') is False:
            logger.warning(f"Tool {config.get('name')}: sandbox.enabled=false ignored "
                           f"(sandbox.enforce_for_generated_tools is on)")
        return kind
    return kind if block.get('enabled') is True else None


def build_sandboxed_tool(config: Dict[str, Any]) -> Optional[BaseMCPTool]:
    """A sandboxed stand-in for this tool, or None if it should load in-process."""
    kind = should_sandbox(config)
    if kind == 'script':
        return SandboxedScriptTool(config)
    if kind == 'python':
        return SandboxedPythonTool(config)
    return None


# ── Common ─────────────────────────────────────────────────────────────────

class _SandboxedTool(BaseMCPTool):
    kind = ''

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        # Validate now so a bad policy fails the load, not the first call
        self.sandbox_policy: SandboxPolicy = policy_from_config(self._policy_block())
        self._metadata = dict(self._metadata or {})
        self._metadata['sandboxed'] = True

    def _policy_block(self) -> Dict[str, Any]:
        return dict(self.config.get('sandbox') or {})

    def policy(self) -> SandboxPolicy:
        """Re-resolved per call, so admin default/max changes apply at once."""
        return policy_from_config(self._policy_block())

    def sandbox_info(self) -> Dict[str, Any]:
        pol = self.policy()
        backend = get_backend(pol.backend)
        return {'kind': self.kind, 'backend': backend.name, 'policy': pol.to_dict()}


# ── Python code tools ──────────────────────────────────────────────────────

def _literal_return(cls_node: ast.ClassDef, method: str):
    for node in cls_node.body:
        if isinstance(node, ast.FunctionDef) and node.name == method:
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Return) and stmt.value is not None:
                    try:
                        return ast.literal_eval(stmt.value)
                    except ValueError:
                        return None
    return None


class SandboxedPythonTool(_SandboxedTool):
    kind = 'python'

    def __init__(self, config: Dict[str, Any]):
        impl = config.get('implementation') or ''
        self.module_name, self.class_name = impl.rsplit('.', 1)
        self.source_path = self._locate(self.module_name)
        super().__init__(config)
        tree = ast.parse(self._source(), filename=str(self.source_path))
        cls = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == self.class_name), None)
        if cls is None:
            raise ImportError(f'class {self.class_name} not found in {self.source_path}')
        self._parsed_input = _literal_return(cls, 'get_input_schema')
        self._parsed_output = _literal_return(cls, 'get_output_schema')

    @staticmethod
    def _locate(module_name: str) -> Path:
        """The module's file, found without executing it (parents are trusted packages)."""
        parent, _, leaf = module_name.rpartition('.')
        spec = importlib.util.find_spec(parent) if parent else None
        for base in (spec.submodule_search_locations or []) if spec else []:
            p = Path(base) / f'{leaf}.py'
            if p.is_file():
                return p
        raise ImportError(f'No module source for {module_name}')

    def _source(self) -> str:
        return self.source_path.read_text(encoding='utf-8')

    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema') or self._parsed_input or {'type': 'object', 'properties': {}}

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema') or self._parsed_output or {}

    def execute(self, arguments: Dict[str, Any]) -> Any:
        pol = self.policy()
        backend = get_backend(pol.backend)
        tool_config = {k: self.config[k] for k in SAFE_CONFIG_KEYS if k in self.config}
        res = backend.run({'op': 'python_tool', 'source': self._source(), 'class_name': self.class_name,
                           'arguments': arguments, 'tool_config': tool_config,
                           'packages': pol.packages}, pol)
        if res.timed_out:
            raise SandboxTimeout(f'{self.name}: exceeded the sandbox time limit of {pol.timeout_seconds}s')
        if res.output_truncated:
            raise SandboxOutputLimit(f'{self.name}: output exceeded the sandbox limit of {pol.max_output_bytes} bytes')
        if res.runner_error:
            raise SandboxError(f'{self.name}: sandbox error: {res.runner_error}')
        try:
            payload = json.loads(res.stdout)
        except ValueError:
            tail = res.stderr.strip().splitlines()[-1:] or ['no output']
            raise SandboxError(f'{self.name}: sandboxed tool ended without a result (exit {res.exit_code}; '
                               f'{_exit_reason(res.exit_code)}): {tail[0][:300]}')
        if res.stderr.strip():
            logger.info(f'{self.name} (sandbox {res.backend}) stderr: {res.stderr[-2000:]}')
        if not payload.get('ok'):
            raise SandboxToolError(f"{payload.get('error_type', 'Error')}: {payload.get('error', '')}")
        return payload.get('result')


def _exit_reason(code: int) -> str:
    sig = code - 128 if code > 128 else (-code if code < 0 else 0)
    return {9: 'killed (memory, CPU or output limit)', 24: 'CPU time limit', 25: 'file size limit',
            31: 'blocked system call'}.get(sig, 'error')


# ── Script tools ───────────────────────────────────────────────────────────

class SandboxedScriptTool(_SandboxedTool):
    kind = 'script'

    def __init__(self, config: Dict[str, Any]):
        info = config.get('script') if isinstance(config.get('script'), dict) else \
            (config.get('implementation') if isinstance(config.get('implementation'), dict) else {})
        self.script_info = dict(info or {})
        self.script_type = self.script_info.get('script_type') or 'bash'
        if self.script_type not in SCRIPT_INTERPRETERS:
            raise ValueError(f'unknown script type {self.script_type}')
        name = config.get('name') or ''
        self.script_file = self.script_info.get('script_file') or f'{name}{SCRIPT_EXTENSIONS[self.script_type]}'
        if '/' in self.script_file or self.script_file.startswith('.'):
            raise ValueError(f'bad script_file {self.script_file!r}')
        self.capture_stderr = bool(self.script_info.get('capture_stderr', True))
        super().__init__(config)

    def _policy_block(self) -> Dict[str, Any]:
        block = dict(self.config.get('sandbox') or {})
        if 'timeout_seconds' not in block and self.script_info.get('timeout_seconds'):
            block['timeout_seconds'] = self.script_info['timeout_seconds']
        env = dict(self.script_info.get('environment_vars') or {})
        env.update(block.get('env') or {})
        if env:
            block['env'] = env
        return block

    def script_path(self) -> Path:
        return SCRIPTS_DIR / self.script_file

    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema') or self.config.get('input_schema') or {
            'type': 'object', 'properties': {'args': {'type': 'array', 'items': {'type': 'string'}}}}

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema') or {}

    @staticmethod
    def _fail(stderr: str, code: int, stdout: str = '') -> Dict[str, Any]:
        return {'stdout': stdout, 'stderr': stderr, 'exit_code': code, 'success': False}

    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        args = arguments.get('args', [])
        if not isinstance(args, list):
            args = [str(args)] if args else []
        args = [str(a) for a in args]
        try:
            content = self.script_path().read_text(encoding='utf-8')
        except OSError:
            return self._fail(f'Script file not found: {self.script_path()}', -2)
        pol = self.policy()
        backend = get_backend(pol.backend)
        argv = list(SCRIPT_INTERPRETERS[self.script_type]) + [self.script_file] + args
        try:
            res = backend.run({'op': 'exec', 'files': {self.script_file: content}, 'argv': argv}, pol)
        except SandboxError as e:
            return self._fail(str(e), -3)
        if res.timed_out:
            return self._fail(f'Script timed out after {pol.timeout_seconds} seconds', -1, res.stdout)
        if res.runner_error:
            return self._fail(f'Sandbox error: {res.runner_error}', -3)
        stderr = res.stderr if self.capture_stderr else ''
        if res.output_truncated:
            return self._fail(stderr + f'\n[sandbox: output exceeded {pol.max_output_bytes} bytes; script stopped]',
                              -4, res.stdout)
        return {'stdout': res.stdout, 'stderr': stderr, 'exit_code': res.exit_code,
                'success': res.exit_code == 0}
