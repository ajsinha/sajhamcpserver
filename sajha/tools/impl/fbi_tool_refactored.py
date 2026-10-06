"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
FBI Crime Data Explorer (CDE) MCP tools.

Every tool calls the current CDE API behind the api.data.gov gateway,
``https://api.usa.gov/crime/fbi/cde``. The paths used are the ones in the API
specification the Crime Data Explorer publishes on its "API" page
(https://cde.ucr.cjis.gov/LATEST/webapp/#/pages/docApi):

    /summarized/national/{offense}?from=MM-YYYY&to=MM-YYYY
    /summarized/state/{state}/{offense}?from=MM-YYYY&to=MM-YYYY
    /summarized/agency/{ori}/{offense}?from=MM-YYYY&to=MM-YYYY
    /agency/byStateAbbr/{state}
    /pe/{state}/{ori}?from=YYYY&to=YYYY
    /nibrs/national/{offense}?type=counts|totals&from=MM-YYYY&to=MM-YYYY
    /nibrs/state/{state}/{offense}?type=counts|totals&from=MM-YYYY&to=MM-YYYY

The summarized endpoints return monthly series keyed by display name
("United States Offenses", "California Clearances", ...); the helpers below turn
them into annual figures. A monthly rate is offenses per 100,000 people in the
population covered by reporting agencies that month, so an annual rate is the sum
of the monthly rates.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional

from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.http_utils import ENCODINGS_DEFAULT, safe_json_response

API_URL = 'https://api.usa.gov/crime/fbi/cde'
DEFAULT_TIMEOUT = 30
MIN_YEAR = 1985  # earliest year the Crime Data Explorer serves

# Tool offense names -> /summarized offense codes (spec schema "summarized_offenses")
SUMMARIZED_OFFENSES = {
    'violent_crime': 'V',
    'homicide': 'HOM',
    'rape': 'RPE',
    'robbery': 'ROB',
    'aggravated_assault': 'ASS',
    'property_crime': 'P',
    'burglary': 'BUR',
    'larceny': 'LAR',
    'motor_vehicle_theft': 'MVT',
    'arson': 'ARS',
}

# Tool offense names -> NIBRS offense codes (spec schema "nibrs_offenses"). NIBRS has
# no single code for the violent/property aggregates or for larceny as a whole.
NIBRS_OFFENSES = {
    'homicide': '09A',            # Murder and Nonnegligent Manslaughter
    'rape': '11A',
    'robbery': '120',
    'aggravated_assault': '13A',
    'simple_assault': '13B',
    'burglary': '220',            # Burglary/Breaking & Entering
    'motor_vehicle_theft': '240',
    'arson': '200',
    'kidnapping': '100',
    'identity_theft': '26F',
}

# search_agencies agency_type -> CDE agency_type_name values
AGENCY_TYPES = {
    'city': {'City'},
    'county': {'County'},
    'state': {'State Police', 'Other State Agency'},
    'university': {'University or College'},
    'tribal': {'Tribal'},
    'other': {'Other'},
}

STATE_NAMES = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
    'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
    'DC': 'District of Columbia', 'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii',
    'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa', 'KS': 'Kansas',
    'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
    'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
    'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada',
    'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York',
    'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma',
    'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island', 'SC': 'South Carolina',
    'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas', 'UT': 'Utah',
    'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington', 'WV': 'West Virginia',
    'WI': 'Wisconsin', 'WY': 'Wyoming',
}

US = 'United States'
KEY_HELP = ('Set an api.data.gov key in the FBI_API_KEY environment variable '
            '(read through config key fbi.api.key); keys are free at https://api.data.gov/signup/.')


class FBIAPIError(ValueError):
    """A CDE / api.data.gov failure, with a message an agent can act on."""


# ── Parsing helpers (pure; unit-tested against recorded responses) ───────────

def _month_year(key: str) -> int:
    """'MM-YYYY' -> YYYY"""
    return int(key.split('-')[1])


