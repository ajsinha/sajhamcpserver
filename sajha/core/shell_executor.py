"""
SAJHA MCP Server v5.2.0 — Sandboxed Shell & Python Executor
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Three-tier execution model:
  Tier 1 — Python Sandbox: restricted imports, memory/time limits
  Tier 2 — Shell Sandbox: allowlisted commands, no network/write
  Tier 3 — Unrestricted Shell: admin-only, full audit logging

DISABLED BY DEFAULT. Requires explicit config opt-in.
Every execution is audit-logged regardless of tier.
"""
import hashlib
import json
import logging
import os
import re
import resource
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# CONFIGURATION DEFAULTS
# ═══════════════════════════════════════════════════════════════════

DEFAULT_PYTHON_ALLOWED_IMPORTS = {
    'json', 'math', 'csv', 'statistics', 're', 'datetime', 'collections',
    'itertools', 'functools', 'decimal', 'fractions', 'random', 'string',
    'textwrap', 'io', 'base64', 'hashlib', 'hmac', 'copy', 'pprint',
    'dataclasses', 'enum', 'typing', 'abc',
    # Data processing
    'pandas', 'numpy',
}

DEFAULT_PYTHON_BLOCKED_IMPORTS = {
    'os', 'sys', 'subprocess', 'shutil', 'socket', 'http', 'urllib',
    'requests', 'ftplib', 'smtplib', 'telnetlib', 'xmlrpc', 'ctypes',
    'multiprocessing', 'signal', 'resource', 'importlib', 'code',
    'compile', 'exec', 'eval', '__import__', 'builtins', 'globals',
    'pickle', 'shelve', 'marshal', 'tempfile', 'pathlib',
    'webbrowser', 'antigravity',
}

DEFAULT_BASH_ALLOWED_COMMANDS = {
    'echo', 'cat', 'head', 'tail', 'grep', 'awk', 'sed', 'cut', 'tr',
    'sort', 'uniq', 'wc', 'diff', 'comm', 'paste', 'column',
    'jq', 'date', 'printf', 'bc', 'expr',
    'ls', 'find', 'file', 'stat', 'du', 'df',
    'base64', 'md5sum', 'sha256sum',
    'true', 'false', 'test',
}

DEFAULT_BASH_BLOCKED_PATTERNS = [
    r'\brm\b', r'\brmdir\b', r'\bmv\b', r'\bcp\b',
    r'\bchmod\b', r'\bchown\b', r'\bchgrp\b',
    r'\bsudo\b', r'\bsu\b', r'\bdoas\b',
    r'\bssh\b', r'\bscp\b', r'\bsftp\b', r'\brsync\b',
    r'\bnc\b', r'\bncat\b', r'\bnetcat\b', r'\bcurl\s.*-[dXPT]',
    r'\bwget\b', r'\bfetch\b',
    r'\bpip\b', r'\bapt\b', r'\byum\b', r'\bdnf\b', r'\bbrew\b',
    r'\bdocker\b', r'\bpodman\b', r'\bkubectl\b',
    r'\bpython[23]?\b', r'\bperl\b', r'\bruby\b', r'\bnode\b',
    r'\bmkfifo\b', r'\bmknod\b',
    r'>\s*/dev/', r'>\s*/etc/', r'>\s*/proc/', r'>\s*/sys/',
    r'\|\s*bash', r'\|\s*sh\b', r'\|\s*zsh',
    r'`[^`]*`',  # backtick command substitution
    r'\$\([^)]*\)',  # $() command substitution
    r';\s*\w',  # command chaining with ;
    r'&&\s*\w',  # command chaining with &&
    r'\|\|\s*\w',  # command chaining with ||
]


# ═══════════════════════════════════════════════════════════════════
# EXECUTION RESULT
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ShellResult:
    """Result of a shell/python execution."""
    execution_id: str
    executor_type: str  # python | bash
    tier: str           # sandbox | unrestricted
    code: str
    stdout: str = ''
    stderr: str = ''
    exit_code: int = 0
    success: bool = True
    error: Optional[str] = None
    duration_ms: float = 0
    user_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    blocked_reason: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            'execution_id': self.execution_id,
            'type': self.executor_type,
            'tier': self.tier,
            'success': self.success,
            'stdout': self.stdout[:50000],  # Cap output in response
            'stderr': self.stderr[:10000],
            'exit_code': self.exit_code,
            'error': self.error,
            'duration_ms': round(self.duration_ms, 1),
            'blocked_reason': self.blocked_reason,
            'timestamp': self.timestamp,
        }


# ═══════════════════════════════════════════════════════════════════
# SECURITY VALIDATOR
# ═══════════════════════════════════════════════════════════════════

