# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Market data tools fixed in phase 8.1 (Roadmap L22): OpenBB, Yahoo Finance, Alpha Vantage.

No network: OpenBB is a fake object (one test reads the installed OpenBB's command catalogue,
which is local), yfinance and urllib are patched.
"""
import io
import json
import types
from pathlib import Path
from unittest import mock

import jsonschema
import pandas as pd
import pytest

from sajha.tools.impl import alphavantage_tools as av
from sajha.tools.impl import openbb_tools as ob
from sajha.tools.impl import yahoo_finance_tool as yh
from sajha.tools.impl import yfinance_tools as yft

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / 'config' / 'tools'
FOLDERS = ('openbb', 'yahoo', 'alphavantage')


def cfg(folder, name):
    return json.loads((TOOLS / folder / f'{name}.json').read_text())


def all_configs(folder):
    return [json.loads(p.read_text()) for p in sorted((TOOLS / folder).glob('*.json'))]


# ── descriptions and schemas ───────────────────────────────────────────────

@pytest.mark.parametrize('folder', FOLDERS)
def test_descriptions_fit_and_examples_validate(folder):
    for c in all_configs(folder):
        desc = c['description']
        assert len(desc) <= 1000, c['name']
        assert 'Example: ' in desc, c['name']
        example = json.loads(desc.split('Example: ', 1)[1])
        jsonschema.validate(example, c['inputSchema'])
        for e in c.get('metadata', {}).get('examples') or []:
            jsonschema.validate(e['input'], c['inputSchema'])
        props = c['inputSchema'].get('properties', {})
        for req in c['inputSchema'].get('required', []):
            assert 'default' not in props[req], f'{c["name"]}: required {req} has a default'
        for k, p in props.items():
            if 'default' in p:
                jsonschema.validate(p['default'], {a: b for a, b in p.items() if a != 'default'})
        for stale in ("'demo' key", 'currently returns an error', 'the schema says', 'yf.Screener'):
            assert stale not in desc, (c['name'], stale)


REMOVED = ['openbb_commodity_lbma_gold', 'openbb_commodity_lbma_silver', 'openbb_commodity_search',
           'openbb_index_search', 'openbb_equity_fundamental_overview', 'openbb_fixedincome_moody',
           'openbb_news_search']


def test_removed_openbb_tools_are_gone():
    for name in REMOVED:
        assert not (TOOLS / 'openbb' / f'{name}.json').exists(), name
        assert name not in ob.TOOL_COMMANDS


def test_every_openbb_tool_names_a_command():
    names = {c['name'] for c in all_configs('openbb')}
    assert names == set(ob.TOOL_COMMANDS)


def test_openbb_commands_and_default_providers_exist_in_installed_openbb():
    """The installed OpenBB (requirements.txt) has every command, and offers each tool's provider
    enum and default; reads OpenBB's local catalogue only."""
    pytest.importorskip('openbb')
    obb = ob._get_obb()
    for c in all_configs('openbb'):
        path = ob.TOOL_COMMANDS[c['name']][0]
        assert ob.resolve_command(obb, path) is not None, (c['name'], path)
        provs = set(ob.command_providers(obb, path))
        p = c['inputSchema']['properties']['provider']
        assert p['default'] in provs and set(p['enum']) <= provs, c['name']
        accepted = set().union(*(ob.command_parameters(obb, path, prov) for prov in p['enum']))
        renames = ob.TOOL_COMMANDS[c['name']][1]
        for arg in c['inputSchema']['properties']:
            if arg in ('provider', 'limit'):
                continue
            assert renames.get(arg, arg) in accepted, f'{c["name"]}: no provider of {path} accepts {arg}'


# ── OpenBB with a fake SDK ─────────────────────────────────────────────────

class _Model:
    def __init__(self, **kw):
        self.kw = kw

    def model_dump(self, mode='json'):
        return dict(self.kw)