def _series_entities(data: Dict) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Flatten a /summarized (or /nibrs type=counts) response into
    ``{entity: {series: {MM-YYYY: value}}}`` where series is one of offenses,
    clearances, offense_rate, clearance_rate, population, participated_population,
    coverage_pct."""
    out: Dict[str, Dict[str, Dict[str, float]]] = {}

    def put(entity, series, values):
        if isinstance(values, dict):
            out.setdefault(entity, {})[series] = values

    offenses = data.get('offenses') or {}
    for kind, prefix in (('actuals', ''), ('rates', '_rate')):
        for label, values in (offenses.get(kind) or {}).items():
            for suffix, series in ((' Offenses', 'offenses'), (' Clearances', 'clearances')):
                if label.endswith(suffix):
                    name = label[:-len(suffix)]
                    put(name, series if not prefix else series[:-1] + '_rate', values)
    pops = data.get('populations') or {}
    for series in ('population', 'participated_population'):
        for name, values in (pops.get(series) or {}).items():
            put(name, series, values)
    coverage = (data.get('tooltips') or {}).get('Percent of Population Coverage') or {}
    for name, values in coverage.items():
        put(name, 'coverage_pct', values)
    return out


def _annual(entity: Dict[str, Dict[str, float]], year: int) -> Dict[str, Any]:
    """Annual figures for one entity from its monthly series."""
    def months(series):
        return {k: v for k, v in (entity.get(series) or {}).items()
                if v is not None and _month_year(k) == year}

    offenses, clearances = months('offenses'), months('clearances')
    rates = months('offense_rate')
    population, participated = months('population'), months('participated_population')
    coverage = months('coverage_pct')

    total = int(sum(offenses.values())) if offenses else None
    cleared = int(sum(clearances.values())) if clearances else None
    last = max(population) if population else None
    return {
        'total_incidents': total,
        'total_cleared': cleared,
        'clearance_rate_pct': round(cleared / total * 100, 2) if total and cleared is not None else None,
        'rate_per_100k': round(sum(rates.values()), 2) if rates else None,
        'population': int(population[last]) if last else None,
        'participated_population': int(sum(participated.values()) / len(participated)) if participated else None,
        'population_coverage_pct': round(sum(coverage.values()) / len(coverage), 2) if coverage else None,
        'months_reported': len(rates) if rates else len(offenses),
    }


def _monthly(entity: Dict[str, Dict[str, float]], year: int) -> List[Dict[str, Any]]:
    rates = entity.get('offense_rate') or {}
    counts = entity.get('offenses') or {}
    keys = sorted((k for k in set(rates) | set(counts) if _month_year(k) == year),
                  key=lambda k: int(k[:2]))
    return [{'month': f'{year}-{k[:2]}', 'incidents': counts.get(k), 'rate_per_100k': rates.get(k)}
            for k in keys]


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return round(a / b * 100, 2) if a is not None and b else None


def _metadata(data: Dict, endpoint: str) -> Dict[str, Any]:
    props = data.get('cde_properties') or {}
    return {
        'data_source': 'FBI Crime Data Explorer (UCR summarized SRS + NIBRS)',
        'endpoint': endpoint,
        'data_last_refreshed': (props.get('last_refresh_date') or {}).get('UCR'),
        'data_available_through': (props.get('max_data_date') or {}).get('UCR'),
    }


class FBIBaseTool(BaseMCPTool):
    """Shared HTTP, key and validation logic for the FBI tools."""

    tool_name = ''
    tool_description = ''

    def __init__(self, config: Dict = None):
        merged = {'name': self.tool_name, 'description': self.tool_description,
                  'version': '3.0.0', 'enabled': True}
        merged.update(config or {})
        super().__init__(merged)
        self.api_url = (self.config.get('api_url') or API_URL).rstrip('/')
        self.timeout = float(self.config.get('timeout') or DEFAULT_TIMEOUT)
        self.api_key = self._resolve_api_key()

    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})

    # -- configuration ------------------------------------------------------

    def _resolve_api_key(self) -> str:
        """api.data.gov key: tool config ``api_key`` (``${fbi.api.key:}`` in the shipped
        configs, i.e. FBI_API_KEY), then FBI_API_KEY / DATA_GOV_API_KEY env vars, then
        api.data.gov's heavily rate-limited ``DEMO_KEY``."""
        for candidate in (self.config.get('api_key'),
                          os.environ.get('FBI_API_KEY'),
                          os.environ.get('DATA_GOV_API_KEY')):
            if candidate and isinstance(candidate, str) and not candidate.startswith('${'):
                return candidate
        return 'DEMO_KEY'

    # -- HTTP ---------------------------------------------------------------

    def _get(self, path: str, params: Dict = None) -> Any:
        url = f'{self.api_url}/{path.lstrip("/")}'
        if params:
            url += '?' + urllib.parse.urlencode(params, safe='*')
        req = urllib.request.Request(url, headers={
            'User-Agent': 'SAJHA-MCP-Server',
            'Accept': 'application/json',
            # api.data.gov accepts the key as a header, which keeps it out of URLs and logs
            'X-Api-Key': self.api_key,
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return safe_json_response(response, ENCODINGS_DEFAULT)
        except urllib.error.HTTPError as e:
            raise self._http_error(e, path) from None
        except urllib.error.URLError as e:
            raise FBIAPIError(f'FBI CDE API unreachable ({e.reason}); try again later') from None
        except TimeoutError:
            raise FBIAPIError(f'FBI CDE API did not answer within {self.timeout:g}s') from None
        except json.JSONDecodeError:
            raise FBIAPIError(f'FBI CDE API returned a non-JSON response for {path}') from None

    def _http_error(self, e: urllib.error.HTTPError, path: str) -> FBIAPIError:
        try:
            body = e.read().decode('utf-8', 'replace').strip()
        except Exception:
            body = ''
        code, message = '', body
        try:
            err = json.loads(body).get('error') or {}
            code, message = err.get('code', ''), err.get('message', body)
        except (ValueError, AttributeError):
            pass
        demo = self.api_key == 'DEMO_KEY'
        if e.code == 429 or code == 'OVER_RATE_LIMIT':
            hint = ('No key is configured, so the shared DEMO_KEY was used; it allows only a few '
                    'requests. ' + KEY_HELP) if demo else 'Wait and retry, or use a key with a higher limit.'
            return FBIAPIError(f'FBI API rate limit exceeded. {hint}')
        if e.code in (401, 403) or code.startswith('API_KEY'):
            return FBIAPIError(f'FBI API key rejected ({code or e.code}). {KEY_HELP}')
        if e.code == 400:
            return FBIAPIError(f'FBI CDE API rejected the request: {message or "bad request"}')
        if e.code == 404:
            return FBIAPIError(f'FBI CDE API has no resource at {path}')
        return FBIAPIError(f'FBI CDE API request failed: HTTP {e.code} {message[:200]}'.rstrip())

    # -- validation ---------------------------------------------------------

    @staticmethod
    def _default_year() -> int:
        """Most recent complete year."""
        return datetime.now().year - 1

    def _year(self, value, name='year') -> int:
        year = int(value) if value is not None else self._default_year()
        if not MIN_YEAR <= year <= datetime.now().year:
            raise ValueError(f'{name} must be between {MIN_YEAR} and {datetime.now().year}')
        return year

    @staticmethod
    def _state(value: str) -> str:
        state = (value or '').strip().upper()
        if state not in STATE_NAMES:
            raise ValueError(f'Invalid state code: {value!r} (use a two-letter USPS code, e.g. CA)')
        return state

    @staticmethod
    def _offense(value: str, table: Dict[str, str] = SUMMARIZED_OFFENSES) -> str:
        if value not in table:
            raise ValueError(f'Unsupported offense_type {value!r}; choose one of: {", ".join(table)}')
        return table[value]

    @staticmethod
    def _ori(value: str) -> str:
        ori = (value or '').strip().upper()
        if len(ori) != 9 or not ori.isalnum():
            raise ValueError(f'Invalid ORI {value!r}: an ORI is 9 letters/digits, e.g. VT0040100')
        return ori

    # -- shared fetches -----------------------------------------------------

    def _summarized(self, scope_path: str, offense: str, start_year: int, end_year: int):
        path = f'summarized/{scope_path}/{offense}'
        data = self._get(path, {'from': f'01-{start_year}', 'to': f'12-{end_year}'})
        if not isinstance(data, dict):
            raise FBIAPIError(f'Unexpected response from {path}')
        return data, _series_entities(data), path

    def _state_agencies(self, state: str) -> List[Dict[str, Any]]:
        data = self._get(f'agency/byStateAbbr/{state}')
        agencies = []
        if isinstance(data, dict):
            for county_list in data.values():
                if isinstance(county_list, list):
                    agencies.extend(a for a in county_list if isinstance(a, dict) and a.get('ori'))
        return agencies


class FBIGetNationalStatisticsTool(FBIBaseTool):
    """Nationwide offense counts and rates for one year."""

    tool_name = 'fbi_get_national_statistics'
    tool_description = 'Nationwide US offense counts, rates and clearances for one year'

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        offense_type = arguments['offense_type']
        offense = self._offense(offense_type)
        year = self._year(arguments.get('year'))
        data, entities, path = self._summarized('national', offense, year, year)
        us = entities.get(US)
        if not us:
            raise FBIAPIError(f'No national data for {offense_type} in {year}')
        result = {
            'offense_type': offense_type,
            'year': year,
            'national_data': _annual(us, year),
            'metadata': _metadata(data, path),
        }
        if arguments.get('include_monthly'):
            result['monthly'] = _monthly(us, year)
        return result


class FBIGetStateStatisticsTool(FBIBaseTool):
    """State offense counts and rates, compared with the national rate."""

    tool_name = 'fbi_get_state_statistics'
    tool_description = 'Offense counts, rates and clearances for one US state, compared with the nation'

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        state = self._state(arguments['state'])
        offense_type = arguments['offense_type']
        offense = self._offense(offense_type)
        year = self._year(arguments.get('year'))
        data, entities, path = self._summarized(f'state/{state}', offense, year, year)
        name = STATE_NAMES[state]
        if name not in entities:
            raise FBIAPIError(f'No data for {name} ({offense_type}, {year})')
        state_data = _annual(entities[name], year)
        national_rate = _annual(entities.get(US, {}), year)['rate_per_100k']
        result = {
            'state': state,
            'state_name': name,
            'offense_type': offense_type,
            'year': year,
            'state_data': state_data,
            'comparison': {
                'national_rate_per_100k': national_rate,
                'percent_of_national': _pct(state_data['rate_per_100k'], national_rate),
            },
            'metadata': _metadata(data, path),
        }
        if arguments.get('include_monthly'):
            result['monthly'] = _monthly(entities[name], year)
        return result


class FBIGetAgencyStatisticsTool(FBIBaseTool):
    """Agency offense counts and rates, compared with its state and the nation."""

    tool_name = 'fbi_get_agency_statistics'
    tool_description = 'Offense counts, rates and clearances for one law enforcement agency (by ORI)'

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        ori = self._ori(arguments['ori'])
        offense_type = arguments['offense_type']
        offense = self._offense(offense_type)
        year = self._year(arguments.get('year'))
        data, entities, path = self._summarized(f'agency/{ori}', offense, year, year)
        state = ori[:2]
        state_name = STATE_NAMES.get(state)
        others = {US, state_name}
        agency_names = [n for n, s in entities.items() if n not in others and 'offenses' in s]
        if not agency_names:
            raise FBIAPIError(f'No data for agency {ori} ({offense_type}, {year}); '
                              'check the ORI with fbi_search_agencies')
        agency_name = agency_names[0]
        agency = _annual(entities[agency_name], year)
        state_rate = _annual(entities.get(state_name, {}), year)['rate_per_100k']
        national_rate = _annual(entities.get(US, {}), year)['rate_per_100k']
        return {
            'ori': ori,
            'agency_name': agency_name,
            'state': state,
            'offense_type': offense_type,
            'year': year,
            'agency_data': agency,
            'comparison': {
                'state_rate_per_100k': state_rate,
                'national_rate_per_100k': national_rate,
                'percent_of_state': _pct(agency['rate_per_100k'], state_rate),
                'percent_of_national': _pct(agency['rate_per_100k'], national_rate),
            },
            'metadata': _metadata(data, path),
        }


class FBISearchAgenciesTool(FBIBaseTool):
    """Find agencies (and their ORI codes) in a state."""

    tool_name = 'fbi_search_agencies'
    tool_description = 'List or search the law enforcement agencies in a US state to find ORI codes'

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        state = self._state(arguments['state'])
        name = (arguments.get('agency_name') or '').strip().lower()
        county = (arguments.get('county') or '').strip().lower()
        agency_type = arguments.get('agency_type') or 'all'
        if agency_type != 'all' and agency_type not in AGENCY_TYPES:
            raise ValueError(f'Unsupported agency_type {agency_type!r}')
        limit = max(1, min(int(arguments.get('limit') or 20), 500))

        matches = []
        for a in self._state_agencies(state):
            if name and name not in (a.get('agency_name') or '').lower():
                continue
            if county and county not in (a.get('counties') or '').lower():
                continue
            if agency_type != 'all' and a.get('agency_type_name') not in AGENCY_TYPES[agency_type]:
                continue
            matches.append({
                'ori': a['ori'],
                'agency_name': a.get('agency_name'),
                'agency_type': a.get('agency_type_name'),
                'county': a.get('counties'),
                'state': a.get('state_abbr') or state,
                'state_name': a.get('state_name') or STATE_NAMES[state],
                'is_nibrs': bool(a.get('is_nibrs')),
                'nibrs_start_date': a.get('nibrs_start_date'),
                'latitude': a.get('latitude'),
                'longitude': a.get('longitude'),
            })
        matches.sort(key=lambda m: (m['agency_name'] or ''))
        return {
            'state': state,
            'search_query': arguments.get('agency_name') or '',
            'total_results': len(matches),
            'agencies': matches[:limit],
        }


class FBIGetOffenseDataTool(FBIBaseTool):
    """NIBRS victim / offender / weapon / location breakdowns for an offense."""

    tool_name = 'fbi_get_offense_data'
    tool_description = 'NIBRS incident breakdowns (victims, offenders, weapons, locations) for an offense'

    @staticmethod
    def _clean(breakdown: Any, top: int) -> Any:
        """Drop zero buckets and sort descending; keep the top N."""
        if not isinstance(breakdown, dict):
            return breakdown
        items = [(k, v) for k, v in breakdown.items() if isinstance(v, (int, float)) and v]
        items.sort(key=lambda kv: kv[1], reverse=True)
        return dict(items[:top])

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        offense_type = arguments['offense_type']
        code = self._offense(offense_type, NIBRS_OFFENSES)
        year = self._year(arguments.get('year'))
        state = arguments.get('state')
        top = max(1, min(int(arguments.get('top_n') or 10), 100))
        if state:
            state = self._state(state)
            scope_path, entity = f'nibrs/state/{state}/{code}', STATE_NAMES[state]
        else:
            scope_path, entity = f'nibrs/national/{code}', US
        window = {'from': f'01-{year}', 'to': f'12-{year}'}

        counts = self._get(scope_path, dict(window, type='counts'))
        entities = _series_entities(counts if isinstance(counts, dict) else {})
        totals = _annual(entities.get(entity, {}), year)
        result = {
            'offense_type': offense_type,
            'nibrs_offense_code': code,
            'year': year,
            'scope': 'state' if state else 'national',
            'total_offenses': totals['total_incidents'],
            'rate_per_100k': totals['rate_per_100k'],
            'nibrs_population_coverage_pct': totals['population_coverage_pct'],
            'metadata': _metadata(counts if isinstance(counts, dict) else {}, scope_path),
        }
        if state:
            result['state'] = state
        if arguments.get('include_subcategories', True):
            detail = self._get(scope_path, dict(window, type='totals'))
            if isinstance(detail, dict):
                result['breakdown'] = {
                    group: {k: self._clean(v, top) for k, v in (detail.get(group) or {}).items()}
                    for group in ('victim', 'offender', 'offense')
                }
        return result


class FBIGetParticipationRateTool(FBIBaseTool):
    """Share of the population covered by agencies reporting to the UCR programme."""

    tool_name = 'fbi_get_participation_rate'
    tool_description = 'Population covered by agencies reporting crime data, nationally or for a state'

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        year = self._year(arguments.get('year'))
        state = arguments.get('state')
        if state:
            state = self._state(state)
            scope_path, entity = f'state/{state}', STATE_NAMES[state]
        else:
            scope_path, entity = 'national', US
        # Coverage is published alongside the summarized offense series; violent crime
        # is used because every reporting agency reports it.
        data, entities, path = self._summarized(scope_path, 'V', year, year)
        series = entities.get(entity)
        if not series:
            raise FBIAPIError(f'No participation data for {entity} in {year}')
        annual = _annual(series, year)
        cov = {k: v for k, v in (series.get('coverage_pct') or {}).items() if _month_year(k) == year}
        part = series.get('participated_population') or {}
        result = {
            'scope': 'state' if state else 'national',
            'year': year,
            'participation_data': {
                'total_population': annual['population'],
                'average_participated_population': annual['participated_population'],
                'average_population_coverage_pct': annual['population_coverage_pct'],
                'months_reported': annual['months_reported'],
            },
            'monthly': [{'month': f'{year}-{k[:2]}', 'population_coverage_pct': v,
                         'participated_population': part.get(k)}
                        for k, v in sorted(cov.items(), key=lambda kv: int(kv[0][:2]))],
            'metadata': _metadata(data, path),
        }
        if state:
            result['state'] = state
        return result


class FBIGetAgencyDetailsTool(FBIBaseTool):
    """Directory entry for an agency plus its police-employee counts."""

    tool_name = 'fbi_get_agency_details'
    tool_description = 'Directory details and staffing (officers, civilians) for one agency by ORI'

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        ori = self._ori(arguments['ori'])
        state = ori[:2]
        if state not in STATE_NAMES:
            raise ValueError(f'ORI {ori} does not start with a supported state code')
        year = self._year(arguments.get('year'))
        agency = next((a for a in self._state_agencies(state) if a.get('ori') == ori), None)
        if agency is None:
            raise FBIAPIError(f'Agency {ori} is not in the FBI agency list for {state}; '
                              'find valid ORIs with fbi_search_agencies')
        result = {
            'ori': ori,
            'agency_name': agency.get('agency_name'),
            'agency_type': agency.get('agency_type_name'),
            'location': {
                'state': state,
                'state_name': agency.get('state_name') or STATE_NAMES[state],
                'county': agency.get('counties'),
                'latitude': agency.get('latitude'),
                'longitude': agency.get('longitude'),
            },
            'reporting_status': {
                'is_nibrs': bool(agency.get('is_nibrs')),
                'nibrs_start_date': agency.get('nibrs_start_date'),
            },
            'personnel': None,
        }
        try:
            pe = self._get(f'pe/{state}/{ori}', {'from': str(year), 'to': str(year)})
        except FBIAPIError as e:
            result['personnel_error'] = str(e)
            return result
        y = str(year)
        actuals = (pe or {}).get('actuals') or {}
        val = lambda label: (actuals.get(label) or {}).get(y)
        if any(val(k) is not None for k in ('Male Officers', 'Female Officers')):
            officers = (val('Male Officers') or 0) + (val('Female Officers') or 0)
            civilians = (val('Male Civilians') or 0) + (val('Female Civilians') or 0)
            result['personnel'] = {
                'year': year,
                'male_officers': val('Male Officers'),
                'female_officers': val('Female Officers'),
                'total_officers': officers,
                'male_civilians': val('Male Civilians'),
                'female_civilians': val('Female Civilians'),
                'total_civilians': civilians,
                'total_employees': officers + civilians,
                'employees_per_1000': ((pe.get('rates') or {})
                                       .get('Law Enforcement Employees per 1,000 People') or {}).get(y),
                'population_served': ((pe.get('populations') or {})
                                      .get('Participated Population') or {}).get(y),
            }
        return result


class FBIGetCrimeTrendTool(FBIBaseTool):
    """Year-by-year series and trend statistics for an offense."""

    tool_name = 'fbi_get_crime_trend'
    tool_description = 'Year-by-year offense trend for the nation, a state or an agency'

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        offense_type = arguments['offense_type']
        offense = self._offense(offense_type)
        start_year = self._year(arguments['start_year'], 'start_year')
        end_year = self._year(arguments['end_year'], 'end_year')
        if start_year > end_year:
            raise ValueError('start_year must be less than or equal to end_year')
        per_capita = arguments.get('per_capita', True)

        if arguments.get('ori'):
            ori = self._ori(arguments['ori'])
            scope, scope_path = 'agency', f'agency/{ori}'
        elif arguments.get('state'):
            state = self._state(arguments['state'])
            scope, scope_path = 'state', f'state/{state}'
        else:
            scope, scope_path = 'national', 'national'
        data, entities, path = self._summarized(scope_path, offense, start_year, end_year)

        if scope == 'national':
            entity = entities.get(US)
        elif scope == 'state':
            entity = entities.get(STATE_NAMES[state])
        else:
            names = [n for n, s in entities.items()
                     if n not in (US, STATE_NAMES.get(ori[:2])) and 'offenses' in s]
            entity = entities[names[0]] if names else None
        if not entity:
            raise FBIAPIError(f'No {scope} data for {offense_type} in {start_year}-{end_year}')

        metric = 'rate_per_100k' if per_capita else 'total_incidents'
        series = []
        for year in range(start_year, end_year + 1):
            annual = _annual(entity, year)
            if not annual['months_reported']:
                continue
            value, prev = annual[metric], (series[-1][metric] if series else None)
            series.append({
                'year': year,
                'total_incidents': annual['total_incidents'],
                'rate_per_100k': annual['rate_per_100k'],
                'months_reported': annual['months_reported'],
                'percent_change': (round((value - prev) / prev * 100, 2)
                                   if value is not None and prev else None),
            })
        if not series:
            raise FBIAPIError(f'No data for {offense_type} in {start_year}-{end_year}')

        values = [s[metric] for s in series if s[metric] is not None]
        first, last = (values[0], values[-1]) if values else (None, None)
        overall = round((last - first) / first * 100, 2) if first else 0.0
        changes = [abs(s['percent_change']) for s in series[1:] if s['percent_change'] is not None]
        avg_change = sum(changes) / len(changes) if changes else 0.0
        by_metric = [s for s in series if s[metric] is not None]
        return {
            'offense_type': offense_type,
            'scope': scope,
            'metric': metric,
            'time_period': {'start_year': start_year, 'end_year': end_year,
                            'years_analyzed': len(series)},
            'time_series': series,
            'trend_analysis': {
                'overall_change': overall,
                'average_annual_change': round(overall / (len(series) - 1), 2) if len(series) > 1 else 0.0,
                'direction': 'increasing' if overall > 5 else 'decreasing' if overall < -5 else 'stable',
                'peak_year': max(by_metric, key=lambda s: s[metric])['year'] if by_metric else None,
                'lowest_year': min(by_metric, key=lambda s: s[metric])['year'] if by_metric else None,
                'volatility': 'high' if avg_change > 10 else 'medium' if avg_change > 5 else 'low',
            },
            'metadata': _metadata(data, path),
        }


class FBICompareStatesTool(FBIBaseTool):
    """Rank several states on one offense for one year."""

    tool_name = 'fbi_compare_states'
    tool_description = 'Compare offense rates across several US states for one year'

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        states = [self._state(s) for s in arguments['states']]
        if len(set(states)) < 2:
            raise ValueError('Provide at least two different states')
        offense_type = arguments['offense_type']
        offense = self._offense(offense_type)
        year = self._year(arguments.get('year'))
        per_capita = arguments.get('per_capita', True)

        rows, national, errors, meta = [], None, {}, {}
        for state in dict.fromkeys(states):
            try:
                data, entities, path = self._summarized(f'state/{state}', offense, year, year)
            except FBIAPIError as e:
                errors[state] = str(e)
                continue
            meta = meta or _metadata(data, 'summarized/state/{state}/' + offense)
            if national is None and US in entities:
                national = _annual(entities[US], year)['rate_per_100k']
            annual = _annual(entities.get(STATE_NAMES[state], {}), year)
            if not annual['months_reported']:
                errors[state] = f'No data for {state} in {year}'
                continue
            rows.append({
                'state': state,
                'state_name': STATE_NAMES[state],
                'total_incidents': annual['total_incidents'],
                'rate_per_100k': annual['rate_per_100k'],
                'state_population': annual['population'],
                'population_coverage_pct': annual['population_coverage_pct'],
                'percent_of_national': None,
            })
        if not rows:
            raise FBIAPIError(f'No data for any of the requested states: {errors}')

        for row in rows:
            row['percent_of_national'] = _pct(row['rate_per_100k'], national)
        key = 'rate_per_100k' if per_capita else 'total_incidents'
        rows.sort(key=lambda r: r[key] or 0, reverse=True)
        for rank, row in enumerate(rows, 1):
            row['rank'] = rank
        values = [r[key] or 0 for r in rows]
        result = {
            'offense_type': offense_type,
            'year': year,
            'comparison_type': 'per_capita' if per_capita else 'absolute',
            'states_compared': rows,
            'comparison_summary': {
                'highest_state': rows[0]['state'],
                'lowest_state': rows[-1]['state'],
                'range': round(max(values) - min(values), 2),
                'average_of_compared': round(sum(values) / len(values), 2),
            },
            'metadata': meta,
        }
        if arguments.get('include_national_average', True):
            result['national_reference'] = {'rate_per_100k': national}
        if errors:
            result['errors'] = errors
        return result


FBI_TOOLS = {cls.tool_name: cls for cls in (
    FBIGetNationalStatisticsTool, FBIGetStateStatisticsTool, FBIGetAgencyStatisticsTool,
    FBISearchAgenciesTool, FBIGetOffenseDataTool, FBIGetParticipationRateTool,
    FBIGetAgencyDetailsTool, FBIGetCrimeTrendTool, FBICompareStatesTool)}
