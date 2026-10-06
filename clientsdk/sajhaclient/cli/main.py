"""
``sajha`` — the SAJHA command line.

Talks to a SAJHA server over HTTP with the client SDK: MCP operations (tools,
prompts) through :class:`sajhaclient.SajhaMCPSyncClient` (the official MCP SDK,
``pip install 'sajhaclient[cli]'``), everything else through the REST API.
``sajha serve`` starts a server from a SAJHA checkout, over HTTP or, with
``--stdio``, over stdin/stdout for desktop MCP clients.

The guide is docs/clients/Command Line.md.

Exit codes:
    0  success
    1  the operation failed (tool returned an error, server error, bad input)
    2  usage error (bad command line)
    3  authentication required or rejected (run ``sajha login``)
    4  permission denied (the identity lacks the role or tool access)
    5  not found (tool, prompt, upstream, endpoint)
    6  cannot reach the server
    130 interrupted
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from sajhaclient import __version__
from sajhaclient.cli import profiles
from sajhaclient.cli.render import (AskRenderer, Out, dump, first_line, iter_sse, print_schema,
                                    print_tool_result, table)
from sajhaclient.exceptions import (SajhaAuthError, SajhaConnectionError, SajhaError, SajhaMCPError,
                                    SajhaNotFoundError, SajhaPermissionError, SajhaValidationError)

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_AUTH, EXIT_FORBIDDEN, EXIT_NOT_FOUND, EXIT_UNREACHABLE = 0, 1, 2, 3, 4, 5, 6
EXIT_INTERRUPTED = 130


class CLIError(Exception):
    def __init__(self, message: str, code: int = EXIT_FAIL):
        super().__init__(message)
        self.code = code


# ── context: settings, clients ───────────────────────────────────

class Context:
    def __init__(self, args: argparse.Namespace, out: Out):
        self.args = args
        self.out = out
        self.settings = profiles.resolve(server=args.server, api_key=args.api_key,
                                         profile=args.profile, timeout=args.timeout)
        self._rest = None

    @property
    def json_output(self) -> bool:
        return bool(getattr(self.args, "json_out", False)) or getattr(self.args, "output", None) == "json"

    def auth(self):
        from sajhaclient.auth import ApiKeyAuth, JWTAuth, NoAuth
        s = self.settings
        if s.api_key:
            return ApiKeyAuth(s.api_key)
        if s.token:
            return JWTAuth.from_token(s.token)
        return NoAuth()

    def config(self):
        from sajhaclient.config import SajhaConfig
        return SajhaConfig(base_url=self.settings.url, timeout=self.settings.timeout, max_retries=1)

    def rest(self):
        if self._rest is None:
            from sajhaclient.client import SajhaClient
            self._rest = SajhaClient(self.config(), auth=self.auth())
        return self._rest

    def request(self, method: str, path: str, body: Optional[Dict] = None, params: Optional[Dict] = None):
        return self.rest()._request(method, path, body=body, params=params)

    def mcp(self):
        """A connected SajhaMCPSyncClient (protocol negotiated automatically)."""
        try:
            from sajhaclient.standard import SajhaMCPSyncClient, require_mcp
            require_mcp()
        except ImportError as e:
            raise CLIError(f"{e}\n  (install the CLI extra: pip install 'sajhaclient[cli]')")
        client = SajhaMCPSyncClient(self.settings.url, config=self.config(), auth=self.auth(),
                                    client_name="sajha-cli")
        try:
            client.connect()
        except Exception as e:
            raise translate(e, self.settings.url)
        return client

    def open_stream(self, path: str, body: Dict[str, Any]):
        """POST JSON and return the open urllib response of an SSE stream."""
        auth = self.auth()
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream",
                   "User-Agent": f"sajha-cli/{__version__}", **auth.get_headers()}
        req = urllib.request.Request(self.settings.url + path, data=json.dumps(body).encode("utf-8"),
                                     headers=headers, method="POST")
        try:
            return urllib.request.urlopen(req, timeout=max(self.settings.timeout, 300))
        except urllib.error.HTTPError as e:
            raise http_error(e.code, e.read().decode("utf-8", errors="replace"), path)
        except urllib.error.URLError as e:
            raise CLIError(f"cannot reach {self.settings.url}: {e.reason}", EXIT_UNREACHABLE)


def _error_text(body: str) -> str:
    try:
        data = json.loads(body)
    except ValueError:
        return body.strip()[:500]
    if isinstance(data, dict):
        return str(data.get("error") or data.get("detail") or data.get("message") or data)
    return str(data)


def http_error(status: int, body: str, what: str = "") -> CLIError:
    text = _error_text(body)
    if status == 401:
        return CLIError(f"authentication required or rejected ({text}); run 'sajha login' or pass --api-key",
                        EXIT_AUTH)
    if status == 403:
        return CLIError(f"permission denied: {text}", EXIT_FORBIDDEN)
    if status == 404:
        return CLIError(f"not found: {what or text}", EXIT_NOT_FOUND)
    return CLIError(f"HTTP {status}: {text}", EXIT_FAIL)


def translate(e: BaseException, url: str = "") -> CLIError:
    """Map SDK / transport errors to a CLIError with a meaningful exit code."""
    if isinstance(e, CLIError):
        return e
    if isinstance(e, SajhaAuthError):
        return CLIError(f"authentication failed: {e}; run 'sajha login' or pass --api-key", EXIT_AUTH)
    if isinstance(e, SajhaPermissionError):
        return CLIError(str(e), EXIT_FORBIDDEN)
    if isinstance(e, SajhaNotFoundError):
        return CLIError(str(e), EXIT_NOT_FOUND)
    if isinstance(e, SajhaConnectionError):
        text = str(e)
        for code, exit_code in (("401", EXIT_AUTH), ("403", EXIT_FORBIDDEN)):
            if f" {code} " in text or f"'{code} " in text or f"{code} Unauthorized" in text or f"{code} Forbidden" in text:
                return CLIError(f"server answered {code}: run 'sajha login' or pass --api-key", exit_code)
        return CLIError(f"cannot reach {url or 'the server'}: {text}", EXIT_UNREACHABLE)
    if isinstance(e, SajhaMCPError):
        if e.code in (-32001,):
            return CLIError(f"MCP error {e.code}: {e.message}", EXIT_AUTH)
        if e.code in (-32002, -32010):
            return CLIError(f"MCP error {e.code}: {e.message}", EXIT_FORBIDDEN)
        return CLIError(f"MCP error {e.code}: {e.message}", EXIT_FAIL)
    if isinstance(e, SajhaValidationError):
        return CLIError(str(e), EXIT_FAIL)
    if isinstance(e, SajhaError):
        return CLIError(str(e), EXIT_FAIL)
    # httpx2 status errors from the MCP SDK transport
    status = getattr(getattr(e, "response", None), "status_code", None)
    if isinstance(status, int):
        return http_error(status, "", "")
    for leaf in _leaves(e):
        if leaf is not e:
            mapped = translate(leaf, url)
            if mapped.code != EXIT_FAIL or not isinstance(leaf, Exception):
                return mapped
    return CLIError(f"{type(e).__name__}: {e}", EXIT_FAIL)


def _leaves(e: BaseException):
    subs = getattr(e, "exceptions", None)
    if subs:
        for s in subs:
            yield from _leaves(s)
    else:
        yield e


# ── argument helpers ─────────────────────────────────────────────

def parse_kv(pairs: List[str], schema: Optional[Dict[str, Any]] = None, strings_only: bool = False) -> Dict[str, Any]:
    """``k=v`` pairs -> dict.  Values are typed by the input schema (string stays string;
    numbers, booleans, arrays and objects are parsed as JSON); without a schema, JSON
    if it parses, else the raw string.  ``k=@file`` reads the value from a file."""
    props = (schema or {}).get("properties") or {}
    result: Dict[str, Any] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise CLIError(f"--arg expects key=value, got {pair!r}", EXIT_USAGE)
        key, value = pair.split("=", 1)
        key = key.strip()
        if value.startswith("@") and len(value) > 1:
            try:
                value = Path(value[1:]).expanduser().read_text(encoding="utf-8")
            except OSError as e:
                raise CLIError(f"--arg {key}: cannot read {value[1:]}: {e}", EXIT_USAGE)
        if strings_only:
            result[key] = value
            continue
        kind = (props.get(key) or {}).get("type") if isinstance(props.get(key), dict) else None
        if kind == "string" or (isinstance(kind, list) and kind == ["string"]):
            result[key] = value
            continue
        try:
            result[key] = json.loads(value)
        except ValueError:
            if kind in ("integer", "number", "boolean", "array", "object"):
                raise CLIError(f"--arg {key}: expected {kind}, got {value!r}", EXIT_USAGE)
            result[key] = value
    return result


def load_json_arg(value: str, what: str = "--json") -> Dict[str, Any]:
    if value == "-":
        text = sys.stdin.read()
    elif value.startswith("@"):
        try:
            text = Path(value[1:]).expanduser().read_text(encoding="utf-8")
        except OSError as e:
            raise CLIError(f"{what}: {e}", EXIT_USAGE)
    else:
        text = value
    try:
        data = json.loads(text)
    except ValueError as e:
        raise CLIError(f"{what}: not valid JSON ({e})", EXIT_USAGE)
    if not isinstance(data, dict):
        raise CLIError(f"{what}: must be a JSON object", EXIT_USAGE)
    return data


def tool_group(name: str) -> str:
    """The provider group of a tool: its name prefix, as the server's tool-group pages use."""
    return name.split("_")[0] if "_" in name else name