def fake_obb(rows, providers=('federal_reserve', 'fred'), params=('start_date', 'end_date'),
             path='fixedincome.rate.effr'):
    calls = []

    def command(**kw):
        calls.append(kw)
        return types.SimpleNamespace(results=[_Model(**r) for r in rows])

    root = types.SimpleNamespace()
    node = root
    parts = path.split('.')
    for part in parts[:-1]:
        child = types.SimpleNamespace()
        setattr(node, part, child)
        node = child
    setattr(node, parts[-1], command)
    root.coverage = types.SimpleNamespace(commands={'.' + path: list(providers)})
    root.reference = {'paths': {'/' + path.replace('.', '/'): {'parameters': {
        'standard': [{'name': n} for n in params], providers[0]: []}}}}
    root.user = types.SimpleNamespace(credentials=types.SimpleNamespace(fmp_api_key=None, fred_api_key=None,
                                                                        alpha_vantage_api_key=None))
    return root, calls


def test_generic_tool_filters_arguments_caps_rows_and_keeps_newest(monkeypatch):
    rows = [{'date': f'2026-01-{d:02d}', 'rate': d / 100} for d in range(1, 31)]
    obb, calls = fake_obb(rows)
    monkeypatch.setattr(ob, '_obb', obb)
    tool = ob.OpenBBGenericTool(cfg('openbb', 'openbb_fixedincome_effr'))
    out = tool.execute({'start_date': '2026-01-01', 'limit': 5, 'bogus': 1})
    assert calls == [{'provider': 'federal_reserve', 'start_date': '2026-01-01'}]
    assert out['data_points'] == 30 and out['truncated'] is True
    assert [r['date'] for r in out['data']] == [f'2026-01-{d}' for d in range(26, 31)]   # most recent rows
    assert out['ignored_arguments'] == ['bogus']


def test_generic_tool_refuses_a_provider_the_command_lacks(monkeypatch):
    obb, calls = fake_obb([])
    monkeypatch.setattr(ob, '_obb', obb)
    out = ob.OpenBBGenericTool(cfg('openbb', 'openbb_fixedincome_effr')).execute({'provider': 'yfinance'})
    assert 'not available' in out['error'] and 'federal_reserve' in out['error'] and not calls


def test_missing_command_errors_and_raises_notice(monkeypatch):
    obb, _ = fake_obb([], path='fixedincome.rate.other')
    monkeypatch.setattr(ob, '_obb', obb)
    raised = []
    import sajha.notices as notices
    monkeypatch.setattr(notices, 'raise_notice', lambda nid, **kw: raised.append((nid, kw['severity'])))
    out = ob.OpenBBGenericTool(cfg('openbb', 'openbb_fixedincome_effr')).execute({})
    assert 'has no obb.fixedincome.rate.effr' in out['error']
    assert raised == [('tools.openbb_command:openbb_fixedincome_effr', 'info')]


def test_screener_renames_market_cap_and_uses_schema_default_provider(monkeypatch):
    obb, calls = fake_obb([{'symbol': 'AAA'}], providers=('yfinance', 'fmp'),
                          params=('sector', 'mktcap_min', 'mktcap_max', 'limit'), path='equity.screener')
    monkeypatch.setattr(ob, '_obb', obb)
    out = ob.OpenBBEquityScreenerTool(cfg('openbb', 'openbb_equity_screener')).execute(
        {'sector': 'technology', 'market_cap_min': 10 ** 10})
    assert calls == [{'provider': 'yfinance', 'sector': 'technology', 'mktcap_min': 10 ** 10, 'limit': 25}]
    assert out['results'] == [{'symbol': 'AAA'}] and 'ignored_arguments' not in out


