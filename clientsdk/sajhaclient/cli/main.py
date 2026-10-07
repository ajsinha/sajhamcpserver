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


def cmd_studio_import_openapi(ctx: Context) -> int:
    """Import an OpenAPI 3.x / Swagger 2.0 spec (URL or file) as tools (design: docs/architecture/API Import.md)."""
    a = ctx.args
    source = a.source
    body: Dict[str, Any] = {"kind": "graphql" if a.graphql else "openapi"}
    path = Path(source).expanduser()
    if "://" not in source and path.exists():
        try:
            body["text"] = path.read_text(encoding="utf-8")
        except OSError as e:
            raise CLIError(f"cannot read {path}: {e}", EXIT_USAGE)
    else:
        body["url"] = source
    for key, value in (("prefix", a.prefix), ("base_url", a.base_url)):
        if value:
            body[key] = value
    if a.server_index is not None:
        body["server_index"] = a.server_index
    if a.auth:
        body["auth"] = load_json_arg(a.auth, "--auth")
    body["filters"] = {"tags": a.tag or [], "methods": a.method or [], "path": a.path or ""}

    def _post(endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return ctx.request("POST", f"/admin/studio/api-import/{endpoint}", body=data)
        except SajhaValidationError as e:
            raise CLIError(_error_text(str(e).split(":", 1)[-1]), EXIT_FAIL)
        except Exception as e:
            raise translate(e, ctx.settings.url)

    plan = _post("parse", body)
    ops = plan.get("operations") or []
    selected = list(a.select or []) or [o["key"] for o in ops if o.get("selected")]
    unknown = [k for k in selected if k not in {o["key"] for o in ops}]
    if unknown:
        raise CLIError(f"no such operation: {', '.join(unknown)} (keys look like 'GET /pets/{{petId}}')", EXIT_USAGE)
    if a.dry_run:
        if ctx.json_output:
            ctx.out.json(plan)
            return EXIT_OK
        api = plan.get("api") or {}
        ctx.out.print(f"{api.get('title')} {api.get('version') or ''} -> {api.get('base_url') or '(no base URL)'}".strip())
        rows = []
        for o in ops:
            mark = "*" if o["key"] in selected else " "
            flag = o.get("unsupported") or (f"name used by {o['conflict']}" if o.get("conflict") else "")
            rows.append((mark, o.get("status", ""), o["name"], o["key"] if not flag else f"{o['key']}  [{flag}]"))
        table(ctx.out, rows, ("", "STATUS", "TOOL", "OPERATION"))
        for w in plan.get("warnings") or []:
            ctx.out.note(f"warning: {w}")
        return EXIT_OK
    if not selected:
        raise CLIError("nothing to deploy (no selectable operation; see --dry-run)", EXIT_FAIL)
    result = _post("deploy", {**body, "prefix": (plan.get("api") or {}).get("prefix"), "selected": selected})
    if ctx.json_output:
        ctx.out.json(result)
    else:
        ctx.out.print(result.get("message") or "Imported")
        for f in result.get("failed") or []:
            ctx.out.note(f"failed: {f.get('name')}: {f.get('error')}")
    return EXIT_OK if result.get("success", True) else EXIT_FAIL


def cmd_studio_describe(ctx: Context) -> int:
    """Describe a tool in plain words: SAJHA proposes it, checks it and runs its tests; with --deploy and a
    confirmation, deploys exactly the reviewed version (design: docs/architecture/Tool Generation.md)."""
    a = ctx.args
    text = " ".join(a.description).strip()
    if text == "-":
        text = sys.stdin.read().strip()
    if not text:
        raise CLIError("describe the tool, e.g. sajha studio describe \"query table orders by region\"", EXIT_USAGE)

    def _post(endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return ctx.request("POST", f"/admin/studio/describe/{endpoint}", body=data)
        except SajhaValidationError as e:
            raise CLIError(_error_text(str(e).split(":", 1)[-1]), EXIT_FAIL)
        except Exception as e:
            raise translate(e, ctx.settings.url)

    draft = _post("propose", {"description": text, "kind": a.kind or "auto"})
    if not draft.get("errors"):
        draft = _post("test", {"draft_id": draft["id"], "live": bool(a.live)})
    out = ctx.out
    p = draft.get("proposal") or {}
    if ctx.json_output and not a.deploy:
        out.json(draft)
    elif not ctx.json_output:
        out.print(f"{p.get('kind')} tool {p.get('name')}: {p.get('description')}")
        out.note(f"model {draft.get('model')} · draft {draft.get('id')} · version {str(draft.get('hash'))[:12]}")
        for e in draft.get("errors") or []:
            out.print(f"  error: {e}")
        for w in draft.get("warnings") or []:
            out.note(f"warning: {w}")
        for n in p.get("notes") or []:
            out.note(f"note: {n}")
        for f in draft.get("files") or []:
            lines = (f.get("content") or "").count("\n") + 1
            out.print(f"  new file {f.get('path')} ({lines} lines)")
            if a.show_files or a.deploy:
                out.print(f.get("diff") or f.get("content") or "")
        run = draft.get("tests_run") or {}
        rows = [(r.get("status", ""), "live" if r.get("live") else "", r.get("name", ""), r.get("detail") or "")
                for r in run.get("results") or []]
        if rows:
            table(out, rows, ("RESULT", "", "CASE", "DETAIL"))
        if draft.get("handoff"):
            out.print(f"An OpenAPI spec is imported operation by operation: {ctx.settings.url}{draft['handoff']}")
    if draft.get("errors"):
        return EXIT_FAIL
    counts = (draft.get("tests_run") or {}).get("counts") or {}
    if not a.deploy:
        return EXIT_FAIL if counts.get("failed") else EXIT_OK
    if draft.get("handoff"):
        raise CLIError("an OpenAPI proposal is deployed from Import an API (see the link above)", EXIT_FAIL)
    if not a.yes:
        if not sys.stdin.isatty():
            raise CLIError("--deploy needs a confirmation: run it in a terminal, or add --yes after reviewing "
                           "the files", EXIT_USAGE)
        answer = input(f"Deploy {p.get('name')} now? Type the tool name to approve: ").strip()
        if answer != p.get("name"):
            out.note("not deployed")
            return EXIT_FAIL
    result = _post("deploy", {"draft_id": draft["id"], "hash": draft.get("hash"), "approve": True,
                              "accept_failures": bool(a.accept_failures)})
    if ctx.json_output:
        out.json(result)
    else:
        out.print(result.get("message") or f"Deployed {p.get('name')}")
    return EXIT_OK if result.get("success", True) else EXIT_FAIL


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


# ── commands: SAJHA Net ──────────────────────────────────────────

def _net(ctx: Context, method: str, path: str, body: Optional[Dict] = None):
    try:
        return ctx.request(method, "/api/sajhanet" + path, body=body)
    except SajhaNotFoundError:
        raise CLIError("this server has no SAJHA Net API (/api/sajhanet), or the net is not configured", EXIT_NOT_FOUND)
    except SajhaValidationError as e:
        raise CLIError(_error_text(str(e).split(":", 1)[-1]), EXIT_FAIL)
    except Exception as e:
        raise translate(e, ctx.settings.url)


def _net_path(ctx: Context, tail: str) -> str:
    return f"/nets/{ctx.args.net}{tail}"


def cmd_net_status(ctx: Context) -> int:
    data = _net(ctx, "GET", "/status")
    if ctx.json_output:
        ctx.out.json(data)
        return EXIT_OK
    if not data.get("enabled"):
        ctx.out.note("SAJHA Net is off on this server (sajhanet.enabled: false)")
        return EXIT_OK
    for n in data.get("nets") or []:
        state = "name conflict" if n.get("refused") else "joined" if n.get("joined") else "not joined"
        ctx.out.print(f"{n.get('net')}: {n.get('instance') or '-'} ({state}){' founder' if n.get('founder') else ''}"
                      f"{' CA' if (n.get('ca') or {}).get('initialised') else ''}")
        for line in [n.get("error"), n.get("config_error")] + list(n.get("last_errors") or []):
            if line:
                ctx.out.note(f"  {line}")
        rows = [(m.get("name"), m.get("state"), m.get("url") or "", m.get("last_seen") or "")
                for m in n.get("members") or []]
        if rows:
            table(ctx.out, rows, ("INSTANCE", "STATE", "URL", "LAST SEEN"))
    return EXIT_OK


def cmd_net_peers_add(ctx: Context) -> int:
    data = _net(ctx, "POST", _net_path(ctx, "/peers"), {"address": ctx.args.address,
                                                         "keep_as_seed": bool(ctx.args.keep_as_seed)})
    if ctx.json_output:
        ctx.out.json(data)
    else:
        ctx.out.print(f"Joined {ctx.args.net} through {data.get('peer')} ({data.get('url')})"
                      + ("; kept as a runtime seed" if data.get("kept_as_seed") else ""))
    return EXIT_OK


def cmd_net_peers_list(ctx: Context) -> int:
    data = _net(ctx, "GET", "/status")
    net = next((n for n in data.get("nets") or [] if n.get("net") == ctx.args.net), None)
    if net is None:
        raise CLIError(f"this server is not configured for net {ctx.args.net}", EXIT_NOT_FOUND)
    if ctx.json_output:
        ctx.out.json({"members": net.get("members") or [], "seeds": net.get("seeds") or [],
                      "runtime_seeds": net.get("runtime_seeds") or []})
        return EXIT_OK
    rows = [(m.get("name"), m.get("state"), m.get("url") or "") for m in net.get("members") or []]
    table(ctx.out, rows, ("INSTANCE", "STATE", "URL"))
    return EXIT_OK


def cmd_net_ca_init(ctx: Context) -> int:
    data = _net(ctx, "POST", _net_path(ctx, "/ca/init"), {})
    if ctx.json_output:
        ctx.out.json(data)
    else:
        ctx.out.print(f"CA of {ctx.args.net} initialised; thumbprint {data.get('thumbprint')}")
        ctx.out.note(f"Back up the CA key now ({data.get('key_ref')}); it is the only copy.")
    return EXIT_OK


def cmd_net_ca_enroll(ctx: Context) -> int:
    data = _net(ctx, "POST", _net_path(ctx, "/ca/tokens"), {"instance": ctx.args.instance,
                                                             "host": ctx.args.host or ""})
    if ctx.json_output:
        ctx.out.json(data)
    else:
        ctx.out.print(f"Enrollment token for {data.get('instance')} in {data.get('net')} "
                      f"(single use, until {data.get('expires_at')}):")
        ctx.out.print(data.get("token", ""))
        ctx.out.note(f"On the new server: sajha net enroll --net {data.get('net')} --ca-url {data.get('ca_url')} "
                     f"--token <token>   (CA thumbprint {data.get('ca_thumbprint')})")
    return EXIT_OK


def cmd_net_ca_revoke(ctx: Context) -> int:
    if not ctx.args.instance and not ctx.args.serial:
        raise CLIError("name an instance or give --serial", EXIT_USAGE)
    data = _net(ctx, "POST", _net_path(ctx, "/ca/revoke"), {"instance": ctx.args.instance or "",
                                                             "serial": ctx.args.serial or "",
                                                             "reason": ctx.args.reason or ""})
    if ctx.json_output:
        ctx.out.json(data)
    else:
        ctx.out.print(f"Revocation list of {data.get('net')} is now version {data.get('version')} "
                      f"({len(data.get('revoked') or [])} entries); gossip spreads it")
    return EXIT_OK


def cmd_net_ca_show(ctx: Context) -> int:
    data = _net(ctx, "GET", _net_path(ctx, "/ca"))
    if ctx.json_output:
        ctx.out.json(data)
        return EXIT_OK
    rows = [(c.get("instance"), c.get("serial"), c.get("not_after"), c.get("renews") or "") for c in data.get("issued") or []]
    table(ctx.out, rows, ("INSTANCE", "SERIAL", "NOT AFTER", "RENEWS"))
    rl = data.get("revocation_list") or {}
    ctx.out.note(f"revocation list version {rl.get('version')}, {len(rl.get('revoked') or [])} entries; "
                 f"{len(data.get('pending_tokens') or [])} pending tokens")
    return EXIT_OK


def cmd_net_enroll(ctx: Context) -> int:
    token = ctx.args.token
    if token == "-":
        token = sys.stdin.readline().strip()
    data = _net(ctx, "POST", _net_path(ctx, "/enroll"), {"ca_url": ctx.args.ca_url, "token": token})
    if ctx.json_output:
        ctx.out.json(data)
    else:
        c = data.get("certificate") or {}
        ctx.out.print(f"Enrolled in {ctx.args.net} as {c.get('instance')}: certificate {c.get('serial')} "
                      f"until {c.get('not_after')}")
    return EXIT_OK


def cmd_net_renew(ctx: Context) -> int:
    data = _net(ctx, "POST", _net_path(ctx, "/renew"), {})
    if ctx.json_output:
        ctx.out.json(data)
    else:
        c = data.get("certificate") or {}
        ctx.out.print(f"Renewed: certificate {c.get('serial')} until {c.get('not_after')} (renews {c.get('renews')})")
    return EXIT_OK


def cmd_net_pin(ctx: Context) -> int:
    data = _net(ctx, "POST", _net_path(ctx, "/pins"), {"thumbprint": ctx.args.thumbprint})
    if ctx.json_output:
        ctx.out.json(data)
    else:
        ctx.out.print(f"Pinned in {ctx.args.net}: {len(data.get('pins') or [])} thumbprints")
    return EXIT_OK


# ── commands: workflows ──────────────────────────────────────────

_RUN_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _wf(ctx: Context, method: str, path: str, body: Optional[Dict] = None, params: Optional[Dict] = None,
        what: str = ""):
    try:
        return ctx.request(method, "/api/workflows" + path, body=body, params=params)
    except SajhaNotFoundError:
        raise CLIError(f"no such workflow or run: {what}" if what else "this server has no workflows API "
                       "(/api/workflows)", EXIT_NOT_FOUND)
    except SajhaValidationError as e:
        raise CLIError(_error_text(str(e).split(":", 1)[-1]), EXIT_FAIL)
    except Exception as e:
        raise translate(e, ctx.settings.url)


def _dur(run: Dict[str, Any]) -> str:
    if run.get("finished_at") and run.get("started_at"):
        return f"{run['finished_at'] - run['started_at']:.1f}s"
    return "-"


def _when(t) -> str:
    if not t:
        return "-"
    import datetime as _dt
    return _dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")


def cmd_workflows_list(ctx: Context) -> int:
    data = _wf(ctx, "GET", "")
    if ctx.json_output:
        ctx.out.json(data)
        return EXIT_OK
    rows = [(w["name"], "on" if w.get("enabled") else "off", w.get("version"), w.get("owner"),
             ",".join(t["type"] for t in w.get("triggers") or []) or "manual",
             ("tool " if w.get("published") else "") + (w.get("description") or ""))
            for w in data.get("workflows") or []]
    if rows:
        table(ctx.out, rows, ("NAME", "ENABLED", "VER", "OWNER", "TRIGGERS", "DESCRIPTION"))
    else:
        ctx.out.note("no workflows (create one on the Workflows page or POST /api/workflows)")
    return EXIT_OK


def cmd_workflows_run(ctx: Context) -> int:
    a = ctx.args
    inp = load_json_arg(a.json_input, "--input-json") if a.json_input else {}
    if a.input:
        inp.update(parse_kv(a.input))
    body: Dict[str, Any] = {"input": inp}
    if a.idempotency_key:
        body["idempotency_key"] = a.idempotency_key
    if a.wait:
        body["wait"] = a.wait
        try:    # the HTTP call must outlive the server-side wait
            ctx.settings.timeout = max(float(ctx.settings.timeout or 30), min(a.wait, 300) + 15)
        except (AttributeError, TypeError):
            pass
    data = _wf(ctx, "POST", f"/{a.name}/runs", body, what=a.name)
    run = data.get("run") or {}
    if ctx.json_output:
        ctx.out.json(run)
    else:
        ctx.out.print(f"run {run.get('id')}: {run.get('status')}"
                      + (f" ({run['error']})" if run.get("error") else ""))
        if run.get("status") == "succeeded" and run.get("output") is not None:
            ctx.out.json(run["output"])
    return EXIT_FAIL if run.get("status") in ("failed", "cancelled") else EXIT_OK


def cmd_workflows_runs(ctx: Context) -> int:
    a = ctx.args
    params = {"limit": a.limit}
    if a.status:
        params["status"] = a.status
    data = _wf(ctx, "GET", f"/{a.name}/runs", params=params, what=a.name)
    if ctx.json_output:
        ctx.out.json(data)
        return EXIT_OK
    rows = [(r["id"], _when(r.get("created_at")), r.get("status"), r.get("trigger_type"), _dur(r),
             (r.get("error") or "")[:120]) for r in data.get("runs") or []]
    if rows:
        table(ctx.out, rows, ("RUN", "CREATED", "STATUS", "TRIGGER", "TIME", "ERROR"))
    else:
        ctx.out.note("no runs yet")
    return EXIT_OK


def cmd_workflows_show(ctx: Context) -> int:
    a = ctx.args
    if _RUN_ID.match(a.target):
        run = (_wf(ctx, "GET", f"/runs/{a.target}", what=a.target) or {}).get("run") or {}
        if ctx.json_output:
            ctx.out.json(run)
            return EXIT_OK
        ctx.out.print(f"run {run.get('id')} of {run.get('workflow')} v{run.get('version')}: {run.get('status')} "
                      f"(trigger {run.get('trigger_type')}, run as {run.get('run_as')}, {_dur(run)})")
        if run.get("error"):
            ctx.out.print(f"error: {run['error']}")
        rows = [(s["step_id"], s.get("kind"), s.get("status"), s.get("attempts"),
                 f"{s['duration_ms']:.0f}ms" if s.get("duration_ms") is not None else "-",
                 (s.get("error") or "")[:120]) for s in run.get("steps") or []]
        if rows:
            table(ctx.out, rows, ("STEP", "KIND", "STATUS", "TRIES", "TIME", "ERROR"))
        return EXIT_OK
    if a.yaml:
        import urllib.parse as _up
        req = urllib.request.Request(f"{ctx.settings.url}/api/workflows/{_up.quote(a.target)}?format=yaml",
                                     headers={"Accept": "application/yaml", **ctx.auth().get_headers()})
        try:
            with urllib.request.urlopen(req, timeout=ctx.settings.timeout) as resp:
                ctx.out.print(resp.read().decode("utf-8").rstrip())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise CLIError(f"no such workflow: {a.target}", EXIT_NOT_FOUND)
            raise http_error(e.code, e.read().decode("utf-8", errors="replace"), a.target)
        except urllib.error.URLError as e:
            raise CLIError(f"cannot reach {ctx.settings.url}: {e.reason}", EXIT_UNREACHABLE)
        return EXIT_OK
    data = _wf(ctx, "GET", f"/{a.target}", what=a.target)
    ctx.out.json(data if ctx.json_output else data.get("definition") or data)
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


def cmd_db(ctx: Context) -> int:
    """``sajha db ...``: the server's schema helper (``python -m sajha.db``) in a checkout."""
    a = ctx.args
    root = find_server_root(a.root)
    rest = list(a.rest or [])
    if rest and rest[0] == "--":
        rest = rest[1:]
    os.chdir(root)
    os.execv(sys.executable, [sys.executable, "-m", "sajha.db", *rest])
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
        description="SAJHA MCP Server command line: tools, prompts, ask, Studio, federation, SAJHA Net, workflows, and the "
                    "stdio server.",
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

    p = add(sub, "studio", None, "describe, deploy, import or delete MCP Studio tools (admin or the studio permission)")
    ss = p.add_subparsers(dest="studio_cmd", metavar="ACTION")
    sd = add(ss, "deploy", cmd_studio_deploy, "deploy a Python file with a @sajhamcptool function")
    json_flag(sd)
    sd.add_argument("file")
    sd.add_argument("--name", "-n", help="tool name (default: the file name)")
    sd.add_argument("--dry-run", action="store_true", help="analyse only (POST /admin/studio/analyze)")
    sx = add(ss, "delete", cmd_studio_delete, "delete a Studio-generated tool")
    json_flag(sx)
    sx.add_argument("name")
    si = add(ss, "import-openapi", cmd_studio_import_openapi,
             "import an OpenAPI 3.x / Swagger 2.0 spec (URL or file) as tools; --graphql for a GraphQL endpoint")
    json_flag(si)
    si.add_argument("source", help="spec URL, spec file, or (with --graphql) the endpoint URL")
    si.add_argument("--prefix", help="tool-name prefix and API id (default: from the title)")
    si.add_argument("--base-url", help="the API's base URL (default: the spec's first server)")
    si.add_argument("--server-index", type=int, dest="server_index", help="index of the spec server to use")
    si.add_argument("--tag", action="append", help="only operations with this tag (repeatable)")
    si.add_argument("--method", action="append", help="only this HTTP method (repeatable)")
    si.add_argument("--path", help="only paths containing this text, or matching this glob")
    si.add_argument("--select", action="append", metavar="'METHOD /path'",
                    help="deploy this operation (repeatable; default: every selectable one)")
    si.add_argument("--auth", metavar="JSON", help="credentials by scheme as JSON (@file, '-'); secrets as "
                                                   "references, e.g. {\"api_key\": {\"type\": \"apiKey\", "
                                                   "\"value_ref\": \"env:KEY\"}}")
    si.add_argument("--graphql", action="store_true", help="the source is a GraphQL endpoint or introspection file")
    si.add_argument("--dry-run", action="store_true", help="preview only (POST /admin/studio/api-import/parse)")
    sdesc = add(ss, "describe", cmd_studio_describe,
                "describe a tool in plain words: SAJHA proposes it and runs its tests; --deploy to approve it")
    json_flag(sdesc)
    sdesc.add_argument("description", nargs="+", help="what the tool should do ('-' reads stdin)")
    sdesc.add_argument("--kind", choices=("auto", "python", "rest", "dbquery", "composite", "openapi"),
                       help="the kind of tool to propose (default: SAJHA chooses)")
    sdesc.add_argument("--live", action="store_true", help="also run the test cases that need the network")
    sdesc.add_argument("--show-files", action="store_true", help="print every file the deploy would write")
    sdesc.add_argument("--deploy", action="store_true",
                       help="deploy after showing the files and tests, once you confirm by typing the tool name")
    sdesc.add_argument("--yes", action="store_true", help="with --deploy: skip the typed confirmation")
    sdesc.add_argument("--accept-failures", action="store_true", dest="accept_failures",
                       help="with --deploy: deploy even if tests failed or none ran")
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

    p = add(sub, "net", None, "SAJHA Net: status, peers, the CA, enrollment and renewal (admin)")
    ns = p.add_subparsers(dest="net_cmd", metavar="ACTION")

    def net_flag(q):
        q.add_argument("--net", default="default", help="the net (default: default)")
        json_flag(q)
    nst = add(ns, "status", cmd_net_status, "the nets this server is in and the members it knows")
    json_flag(nst)
    pp = add(ns, "peers", None, "members of a net; add a peer by address")
    pps = pp.add_subparsers(dest="net_peers_cmd", metavar="ACTION")
    pl = add(pps, "list", cmd_net_peers_list, "the members and seeds of a net")
    net_flag(pl)
    pa = add(pps, "add", cmd_net_peers_add, "contact a peer at an address now (an ordinary signed join)")
    net_flag(pa)
    pa.add_argument("address", help="ip:port, host:port or a URL")
    pa.add_argument("--keep-as-seed", action="store_true", dest="keep_as_seed", help="also keep it as a runtime seed")
    pp.set_defaults(func=lambda ctx, _p=pp: _usage(_p))
    cp = add(ns, "ca", None, "the net's CA, on its CA instance: init, enroll (create a token), revoke, show")
    cps = cp.add_subparsers(dest="net_ca_cmd", metavar="ACTION")
    ci = add(cps, "init", cmd_net_ca_init, "create the CA key and certificate of a net (once)")
    net_flag(ci)
    ce = add(cps, "enroll", cmd_net_ca_enroll, "create a single-use enrollment token for an instance name")
    net_flag(ce)
    ce.add_argument("instance")
    ce.add_argument("--host", help="bind the token to the host the certificate will name")
    cr = add(cps, "revoke", cmd_net_ca_revoke, "revoke an instance (removal from the net) or one certificate")
    net_flag(cr)
    cr.add_argument("instance", nargs="?")
    cr.add_argument("--serial", help="revoke one certificate by serial (a lost key)")
    cr.add_argument("--reason")
    cs = add(cps, "show", cmd_net_ca_show, "issued certificates, pending tokens and the revocation list")
    net_flag(cs)
    cp.set_defaults(func=lambda ctx, _p=cp: _usage(_p))
    ne = add(ns, "enroll", cmd_net_enroll, "obtain this server's certificate from the net's CA with a token")
    net_flag(ne)
    ne.add_argument("--ca-url", required=True, dest="ca_url", help="the CA instance's base URL")
    ne.add_argument("--token", required=True, help="the enrollment token ('-' reads stdin)")
    nr = add(ns, "renew", cmd_net_renew, "renew this server's certificate now (it also renews by itself)")
    net_flag(nr)
    npn = add(ns, "pin", cmd_net_pin, "manual mode: pin a peer's certificate thumbprint")
    net_flag(npn)
    npn.add_argument("thumbprint")
    p.set_defaults(func=lambda ctx, _p=p: _usage(_p))

    p = add(sub, "workflows", None, "workflows: list, run, run history, show a definition or a run")
    ws = p.add_subparsers(dest="workflows_cmd", metavar="ACTION")
    wl = add(ws, "list", cmd_workflows_list, "your workflows (administrators: all)")
    json_flag(wl)
    wr = add(ws, "run", cmd_workflows_run, "start a run (exit 1 when it fails)")
    json_flag(wr)
    wr.add_argument("name")
    wr.add_argument("--input", action="append", metavar="KEY=VALUE", help="an input field")
    wr.add_argument("--input-json", dest="json_input", metavar="JSON", help="the whole input as JSON (@file, '-')")
    wr.add_argument("--wait", type=float, default=0, metavar="SECONDS", help="wait for the run to finish (max 300)")
    wr.add_argument("--idempotency-key", help="repeat-safe: a second run with this key returns the first")
    wn = add(ws, "runs", cmd_workflows_runs, "a workflow's run history")
    json_flag(wn)
    wn.add_argument("name")
    wn.add_argument("--status", choices=("queued", "running", "waiting", "succeeded", "failed", "cancelled"))
    wn.add_argument("--limit", type=int, default=20)
    wsh = add(ws, "show", cmd_workflows_show, "a definition (NAME) or a run with its steps (RUN_ID)")
    json_flag(wsh)
    wsh.add_argument("target", metavar="NAME|RUN_ID")
    wsh.add_argument("--yaml", action="store_true", help="the definition as YAML")
    p.set_defaults(func=lambda ctx, _p=p: _usage(_p))

    p = add(sub, "serve", cmd_serve, "run the server from a SAJHA checkout: HTTP, or MCP over stdio "
                                     "(stdio identity: --user, or --api-key / env SAJHA_API_KEY)")
    p.add_argument("--stdio", action="store_true", help="speak MCP on stdin/stdout (desktop clients)")
    p.add_argument("--user", help="stdio: act as this SAJHA user (env SAJHA_STDIO_USER)")
    p.add_argument("--root", help="the SAJHA checkout (env SAJHA_HOME)")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("rest", nargs=argparse.REMAINDER, help="passed to the server (e.g. --log-level INFO, --with-ai)")

    p = add(sub, "db", cmd_db, "database schema helper in a SAJHA checkout (runs python -m sajha.db there): "
                               "check | sql [--dialect D] [--seed] | upgrade-sql")
    p.add_argument("--root", help="the SAJHA checkout (env SAJHA_HOME)")
    p.add_argument("rest", nargs=argparse.REMAINDER, help="check | sql | upgrade-sql ... (see python -m sajha.db -h)")

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
