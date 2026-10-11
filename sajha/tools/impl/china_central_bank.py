"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
People's Bank of China (PBoC) MCP tools.

The PBoC has no open API. These tools read Chinese series from FRED (needs FRED_API_KEY) and
from the IMF SDMX API (no key) through sajha/tools/impl/central_bank_series.py. Each series id
was checked live; FRED carries no Chinese government bond yield, lending or deposit rate,
Loan Prime Rate or current money supply, so those are not offered.
"""

from typing import Any, Dict

from sajha.tools.impl.central_bank_series import (
    CentralBankSeriesTool, LIST_OUTPUT, LIST_SCHEMA, Series)

PBOC_SERIES: Dict[str, Series] = {
    # rates
    'discount_rate': ('fred', 'INTDSRCNM193N', 'PBoC discount rate (IMF series on FRED), % a year, monthly'),
    'interbank_3m': ('fred', 'IR3TIB01CNM156N', '3-month interbank rate (OECD series on FRED), %, monthly'),
    # fx
    'usd_cny': ('fred', 'DEXCHUS', 'Chinese yuan per US dollar, daily (noon buying rate, New York)'),
    # prices
    'cpi': ('imf', 'CPI', 'CHN.CPI._T.IX.M', 'Consumer price index, all items (IMF CPI), monthly'),
    'cpi_inflation': ('imf', 'CPI', 'CHN.CPI._T.YOY_PCH_PA_PT.M',
                      'CPI inflation, % change on a year earlier (IMF CPI), monthly'),
    # economy
    'gdp': ('fred', 'MKTGDPCNA646NWDB', 'GDP, current US dollars (World Bank series on FRED), annual'),
    'gdp_growth': ('imf', 'IMF.RES,WEO', 'CHN.NGDP_RPCH.A',
                   'Real GDP growth, % (IMF World Economic Outlook, annual, includes projections)'),
    'exports': ('fred', 'XTEXVA01CNM667S', 'Goods exports, US dollars, seasonally adjusted, monthly (OECD)'),
    'imports': ('fred', 'XTIMVA01CNM667S', 'Goods imports, US dollars, seasonally adjusted, monthly (OECD)'),
    'trade_balance': ('fred', 'XTNTVA01CNM667S', 'Goods trade balance, US dollars, seasonally adjusted, monthly (OECD)'),
    'house_price_index': ('fred', 'QCNN628BIS', 'Residential property prices, index 2010=100, quarterly (BIS)'),
}

CATEGORIES = {
    'rates': ['discount_rate', 'interbank_3m'],
    'fx': ['usd_cny'],
    'prices': ['cpi', 'cpi_inflation'],
    'economy': ['gdp', 'gdp_growth', 'exports', 'imports', 'trade_balance', 'house_price_index'],
}


class PeoplesBankOfChinaBaseTool(CentralBankSeriesTool):
    SERIES = PBOC_SERIES
    CATEGORIES = CATEGORIES

    @property
    def fred_series(self) -> Dict[str, str]:
        return {k: v[1] for k, v in PBOC_SERIES.items() if v[0] == 'fred'}


class PBoCGetPolicyRateTool(PeoplesBankOfChinaBaseTool):
    """PBoC discount rate and the 3-month interbank rate."""
    CHOICE = ('rate_type', ('discount_rate', 'interbank_3m'), 'discount_rate')


class PBoCGetExchangeRateTool(PeoplesBankOfChinaBaseTool):
    """Yuan per US dollar."""
    CHOICE = ('currency_pair', ('usd_cny',), 'usd_cny')


class PBoCGetInflationTool(PeoplesBankOfChinaBaseTool):
    """Chinese CPI (IMF)."""
    CHOICE = ('measure', ('cpi', 'cpi_inflation'), 'cpi')


class PBoCGetEconomicIndicatorTool(PeoplesBankOfChinaBaseTool):
    """GDP, growth, trade and property prices."""
    CHOICE = ('indicator', tuple(CATEGORIES['economy']), 'gdp_growth')


class PBoCListSeriesTools(PeoplesBankOfChinaBaseTool):
    """The series the pboc_ tools read; no network call."""

    def get_input_schema(self) -> Dict:
        return LIST_SCHEMA(CATEGORIES)

    def get_output_schema(self) -> Dict:
        return LIST_OUTPUT

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        return self._list(arguments.get('category') or 'all')


# Tool registry
PBOC_TOOLS = {
    'pboc_get_policy_rate': PBoCGetPolicyRateTool,
    'pboc_get_exchange_rate': PBoCGetExchangeRateTool,
    'pboc_get_inflation': PBoCGetInflationTool,
    'pboc_get_economic_indicator': PBoCGetEconomicIndicatorTool,
    'pboc_list_series': PBoCListSeriesTools,
}