def test_index_constituents_sends_symbol(monkeypatch):
    obb, calls = fake_obb([{'symbol': 'AAPL'}], providers=('fmp',), params=('symbol',), path='index.constituents')
    monkeypatch.setattr(ob, '_obb', obb)
    out = ob.OpenBBIndexConstituentsTool(cfg('openbb', 'openbb_index_constituents')).execute({'index': 'dowjones'})
    assert calls == [{'provider': 'fmp', 'symbol': 'dowjones'}] and out['count'] == 1


def test_treasury_rates_keep_dates(monkeypatch):
    obb, calls = fake_obb([{'date': '2026-10-01', 'year_10': 0.0524}], providers=('federal_reserve', 'fmp'),
                          path='fixedincome.government.treasury_rates')
    monkeypatch.setattr(ob, '_obb', obb)
    out = ob.OpenBBTreasuryRatesTool(cfg('openbb', 'openbb_treasury_rates')).execute({'start_date': '2026-10-01'})
    assert out['rates'] == [{'date': '2026-10-01', 'year_10': 0.0524}]
    assert calls[0]['provider'] == 'federal_reserve' and calls[0]['start_date'] == '2026-10-01'


def test_sajha_keys_fill_only_empty_openbb_credentials(monkeypatch):
    import sajha.core.config as config
    values = {'fmp.api.key': 'fmp-key', 'fred.api.key': '', 'alpha_vantage.api.key': 'av-key'}
    monkeypatch.setattr(config, '_get', lambda key, default='': values.get(key, default))
    obb, _ = fake_obb([])
    obb.user.credentials.alpha_vantage_api_key = 'from-user-settings'
    assert ob.apply_sajha_credentials(obb) == ['fmp_api_key']
    assert obb.user.credentials.fmp_api_key == 'fmp-key'
    assert obb.user.credentials.alpha_vantage_api_key == 'from-user-settings'
    assert obb.user.credentials.fred_api_key is None


def test_cap_rows_keeps_first_rows_when_not_dated():
    rows = [{'symbol': str(i)} for i in range(5)]
    assert ob.cap_rows(rows, 2) == (rows[:2], 5, True)
    dated = [{'ex_dividend_date': f'2026-0{i}-01'} for i in range(1, 6)]
    assert ob.cap_rows(dated, 2)[0] == dated[-2:]


# ── Yahoo ──────────────────────────────────────────────────────────────────

def test_yahoo_quote_goes_through_yfinance():
    info = {'longName': 'Apple Inc.', 'regularMarketPrice': 336.64, 'currency': 'USD', 'trailingPE': 38.6,
            'regularMarketTime': 1791576000, 'exchange': 'NMS'}
    fake = mock.MagicMock()
    fake.Ticker.return_value.info = info
    with mock.patch.dict('sys.modules', {'yfinance': fake}):
        out = yh.YahooGetQuoteTool(cfg('yahoo', 'yahoo_get_quote')).execute({'symbol': 'aapl'})
    fake.Ticker.assert_called_once_with('AAPL')
    assert out['price'] == 336.64 and out['pe_ratio'] == 38.6 and out['exchange'] == 'NMS'
    assert out['market_time'].startswith('2026-10-')
    fake.Ticker.return_value.info = {'trailingPegRatio': None}
    with mock.patch.dict('sys.modules', {'yfinance': fake}), pytest.raises(ValueError, match='No quote'):
        yh.YahooGetQuoteTool(cfg('yahoo', 'yahoo_get_quote')).execute({'symbol': 'ZZZZ'})


def test_yahoo_search_maps_exchange_names_to_yahoo_codes():
    quotes = [{'symbol': 'AAPL', 'exchange': 'NMS', 'exchDisp': 'NASDAQ'},
              {'symbol': 'APLE', 'exchange': 'NYQ', 'exchDisp': 'NYSE'},
              {'symbol': 'AAPL.MX', 'exchange': 'MEX'},
              {'symbol': 'APPF', 'exchange': 'NGM', 'exchDisp': 'NASDAQ'}]
    tool = yh.YahooSearchSymbolsTool(cfg('yahoo', 'yahoo_search_symbols'))
    with mock.patch.object(tool, '_make_request', return_value={'quotes': quotes}) as req:
        out = tool.execute({'query': 'apple', 'exchange': 'NASDAQ', 'limit': 5})
    assert [r['symbol'] for r in out['results']] == ['AAPL', 'APPF']
    assert 'quotesCount=25' in req.call_args[0][0]
    with mock.patch.object(tool, '_make_request', return_value={'quotes': quotes}):
        assert [r['symbol'] for r in tool.execute({'query': 'apple', 'exchange': 'NYSE'})['results']] == ['APLE']


