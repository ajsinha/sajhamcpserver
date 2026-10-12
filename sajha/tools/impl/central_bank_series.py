"""
SAJHA MCP Server — shared base for the PBoC and BoJ tools: named series from FRED or the IMF.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Neither central bank publishes an open API, so each tool reads a named series from FRED
(api.stlouisfed.org, needs FRED_API_KEY; sajha/tools/impl/fred_key.py) or from the IMF SDMX API
(api.imf.org, no key; sajha/tools/impl/sdmx_client.py). Every series id was checked live when it
was added; a label with no openly published series is not offered. With no date, a call returns
the last ``recent_periods`` observations (default 10); with a date, the whole range.
"""

import logging
from datetime import datetime
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.http_utils import ENCODINGS_DEFAULT, safe_json_response
from sajha.tools.impl import sdmx_client
from sajha.tools.impl.fred_key import fred_api_key
from sajha.core import outbound

logger = logging.getLogger(__name__)

FRED_OBSERVATIONS = "https://api.stlouisfed.org/fred/series/observations"
FRED_SOURCE = 'FRED (Federal Reserve Bank of St. Louis)'
DEFAULT_RECENT = 10

# A series: ('fred', series id, label) or ('imf', dataflow, key, label)
Series = Tuple[str, ...]


def date_schema(maximum: int = 500) -> Dict[str, Any]:
    return {
        "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
        "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
        "recent_periods": {"type": "integer", "minimum": 1, "maximum": maximum, "default": DEFAULT_RECENT,
                           "description": "The last N observations; used only when neither date is given"},
    }


SERIES_OUTPUT = {
    "type": "object",
    "properties": {
        "series_code": {"type": "string"},
        "series_id": {"type": "string"},
        "label": {"type": "string"},
        "source": {"type": "string"},
        "observation_count": {"type": "integer"},
        "observations": {"type": "array", "items": {"type": "object", "properties": {
            "date": {"type": "string"}, "value": {"type": "number"}}}},
    },
}


class CentralBankSeriesTool(BaseMCPTool):
    """Base: ``SERIES`` maps a shorthand to its source; ``CHOICE`` is (argument, values, default)."""

    SERIES: Dict[str, Series] = {}
    CHOICE: Tuple[str, Tuple[str, ...], str] = ('', (), '')
    CATEGORIES: Dict[str, List[str]] = {}

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.fred_api_key = None

    # -- schema -------------------------------------------------------------
    def get_input_schema(self) -> Dict:
        arg, values, default = self.CHOICE
        props = {arg: {"type": "string", "enum": list(values), "default": default, "description": "Which series"}}
        props.update(date_schema())
        return {"type": "object", "properties": props}

    def get_output_schema(self) -> Dict:
        return SERIES_OUTPUT

    # -- fetching -----------------------------------------------------------
    def _get_api_key(self) -> str:
        if not self.fred_api_key:
            self.fred_api_key = fred_api_key(self.config)
        return self.fred_api_key

    def _fetch_series(self, series_id: str, start_date: Optional[str] = None, end_date: Optional[str] = None,
                      recent_periods: Optional[int] = None) -> Dict[str, Any]:
        spec = self.SERIES.get(series_id) or ('fred', series_id, series_id)
        last_n = None if (start_date or end_date) else int(recent_periods or DEFAULT_RECENT)
        if spec[0] == 'imf':
            return self._fetch_imf(series_id, spec[1], spec[2], spec[3], start_date, end_date, last_n)
        return self._fetch_fred(series_id, spec[1], spec[2], start_date, end_date, last_n)

    def _fetch_fred(self, series_id: str, code: str, label: str, start_date, end_date, last_n) -> Dict:
        params = {'series_id': code, 'api_key': self._get_api_key(), 'file_type': 'json',
                  'sort_order': 'desc' if last_n else 'asc'}
        if start_date:
            params['observation_start'] = start_date
        if end_date:
            params['observation_end'] = end_date
        if last_n:
            params['limit'] = last_n
        url = f"{FRED_OBSERVATIONS}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'SAJHA-MCP-Server', 'Accept': 'application/json'})
        try:
            with outbound.urlopen(req, timeout=30) as response:
                data = safe_json_response(response, ENCODINGS_DEFAULT)
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                raise ValueError(f"FRED has no series {code} (or the parameters are invalid)")
            raise ValueError(f"FRED API error: HTTP {e.code}")
        except Exception as e:
            raise ValueError(f"Failed to get FRED series {code}: {e}")
        observations = []
        for obs in data.get('observations') or []:
            try:
                observations.append({'date': obs.get('date'), 'value': float(obs.get('value'))})
            except (TypeError, ValueError):
                continue                        # FRED marks a missing value with '.'
        if last_n:
            observations.reverse()
        return {'series_code': code, 'series_id': series_id, 'label': label, 'source': FRED_SOURCE,
                'observation_count': len(observations), 'observations': observations}

    def _fetch_imf(self, series_id: str, flow: str, key: str, label: str, start_date, end_date, last_n) -> Dict:
        end = (end_date or '')[:7] or None
        if end is None and flow.endswith('WEO'):
            end = str(datetime.now().year)      # WEO runs years ahead: stop at this year's projection
        try:
            result = sdmx_client.fetch('imf', flow, key, start=(start_date or '')[:7] or None,
                                       end=end, last_n=last_n)
        except sdmx_client.SdmxError as e:
            raise ValueError(f"IMF data portal: {e}")
        s = sdmx_client.one_series(result)
        observations = [{'date': o['period'], 'value': o['value']}
                        for o in (s or {}).get('observations', []) if o['value'] is not None]
        return {'series_code': f"{flow}.{key}", 'series_id': series_id, 'label': label,
                'source': result['source'], 'observation_count': len(observations),
                'observations': observations}

    # -- calls --------------------------------------------------------------
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        arg, values, default = self.CHOICE
        value = arguments.get(arg) or default
        if value not in values:
            raise ValueError(f"Unsupported {arg}: {value}. Use one of: {', '.join(values)}")
        return self._fetch_series(value, arguments.get('start_date'), arguments.get('end_date'),
                                  arguments.get('recent_periods'))

    def _list(self, category: str) -> Dict:
        if category != 'all' and category not in self.CATEGORIES:
            raise ValueError(f"Unknown category: {category}. Use one of: {', '.join(self.CATEGORIES)}, all")
        names = [n for c, ns in self.CATEGORIES.items() if category in ('all', c) for n in ns]
        rows = []
        for name in names:
            spec = self.SERIES[name]
            if spec[0] == 'imf':
                rows.append({'id': name, 'code': f"{spec[1]}.{spec[2]}", 'source': 'IMF', 'label': spec[3]})
            else:
                rows.append({'id': name, 'code': spec[1], 'fred_code': spec[1], 'source': 'FRED', 'label': spec[2]})
        return {'category': category, 'count': len(rows), 'series': rows,
                'source': 'FRED (needs FRED_API_KEY) and the IMF data portal (no key)'}


LIST_SCHEMA = lambda categories: {  # noqa: E731
    "type": "object",
    "properties": {"category": {"type": "string", "enum": list(categories) + ['all'], "default": "all",
                                "description": "Category filter"}},
}
LIST_OUTPUT = {"type": "object", "properties": {
    "category": {"type": "string"}, "count": {"type": "integer"}, "source": {"type": "string"},
    "series": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"}, "code": {"type": "string"}, "source": {"type": "string"},
        "label": {"type": "string"}}}}}}
