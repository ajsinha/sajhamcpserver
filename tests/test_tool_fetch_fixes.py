"""
Wave 13 stream B: tool fetches go through the outbound guard, and the fixes to broken tools.

The urllib- and requests-shaped entry points of sajha/core/outbound.py, the CoinGecko throttle and
errors, the live check's keyless and rate-limit rules, the investor-relations SEC fallback and the
OpenBB economic calendar's window. Docs: docs/security/Security Model.md, Tool Quality §12.4.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest import mock

import pytest

from sajha.core import outbound


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype='application/json', extra=()):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        for k, v in extra:
            self.send_header(k, v)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith('/missing'):
            return self._send(404, b'{"error": "nope"}')
        self._send(200, json.dumps({'path': self.path, 'ua': self.headers.get('User-Agent')}).encode(),
                   extra=(('Set-Cookie', 'sid=1; Path=/'),))

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        self._send(200, json.dumps({'body': self.rfile.read(n).decode(),
                                    'ctype': self.headers.get('Content-Type')}).encode())

    def log_message(self, *a):
        pass


@pytest.fixture()
def local_server(monkeypatch):
    srv = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv('SAJHA_TOOLS_OUTBOUND_EXEMPT_HOSTS', '127.0.0.1/32')
    yield f'http://127.0.0.1:{srv.server_address[1]}'
    srv.shutdown()
    srv.server_close()


# ── outbound.urlopen and outbound.requests_compat ──────────────────────────

def test_urlopen_takes_a_request_and_answers_like_urllib(local_server):
    req = urllib.request.Request(local_server + '/a?x=1', headers={'User-Agent': 'probe/1'})
    with outbound.urlopen(req, timeout=5) as r:
        data = json.loads(r.read())
        assert r.status == 200 and r.getcode() == 200
        assert r.info().get('Content-Type') == 'application/json'
        assert 'sid=1' in r.headers.get('Set-Cookie', '')
    assert data == {'path': '/a?x=1', 'ua': 'probe/1'}


def test_urlopen_raises_httperror_with_a_readable_body(local_server):
    with pytest.raises(urllib.error.HTTPError) as e:
        outbound.urlopen(local_server + '/missing', timeout=5)
    assert e.value.code == 404 and json.loads(e.value.read()) == {'error': 'nope'}


def test_urlopen_refuses_blocked_destinations():
    with pytest.raises(outbound.Refused):
        outbound.urlopen('http://169.254.169.254/latest/meta-data/', timeout=5)
    with pytest.raises(outbound.Refused):
        outbound.urlopen(urllib.request.Request('http://localhost:9/x'), timeout=5)


def test_urlopen_turns_a_failed_connection_into_urlerror(monkeypatch):
    monkeypatch.setattr(outbound, 'request', mock.Mock(side_effect=outbound.FetchError('reset')))
    with pytest.raises(urllib.error.URLError, match='reset'):
        outbound.urlopen('https://example.org/', timeout=5)


def test_requests_compat_sends_a_form_and_json(local_server):
    r = outbound.requests_compat.post(local_server + '/token', data={'a': '1', 'b': 'x y'}, timeout=5)
    assert r.status_code == 200
    assert r.json() == {'body': 'a=1&b=x+y', 'ctype': 'application/x-www-form-urlencoded'}
    r = outbound.requests_compat.request('POST', local_server + '/j', json={'k': 1}, timeout=(3, 5))
    assert json.loads(r.json()['body']) == {'k': 1}
    with pytest.raises(outbound.Refused):
        outbound.requests_compat.get('http://169.254.169.254/')


def test_a_rerouted_tool_is_refused_by_the_guard(monkeypatch):
    """A tool's fixed host that resolves to a blocked address is refused before anything is sent."""
    monkeypatch.setattr(outbound, 'resolve', lambda host, port: ['169.254.169.254'])
    sent = mock.Mock()
    monkeypatch.setattr('sajha.api_import.fetch.request', sent)
    from sajha.tools.impl.calc_tools import CalcCurrencyConverterTool
    out = CalcCurrencyConverterTool({'name': 'calc_currency_converter'}).execute({'from': 'USD', 'to': 'EUR'})
    assert 'refused' in str(out) and 'cloud metadata' in str(out) and not sent.called


# ── CoinGecko ──────────────────────────────────────────────────────────────