def test_yahoo_history_adjusted_close_is_yahoos_adjclose():
    chart = {'chart': {'result': [{'timestamp': [1760000000, 1760086400], 'meta': {'currency': 'USD'},
                                   'indicators': {'quote': [{'open': [1, 2], 'high': [1, 2], 'low': [1, 2],
                                                             'close': [10.0, 11.0], 'volume': [5, 6]}],
                                                  'adjclose': [{'adjclose': [9.5, 11.0]}]}}]}}
    tool = yh.YahooGetHistoryTool(cfg('yahoo', 'yahoo_get_history'))
    with mock.patch.object(tool, '_make_request', return_value=chart) as req:
        out = tool.execute({'symbol': 'KO'})
    assert [h['adjusted_close'] for h in out['history']] == [9.5, 11.0]
    assert [h['close'] for h in out['history']] == [10.0, 11.0]
    assert 'includeAdjustedClose=true' in req.call_args[0][0]


def _history(n):
    idx = pd.date_range('2025-01-01', periods=n, freq='D', name='Date')
    return pd.DataFrame({'Close': range(n)}, index=idx)


@pytest.mark.parametrize('cls,name,arg,key', [
    (yft.YFIndexHistoryTool, 'yf_index_history', {'index': '^GSPC'}, 'prices'),
    (yft.YFForexHistoryTool, 'yf_forex_history', {'pair': 'EUR/USD'}, 'rates'),
    (yft.YFStockHistoryTool, 'yf_stock_history', {'symbol': 'AAPL'}, 'prices'),
])
def test_yfinance_histories_return_the_newest_rows(cls, name, arg, key):
    fake = mock.MagicMock()
    fake.Ticker.return_value.history.return_value = _history(300)
    with mock.patch.object(yft, '_yf', fake):
        out = cls(cfg('yahoo', name)).execute(dict(arg, limit=3))
    assert out['data_points'] == 300 and out['truncated'] is True
    assert [r['Close'] for r in out[key]] == [297, 298, 299]
    if name == 'yf_forex_history':
        fake.Ticker.assert_called_once_with('EURUSD=X')


def test_multi_ticker_history_caps_tickers_and_keeps_newest_rows():
    tool = yft.YFMultiTickerHistoryTool(cfg('yahoo', 'yf_multi_ticker_history'))
    assert 'at most 10' in tool.execute({'symbols': ' '.join(f'T{i}' for i in range(11))})['error']
    cols = pd.MultiIndex.from_product([['AAA', 'BBB'], ['Close']])
    df = pd.DataFrame([[i, 10 * i] for i in range(40)], columns=cols,
                      index=pd.date_range('2026-01-01', periods=40, name='Date'))
    fake = mock.MagicMock()
    fake.download.return_value = df
    with mock.patch.object(yft, '_yf', fake):
        out = tool.execute({'symbols': 'aaa, BBB', 'limit': 2})
    assert out['symbols'] == ['AAA', 'BBB'] and out['data_points'] == {'AAA': 40, 'BBB': 40}
    assert [r['Close'] for r in out['data']['BBB']] == [380, 390]