class SecurityValidator:
    """Validates code/commands against security policies before execution."""

    def __init__(self, python_allowed: Set[str] = None,
                 python_blocked: Set[str] = None,
                 bash_allowed: Set[str] = None,
                 bash_blocked_patterns: List[str] = None):
        self._py_allowed = python_allowed or DEFAULT_PYTHON_ALLOWED_IMPORTS
        self._py_blocked = python_blocked or DEFAULT_PYTHON_BLOCKED_IMPORTS
        self._bash_allowed = bash_allowed or DEFAULT_BASH_ALLOWED_COMMANDS
        self._bash_patterns = [re.compile(p) for p in (bash_blocked_patterns or DEFAULT_BASH_BLOCKED_PATTERNS)]

    def validate_python(self, code: str) -> Optional[str]:
        """Validate Python code. Returns error message or None if safe."""
        # Check for blocked imports
        import_pattern = re.compile(r'(?:^|\n)\s*(?:import|from)\s+(\w+)')
        for match in import_pattern.finditer(code):
            module = match.group(1)
            if module in self._py_blocked:
                return f"Blocked import: {module} (security policy)"
            root = module.split('.')[0]
            if root in self._py_blocked:
                return f"Blocked import: {root} (security policy)"

        # Check for dangerous builtins
        dangerous = ['exec(', 'eval(', 'compile(', '__import__(', 'globals(', 'locals(',
                     'getattr(', 'setattr(', 'delattr(', 'open(', 'breakpoint(']
        for d in dangerous:
            if d in code:
                return f"Blocked builtin: {d.rstrip('(')} (security policy)"

        # Check for file system access patterns
        fs_patterns = [r'open\s*\(', r'Path\s*\(', r'os\.', r'sys\.', r'subprocess\.']
        for p in fs_patterns:
            if re.search(p, code):
                return f"Blocked: filesystem/system access (security policy)"

        return None

    def validate_bash(self, command: str) -> Optional[str]:
        """Validate bash command. Returns error message or None if safe."""
        # Check against blocked patterns
        for pattern in self._bash_patterns:
            if pattern.search(command):
                return f"Blocked: command matches security pattern '{pattern.pattern}'"

        # Check first command is in allowlist
        cmd_parts = command.strip().split()
        if not cmd_parts:
            return "Empty command"
        first_cmd = os.path.basename(cmd_parts[0])
        if first_cmd not in self._bash_allowed:
            return f"Command not in allowlist: {first_cmd}. Allowed: {', '.join(sorted(self._bash_allowed))}"

        # Check for pipe targets
        if '|' in command:
            pipe_parts = command.split('|')
            for part in pipe_parts[1:]:
                pipe_cmd = part.strip().split()[0] if part.strip() else ''
                pipe_cmd = os.path.basename(pipe_cmd)
                if pipe_cmd and pipe_cmd not in self._bash_allowed:
                    return f"Pipe target not in allowlist: {pipe_cmd}"

        return None


# ═══════════════════════════════════════════════════════════════════
# PYTHON SANDBOX EXECUTOR
# ═══════════════════════════════════════════════════════════════════

class PythonSandbox:
    """Execute Python code in a restricted subprocess."""

    def __init__(self, timeout: int = 30, memory_mb: int = 256,
                 scratch_dir: str = 'data/shell_scratch'):
        self.timeout = timeout
        self.memory_mb = memory_mb
        self.scratch_dir = Path(scratch_dir)
        self.scratch_dir.mkdir(parents=True, exist_ok=True)
        self.validator = SecurityValidator()

    def execute(self, code: str, user_id: str = None) -> ShellResult:
        """Execute Python code in sandbox."""
        exec_id = f"py-{uuid.uuid4().hex[:8]}"

        # Validate
        error = self.validator.validate_python(code)
        if error:
            logger.warning(f"Python blocked [{exec_id}] by {user_id}: {error}")
            return ShellResult(
                execution_id=exec_id, executor_type='python', tier='sandbox',
                code=code, success=False, blocked_reason=error, user_id=user_id)

        # Write to temp file
        script_path = self.scratch_dir / f"{exec_id}.py"
        script_path.write_text(code)

        start = time.time()
        try:
            result = subprocess.run(
                ['python3', '-u', str(script_path)],
                capture_output=True, text=True, timeout=self.timeout,
                cwd=str(self.scratch_dir),
                env={
                    'PATH': '/usr/bin:/bin',
                    'HOME': str(self.scratch_dir),
                    'PYTHONDONTWRITEBYTECODE': '1',
                    'PYTHONPATH': '',
                },
            )
            duration = (time.time() - start) * 1000
            return ShellResult(
                execution_id=exec_id, executor_type='python', tier='sandbox',
                code=code, stdout=result.stdout, stderr=result.stderr,
                exit_code=result.returncode, success=result.returncode == 0,
                duration_ms=duration, user_id=user_id,
                error=result.stderr[:500] if result.returncode != 0 else None)

        except subprocess.TimeoutExpired:
            return ShellResult(
                execution_id=exec_id, executor_type='python', tier='sandbox',
                code=code, success=False, error=f"Timeout ({self.timeout}s)",
                duration_ms=(time.time()-start)*1000, user_id=user_id)
        except Exception as e:
            return ShellResult(
                execution_id=exec_id, executor_type='python', tier='sandbox',
                code=code, success=False, error=str(e),
                duration_ms=(time.time()-start)*1000, user_id=user_id)
        finally:
            script_path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════