def _cg(monkeypatch, answer):
    from sajha.tools.impl import coingecko_tools as cg
    from sajha.core.state import get_state_store
    get_state_store().delete(cg.THROTTLE_KEY)
    get_state_store().delete(cg.COOLDOWN_KEY)
    monkeypatch.setattr(cg.outbound, 'request', answer)
    return cg


def test_coingecko_429_is_a_clear_rate_limit_error(monkeypatch):
    answer = mock.Mock(return_value=outbound.Response(429, 'Too Many Requests', {'retry-after': '30'},
                                                      b'{"status": {"error_code": 429}}', 'https://x'))
    cg = _cg(monkeypatch, answer)
    tool = cg.CGMarketGlobalTool({'name': 'cg_market_global'})
    with pytest.raises(ValueError, match=r'rate limit \(HTTP 429\).*retry after 30 s'):
        tool.execute({})
    # every worker now waits out CoinGecko's Retry-After without calling, and the check paces itself by it
    with pytest.raises(ValueError, match='CoinGecko asked SAJHA to wait'):
        tool.execute({})
    assert answer.call_count == 1 and 25 < tool.check_pause_seconds <= 30
    from sajha.core.state import get_state_store
    get_state_store().delete(cg.COOLDOWN_KEY)


def test_coingecko_history_beyond_a_year_explains_the_plan_limit(monkeypatch):
    body = b'{"error": {"status": {"error_code": 10012, "error_message": "exceeds the allowed time range"}}}'
    cg = _cg(monkeypatch, mock.Mock(return_value=outbound.Response(401, 'Unauthorized', {}, body, 'https://x')))
    with pytest.raises(ValueError, match='past 365 days'):
        cg.CGCoinHistoryTool({'name': 'cg_coin_history'}).execute({'id': 'bitcoin', 'date': '31-12-2020'})


def test_coingecko_history_defaults_to_yesterday(monkeypatch):
    answer = mock.Mock(return_value=outbound.Response(200, 'OK', {}, b'{"id": "bitcoin"}', 'https://x'))
    cg = _cg(monkeypatch, answer)
    assert cg.CGCoinHistoryTool({'name': 'cg_coin_history'}).execute({'id': 'bitcoin'}) == {'id': 'bitcoin'}
    assert 'date=' in answer.call_args[0][1] and 'localization=false' in answer.call_args[0][1]


def test_coingecko_shares_one_per_minute_budget(monkeypatch):
    monkeypatch.setenv('SAJHA_COINGECKO_CALLS_PER_MINUTE', '2')
    answer = mock.Mock(return_value=outbound.Response(200, 'OK', {}, b'{"data": {}}', 'https://x'))
    cg = _cg(monkeypatch, answer)
    tool = cg.CGMarketGlobalTool({'name': 'cg_market_global'})
    tool.execute({})
    tool.execute({})
    with pytest.raises(ValueError, match='SAJHA allows 2 CoinGecko calls a minute'):
        tool.execute({})
    assert answer.call_count == 2
    assert tool.check_pause_seconds == 30.0


def test_coingecko_configs_cache_their_results():
    import glob
    for path in glob.glob('config/tools/coingecko/cg_*.json'):
        assert json.load(open(path)).get('cache_ttl', 0) > 0, path


# ── the live check's rules ─────────────────────────────────────────────────

def test_check_calls_keyless_fallback_tools_and_keeps_rate_limits_apart():
    from sajha.quality import check
    keyed = SimpleNamespace(config={'api_key': '${fbi.api.key:}'})
    assert check.missing_key(keyed) == 'api_key'
    assert check.missing_key(SimpleNamespace(config={'api_key': ''}, keyless_fallback=True)) == ''
    err = ValueError('CoinGecko rate limit (HTTP 429): ... A free demo key (COINGECKO_API_KEY) raises the limit')
    assert check.classify(SimpleNamespace(), error=err)[0] == 'error'
    assert check.classify(SimpleNamespace(), error=ValueError('FRED API key not configured'))[0] == 'not_configured'
    assert check._tool_pause(SimpleNamespace(check_pause_seconds=12)) == 12.0


def test_fbi_and_un_tools_declare_their_keyless_fallback():
    from sajha.tools.impl.fbi_tool_refactored import FBIBaseTool
    from sajha.tools.impl.united_nations_tool_refactored import UnitedNationsBaseTool
    assert FBIBaseTool.keyless_fallback is True and UnitedNationsBaseTool.keyless_fallback is True