def test_crypto_info_appends_usd_only_without_a_pair():
    fake = mock.MagicMock()
    fake.Ticker.return_value.info = {'name': 'x'}
    with mock.patch.object(yft, '_yf', fake):
        assert yft.YFCryptoInfoTool({}).execute({'symbol': 'eth'})['symbol'] == 'ETH-USD'
        assert yft.YFCryptoInfoTool({}).execute({'symbol': 'BTC-EUR'})['symbol'] == 'BTC-EUR'


def test_screener_uses_yf_screen():
    fake = mock.MagicMock()
    fake.screen.return_value = {'title': 'Day Gainers', 'total': 99,
                                'quotes': [{'symbol': 'A', 'regularMarketPrice': 1.0, 'junk': 1}] * 3}
    with mock.patch.object(yft, '_yf', fake):
        out = yft.YFScreenerTool(cfg('yahoo', 'yf_screener')).execute({'screen_type': 'day_gainers', 'limit': 2})
    fake.screen.assert_called_once_with('day_gainers', count=2)
    assert out['count'] == 2 and out['results'][0] == {'symbol': 'A', 'regularMarketPrice': 1.0}


def test_trending_tickers_read_yahoos_trending_endpoint():
    body = json.dumps({'finance': {'result': [{'quotes': [{'symbol': 'ASML'}, {'symbol': 'JPM'}]}]}}).encode()
    with mock.patch('urllib.request.urlopen', return_value=io.BytesIO(body)) as op:
        out = yft.YFTrendingTickersTool(cfg('yahoo', 'yf_trending_tickers')).execute({'region': 'us', 'limit': 5})
    assert out == {'region': 'US', 'count': 2, 'symbols': ['ASML', 'JPM']}
    assert op.call_args[0][0].full_url.startswith('https://query1.finance.yahoo.com/v1/finance/trending/US?')


# ── Alpha Vantage ──────────────────────────────────────────────────────────

def _av_tool(name, key='k'):
    c = cfg('alphavantage', name)
    c['api_key'] = key
    mod, cls = c['implementation'].rsplit('.', 1)
    return getattr(av, cls)(c), c


def test_av_without_key_is_a_configuration_error():
    tool, _ = _av_tool('av_stock_quote', key='${alpha_vantage.api.key}')
    with mock.patch('urllib.request.urlopen') as op:
        out = tool.execute({'symbol': 'IBM'})
    assert 'ALPHA_VANTAGE_API_KEY' in out['error'] and not op.called


def test_av_notes_become_errors():
    tool, _ = _av_tool('av_stock_quote')
    for note in ('Error Message', 'Information', 'Note'):
        with mock.patch.object(av, 'safe_json_response', return_value={note: 'nope'}), \
                mock.patch('urllib.request.urlopen'):
            out = tool.execute({'symbol': 'IBM'})
        assert out['error'] == 'Alpha Vantage: nope' and out['av_note'] == note


def test_av_code_sends_the_schema_defaults():
    """With only the required arguments, the request carries each schema default; a schema
    property the code does not send would be a lie, so none may exist."""
    for c in all_configs('alphavantage'):
        tool, _ = _av_tool(c['name'])
        props = c['inputSchema']['properties']
        args = {k: 'IBM' for k in c['inputSchema'].get('required', [])}
        with mock.patch.object(tool, '_av_get', return_value={}) as get:
            tool.execute(args)
        sent = get.call_args.kwargs
        names = {'from': 'from_currency' if c['name'] == 'av_forex_rate' else 'from_symbol',
                 'to': 'to_currency' if c['name'] == 'av_forex_rate' else 'to_symbol'}
        for k, p in props.items():
            assert names.get(k, k) in sent, f'{c["name"]}: {k} is in the schema but never sent'
            if 'default' in p:
                assert sent[names.get(k, k)] == p['default'], f'{c["name"]}: {k}'


def test_av_vwap_is_intraday_only():
    props = cfg('alphavantage', 'av_vwap')['inputSchema']['properties']
    assert props['interval']['default'] == '15min' and 'daily' not in props['interval']['enum']
    assert 'time_period' not in props
