"""
SAJHA MCP Server — one client for SDMX 2.1 REST data services (Tool Quality §12.3).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

The ECB, the IMF, the BIS, Eurostat, the OECD and the ABS all answer
the same SDMX 2.1 REST pattern:

    {base}/data/{flow}/{key}?startPeriod=..&endPeriod=..&lastNObservations=N

They differ in two settings, which a :class:`SdmxHost` profile records:

* the flow-reference syntax: a bare id (``EXR``) or ``AGENCY,ID,VERSION`` (``IMF.RES,WEO``);
* how SDMX-CSV is selected: a ``format=`` value (ECB ``csvdata``) or an ``Accept`` header
  (IMF ``application/vnd.sdmx.data+csv;version=1.0.0``).

Every fetch goes through the outbound fetch guard and HTTP proxy (``sajha/core/outbound.py``),
and only to the profile's own base URL, so a tool cannot be pointed at another host. An empty
answer, including the 404 ``NoRecordsFound`` some servers send, is "no data", not an error.
SDMX-CSV is the wire format; :func:`parse_sdmx_json` reads SDMX-JSON for a host that has no CSV.
Structure queries (dataflows, a flow's dimensions and codes) are cached per process for an hour.
"""

from __future__ import annotations

import csv
import io
import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sajha.core import outbound

USER_AGENT = 'SAJHA-MCP-Server (SDMX client)'
_STRUCTURE_TTL = 3600.0
_MAX_BYTES = 20 * 1024 * 1024
_MONTHLY = re.compile(r'^(\d{4})-M(\d{2})$')       # IMF: 2026-M08 -> 2026-08


class SdmxError(ValueError):
    """An SDMX service answered with an error (or could not be reached)."""


@dataclass(frozen=True)
class SdmxHost:
    """How one SDMX 2.1 REST service is addressed."""
    name: str
    base_url: str                      # up to, not including, /data or /dataflow
    agency: str = ''                   # default agency for the AGENCY,ID,VERSION syntax
    agency_flow_ref: bool = False      # True: flow reference is AGENCY,ID[,VERSION]
    csv_format: str = ''               # format=<value> selects SDMX-CSV (ECB: csvdata)
    csv_accept: str = ''               # Accept header that selects SDMX-CSV (IMF, BIS, ABS)
    source: str = ''                   # attribution put on every result
    extra_params: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)

    def flow_ref(self, flow: str, agency: Optional[str] = None, version: Optional[str] = None) -> str:
        flow = str(flow).strip()
        if not self.agency_flow_ref or ',' in flow:
            return flow
        ref = f"{agency or self.agency},{flow}"
        return f"{ref},{version}" if version else ref


HOSTS: Dict[str, SdmxHost] = {
    'ecb': SdmxHost(
        name='ecb', base_url='https://data-api.ecb.europa.eu/service',
        csv_format='csvdata', source='Source: ECB Data Portal (data-api.ecb.europa.eu)'),
    'imf': SdmxHost(
        name='imf', base_url='https://api.imf.org/external/sdmx/2.1',
        agency='IMF.STA', agency_flow_ref=True,
        csv_accept='application/vnd.sdmx.data+csv;version=1.0.0',
        source='Source: IMF data portal (api.imf.org SDMX 2.1)'),
}


def register_host(host: SdmxHost) -> SdmxHost:
    """Add (or replace) a host profile; phase 8.2 sources register theirs here."""
    HOSTS[host.name] = host
    return host


def host(name: str) -> SdmxHost:
    try:
        return HOSTS[name]
    except KeyError:
        raise SdmxError(f"Unknown SDMX host profile: {name}")


# ── HTTP ─────────────────────────────────────────────────────────────────────

def _get(h: SdmxHost, path: str, params: List[Tuple[str, str]], accept: str, timeout: float):
    url = f"{h.base_url}/{path.lstrip('/')}"
    if not url.startswith(h.base_url + '/'):          # pinned: never another host
        raise SdmxError(f"{h.name}: refused path {path!r}")
    headers = {'User-Agent': USER_AGENT, 'Accept': accept}
    try:
        return outbound.request('GET', url, params=params, headers=headers, timeout=timeout,
                                max_bytes=_MAX_BYTES)
    except outbound.FetchTimeout:
        raise SdmxError(f"{h.name}: the SDMX service did not answer within {timeout:g} s")
    except (outbound.Refused, outbound.FetchError) as e:
        raise SdmxError(f"{h.name}: could not reach the SDMX service: {e}")


