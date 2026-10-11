"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
IMF (International Monetary Fund) MCP tools.

The IMF retired its legacy SDMX JSON service (dataservices.imf.org) and its International
Financial Statistics database. These tools read the IMF's current SDMX 2.1 API
(api.imf.org/external/sdmx/2.1, no key) through the shared SDMX client
(sajha/tools/impl/sdmx_client.py). Former IFS indicators come from their successor dataflows
(CPI, ER, MFS_IR, IL, MFS_MA); WEO and BOP keep their names. Countries are ISO alpha-3 on the
wire; alpha-2 is accepted and converted (sajha/tools/impl/country_codes.py).
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.impl import country_codes, sdmx_client

# Dataflow id -> owning agency, for the flows these tools name
AGENCIES = {'WEO': 'IMF.RES', 'PCPS': 'IMF.RES', 'CTOT': 'IMF.RES'}

# Friendly WEO names -> WEO indicator codes (verified in CL_WEO_INDICATOR)
WEO_INDICATORS = {
    'gdp_growth': 'NGDP_RPCH',
    'gdp_usd': 'NGDPD',
    'gdp_per_capita': 'NGDPDPC',
    'inflation_avg': 'PCPIPCH',
    'inflation_eop': 'PCPIEPCH',
    'unemployment': 'LUR',
    'current_account': 'BCA_NGDPD',
    'fiscal_balance': 'GGXCNL_NGDP',
    'public_debt': 'GGXWDG_NGDP',
    'exports_volume': 'TXG_RPCH',
    'imports_volume': 'TMG_RPCH',
    'population': 'LP',
}

# Former IFS indicators -> (successor dataflow, key template); {c} country, {f} frequency
IFS_INDICATORS: Dict[str, Tuple[str, str]] = {
    'exchange_rate': ('ER', '{c}.XDC_USD.EOP_RT.{f}'),            # national currency per USD, end of period
    'exchange_rate_avg': ('ER', '{c}.XDC_USD.PA_RT.{f}'),         # national currency per USD, period average
    'policy_rate': ('MFS_IR', '{c}.MFS166_RT_PT_A_PT.{f}'),       # monetary policy-related rate, % p.a.
    'treasury_bill_yield': ('MFS_IR', '{c}.GSTBILY_RT_PT_A_PT.{f}'),
    'deposit_rate': ('MFS_IR', '{c}.MFS135_RT_PT_A_PT.{f}'),
    'lending_rate': ('MFS_IR', '{c}.MFS162_RT_PT_A_PT.{f}'),
    'money_market_rate': ('MFS_IR', '{c}.MMRT_RT_PT_A_PT.{f}'),
    'cpi': ('CPI', '{c}.CPI._T.IX.{f}'),                          # index
    'cpi_inflation': ('CPI', '{c}.CPI._T.YOY_PCH_PA_PT.{f}'),     # % change on a year earlier
    'international_reserves': ('IL', '{c}.TRGMV_REVS.USD.{f}'),   # total reserves, gold at market value, USD
    'broad_money': ('MFS_MA', '{c}.BM_MAI.XDC.{f}'),              # national currency
}

# BOP shorthands -> BOP_ACCOUNTING_ENTRY.INDICATOR
BOP_INDICATORS = {
    'current_account': 'NETCD_T.CAB',
    'goods_and_services': 'NETCD_T.GS',
    'capital_account': 'NETCD_T.KAB',
    'financial_account': 'NNAFANIL_T.FAB',
    'current_account_credit': 'CD_T.TCDCA',
    'current_account_debit': 'DB_T.TDBCA',
}

PROFILE = {'GDP Growth': 'NGDP_RPCH', 'Inflation': 'PCPIPCH', 'Unemployment': 'LUR',
           'Current Account': 'BCA_NGDPD', 'Public Debt': 'GGXWDG_NGDP'}


def _country(code: Any) -> str:
    """ISO alpha-3 for a country; anything else (an IMF group code such as G001) upper-cased."""
    if not code or not str(code).strip():
        raise ValueError("A country_code is required (ISO alpha-3 such as USA, or alpha-2 such as US)")
    return country_codes.to_alpha3(code) or str(code).strip().upper()


