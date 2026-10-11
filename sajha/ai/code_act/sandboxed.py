"""
SAJHA MCP Server — running model-written Python in the Sandbox, and checking what it prints.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Reference: docs/architecture/Quantitative Planners.md §3.5 and docs/architecture/Sandbox.md.

The code runs through the sandbox's default backend (``sandbox.default_backend``) with the network
off, in the sandbox's fresh temporary work directory, under the sandbox's time, memory, process,
file-size and output limits (``sandbox.defaults`` capped by ``sandbox.max``). Three files are
written there: ``code.py`` (the model's code), ``input.json`` (the payload) and ``main.py``, a
small wrapper that puts ``input.json`` on standard input and runs ``code.py`` as ``__main__``.

Standard output must be exactly one JSON object of quantities::

    {"quantities": {"<name>": {"value": <number | list | list of lists>, "unit": "<unit>", "as_of": "..."}}}

(the ``quantities`` wrapper may be left out). Anything else is a :class:`CodeOutputError`, whose
message is returned to the model.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

MAX_CODE_CHARS = 20000
MAX_INPUT_BYTES = 1_000_000
MAX_QUANTITIES = 50
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

WRAPPER = (
    "import os, runpy, sys\n"
    "fd = os.open('input.json', os.O_RDONLY)\n"
    "os.dup2(fd, 0)\n"
    "os.close(fd)\n"
    "sys.stdin = open(0, 'r', encoding='utf-8', closefd=False)\n"
    "sys.argv = ['code.py']\n"
    "runpy.run_path('code.py', run_name='__main__')\n"
)


class CodeOutputError(ValueError):
    """What the code printed is not quantities as JSON (the message is for the model)."""


@dataclass
class CodeRun:
    ok: bool
    error: str = ""
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    backend: str = ""
    duration_ms: float = 0.0
    quantities: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def policy():
    """The sandbox policy for code_act: the administrator's defaults and caps, network always off."""
    from sajha.sandbox import policy_from_config
    return policy_from_config({"network": "none"})


def run_code(code: str, input_json: str) -> CodeRun:
    """Run ``code`` in the sandbox with ``input_json`` on standard input. Never raises for what the
    code does; a sandbox that cannot run is reported as an error too."""
    from sajha.sandbox import SandboxError, get_backend
    if len(code) > MAX_CODE_CHARS:
        return CodeRun(False, f"the code is {len(code)} characters; at most {MAX_CODE_CHARS}")
    try:
        pol = policy()
        backend = get_backend(None)
        res = backend.run({"op": "exec", "files": {"code.py": code, "input.json": input_json, "main.py": WRAPPER},
                           "argv": ["{python}", "-I", "-B", "main.py"]}, pol)
    except SandboxError as e:
        return CodeRun(False, f"the sandbox could not run the code: {e}")
    except Exception as e:                     # a policy error: an administrator's setting
        return CodeRun(False, f"the sandbox could not run the code: {e.__class__.__name__}: {e}")
    run = CodeRun(False, stdout=res.stdout, stderr=res.stderr, exit_code=res.exit_code, backend=res.backend,
                  duration_ms=round(res.duration_ms, 1))
    if res.timed_out:
        run.error = f"the code ran longer than {pol.timeout_seconds} s and was stopped"
    elif res.output_truncated:
        run.error = f"the code printed more than {pol.max_output_bytes} bytes and was stopped"
    elif res.runner_error:
        run.error = f"the sandbox failed: {res.runner_error}"
    elif res.exit_code != 0:
        tail = (res.stderr or "").strip()[-1500:]
        run.error = f"the code exited with status {res.exit_code}" + (f":\n{tail}" if tail else "")
    else:
        try:
            run.quantities = parse_output(res.stdout)
            run.ok = True
        except CodeOutputError as e:
            run.error = str(e)
    return run


def parse_output(stdout: str) -> Dict[str, Dict[str, Any]]:
    """The quantities the code printed: ``{name: {value, unit, as_of?}}``, checked for shape."""
    text = (stdout or "").strip()
    if not text:
        raise CodeOutputError("the code printed nothing; print one JSON object of quantities to standard output")
    try:
        data = json.loads(text)
    except ValueError:
        raise CodeOutputError("standard output is not one JSON object (print only the JSON; send anything else "
                              f"to standard error). It began: {text[:200]!r}")
    if not isinstance(data, dict):
        raise CodeOutputError("standard output must be a JSON object of quantities, not "
                              f"{type(data).__name__}")
    qs = data["quantities"] if isinstance(data.get("quantities"), dict) and len(data) == 1 else data
    if not qs:
        raise CodeOutputError("the output names no quantities")
    if len(qs) > MAX_QUANTITIES:
        raise CodeOutputError(f"{len(qs)} quantities; at most {MAX_QUANTITIES}")
    out: Dict[str, Dict[str, Any]] = {}
    for name, q in qs.items():
        if not NAME.match(str(name)):
            raise CodeOutputError(f"quantity name {name!r} is not an identifier (letters, digits, underscore)")
        if not isinstance(q, dict) or "value" not in q or "unit" not in q:
            raise CodeOutputError(f'quantity "{name}" must be {{"value": ..., "unit": "..."}}; a bare number has '
                                  f"no unit")
        extra = set(q) - {"value", "unit", "as_of"}
        if extra:
            raise CodeOutputError(f'quantity "{name}": unknown keys {", ".join(sorted(extra))}')
        if not isinstance(q["unit"], str) or not q["unit"].strip():
            raise CodeOutputError(f'quantity "{name}": unit must be a non-empty string such as "USD mn", '
                                  f'"percent", "bp", "ratio", "count" or "unitless"')
        out[str(name)] = {"value": q["value"], "unit": q["unit"].strip(),
                          "as_of": None if q.get("as_of") is None else str(q["as_of"])}
    return out


def build_input(question: str, quantities: List[Dict[str, Any]], results: List[Dict[str, Any]]) -> str:
    """The JSON the code reads on standard input: the question, the workspace's quantities and the
    run's successful results (their data, or the preview when the data is not held or too large)."""
    rows = []
    for r in results:
        if not r.get("ok"):
            continue
        rows.append({"id": r.get("id"), "tool": r.get("tool"), "arguments": r.get("arguments") or {},
                     "data": r.get("data") if r.get("data") is not None else r.get("preview")})
    payload = {"question": question, "quantities": {q["name"]: {k: q.get(k) for k in ("value", "unit", "as_of")}
                                                    for q in quantities if q.get("name")},
               "results": rows}
    text = json.dumps(payload, default=str, sort_keys=True)
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:          # too big: previews only
        for row in payload["results"]:
            row["data"] = str(row["data"])[:2000]
        text = json.dumps(payload, default=str, sort_keys=True)
    return text
