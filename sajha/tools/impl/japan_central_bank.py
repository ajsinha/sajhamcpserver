"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Bank of Japan (BoJ) MCP tools.

Japanese series from FRED (needs FRED_API_KEY) and the IMF SDMX API (no key), through
sajha/tools/impl/central_bank_series.py. Each series id was checked live. FRED's Japanese
discount rate (ended 2017), M1/M2 (ended 2017), M3 (ended 2023), CPI (ended 2021), PPI and
industrial production (ended 2024) are no longer published there, so they are not offered;
CPI and broad money come from the IMF instead.
"""

from typing import Any, Dict

from sajha.tools.impl.central_bank_series import (
    CentralBankSeriesTool, LIST_OUTPUT, LIST_SCHEMA, Series)

BOJ_SERIES: Dict[str, Series] = {
    # rates
    'jgb_10y': ('fred', 'IRLTLT01JPM156N', '10-year JGB yield, %, monthly (OECD series on FRED)'),
    'jgb_3m': ('fred', 'IR3TIB01JPM156N', '3-month interbank rate, %, monthly (OECD series on FRED)'),
    'call_money': ('fred', 'IRSTCI01JPM156N', 'Overnight call money rate, %, monthly (OECD series on FRED)'),
    # fx
    'usd_jpy': ('fred', 'DEXJPUS', 'Japanese yen per US dollar, daily (noon buying rate, New York)'),
    'eur_jpy': ('fred', 'DEXJPUS*DEXUSEU', 'Japanese yen per euro, daily, derived as DEXJPUS x DEXUSEU'),
    # money
    'broad_money': ('imf', 'MFS_MA', 'JPN.BM_MAI.XDC.M', 'Broad money, yen, monthly (IMF MFS_MA)'),
    # prices
    'cpi': ('imf', 'CPI', 'JPN.CPI._T.IX.M', 'Consumer price index, all items (IMF CPI), monthly'),
    'cpi_inflation': ('imf', 'CPI', 'JPN.CPI._T.YOY_PCH_PA_PT.M',
                      'CPI inflation, % change on a year earlier (IMF CPI), monthly'),
    # economy
    'gdp': ('fred', 'JPNRGDPEXP', 'Real GDP, billions of chained 2015 yen, quarterly, seasonally adjusted'),
    'unemployment': ('fred', 'LRUNTTTTJPM156S', 'Unemployment rate, %, monthly, seasonally adjusted (OECD)'),
    'exports': ('fred', 'XTEXVA01JPM664S', 'Goods exports, yen, monthly, seasonally adjusted (OECD)'),
    'imports': ('fred', 'XTIMVA01JPM664S', 'Goods imports, yen, monthly, seasonally adjusted (OECD)'),
    'trade_balance': ('fred', 'XTNTVA01JPM664S', 'Goods trade balance (exports less imports), yen, monthly, seasonally adjusted (OECD)'),
}

CATEGORIES = {
    'rates': ['jgb_10y', 'jgb_3m', 'call_money'],
    'fx': ['usd_jpy', 'eur_jpy'],
    'money': ['broad_money'],
    'prices': ['cpi', 'cpi_inflation'],
    'economy': ['gdp', 'unemployment', 'exports', 'imports', 'trade_balance'],
}


class BankOfJapanBaseTool(CentralBankSeriesTool):
    SERIES = BOJ_SERIES
    CATEGORIES = CATEGORIES

    @property
    def fred_series(self) -> Dict[str, str]:
        return {k: v[1] for k, v in BOJ_SERIES.items() if v[0] == 'fred'}


class BoJGetJGBYieldTool(BankOfJapanBaseTool):
    """10-year JGB yield and 3-month interbank rate."""
    CHOICE = ('bond_term', ('10y', '3m'), '10y')

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        term = arguments.get('bond_term') or '10y'
        if term not in ('10y', '3m'):
            raise ValueError(f"Unsupported bond_term: {term}. Use one of: 10y, 3m")
        return self._fetch_series(f"jgb_{term}", arguments.get('start_date'), arguments.get('end_date'),
                                  arguments.get('recent_periods'))


class BoJGetPolicyRateTool(BankOfJapanBaseTool):
    """Overnight call money rate (the BoJ's operating target)."""
    CHOICE = ('rate_type', ('call_money',), 'call_money')


class BoJGetExchangeRateTool(BankOfJapanBaseTool):
    """Yen per US dollar and yen per euro."""
    CHOICE = ('currency_pair', ('usd_jpy', 'eur_jpy'), 'usd_jpy')

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        pair = arguments.get('currency_pair') or 'usd_jpy'
        if pair not in ('usd_jpy', 'eur_jpy'):
            raise ValueError(f"Unsupported currency_pair: {pair}. Use one of: usd_jpy, eur_jpy")
        start, end, recent = arguments.get('start_date'), arguments.get('end_date'), arguments.get('recent_periods')
        if pair == 'usd_jpy':
            return self._fetch_series('usd_jpy', start, end, recent)
        # EUR/JPY is not on FRED: cross JPY per USD (DEXJPUS) with USD per EUR (DEXUSEU) by date.
        usd_jpy = self._fetch_series('DEXJPUS', start, end, recent)
        usd_eur = self._fetch_series('DEXUSEU', start, end, recent)
        eur_by_date = {o['date']: o['value'] for o in usd_eur['observations']}
        observations = [{'date': o['date'], 'value': round(o['value'] * eur_by_date[o['date']], 4)}
                        for o in usd_jpy['observations'] if o['date'] in eur_by_date]
        return {'series_code': 'DEXJPUS*DEXUSEU', 'series_id': 'eur_jpy', 'label': BOJ_SERIES['eur_jpy'][2],
                'source': 'FRED (Federal Reserve Bank of St. Louis), derived cross rate',
                'units': 'Japanese yen per euro', 'observation_count': len(observations),
                'observations': observations}


class BoJGetMoneySupplyTool(BankOfJapanBaseTool):
    """Broad money (IMF)."""
    CHOICE = ('aggregate', ('broad_money',), 'broad_money')


class BoJGetInflationTool(BankOfJapanBaseTool):
    """CPI level and inflation (IMF)."""
    CHOICE = ('index_type', ('cpi', 'cpi_inflation'), 'cpi')


class BoJGetEconomicIndicatorTool(BankOfJapanBaseTool):
    """GDP, unemployment and goods trade."""
    CHOICE = ('indicator', tuple(CATEGORIES['economy']), 'gdp')


class BoJListSeriesTools(BankOfJapanBaseTool):
    """The series the boj_ tools read; no network call."""

    def get_input_schema(self) -> Dict:
        return LIST_SCHEMA(CATEGORIES)

    def get_output_schema(self) -> Dict:
        return LIST_OUTPUT

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        return self._list(arguments.get('category') or 'all')


# Tool registry
BOJ_TOOLS = {
    'boj_get_jgb_yield': BoJGetJGBYieldTool,
    'boj_get_policy_rate': BoJGetPolicyRateTool,
    'boj_get_exchange_rate': BoJGetExchangeRateTool,
    'boj_get_money_supply': BoJGetMoneySupplyTool,
    'boj_get_inflation': BoJGetInflationTool,
    'boj_get_economic_indicator': BoJGetEconomicIndicatorTool,
    'boj_list_series': BoJListSeriesTools,
}