class IMFBaseTool(BaseMCPTool):
    """Shared IMF access through the SDMX client."""

    def get_input_schema(self) -> Dict:
        return {"type": "object", "properties": {}}

    def get_output_schema(self) -> Dict:
        return {"type": "object"}

    def _names(self, flow: str) -> Dict[str, Dict[str, str]]:
        """Code names per dimension of a flow, for readable series names (cached by the client)."""
        try:
            st = sdmx_client.flow_structure('imf', flow, agency=AGENCIES.get(flow))
        except sdmx_client.SdmxError:
            return {}
        return {d['id']: {c['id']: c['name'] for c in d['codes']} for d in st['dimensions']}

    def _query(self, flow: str, key: str, start_year: Optional[int] = None,
               end_year: Optional[int] = None) -> List[Dict[str, Any]]:
        try:
            result = sdmx_client.fetch('imf', flow, key, agency=AGENCIES.get(flow),
                                       start=str(start_year) if start_year else None,
                                       end=str(end_year) if end_year else None, timeout=45)
        except sdmx_client.SdmxError as e:
            raise ValueError(f"IMF data portal: {e}")
        names = None
        out = []
        for s in result['series']:
            name = s['attributes'].get('SERIES_NAME')
            if not name:
                names = names if names is not None else self._names(flow)
                name = ', '.join(names.get(d, {}).get(v, v) for d, v in s['dimensions'].items()
                                 if d not in ('COUNTRY', 'FREQUENCY'))
            out.append({'key': s['key'], 'dimensions': s['dimensions'], 'name': name,
                        'latest_actual_year': s['attributes'].get('LATEST_ACTUAL_ANNUAL_DATA'),
                        'data': [{'period': o['period'], 'value': o['value']} for o in s['observations']]})
        return out

    def _series(self, flow: str, key: str, start_year=None, end_year=None, **extra) -> Dict[str, Any]:
        series = self._query(flow, key, start_year, end_year)
        s = series[0] if series else {'name': None, 'data': []}
        out = {'database': flow, 'key': key, **extra, 'name': s['name'], 'data': s['data'],
               'count': len(s['data']), 'source': sdmx_client.host('imf').source}
        if s.get('latest_actual_year'):
            out['latest_actual_year'] = s['latest_actual_year']
        if not s['data']:
            out['note'] = 'No data: the IMF has no observations for this series and period.'
        return out


class IMFGetDatabasesTool(IMFBaseTool):
    """List the IMF's dataflows (databases)."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        search = (arguments.get('search') or '').strip().lower()
        try:
            flows = sdmx_client.dataflows('imf')
        except sdmx_client.SdmxError as e:
            raise ValueError(f"IMF data portal: {e}")
        rows = [{'code': f['id'], 'agency': f['agency'], 'version': f['version'], 'name': f['name']}
                for f in flows if not f['id'].endswith('_VINTAGE')
                and (not search or search in f['id'].lower() or search in f['name'].lower())]
        rows.sort(key=lambda r: r['code'])
        return {'databases': rows, 'count': len(rows), 'source': sdmx_client.host('imf').source}


class IMFGetDataflowsTool(IMFBaseTool):
    """The key structure of one IMF dataflow: its dimensions and their codes."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        flow = str(arguments.get('database') or '').strip().upper()
        if not flow:
            raise ValueError("database is required (a dataflow id such as WEO, CPI, BOP; see imf_get_databases)")
        only = (arguments.get('dimension') or '').strip().upper()
        search = (arguments.get('search') or '').strip().lower()
        limit = int(arguments.get('limit') or 50)
        try:
            st = sdmx_client.flow_structure('imf', flow, agency=AGENCIES.get(flow))
        except sdmx_client.SdmxError as e:
            raise ValueError(f"IMF data portal: {e}")
        dims = []
        for d in st['dimensions']:
            if only and d['id'] != only:
                continue
            codes = [c for c in d['codes'] if not search or search in c['id'].lower() or search in c['name'].lower()]
            dims.append({'position': len(dims) + 1 if not only else d['position'], 'id': d['id'],
                         'code_count': len(codes), 'codes': codes[:limit], 'truncated': len(codes) > limit})
        return {'database': flow, 'flow': st['flow'], 'name': st['name'],
                'key_template': '.'.join(d['id'] for d in st['dimensions']),
                'dimensions': dims, 'source': sdmx_client.host('imf').source}


class IMFGetDataTool(IMFBaseTool):
    """Any IMF series by dataflow and key (or country, indicator and frequency)."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        flow = str(arguments.get('database') or '').strip().upper()
        if not flow:
            raise ValueError("database is required (a dataflow id such as WEO, CPI, BOP)")
        key = (arguments.get('key') or '').strip()
        frequency = arguments.get('frequency', 'A')
        if not key:
            indicator = arguments.get('indicator_code')
            if not (arguments.get('country_code') and indicator):
                raise ValueError("Give key, or country_code and indicator_code")
            dims = [d['id'] for d in sdmx_client.flow_structure('imf', flow, agency=AGENCIES.get(flow))['dimensions']]
            if dims != ['COUNTRY', 'INDICATOR', 'FREQUENCY']:
                raise ValueError(f"{flow} keys have the dimensions {'.'.join(dims)}; pass the full key "
                                 f"(imf_get_dataflows shows the codes)")
            key = f"{_country(arguments['country_code'])}.{indicator}.{frequency}"
        series = self._query(flow, key, arguments.get('start_year'), arguments.get('end_year'))
        out = {'database': flow, 'key': key, 'series': series, 'count': len(series),
               'source': sdmx_client.host('imf').source}
        if not series:
            out['note'] = 'No data: the IMF has no observations for this key and period.'
        return out


class IMFGetIFSDataTool(IMFBaseTool):
    """Former International Financial Statistics indicators, from their successor dataflows."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        indicator = arguments.get('indicator')
        if indicator not in IFS_INDICATORS:
            raise ValueError(f"indicator must be one of: {', '.join(IFS_INDICATORS)}")
        country = _country(arguments.get('country_code'))
        frequency = arguments.get('frequency', 'M')
        flow, template = IFS_INDICATORS[indicator]
        key = template.format(c=country, f=frequency)
        return self._series(flow, key, arguments.get('start_year'), arguments.get('end_year'),
                            country_code=country, indicator=indicator, frequency=frequency)