def _no_records(status: int, text: str) -> bool:
    if status == 404:
        return True        # ECB, BIS and ABS answer an empty selection with 404 (NoRecordsFound)
    low = (text or '')[:2000].lower()
    return 'norecordsfound' in low or 'no records found' in low or 'no results found' in low


# ── data ─────────────────────────────────────────────────────────────────────

def fetch(host_name: str, flow: str, key: str = '', *, agency: Optional[str] = None,
          version: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None,
          last_n: Optional[int] = None, first_n: Optional[int] = None,
          params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> Dict[str, Any]:
    """Fetch one data query and return
    ``{host, flow, key, source, series: [{key, dimensions, attributes, observations}]}``,
    observations ``[{period, value}]`` oldest first. No data gives ``series: []``."""
    h = host(host_name)
    ref = h.flow_ref(flow, agency, version)
    q: List[Tuple[str, str]] = list(h.extra_params)
    if start:
        q.append(('startPeriod', str(start)))
    if end:
        q.append(('endPeriod', str(end)))
    if last_n:
        q.append(('lastNObservations', str(int(last_n))))
    if first_n:
        q.append(('firstNObservations', str(int(first_n))))
    for k, v in (params or {}).items():
        if v is not None:
            q.append((str(k), str(v)))
    accept = h.csv_accept or 'text/csv'
    if h.csv_format:
        q.append(('format', h.csv_format))
    path = f"data/{ref}/{key}" if key else f"data/{ref}"
    r = _get(h, path, q, accept, timeout)
    result = {'host': h.name, 'flow': ref, 'key': key, 'source': h.source, 'series': []}
    if r.status_code >= 400:
        if _no_records(r.status_code, r.text):
            return result
        raise SdmxError(f"{h.name}: HTTP {r.status_code} for {ref}/{key or '(all)'}: {_brief(r.text)}")
    text = r.text
    if not text.strip() or _no_records(200, text[:200]):
        return result
    ctype = (r.headers.get('content-type') or '').lower()
    if 'json' in ctype or text.lstrip().startswith('{'):
        import json
        result['series'] = parse_sdmx_json(json.loads(text))
    else:
        result['series'] = parse_sdmx_csv(text)
    return result


def _brief(text: str) -> str:
    t = re.sub(r'<[^>]+>', ' ', text or '')
    return re.sub(r'\s+', ' ', t).strip()[:200] or 'no detail'


def _value(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() in ('nan', 'na', '.', 'null'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def normalise_period(period: str) -> str:
    m = _MONTHLY.match(period or '')
    return f"{m.group(1)}-{m.group(2)}" if m else (period or '')


def parse_sdmx_csv(text: str) -> List[Dict[str, Any]]:
    """SDMX-CSV (1.0, and the ECB's csvdata flavour): the dimension columns are those between
    the first column (DATAFLOW or KEY) and TIME_PERIOD; columns after OBS_VALUE are attributes."""
    reader = csv.DictReader(io.StringIO(text))
    cols = reader.fieldnames or []
    if 'TIME_PERIOD' not in cols or 'OBS_VALUE' not in cols:
        raise SdmxError('SDMX-CSV without TIME_PERIOD/OBS_VALUE columns')
    first = 1 if cols and cols[0] in ('DATAFLOW', 'KEY', 'STRUCTURE', 'STRUCTURE_ID') else 0
    if cols[first:first + 1] == ['STRUCTURE_ID']:      # SDMX-CSV 2.0: STRUCTURE, STRUCTURE_ID, ACTION
        first += 2 if 'ACTION' in cols else 1
    dims = cols[first:cols.index('TIME_PERIOD')]
    attrs = [c for c in cols[cols.index('OBS_VALUE') + 1:]]
    series: Dict[str, Dict[str, Any]] = {}
    for row in reader:
        if not (row.get('TIME_PERIOD') or '').strip():
            continue        # the IMF answers an empty selection with one blank row
        key = '.'.join(row.get(d) or '' for d in dims)
        s = series.get(key)
        if s is None:
            s = series[key] = {
                'key': key,
                'dimensions': {d: row.get(d) for d in dims},
                'attributes': {a: row.get(a) for a in attrs if row.get(a) not in (None, '')},
                'observations': [],
            }
        obs = {'period': normalise_period(row.get('TIME_PERIOD') or ''), 'value': _value(row.get('OBS_VALUE'))}
        status = (row.get('OBS_FLAG') or row.get('OBS_STATUS') or '').strip()
        if status:
            obs['status'] = status      # Eurostat OBS_FLAG (p provisional, e estimated) or SDMX OBS_STATUS
        s['observations'].append(obs)
    out = list(series.values())
    for s in out:
        s['observations'].sort(key=lambda o: o['period'])
    return out


def parse_sdmx_json(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """SDMX-JSON 1.0 data message (series keyed ``"0:1:0"``, observations keyed by time index)."""
    body = data.get('data', data)
    sets = body.get('dataSets') or []
    structure = body.get('structure') or (body.get('structures') or [{}])[0]
    dims = (structure.get('dimensions') or {})
    sdims = dims.get('series') or []
    odims = dims.get('observation') or []
    times = next((d.get('values') or [] for d in odims if d.get('id') == 'TIME_PERIOD'),
                 (odims[0].get('values') or []) if odims else [])
    sattrs = (structure.get('attributes') or {}).get('series') or []
    out: List[Dict[str, Any]] = []
    if not sets:
        return out
    for skey, sval in (sets[0].get('series') or {}).items():
        idx = [int(i) for i in skey.split(':')] if skey else []
        dvals = {}
        for pos, d in zip(idx, sdims):
            vals = d.get('values') or []
            dvals[d.get('id')] = vals[pos].get('id') if pos < len(vals) else None
        attributes = {}
        for pos, a in zip(sval.get('attributes') or [], sattrs):
            vals = a.get('values') or []
            if pos is not None and pos < len(vals):
                attributes[a.get('id')] = vals[pos].get('name') or vals[pos].get('id')
        obs = []
        for t, ov in (sval.get('observations') or {}).items():
            ti = int(t)
            period = (times[ti].get('id') if ti < len(times) else '') or ''
            obs.append({'period': normalise_period(period), 'value': _value(ov[0] if ov else None)})
        obs.sort(key=lambda o: o['period'])
        out.append({'key': '.'.join(str(dvals.get(d.get('id')) or '') for d in sdims),
                    'dimensions': dvals, 'attributes': attributes, 'observations': obs})
    return out


def one_series(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The single series of a fully specified key, or None when there was no data."""
    series = result.get('series') or []
    return series[0] if series else None


_FREQ = {'A': 'Annual', 'S': 'Half-yearly', 'Q': 'Quarterly', 'M': 'Monthly', 'W': 'Weekly',
         'D': 'Daily', 'B': 'Daily (business days)'}
_TITLE_ATTRS = ('TITLE', 'SERIES_NAME', 'TITLE_COMPL')
_UNIT_ATTRS = ('UNIT', 'UNIT_MEASURE')


def fetch_series(host_name: str, flow: str, key: str, *, start: Optional[str] = None,
                 end: Optional[str] = None, last_n: Optional[int] = None,
                 agency: Optional[str] = None, timeout: float = 30.0) -> Dict[str, Any]:
    """One fully specified series in the flat shape the central-bank tools return:
    ``{flow, key, series_code, label, unit, unit_multiplier, frequency, source,
    observation_count, observations: [{date, value}]}`` oldest first. No data gives zero
    observations and a ``note``; an unknown series raises :class:`SdmxError`."""
    result = fetch(host_name, flow, key, start=start, end=end, last_n=last_n, agency=agency,
                   timeout=timeout)
    s = one_series(result)
    attrs = (s or {}).get('attributes') or {}
    dims = (s or {}).get('dimensions') or {}
    freq = dims.get('FREQ') or dims.get('FREQUENCY') or (key.split('.')[0] if key else '')
    obs = [{'date': o['period'], 'value': o['value']} for o in (s or {}).get('observations', [])]
    out = {
        'flow': result['flow'], 'key': key, 'series_code': f"{flow}.{key}",
        'label': next((attrs[a] for a in _TITLE_ATTRS if attrs.get(a)), f"{flow}.{key}"),
        'unit': next((attrs[a] for a in _UNIT_ATTRS if attrs.get(a)), None),
        'unit_multiplier': attrs.get('UNIT_MULT'),          # ECB: power of ten applied to the unit
        'frequency': _FREQ.get(freq, freq or None),
        'source': result['source'],
        'observation_count': len(obs),
        'observations': obs,
    }
    if not obs:
        out['note'] = 'The service returned no observations for this series and period.'
    return out


# ── structure ────────────────────────────────────────────────────────────────

_NS = {
    'str': 'http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure',
    'com': 'http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common',
}
_cache: Dict[Tuple, Tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _cached(key: Tuple, build):
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < _STRUCTURE_TTL:
            return hit[1]
    value = build()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _structure(h: SdmxHost, path: str, timeout: float) -> ET.Element:
    r = _get(h, path, [], 'application/vnd.sdmx.structure+xml;version=2.1, application/xml', timeout)
    if r.status_code >= 400:
        raise SdmxError(f"{h.name}: HTTP {r.status_code} for {path}: {_brief(r.text)}")
    try:
        return ET.fromstring(r.content)
    except ET.ParseError as e:
        raise SdmxError(f"{h.name}: unreadable structure message for {path}: {e}")


def _name(el: ET.Element) -> str:
    for n in el.findall('com:Name', _NS):
        if n.get('{http://www.w3.org/XML/1998/namespace}lang', 'en') == 'en':
            return (n.text or '').strip()
    n = el.find('com:Name', _NS)
    return (n.text or '').strip() if n is not None else ''


def dataflows(host_name: str, timeout: float = 60.0) -> List[Dict[str, str]]:
    """Every dataflow the host publishes: agency, id, version, name."""
    h = host(host_name)

    def build():
        root = _structure(h, 'dataflow', timeout)
        return [{'agency': df.get('agencyID', ''), 'id': df.get('id', ''),
                 'version': df.get('version', ''), 'name': _name(df)}
                for df in root.iter(f"{{{_NS['str']}}}Dataflow")]
    return _cached(('dataflows', h.name), build)


def flow_structure(host_name: str, flow: str, agency: Optional[str] = None,
                   timeout: float = 60.0) -> Dict[str, Any]:
    """A dataflow's dimensions in key order, each with its codes (id and name)."""
    h = host(host_name)
    ref = h.flow_ref(flow, agency)
    parts = ref.split(',')
    path = (f"dataflow/{parts[0]}/{parts[1]}/{parts[2] if len(parts) > 2 else 'latest'}"
            if len(parts) > 1 else f"dataflow/all/{ref}/latest")

    def build():
        root = _structure(h, f"{path}?references=all", timeout)
        codelists = {}
        for cl in root.iter(f"{{{_NS['str']}}}Codelist"):
            codelists[cl.get('id')] = [{'id': c.get('id'), 'name': _name(c)}
                                       for c in cl.findall('str:Code', _NS)]
        concept_codelist = {}         # a concept's core representation, when the dimension has none
        for scheme in root.iter(f"{{{_NS['str']}}}ConceptScheme"):
            for c in scheme.findall('str:Concept', _NS):
                ref_el = c.find('str:CoreRepresentation/str:Enumeration/Ref', _NS)
                if ref_el is not None:
                    concept_codelist[(scheme.get('id'), c.get('id'))] = ref_el.get('id')
        dims = []
        dim_list = next(iter(root.iter(f"{{{_NS['str']}}}DimensionList")), None)
        for d in (dim_list.findall('str:Dimension', _NS) if dim_list is not None else []):
            ref_el = d.find('str:LocalRepresentation/str:Enumeration/Ref', _NS)
            cl = ref_el.get('id') if ref_el is not None else None
            if cl is None:
                concept = d.find('str:ConceptIdentity/Ref', _NS)
                if concept is not None:
                    cl = concept_codelist.get((concept.get('maintainableParentID'), concept.get('id')))
            dims.append({'id': d.get('id'), 'position': int(d.get('position') or len(dims) + 1),
                         'codelist': cl, 'codes': codelists.get(cl, [])})
        dims.sort(key=lambda x: x['position'])
        df = next(iter(root.iter(f"{{{_NS['str']}}}Dataflow")), None)
        return {'flow': ref, 'name': _name(df) if df is not None else '', 'dimensions': dims}
    return _cached(('structure', h.name, ref), build)
