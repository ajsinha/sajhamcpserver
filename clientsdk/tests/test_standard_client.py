"""
Tests for sajhaclient.SajhaMCPClient (standard MCP client over the official MCP SDK).

Offline tests always run (lazy import, install hint, auth header stamping,
connection-error mapping). Live tests run against a SAJHA server at
SAJHA_TEST_URL (default http://127.0.0.1:3092) and are skipped if it is not
reachable. Requires: pip install 'sajhaclient[mcp]' pytest

    pytest clientsdk/tests/test_standard_client.py -v
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SDK_ROOT = os.path.dirname(HERE)
if SDK_ROOT not in sys.path:
    sys.path.insert(0, SDK_ROOT)

from sajhaclient import SajhaConfig  # noqa: E402
from sajhaclient.auth import ApiKeyAuth, JWTAuth  # noqa: E402
from sajhaclient.exceptions import SajhaConnectionError, SajhaMCPError  # noqa: E402

BASE_URL = os.environ.get("SAJHA_TEST_URL", "http://127.0.0.1:3092").rstrip("/")
USERNAME = os.environ.get("SAJHA_TEST_USER", "admin")
PASSWORD = os.environ.get("SAJHA_TEST_PASSWORD", "admin123")

CALC_TOOL = "calc_percentage_change"
PROMPT = "bug_diagnosis"
PROMPT_ARGS = {
    "bug_description": "Division returns wrong result",
    "error_message": "ZeroDivisionError: division by zero",
    "code": "def f(a, b):\n    return a / b",
    "language": "python",
}

needs_mcp = pytest.mark.skipif(
    __import__("importlib").util.find_spec("mcp") is None,
    reason="official MCP SDK not installed (pip install 'sajhaclient[mcp]')",
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ── helpers ──────────────────────────────────────────────────────

def _wait_for_server(timeout: float = 30.0) -> bool:
    """The server may be restarting (hot upgrades); wait briefly for /health."""
    deadline = time.time() + timeout
    while True:
        try:
            with urllib.request.urlopen(BASE_URL + "/health", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        if time.time() >= deadline:
            return False
        time.sleep(1.5)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _obtain_jwt():
    """JWT for admin: REST /api/auth/login (JWTAuth), falling back to the web form login cookie."""
    try:
        return JWTAuth(BASE_URL, USERNAME, PASSWORD, timeout=10).token
    except Exception:
        pass
    opener = urllib.request.build_opener(_NoRedirect)
    data = f"user_id={USERNAME}&password={PASSWORD}".encode()
    try:
        resp = opener.open(BASE_URL + "/login", data=data, timeout=10)
        cookie = resp.headers.get("set-cookie", "")
    except urllib.error.HTTPError as e:  # 302/303 redirect after successful login
        cookie = e.headers.get("set-cookie", "") or ""
    m = re.search(r"sajha_token=([^;]+)", cookie)
    return m.group(1) if m else None


@pytest.fixture(scope="module")
def live():
    if not _wait_for_server(timeout=float(os.environ.get("SAJHA_TEST_WAIT", "20"))):
        pytest.skip(f"SAJHA server not reachable at {BASE_URL}")
    pytest.importorskip("mcp")
    token = _obtain_jwt()
    return {"jwt": token}


def _client_kwargs(live):
    # tools/call needs an authenticated session on SAJHA; /mcp itself is open.
    return {"jwt_token": live["jwt"]} if live["jwt"] else {}


async def _retrying_connect(make_client, attempts: int = 4):
    """Connect, retrying while the server restarts."""
    last = None
    for i in range(attempts):
        client = make_client()
        try:
            return await client.connect()
        except SajhaConnectionError as e:
            last = e
            _wait_for_server(timeout=10)
    raise last


# ── offline tests ────────────────────────────────────────────────

def test_import_does_not_import_mcp():
    code = (
        "import sys; sys.path.insert(0, %r); import sajhaclient; "
        "from sajhaclient import SajhaMCPClient, SajhaMCPSyncClient; "
        "print('mcp' in sys.modules)" % SDK_ROOT
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_missing_sdk_raises_install_hint(monkeypatch):
    from sajhaclient import SajhaMCPClient
    monkeypatch.setitem(sys.modules, "mcp", None)  # makes `import mcp` raise ImportError
    with pytest.raises(ImportError, match=r"pip install 'sajhaclient\[mcp\]'"):
        SajhaMCPClient("http://localhost:1")


@needs_mcp
def test_url_and_auth_resolution():
    from sajhaclient import SajhaMCPClient
    c = SajhaMCPClient("http://example.test:3002/", api_key="sja_abc")
    assert c.mcp_url == "http://example.test:3002/mcp"
    assert isinstance(c.auth, ApiKeyAuth)
    assert c.auth.get_headers() == {"X-API-Key": "sja_abc"}

    c = SajhaMCPClient(config=SajhaConfig(base_url="http://h:1", jwt_token="tok"))
    assert c.auth.get_headers() == {"Authorization": "Bearer tok"}
    assert c.rest.config is c.config and c.a2a.config is c.config
    ws = c.websocket()
    assert type(ws).__name__ == "MCPWebSocketClient"
    with pytest.raises(RuntimeError):
        _ = c.negotiated_protocol_version


@needs_mcp
def test_auth_headers_stamped_on_requests():
    import httpx2
    from sajhaclient.standard import _make_httpx_auth

    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx2.Response(200, json={})

    with httpx2.Client(transport=httpx2.MockTransport(handler), auth=_make_httpx_auth(ApiKeyAuth("sja_k"))) as h:
        h.get("http://x/mcp")
    assert seen.get("x-api-key") == "sja_k"

    seen.clear()
    with httpx2.Client(transport=httpx2.MockTransport(handler),
                       auth=_make_httpx_auth(JWTAuth.from_token("jwt123"))) as h:
        h.get("http://x/mcp")
    assert seen.get("authorization") == "Bearer jwt123"


@needs_mcp
@pytest.mark.anyio
async def test_unreachable_server_raises_connection_error():
    from sajhaclient import SajhaMCPClient
    with pytest.raises(SajhaConnectionError):
        async with SajhaMCPClient("http://127.0.0.1:9", config=SajhaConfig(timeout=3)):
            pass


# ── live tests (async API) ───────────────────────────────────────

@pytest.mark.anyio
async def test_live_negotiates_and_lists_tools(live):
    from sajhaclient import SajhaMCPClient
    client = await _retrying_connect(lambda: SajhaMCPClient(BASE_URL, **_client_kwargs(live)))
    try:
        from mcp_types.version import KNOWN_PROTOCOL_VERSIONS
        assert client.negotiated_protocol_version in KNOWN_PROTOCOL_VERSIONS
        page = await client.list_tools()
        assert page.tools, "server returned no tools"
        tools = await client.list_all_tools()
        names = {t.name for t in tools}
        assert len(names) >= len(page.tools)
        assert CALC_TOOL in names
    finally:
        await client.close()


@pytest.mark.anyio
async def test_live_call_calculator_tool(live):
    from sajhaclient import SajhaMCPClient
    client = await _retrying_connect(lambda: SajhaMCPClient(BASE_URL, **_client_kwargs(live)))
    try:
        result = await client.call_tool(CALC_TOOL, {"old_value": 100, "new_value": 125})
        assert not result.is_error, result
        text = " ".join(getattr(c, "text", "") for c in result.content)
        payload = result.structured_content or {}
        assert "25" in text or payload.get("percentage_change") == 25.0
    finally:
        await client.close()


@pytest.mark.anyio
async def test_live_list_prompts(live):
    from sajhaclient import SajhaMCPClient
    client = await _retrying_connect(lambda: SajhaMCPClient(BASE_URL, **_client_kwargs(live)))
    try:
        prompts = await client.list_all_prompts()
        assert PROMPT in {p.name for p in prompts}
    finally:
        await client.close()


@pytest.mark.anyio
async def test_live_get_prompt_with_required_args(live):
    from sajhaclient import SajhaMCPClient
    client = await _retrying_connect(lambda: SajhaMCPClient(BASE_URL, **_client_kwargs(live)))
    try:
        result = await client.get_prompt(PROMPT, PROMPT_ARGS)
        assert result.messages
        text = json.dumps([m.model_dump(mode="json") for m in result.messages])
        assert "ZeroDivisionError" in text
    finally:
        await client.close()


@pytest.mark.anyio
async def test_live_resources_and_sajha_extras(live):
    from sajhaclient import SajhaMCPClient
    client = await _retrying_connect(lambda: SajhaMCPClient(BASE_URL, **_client_kwargs(live)))
    try:
        resources = await client.list_all_resources()
        if resources:
            read = await client.read_resource(str(resources[0].uri))
            assert read.contents
        health = await client.health()
        assert health.get("status")
        schema = await client.tool_schema(CALC_TOOL)
        assert schema.get("name") == CALC_TOOL
        card = client.a2a.get_agent_card()
        assert card.get("name")
    finally:
        await client.close()


# ── live test (sync facade) ──────────────────────────────────────

def test_live_sync_facade(live):
    from sajhaclient import SajhaMCPSyncClient
    for attempt in range(3):
        try:
            client = SajhaMCPSyncClient(BASE_URL, **_client_kwargs(live)).connect()
            break
        except SajhaConnectionError:
            _wait_for_server(timeout=10)
    else:
        pytest.fail("could not connect")
    with client:
        assert client.negotiated_protocol_version
        assert client.list_tools().tools
        result = client.call_tool(CALC_TOOL, {"old_value": 1, "new_value": 2})
        assert not result.is_error