class IMFGetWEODataTool(IMFBaseTool):
    """World Economic Outlook series (annual, with IMF projections)."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        code = arguments.get('indicator_code') or WEO_INDICATORS.get(arguments.get('indicator') or '')
        if not code:
            raise ValueError(f"Give indicator ({', '.join(WEO_INDICATORS)}) or a WEO indicator_code")
        country = _country(arguments.get('country_code'))
        return self._series('WEO', f"{country}.{code}.A", arguments.get('start_year'), arguments.get('end_year'),
                            country_code=country, indicator_code=code, frequency='A')


class IMFGetBOPDataTool(IMFBaseTool):
    """Balance of payments (BPM6), USD."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        code = arguments.get('indicator_code') or BOP_INDICATORS.get(arguments.get('indicator') or '')
        if not code or code.count('.') != 1:
            raise ValueError(f"Give indicator ({', '.join(BOP_INDICATORS)}) or indicator_code as "
                             f"ACCOUNTING_ENTRY.INDICATOR, e.g. NETCD_T.CAB")
        country = _country(arguments.get('country_code'))
        frequency = arguments.get('frequency', 'A')
        return self._series('BOP', f"{country}.{code}.USD.{frequency}", arguments.get('start_year'),
                            arguments.get('end_year'), country_code=country, indicator_code=code,
                            frequency=frequency, unit='USD')


class IMFCompareCountriesTool(IMFBaseTool):
    """One indicator across countries, in one request."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        countries = [_country(c) for c in (arguments.get('country_codes') or [])]
        if len(countries) < 2:
            raise ValueError("country_codes needs at least two countries")
        database = arguments.get('database', 'WEO')
        indicator = arguments.get('indicator')
        if database == 'IFS':
            if indicator not in IFS_INDICATORS:
                raise ValueError(f"For IFS, indicator must be one of: {', '.join(IFS_INDICATORS)}")
            flow, template = IFS_INDICATORS[indicator]
            frequency = arguments.get('frequency', 'A')
            key = template.format(c='+'.join(countries), f=frequency)
        else:
            code = arguments.get('indicator_code') or WEO_INDICATORS.get(indicator or '')
            if not code:
                raise ValueError(f"Give indicator ({', '.join(WEO_INDICATORS)}) or a WEO indicator_code")
            flow, frequency, key = 'WEO', 'A', f"{'+'.join(countries)}.{code}.A"
        series = {s['dimensions'].get('COUNTRY'): s
                  for s in self._query(flow, key, arguments.get('start_year'), arguments.get('end_year'))}
        rows = []
        for c in countries:
            s = series.get(c)
            row = {'country_code': c, 'country_name': country_codes.name(c) or c,
                   'name': s['name'] if s else None, 'data': s['data'] if s else [],
                   'count': len(s['data']) if s else 0}
            if not s:
                row['note'] = 'No data for this country'
            rows.append(row)
        return {'database': flow, 'key': key, 'frequency': frequency, 'countries': rows,
                'source': sdmx_client.host('imf').source}


class IMFGetCountryProfileTool(IMFBaseTool):
    """Five WEO headline indicators for one country over the last five years and this one."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        country = _country(arguments.get('country_code'))
        year = datetime.now().year
        key = f"{country}.{'+'.join(PROFILE.values())}.A"
        series = {s['dimensions'].get('INDICATOR'): s for s in self._query('WEO', key, year - 5, year)}
        indicators = {}
        for label, code in PROFILE.items():
            s = series.get(code)
            if not s or not s['data']:
                indicators[label] = {'code': code, 'error': 'No data for this country'}
                continue
            latest = s['data'][-1]
            indicators[label] = {'code': code, 'name': s['name'], 'latest_value': latest['value'],
                                 'latest_period': latest['period'],
                                 'latest_actual_year': s.get('latest_actual_year'),
                                 'recent_data': s['data'][-3:]}
        return {'country_code': country, 'country_name': country_codes.name(country) or country,
                'indicators': indicators, 'source': sdmx_client.host('imf').source,
                'note': 'WEO values after latest_actual_year are IMF projections.'}


# Tool registry
IMF_TOOLS = {
    'imf_get_databases': IMFGetDatabasesTool,
    'imf_get_dataflows': IMFGetDataflowsTool,
    'imf_get_data': IMFGetDataTool,
    'imf_get_ifs_data': IMFGetIFSDataTool,
    'imf_get_weo_data': IMFGetWEODataTool,
    'imf_get_bop_data': IMFGetBOPDataTool,
    'imf_compare_countries': IMFCompareCountriesTool,
    'imf_get_country_profile': IMFGetCountryProfileTool,
}
