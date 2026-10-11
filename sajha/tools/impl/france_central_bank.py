"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Banque de France / ECB MCP tools.

French and euro area series from the ECB Data Portal (data-api.ecb.europa.eu), read through
the shared SDMX client (sajha/tools/impl/sdmx_client.py). Every series key below was checked
live; a label with no openly published series is not offered (the ECB publishes one French
government bond yield, the 10-year convergence yield, so bdf_get_oat_yield has one term).
"""

from typing import Any, Dict, Optional, Tuple

from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.impl import sdmx_client

# shorthand: (ECB flow, series key)
SERIES: Dict[str, Tuple[str, str]] = {
    # ECB policy rates (business-day frequency; change only on decision dates)
    'ecb_main_refi': ('FM', 'B.U2.EUR.4F.KR.MRR_FR.LEV'),
    'ecb_deposit': ('FM', 'B.U2.EUR.4F.KR.DFR.LEV'),
    'ecb_marginal_lending': ('FM', 'B.U2.EUR.4F.KR.MLFR.LEV'),
    # France, long-term (10-year) government bond yield for convergence purposes, monthly
    'oat_10y': ('IRS', 'M.FR.L.L40.CI.0000.EUR.N.Z'),
    # ECB euro reference rates (units of the currency per euro), daily
    'eur_usd': ('EXR', 'D.USD.EUR.SP00.A'),
    'eur_gbp': ('EXR', 'D.GBP.EUR.SP00.A'),
    'eur_jpy': ('EXR', 'D.JPY.EUR.SP00.A'),
    'eur_cny': ('EXR', 'D.CNY.EUR.SP00.A'),
    # France
    'fr_cpi': ('HICP', 'M.FR.N.000000.4D0.ANR'),                       # HICP, annual rate of change
    'fr_gdp': ('MNA', 'Q.Y.FR.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.V.N'),     # current prices, EUR millions
    'fr_unemployment': ('LFSI', 'M.FR.S.UNEHRT.TOTAL0.15_74.T'),     # percent, seasonally adjusted
    # Euro area
    'ez_cpi': ('HICP', 'M.U2.N.000000.4D0.ANR'),
    'ez_gdp': ('MNA', 'Q.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.V.N'),    # euro area 21, EUR millions
    'm3': ('BSI', 'M.U2.Y.V.M30.X.I.U2.2300.Z01.A'),                  # M3, annual growth rate
}


class BanqueDeFranceBaseTool(BaseMCPTool):
    """Shared fetch for the bdf_ tools: one ECB series, recent_periods as lastNObservations."""

    #: (argument name, allowed shorthands, default) — set by each tool
    choice: Tuple[str, Tuple[str, ...], str] = ('', (), '')
    #: argument value -> SERIES shorthand, where they differ
    aliases: Dict[str, str] = {}

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.common_series = SERIES

    def get_input_schema(self) -> Dict:
        arg, values, default = self.choice
        return {
            "type": "object",
            "properties": {
                arg: {"type": "string", "enum": list(values), "default": default,
                      "description": "Which series"},
                "start_date": {"type": "string", "description": "Start date or period, YYYY-MM-DD (also YYYY-MM or YYYY)"},
                "end_date": {"type": "string", "description": "End date or period, YYYY-MM-DD (also YYYY-MM or YYYY)"},
                "recent_periods": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10,
                                   "description": "The last N observations; used only when neither date is given"},
            },
        }

    def get_output_schema(self) -> Dict:
        return {
            "type": "object",
            "properties": {
                "series_code": {"type": "string"},
                "label": {"type": "string"},
                "unit": {"type": ["string", "null"]},
                "frequency": {"type": ["string", "null"]},
                "source": {"type": "string"},
                "observation_count": {"type": "integer"},
                "observations": {
                    "type": "array",
                    "items": {"type": "object", "properties": {
                        "date": {"type": "string"}, "value": {"type": ["number", "null"]}}},
                },
            },
        }

    def _fetch_series(self, shorthand: str, start_date: Optional[str] = None,
                      end_date: Optional[str] = None, recent_periods: Optional[int] = 10) -> Dict:
        flow, key = self.common_series[shorthand]
        last_n = None if (start_date or end_date) else (recent_periods or 10)
        try:
            out = sdmx_client.fetch_series('ecb', flow, key, start=start_date, end=end_date, last_n=last_n)
        except sdmx_client.SdmxError as e:
            raise ValueError(f"ECB Data Portal: {e}")
        out['series_id'] = shorthand
        return out

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        arg, values, default = self.choice
        value = arguments.get(arg) or default
        if value not in values:
            raise ValueError(f"Invalid {arg}: {value}. Use one of: {', '.join(values)}")
        return self._fetch_series(self.aliases.get(value, value), arguments.get('start_date'),
                                  arguments.get('end_date'), arguments.get('recent_periods', 10))


class BdFGetOATYieldTool(BanqueDeFranceBaseTool):
    """French 10-year government bond yield (ECB long-term interest rate for convergence purposes)."""
    choice = ('bond_term', ('10y',), '10y')
    aliases = {'10y': 'oat_10y'}


class BdFGetECBPolicyRateTool(BanqueDeFranceBaseTool):
    """ECB main refinancing, deposit facility and marginal lending rates."""
    choice = ('rate_type', ('ecb_main_refi', 'ecb_deposit', 'ecb_marginal_lending'), 'ecb_main_refi')


class BdFGetExchangeRateTool(BanqueDeFranceBaseTool):
    """ECB euro reference rates."""
    choice = ('currency_pair', ('eur_usd', 'eur_gbp', 'eur_jpy', 'eur_cny'), 'eur_usd')


class BdFGetFrenchEconomicIndicatorTool(BanqueDeFranceBaseTool):
    """French HICP inflation, GDP and unemployment."""
    choice = ('indicator', ('fr_cpi', 'fr_gdp', 'fr_unemployment'), 'fr_cpi')


class BdFGetEurozoneIndicatorTool(BanqueDeFranceBaseTool):
    """Euro area HICP inflation, GDP and M3 growth."""
    choice = ('indicator', ('ez_cpi', 'ez_gdp', 'm3'), 'ez_cpi')


# Tool registry
BANQUE_DE_FRANCE_TOOLS = {
    'bdf_get_oat_yield': BdFGetOATYieldTool,
    'bdf_get_ecb_policy_rate': BdFGetECBPolicyRateTool,
    'bdf_get_exchange_rate': BdFGetExchangeRateTool,
    'bdf_get_french_indicator': BdFGetFrenchEconomicIndicatorTool,
    'bdf_get_eurozone_indicator': BdFGetEurozoneIndicatorTool,
}