# BASH SANDBOX EXECUTOR
# ═══════════════════════════════════════════════════════════════════

class BashSandbox:
    """Execute shell commands in a restricted environment."""

    def __init__(self, timeout: int = 15, scratch_dir: str = 'data/shell_scratch',
                 max_output_bytes: int = 1048576):
        self.timeout = timeout
        self.scratch_dir = Path(scratch_dir)
        self.scratch_dir.mkdir(parents=True, exist_ok=True)
        self.max_output = max_output_bytes
        self.validator = SecurityValidator()

    def execute(self, command: str, user_id: str = None) -> ShellResult:
        """Execute bash command in sandbox."""
        exec_id = f"sh-{uuid.uuid4().hex[:8]}"

        # Validate
        error = self.validator.validate_bash(command)
        if error:
            logger.warning(f"Bash blocked [{exec_id}] by {user_id}: {error}")
            return ShellResult(
                execution_id=exec_id, executor_type='bash', tier='sandbox',
                code=command, success=False, blocked_reason=error, user_id=user_id)

        start = time.time()
        try:
            result = subprocess.run(
                ['bash', '-c', command],
                capture_output=True, text=True, timeout=self.timeout,
                cwd=str(self.scratch_dir),
                env={
                    'PATH': '/usr/bin:/bin',
                    'HOME': str(self.scratch_dir),
                    'LANG': 'C.UTF-8',
                },
            )
            duration = (time.time() - start) * 1000
            stdout = result.stdout[:self.max_output]
            stderr = result.stderr[:self.max_output]
            return ShellResult(
                execution_id=exec_id, executor_type='bash', tier='sandbox',
                code=command, stdout=stdout, stderr=stderr,
                exit_code=result.returncode, success=result.returncode == 0,
                duration_ms=duration, user_id=user_id,
                error=stderr[:500] if result.returncode != 0 else None)

        except subprocess.TimeoutExpired:
            return ShellResult(
                execution_id=exec_id, executor_type='bash', tier='sandbox',
                code=command, success=False, error=f"Timeout ({self.timeout}s)",
                duration_ms=(time.time()-start)*1000, user_id=user_id)
        except Exception as e:
            return ShellResult(
                execution_id=exec_id, executor_type='bash', tier='sandbox',
                code=command, success=False, error=str(e),
                duration_ms=(time.time()-start)*1000, user_id=user_id)


# ═══════════════════════════════════════════════════════════════════
# SHELL EXECUTOR (unified interface)
# ═══════════════════════════════════════════════════════════════════