# ── investor relations: SEC fallback by 8-K item ───────────────────────────

def test_sec_filings_filter_by_8k_item():
    from sajha.ir.sec_edgar import SECEdgarClient
    client = SECEdgarClient()
    recent = {'accessionNumber': ['1', '2', '3'], 'filingDate': ['2026-01-02'] * 3, 'reportDate': [''] * 3,
              'form': ['8-K', '8-K', '4'], 'fileNumber': [''] * 3, 'primaryDocument': ['a.htm'] * 3,
              'primaryDocDescription': [''] * 3, 'items': ['2.02,9.01', '5.02', '']}
    with mock.patch.object(client, 'get_company_submissions', return_value={'filings': {'recent': recent}}):
        got = client.get_recent_filings('320193', filing_types=['8-K'], limit=10, items=('2.02',))
    assert [f['accession_number'] for f in got] == ['1']


def test_ir_sec_fallback_returns_nothing_for_a_type_no_form_carries():
    from sajha.ir.generic_ir_scraper import GenericIRScraper
    scraper = GenericIRScraper.__new__(GenericIRScraper)
    scraper.sec_client = mock.Mock()
    scraper.company_config = SimpleNamespace(cik='320193')
    scraper.ticker = 'AAPL'
    assert scraper._scrape_from_sec('webcast') == []
    scraper.sec_client.get_recent_filings.assert_not_called()


def test_ir_client_does_not_retry_a_bot_wall(monkeypatch):
    from sajha.ir import http_client
    calls = []

    def refuse(req, timeout=None):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 403, 'Forbidden', {}, None)
    monkeypatch.setattr(http_client.outbound, 'urlopen', refuse)
    c = http_client.EnhancedHTTPClient(min_delay=0, max_delay=0, max_retries=3, timeout=5)
    with pytest.raises(ValueError, match='403'):
        c.fetch('https://ir.example.com/', respect_rate_limit=False)
    assert len(calls) == 1


# ── OpenBB economic calendar ───────────────────────────────────────────────

def test_economy_calendar_defaults_to_a_two_week_window_and_empty_is_not_an_error(monkeypatch):
    from sajha.tools.impl import openbb_tools as ob
    cfg = json.load(open('config/tools/openbb/openbb_economy_calendar.json'))
    tool = ob.OpenBBEconomyCalendarTool(cfg)
    seen = {}

    def fetch(self, arguments, *a, **k):
        seen.update(arguments)
        raise ob.OpenBBCallError('Nasdaq Error -> Economic Events Calendar: No record found.')
    monkeypatch.setattr(ob.OpenBBEconomyCalendarTool, '_fetch', fetch)
    out = tool.execute({})
    assert seen['start_date'] < seen['end_date']
    assert out['data'] == [] and out['data_points'] == 0 and 'no economic events' in out['note']
    assert 'error' not in out


# ── GLEIF fuzzy fallback ───────────────────────────────────────────────────

def test_gleif_fuzzy_results_keep_gleifs_order_and_say_what_matched(monkeypatch):
    from sajha.tools.impl import gleif_tools

    def fz(lei, value):
        return {'attributes': {'value': value}, 'relationships': {'lei-records': {'data': {'id': lei}}}}

    def rec(lei, name):
        return {'id': lei, 'attributes': {'lei': lei, 'entity': {'legalName': {'name': name}}}}

    def get(path, params=None):
        p = dict(params or [])
        if path == 'fuzzycompletions':
            return 200, {'data': [fz('B' * 20, 'Deutsche Bank A.G.'), fz('A' * 20, 'Deutsche Bank AG NY')]}
        if 'filter[lei]' in p:
            return 200, {'data': [rec('A' * 20, 'Second'), rec('B' * 20, 'First')]}     # GLEIF sorts by LEI
        return 200, {'data': [], 'meta': {'pagination': {'total': 0}}}
    monkeypatch.setattr(gleif_tools, 'get', get)
    out = gleif_tools.GleifSearchTool(json.load(open('config/tools/gleif/gleif_search.json'))).execute(
        {'name': 'Deutshe Bank', 'limit': 5})
    assert out['matched_by'] == 'fuzzy'
    assert [r['lei'] for r in out['results']] == ['B' * 20, 'A' * 20]
    assert out['results'][0]['matched_value'] == 'Deutsche Bank A.G.'