# ── commands: account ────────────────────────────────────────────

def cmd_login(ctx: Context) -> int:
    a, out, s = ctx.args, ctx.out, ctx.settings
    if a.with_api_key:
        key = a.with_api_key if a.with_api_key != "-" else sys.stdin.readline().strip()
        ctx.settings.api_key, ctx.settings.token = key, None
        ctx._rest = None
        try:
            ctx.mcp().close()     # validates the key
        except CLIError as e:
            raise CLIError(f"API key rejected: {e}", e.code)
        path = profiles.update_profile(s.profile, url=s.url, api_key=key, token=None, user=None)
        out.print(f"Stored API key for profile '{s.profile}' ({s.url}) in {path}")
        return EXIT_OK
    username = a.username or s.user or input("Username: ").strip()
    if a.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = os.environ.get("SAJHA_PASSWORD") or getpass.getpass(f"Password for {username}: ")
    if not username or not password:
        raise CLIError("username and password are required", EXIT_USAGE)
    req = urllib.request.Request(s.url + "/api/auth/login",
                                 data=json.dumps({"user_id": username, "password": password}).encode(),
                                 headers={"Content-Type": "application/json", "Accept": "application/json",
                                          "User-Agent": f"sajha-cli/{__version__}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=s.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code in (401, 423, 429):
            raise CLIError(f"login failed: {_error_text(body)}", EXIT_AUTH)
        raise http_error(e.code, body, "/api/auth/login")
    except urllib.error.URLError as e:
        raise CLIError(f"cannot reach {s.url}: {e.reason}", EXIT_UNREACHABLE)
    token = data.get("token")
    if not token:
        raise CLIError("login response carried no token", EXIT_FAIL)
    path = profiles.update_profile(s.profile, url=s.url, user=username, token=token, api_key=None)
    user = data.get("user") or {}
    out.print(f"Logged in to {s.url} as {user.get('user_id', username)} "
              f"(roles: {', '.join(user.get('roles') or []) or '-'}); profile '{s.profile}' saved to {path}")
    if data.get("password_change_required"):
        out.note("note: this account must change its password (web UI: Profile > Change password)")
    return EXIT_OK


def cmd_logout(ctx: Context) -> int:
    profiles.update_profile(ctx.settings.profile, token=None, api_key=None)
    ctx.out.print(f"Removed stored credentials from profile '{ctx.settings.profile}'")
    return EXIT_OK


def cmd_profile(ctx: Context) -> int:
    a, out = ctx.args, ctx.out
    data = profiles.load()
    if a.profile_cmd in (None, "list"):
        if ctx.json_output:
            out.json({"current": data["current"],
                      "profiles": {n: {k: (profiles.redact(v) if k in profiles.SECRET_KEYS else v)
                                       for k, v in p.items()} for n, p in data["profiles"].items()}})
            return EXIT_OK
        if not data["profiles"]:
            out.print("No profiles yet: run 'sajha login' (or 'sajha profile add NAME --url URL').")
            return EXIT_OK
        rows = []
        for name, p in sorted(data["profiles"].items()):
            auth = "api key" if p.get("api_key") else (f"login ({p.get('user')})" if p.get("token") else "none")
            rows.append(("*" if name == data["current"] else " ", name, p.get("url", profiles.DEFAULT_URL), auth))
        table(out, rows, ("", "PROFILE", "URL", "AUTH"))
        return EXIT_OK
    if a.profile_cmd == "use":
        if a.name not in data["profiles"]:
            raise CLIError(f"no profile {a.name!r}", EXIT_NOT_FOUND)
        data["current"] = a.name
        profiles.save(data)
        out.print(f"Current profile: {a.name}")
        return EXIT_OK
    if a.profile_cmd == "add":
        profiles.update_profile(a.name, url=a.url.rstrip("/"))
        out.print(f"Profile '{a.name}' -> {a.url}")
        return EXIT_OK
    if a.profile_cmd == "remove":
        if data["profiles"].pop(a.name, None) is None:
            raise CLIError(f"no profile {a.name!r}", EXIT_NOT_FOUND)
        if data["current"] == a.name:
            data["current"] = profiles.DEFAULT_PROFILE
        profiles.save(data)
        out.print(f"Removed profile '{a.name}'")
        return EXIT_OK
    raise CLIError("unknown profile command", EXIT_USAGE)


# ── commands: server ─────────────────────────────────────────────

def cmd_health(ctx: Context) -> int:
    try:
        data = ctx.rest().health()
    except Exception as e:
        raise translate(e, ctx.settings.url)
    if ctx.json_output:
        ctx.out.json(data)
    else:
        status = data.get("status", "?")
        ctx.out.print(f"{ctx.settings.url}: {ctx.out.c(status, 'green' if status == 'healthy' else 'yellow')}  "
                      f"{data.get('app_name', 'SAJHA')} {data.get('version', '')}  "
                      f"tools {data.get('tools_count', '?')}  prompts {data.get('prompts_count', '?')}  "
                      f"db {data.get('db_type', '?')}")
    return EXIT_OK if data.get("status") == "healthy" else EXIT_FAIL


def cmd_config(ctx: Context) -> int:
    out = ctx.out
    if ctx.args.remote:
        try:
            data = ctx.request("GET", "/api/ai/config")
        except Exception as e:
            raise translate(e, ctx.settings.url)
        out.json(data)
        return EXIT_OK
    desc = ctx.settings.describe()
    if ctx.json_output:
        out.json(desc)
        return EXIT_OK
    sources = desc.pop("sources")
    for k, v in desc.items():
        src = sources.get(k)
        out.print(f"{k:12} {v if v is not None else '-'}" + (out.c(f"   ({src})", "dim") if src else ""))
    return EXIT_OK


# ── commands: tools ──────────────────────────────────────────────

def _all_tools(ctx: Context):
    client = ctx.mcp()
    try:
        return [dump(t) for t in client.list_all_tools()], client
    except Exception as e:
        client.close()
        raise translate(e, ctx.settings.url)


def cmd_tools_list(ctx: Context) -> int:
    a, out = ctx.args, ctx.out
    tools, client = _all_tools(ctx)
    client.close()
    if a.filter:
        try:
            rx = re.compile(a.filter, re.IGNORECASE)
        except re.error as e:
            raise CLIError(f"--filter: bad regular expression: {e}", EXIT_USAGE)
        tools = [t for t in tools if rx.search(t["name"]) or rx.search(t.get("description") or "")]
    tools.sort(key=lambda t: t["name"])
    if a.names:
        for t in tools:
            out.print(t["name"])
        return EXIT_OK
    if ctx.json_output:
        if a.group:
            groups: Dict[str, List[str]] = {}
            for t in tools:
                groups.setdefault(tool_group(t["name"]), []).append(t["name"])
            out.json(groups)
        else:
            out.json(tools)
        return EXIT_OK
    if not tools:
        out.note(("no tools visible to this identity match the filter" if a.filter else
                  "no tools visible to this identity") +
                 ("" if ctx.settings.api_key or ctx.settings.token else
                  " (not signed in: run 'sajha login' or pass --api-key)"))
        return EXIT_OK
    if a.group:
        groups = {}
        for t in tools:
            groups.setdefault(tool_group(t["name"]), []).append(t)
        for g in sorted(groups):
            out.print(out.c(f"{g} ({len(groups[g])})", "bold"))
            table(out, [("  " + t["name"], first_line(t.get("description"))) for t in groups[g]])
    else:
        table(out, [(t["name"], first_line(t.get("description"))) for t in tools])
    out.note(f"{len(tools)} tools")
    return EXIT_OK


def _find_tool(tools: List[Dict[str, Any]], name: str) -> Dict[str, Any]:
    for t in tools:
        if t["name"] == name:
            return t
    close = [t["name"] for t in tools if name.lower() in t["name"].lower()][:5]
    hint = f"; did you mean: {', '.join(close)}" if close else ""
    raise CLIError(f"no tool {name!r} visible to this identity{hint}", EXIT_NOT_FOUND)


def cmd_tools_show(ctx: Context) -> int:
    out = ctx.out
    tools, client = _all_tools(ctx)
    client.close()
    tool = _find_tool(tools, ctx.args.name)
    if ctx.json_output:
        out.json(tool)
        return EXIT_OK
    out.print(out.c(tool["name"], "bold") + (f"  ({tool['title']})" if tool.get("title") else ""))
    if tool.get("description"):
        out.print("")
        for line in (tool["description"] or "").strip().splitlines():
            out.print("  " + line)
    out.print("\n" + out.c("Arguments", "bold"))
    print_schema(out, tool.get("inputSchema") or {})
    ann = tool.get("annotations") or {}
    if ann:
        out.print("\n" + out.c("Annotations", "bold"))
        for k, v in ann.items():
            out.print(f"  {k}: {v}")
    if tool.get("outputSchema"):
        out.print("\n" + out.c("Output schema", "bold") + "  (sajha tools show --json for the full schema)")
    out.print("\n" + out.c("Example", "bold"))
    req = (tool.get("inputSchema") or {}).get("required") or []
    out.print(f"  sajha tools call {tool['name']}" + "".join(f" --arg {r}=..." for r in req))
    return EXIT_OK


def cmd_tools_call(ctx: Context) -> int:
    a, out = ctx.args, ctx.out
    json_args = a.json_args if isinstance(a.json_args, str) else None
    if a.json_args is True:
        ctx.args.json_out = True
    client = ctx.mcp()
    try:
        schema = None
        if a.arg and not a.no_schema:
            try:
                schema = (_find_tool([dump(t) for t in client.list_all_tools()], a.name).get("inputSchema"))
            except CLIError:
                schema = None
        arguments = load_json_arg(json_args) if json_args else {}
        arguments.update(parse_kv(a.arg, schema))
        try:
            result = client.call_tool(a.name, arguments)
        except Exception as e:
            err = translate(e, ctx.settings.url)
            if err.code == EXIT_FAIL and "not found" in str(err).lower():
                err.code = EXIT_NOT_FOUND
            raise err
    finally:
        client.close()
    data = dump(result)
    if ctx.json_output:
        out.json(data)
    else:
        print_tool_result(out, result)
    if data.get("isError"):
        if not ctx.json_output:
            out.error(f"tool {a.name} returned an error")
        return EXIT_FAIL
    return EXIT_OK


# ── commands: prompts ────────────────────────────────────────────

def cmd_prompts_list(ctx: Context) -> int:
    out = ctx.out
    client = ctx.mcp()
    try:
        prompts = [dump(p) for p in client.list_all_prompts()]
    except Exception as e:
        raise translate(e, ctx.settings.url)
    finally:
        client.close()
    if ctx.args.filter:
        rx = re.compile(ctx.args.filter, re.IGNORECASE)
        prompts = [p for p in prompts if rx.search(p["name"]) or rx.search(p.get("description") or "")]
    prompts.sort(key=lambda p: p["name"])
    if ctx.json_output:
        out.json(prompts)
        return EXIT_OK
    rows = []
    for p in prompts:
        args = ", ".join((x["name"] + ("" if x.get("required") else "?")) for x in p.get("arguments") or [])
        rows.append((p["name"], args or "-", first_line(p.get("description"))))
    table(out, rows, ("PROMPT", "ARGUMENTS", "DESCRIPTION"))
    return EXIT_OK


def cmd_prompts_get(ctx: Context) -> int:
    out = ctx.out
    arguments = parse_kv(ctx.args.arg, strings_only=True)
    client = ctx.mcp()
    try:
        result = client.get_prompt(ctx.args.name, arguments)
    except Exception as e:
        raise translate(e, ctx.settings.url)
    finally:
        client.close()
    data = dump(result)
    if ctx.json_output:
        out.json(data)
        return EXIT_OK
    if data.get("description"):
        out.note(data["description"])
    for m in data.get("messages") or []:
        content = m.get("content") or {}
        text = content.get("text") if isinstance(content, dict) else str(content)
        out.print(out.c(f"[{m.get('role')}]", "bold"))
        out.print(text if text is not None else json.dumps(content, indent=2))
    return EXIT_OK


# ── commands: ask ────────────────────────────────────────────────

def cmd_ask(ctx: Context) -> int:
    a, out = ctx.args, ctx.out
    question = " ".join(a.question).strip()
    if question == "-":
        question = sys.stdin.read().strip()
    if not question:
        raise CLIError("ask needs a question", EXIT_USAGE)
    body: Dict[str, Any] = {"question": question}
    if a.model:
        body["model"] = a.model
    if a.confirm:
        body["confirm"] = list(a.confirm)
    resp = ctx.open_stream("/api/ai/ask?stream=1", body)
    renderer = AskRenderer(out, verbose=a.verbose)
    try:
        with resp:
            for event in iter_sse(resp):
                if ctx.json_output:
                    if a.events:
                        out.print(json.dumps(event, default=str, ensure_ascii=False))
                    elif event.get("type") == "done":
                        renderer.result = event.get("result")
                    elif event.get("type") == "error":
                        renderer.error = event
                    continue
                renderer.event(event)
    except KeyboardInterrupt:
        raise
    if ctx.json_output and not a.events:
        out.json(renderer.result if renderer.result is not None else {"error": renderer.error})
    if renderer.error:
        return EXIT_FAIL
    if renderer.confirmations and not (renderer.result or {}).get("answer"):
        return EXIT_FAIL
    return EXIT_OK


# ── commands: studio ─────────────────────────────────────────────

def cmd_studio_deploy(ctx: Context) -> int:
    path = Path(ctx.args.file).expanduser()
    try:
        code = path.read_text(encoding="utf-8")
    except OSError as e:
        raise CLIError(f"cannot read {path}: {e}", EXIT_USAGE)
    name = (ctx.args.name or path.stem).strip().lower()
    endpoint = "/admin/studio/analyze" if ctx.args.dry_run else "/admin/studio/deploy"
    try:
        data = ctx.request("POST", endpoint, body={"code": code, "tool_name": name})
    except SajhaValidationError as e:
        raise CLIError(f"Studio refused {path.name}: {_error_text(str(e).split(':', 1)[-1])}", EXIT_FAIL)
    except Exception as e:
        raise translate(e, ctx.settings.url)
    if ctx.json_output:
        ctx.out.json(data)
    elif ctx.args.dry_run:
        ctx.out.print(f"{name}: {data.get('description') or ''}".rstrip())
        for p in data.get("parameters") or []:
            ctx.out.print(f"  {p['name']}: {p.get('type') or 'any'}" + ("" if p.get("required") else " (optional)"))
        for w in data.get("warnings") or []:
            ctx.out.note(f"warning: {w}")
    else:
        ctx.out.print(data.get("message") or f"Deployed {name}")
    return EXIT_OK if data.get("success", True) else EXIT_FAIL


def cmd_studio_delete(ctx: Context) -> int:
    try:
        data = ctx.request("POST", "/admin/studio/delete", body={"tool_name": ctx.args.name})
    except SajhaValidationError as e:
        raise CLIError(_error_text(str(e).split(":", 1)[-1]), EXIT_FAIL)
    except Exception as e:
        raise translate(e, ctx.settings.url)
    if ctx.json_output:
        ctx.out.json(data)
    else:
        ctx.out.print(data.get("message") or "Deleted")
    return EXIT_OK if data.get("success", True) else EXIT_FAIL


# ── commands: federation ─────────────────────────────────────────

def _federation(ctx: Context, method: str, path: str, body: Optional[Dict] = None):
    try:
        return ctx.request(method, "/api/federation" + path, body=body)
    except SajhaNotFoundError:
        if path in ("/upstreams",):
            raise CLIError("this server has no federation API (/api/federation)", EXIT_NOT_FOUND)
        raise CLIError(f"no such upstream: {path.split('/')[2] if path.count('/') >= 2 else path}", EXIT_NOT_FOUND)
    except SajhaValidationError as e:
        raise CLIError(_error_text(str(e).split(":", 1)[-1]), EXIT_FAIL)
    except Exception as e:
        raise translate(e, ctx.settings.url)


def cmd_federation_list(ctx: Context) -> int:
    data = _federation(ctx, "GET", "/upstreams")
    if ctx.json_output:
        ctx.out.json(data)
        return EXIT_OK
    summary = data.get("summary") or {}
    ups = data.get("upstreams") or []
    ctx.out.note(f"federation {'enabled' if summary.get('enabled') else 'disabled'}; "
                 f"{len(ups)} upstreams, {summary.get('exposed_tools', 0)} exposed tools")
    rows = []
    for u in ups:
        counts = u.get("counts") or {}
        where = u.get("url") or u.get("command") or ""
        rows.append((u.get("id"), u.get("state"), u.get("transport"), u.get("prefix") or "",
                     f"{counts.get('approved', 0)}/{len(u.get('items') or [])}", where))
    if rows:
        table(ctx.out, rows, ("ID", "STATE", "TRANSPORT", "PREFIX", "APPROVED", "ENDPOINT"))
    return EXIT_OK


def cmd_federation_add(ctx: Context) -> int:
    a = ctx.args
    body = load_json_arg(a.json_def) if a.json_def else {}
    for key in ("id", "url", "title", "transport", "prefix", "command"):
        v = getattr(a, key, None)
        if v:
            body[key] = v
    if a.header:
        body["headers"] = {**(body.get("headers") or {}), **parse_kv(a.header, strings_only=True)}
    if a.arg_list:
        body["args"] = list(a.arg_list)
    if not body.get("id"):
        raise CLIError("federation add needs --id (or an id in --json)", EXIT_USAGE)
    data = _federation(ctx, "POST", "/upstreams", body)
    if ctx.json_output:
        ctx.out.json(data)
    else:
        ctx.out.print(f"Added upstream '{(data.get('upstream') or {}).get('id', body['id'])}'"
                      " (its tools wait for approval on the Federation page unless auto-approved)")
    return EXIT_OK


def cmd_federation_refresh(ctx: Context) -> int:
    data = _federation(ctx, "POST", f"/upstreams/{ctx.args.id}/refresh")
    if ctx.json_output:
        ctx.out.json(data)
    else:
        u = data.get("upstream") or {}
        ctx.out.print(f"Refreshed '{ctx.args.id}': state {u.get('state')}, {len(u.get('items') or [])} items"
                      + (f"; last error: {u['last_error']}" if u.get("last_error") else ""))
    return EXIT_OK


def cmd_federation_remove(ctx: Context) -> int:
    data = _federation(ctx, "DELETE", f"/upstreams/{ctx.args.id}")
    if ctx.json_output:
        ctx.out.json(data)
    else:
        ctx.out.print(f"Removed upstream '{ctx.args.id}'")
    return EXIT_OK


# ── commands: serve ──────────────────────────────────────────────

def find_server_root(explicit: Optional[str] = None) -> Path:
    candidates = [explicit, os.environ.get("SAJHA_HOME")]
    for c in candidates:
        if c:
            root = Path(c).expanduser().resolve()
            if (root / "sajha" / "cli" / "stdio.py").is_file():
                return root
            raise CLIError(f"{root} is not a SAJHA server checkout (no sajha/cli/stdio.py)", EXIT_USAGE)
    try:
        import sajha  # noqa: F401
        root = Path(sajha.__file__).resolve().parent.parent
        if (root / "sajha" / "cli" / "stdio.py").is_file():
            return root
    except ImportError:
        pass
    here = Path.cwd()
    for p in [here, *here.parents]:
        if (p / "sajha" / "cli" / "stdio.py").is_file() and (p / "run_server.py").is_file():
            return p
    raise CLIError("cannot find the SAJHA server: run from a checkout, or pass --root / set SAJHA_HOME",
                   EXIT_USAGE)


def cmd_serve(ctx: Context) -> int:
    a = ctx.args
    root = find_server_root(a.root)
    rest = list(a.rest or [])
    if rest and rest[0] == "--":
        rest = rest[1:]
    if a.stdio:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from sajha.cli.stdio import main as stdio_main
        argv = list(rest)
        if a.user:
            argv += ["--user", a.user]
        if a.api_key:
            argv += ["--api-key", a.api_key]
        argv += ["--root", str(root)]
        return stdio_main(argv)
    argv = [sys.executable, str(root / "run_server.py")]
    if a.port:
        argv += ["--port", str(a.port)]
    if a.host:
        argv += ["--host", a.host]
    argv += rest
    os.chdir(root)
    os.execv(sys.executable, argv)
    return EXIT_OK  # pragma: no cover


# ── commands: completion, version ────────────────────────────────

def cmd_completion(ctx: Context) -> int:
    from sajhaclient.cli.completion import script
    ctx.out.print(script(ctx.args.shell, build_parser()))
    return EXIT_OK


def cmd_version(ctx: Context) -> int:
    ctx.out.print(f"sajha {__version__} (sajhaclient)")
    return EXIT_OK


# ── parser ───────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    g = common.add_argument_group("connection")
    g.add_argument("--server", "-s", metavar="URL", default=argparse.SUPPRESS,
                   help="server URL (env SAJHA_URL; default from the profile, else http://localhost:3002)")
    g.add_argument("--api-key", "-k", metavar="KEY", default=argparse.SUPPRESS,
                   help="API key (env SAJHA_API_KEY); overrides a stored login")
    g.add_argument("--profile", "-p", metavar="NAME", default=argparse.SUPPRESS,
                   help="profile in ~/.config/sajha/config.json (env SAJHA_PROFILE)")
    g.add_argument("--timeout", type=int, metavar="SEC", default=argparse.SUPPRESS, help="HTTP timeout (default 30)")
    g.add_argument("--output", "-o", choices=("text", "json"), default=argparse.SUPPRESS, help="output format")
    g.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS, help="no ANSI colour")

    def json_flag(p):
        p.add_argument("--json", dest="json_out", action="store_true", default=argparse.SUPPRESS,
                       help="JSON output (same as -o json)")

    parser = argparse.ArgumentParser(
        prog="sajha", parents=[common],
        description="SAJHA MCP Server command line: tools, prompts, ask, Studio, federation, and the stdio server.",
        epilog="Exit codes: 0 ok, 1 failed, 2 usage, 3 auth, 4 forbidden, 5 not found, 6 unreachable. "
               "Guide: docs/clients/Command Line.md")
    json_flag(parser)
    parser.add_argument("--version", action="version", version=f"sajha {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    def add(subparsers, name, func, help_text, **kw):
        p = subparsers.add_parser(name, parents=[common], help=help_text, description=help_text, **kw)
        p.set_defaults(func=func)
        return p

    p = add(sub, "login", cmd_login, "sign in and store a token for this profile (file mode 0600)")
    p.add_argument("--username", "-u")
    p.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    p.add_argument("--with-api-key", metavar="KEY", help="store an API key instead of signing in ('-' reads stdin)")
    add(sub, "logout", cmd_logout, "forget the stored token / API key of this profile")

    p = add(sub, "profile", cmd_profile, "list, add, switch or remove profiles")
    json_flag(p)
    ps = p.add_subparsers(dest="profile_cmd", metavar="ACTION")
    ps.add_parser("list", help="list profiles")
    pu = ps.add_parser("use", help="make a profile current")
    pu.add_argument("name")
    pa = ps.add_parser("add", help="add a profile for a server URL")
    pa.add_argument("name")
    pa.add_argument("url")
    pr = ps.add_parser("remove", help="remove a profile")
    pr.add_argument("name")

    p = add(sub, "health", cmd_health, "server health (GET /health; no credentials needed)")
    json_flag(p)

    p = add(sub, "config", cmd_config, "show configuration")
    cs = p.add_subparsers(dest="config_cmd", metavar="ACTION")
    pc = cs.add_parser("show", parents=[common], help="effective CLI settings and where each came from; "
                                                      "--remote: the server's effective ai.* config (admin)")
    json_flag(pc)
    pc.add_argument("--remote", action="store_true", help="GET /api/ai/config from the server (admin only)")
    pc.set_defaults(func=cmd_config)
    p.set_defaults(func=cmd_config, remote=False)

    p = add(sub, "tools", None, "list, inspect and call tools (MCP)")
    ts = p.add_subparsers(dest="tools_cmd", metavar="ACTION")
    tl = add(ts, "list", cmd_tools_list, "tools this identity can see")
    json_flag(tl)
    tl.add_argument("--filter", "-f", metavar="REGEX", help="match name or description (case-insensitive)")
    tl.add_argument("--group", "-g", action="store_true", help="group by provider (name prefix)")
    tl.add_argument("--names", action="store_true", help="names only, one per line")
    tsh = add(ts, "show", cmd_tools_show, "a tool's description, arguments and annotations")
    json_flag(tsh)
    tsh.add_argument("name")
    tc = add(ts, "call", cmd_tools_call, "call a tool")
    tc.add_argument("name")
    tc.add_argument("--arg", "-a", action="append", default=[], metavar="KEY=VALUE",
                    help="an argument (repeatable); typed by the tool's schema; KEY=@file reads a file")
    tc.add_argument("--json", "-j", dest="json_args", nargs="?", const=True, default=None, metavar="ARGS",
                    help="arguments as a JSON object ('-' = stdin, @file); with no value: JSON output")
    tc.add_argument("--no-schema", action="store_true", help="do not fetch the schema to type --arg values")
    p.set_defaults(func=lambda ctx, _p=p: _usage(_p))

    p = add(sub, "prompts", None, "list and render prompts (MCP)")
    pss = p.add_subparsers(dest="prompts_cmd", metavar="ACTION")
    pl = add(pss, "list", cmd_prompts_list, "prompts this identity can see")
    json_flag(pl)
    pl.add_argument("--filter", "-f", metavar="REGEX")
    pg = add(pss, "get", cmd_prompts_get, "render a prompt with arguments")
    json_flag(pg)
    pg.add_argument("name")
    pg.add_argument("--arg", "-a", action="append", default=[], metavar="KEY=VALUE")
    p.set_defaults(func=lambda ctx, _p=p: _usage(_p))

    p = add(sub, "ask", cmd_ask, "ask a question; SAJHA picks and runs tools (POST /api/ai/ask, streamed)")
    json_flag(p)
    p.add_argument("question", nargs="+", help="the question ('-' reads stdin)")
    p.add_argument("--model", "-m", help="model alias or provider/model")
    p.add_argument("--confirm", action="append", metavar="FINGERPRINT",
                   help="approve a tool call the server asked to confirm (repeatable)")
    p.add_argument("--events", action="store_true", help="with --json: every step event as NDJSON")
    p.add_argument("--verbose", "-v", action="store_true", help="full arguments and summaries")

    p = add(sub, "studio", None, "deploy or delete MCP Studio tools (admin)")
    ss = p.add_subparsers(dest="studio_cmd", metavar="ACTION")
    sd = add(ss, "deploy", cmd_studio_deploy, "deploy a Python file with a @sajhamcptool function")
    json_flag(sd)
    sd.add_argument("file")
    sd.add_argument("--name", "-n", help="tool name (default: the file name)")
    sd.add_argument("--dry-run", action="store_true", help="analyse only (POST /admin/studio/analyze)")
    sx = add(ss, "delete", cmd_studio_delete, "delete a Studio-generated tool")
    json_flag(sx)
    sx.add_argument("name")
    p.set_defaults(func=lambda ctx, _p=p: _usage(_p))

    p = add(sub, "federation", None, "upstream MCP servers SAJHA fronts (admin)")
    fs = p.add_subparsers(dest="federation_cmd", metavar="ACTION")
    fl = add(fs, "list", cmd_federation_list, "upstreams, their state and approved items")
    json_flag(fl)
    fa = add(fs, "add", cmd_federation_add, "add an upstream")
    json_flag(fa)
    fa.add_argument("--id", required=False)
    fa.add_argument("--url")
    fa.add_argument("--title")
    fa.add_argument("--transport", choices=("streamable_http", "sse", "stdio"))
    fa.add_argument("--prefix")
    fa.add_argument("--command", help="stdio upstream: the command to launch")
    fa.add_argument("--arg", dest="arg_list", action="append", metavar="ARG", help="stdio upstream: an argument")
    fa.add_argument("--header", action="append", metavar="NAME=VALUE")
    fa.add_argument("--def", dest="json_def", metavar="JSON", help="the whole definition as JSON (@file, '-')")
    fr = add(fs, "refresh", cmd_federation_refresh, "reconnect and re-list an upstream")
    json_flag(fr)
    fr.add_argument("id")
    fx = add(fs, "remove", cmd_federation_remove, "remove an upstream added at run time")
    json_flag(fx)
    fx.add_argument("id")
    p.set_defaults(func=lambda ctx, _p=p: _usage(_p))

    p = add(sub, "serve", cmd_serve, "run the server from a SAJHA checkout: HTTP, or MCP over stdio "
                                     "(stdio identity: --user, or --api-key / env SAJHA_API_KEY)")
    p.add_argument("--stdio", action="store_true", help="speak MCP on stdin/stdout (desktop clients)")
    p.add_argument("--user", help="stdio: act as this SAJHA user (env SAJHA_STDIO_USER)")
    p.add_argument("--root", help="the SAJHA checkout (env SAJHA_HOME)")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("rest", nargs=argparse.REMAINDER, help="passed to the server (e.g. --log-level INFO, --with-ai)")

    p = add(sub, "completion", cmd_completion, "print a shell completion script")
    p.add_argument("shell", choices=("bash", "zsh", "fish"))
    add(sub, "version", cmd_version, "print the CLI version")
    return parser


def _usage(p: argparse.ArgumentParser) -> int:
    p.print_help(sys.stderr)
    return EXIT_USAGE


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    for name, default in (("server", None), ("api_key", None), ("profile", None), ("timeout", None),
                          ("output", None), ("no_color", False), ("json_out", False)):
        if not hasattr(args, name):
            setattr(args, name, default)
    out = Out(color=False if args.no_color else None)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    try:
        ctx = Context(args, out)
        return int(func(ctx) or 0)
    except CLIError as e:
        out.error(str(e))
        return e.code
    except KeyboardInterrupt:
        out.err.write("\n")
        return EXIT_INTERRUPTED
    except BrokenPipeError:
        return EXIT_OK
    except Exception as e:  # anything the SDK raised that no command mapped
        err = translate(e, getattr(args, "server", None) or "")
        out.error(str(err))
        return err.code