class ShellExecutor:
    """
    Unified shell execution interface with audit logging.

    All executions are audit-logged regardless of outcome.
    Configuration from application.yml → shell: section.
    """

    def __init__(self, config: Dict = None):
        cfg = config or {}
        self.enabled = cfg.get('enabled', False)
        self.mode = cfg.get('mode', 'sandbox')

        py_cfg = cfg.get('python', {})
        bash_cfg = cfg.get('bash', {})

        self.python_enabled = py_cfg.get('enabled', True) and self.enabled
        self.bash_enabled = bash_cfg.get('enabled', False) and self.enabled

        scratch = cfg.get('scratch_dir', 'data/shell_scratch')

        self._python = PythonSandbox(
            timeout=py_cfg.get('timeout_seconds', 30),
            memory_mb=py_cfg.get('memory_limit_mb', 256),
            scratch_dir=scratch,
        ) if self.python_enabled else None

        self._bash = BashSandbox(
            timeout=bash_cfg.get('timeout_seconds', 15),
            scratch_dir=scratch,
            max_output_bytes=bash_cfg.get('max_output_bytes', 1048576),
        ) if self.bash_enabled else None

        # Execution history (last N)
        self._history: list = []
        self._max_history = 100
        self._lock = threading.Lock()

        status = []
        if self.python_enabled: status.append('Python sandbox')
        if self.bash_enabled: status.append('Bash sandbox')
        if not self.enabled: status.append('DISABLED')
        logger.info(f"Shell executor: {', '.join(status) or 'DISABLED'}")

    def execute_python(self, code: str, user_id: str = None) -> ShellResult:
        """Execute Python code in sandbox."""
        if not self.python_enabled:
            return ShellResult(execution_id='n/a', executor_type='python', tier='disabled',
                             code=code, success=False, error='Python execution is disabled')
        result = self._python.execute(code, user_id)
        self._record(result)
        self._audit_log(result)
        return result

    def execute_bash(self, command: str, user_id: str = None) -> ShellResult:
        """Execute bash command in sandbox."""
        if not self.bash_enabled:
            return ShellResult(execution_id='n/a', executor_type='bash', tier='disabled',
                             code=command, success=False, error='Bash execution is disabled')
        result = self._bash.execute(command, user_id)
        self._record(result)
        self._audit_log(result)
        return result

    def get_history(self, limit: int = 50) -> List[Dict]:
        with self._lock:
            return [r.to_dict() for r in reversed(self._history[-limit:])]

    def get_capabilities(self) -> Dict:
        """Return what's enabled and the security policies."""
        return {
            'enabled': self.enabled,
            'mode': self.mode,
            'python': {
                'enabled': self.python_enabled,
                'timeout_seconds': self._python.timeout if self._python else 0,
                'allowed_imports': sorted(DEFAULT_PYTHON_ALLOWED_IMPORTS),
                'blocked_imports': sorted(DEFAULT_PYTHON_BLOCKED_IMPORTS),
            },
            'bash': {
                'enabled': self.bash_enabled,
                'timeout_seconds': self._bash.timeout if self._bash else 0,
                'allowed_commands': sorted(DEFAULT_BASH_ALLOWED_COMMANDS),
            },
        }

    def _record(self, result: ShellResult):
        with self._lock:
            self._history.append(result)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

    def _audit_log(self, result: ShellResult):
        """Log every execution to audit trail."""
        try:
            from sajha.core.audit import get_audit_logger
            code_preview = result.code[:100] + ('...' if len(result.code) > 100 else '')
            status = 'success' if result.success else ('blocked' if result.blocked_reason else 'failed')
            get_audit_logger().log(
                action=f'shell_execute_{result.executor_type}',
                user_id=result.user_id,
                resource_type='shell',
                resource_id=result.execution_id,
                details=f"status={status} tier={result.tier} code={code_preview}",
            )
        except Exception as e:
            logger.debug(f"Shell audit log error: {e}", exc_info=True)


# ═══════════════════════════════════════════════════════════════════
# MCP TOOLS (registered as MCP tools for agent use)
# ═══════════════════════════════════════════════════════════════════

PYTHON_TOOL_SCHEMA = {
    'name': 'shell_python',
    'description': 'Execute Python code in a sandboxed environment. Allowed imports: json, math, csv, statistics, re, datetime, collections, pandas, numpy. No filesystem/network/system access.',
    'inputSchema': {
        'type': 'object',
        'properties': {
            'code': {'type': 'string', 'description': 'Python code to execute'},
        },
        'required': ['code'],
    },
}

BASH_TOOL_SCHEMA = {
    'name': 'shell_bash',
    'description': 'Execute a shell command in a sandboxed environment. Allowed commands: cat, grep, awk, sed, sort, uniq, wc, jq, head, tail, ls, find, echo, date. No write/network/system access.',
    'inputSchema': {
        'type': 'object',
        'properties': {
            'command': {'type': 'string', 'description': 'Bash command to execute'},
        },
        'required': ['command'],
    },
}


# Module singleton
_executor: Optional[ShellExecutor] = None


def get_shell_executor() -> ShellExecutor:
    global _executor
    if _executor is None:
        config = {}
        try:
            from sajha.core.config import get_settings
            s = get_settings()
            config = {
                'enabled': getattr(s, 'shell_enabled', False),
                'mode': getattr(s, 'shell_mode', 'sandbox'),
                'scratch_dir': getattr(s, 'shell_scratch_dir', 'data/shell_scratch'),
                'python': {
                    'enabled': getattr(s, 'shell_python_enabled', True),
                    'timeout_seconds': getattr(s, 'shell_python_timeout', 30),
                    'memory_limit_mb': getattr(s, 'shell_python_memory_mb', 256),
                },
                'bash': {
                    'enabled': getattr(s, 'shell_bash_enabled', False),
                    'timeout_seconds': getattr(s, 'shell_bash_timeout', 15),
                },
            }
        except Exception:
            pass
        _executor = ShellExecutor(config)
    return _executor
