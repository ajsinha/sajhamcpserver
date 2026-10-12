"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Natural hazard tools (tool folder ``hazards``; Open Data Tools §4, L36).

* Earthquakes come from the USGS FDSN event service and its GeoJSON summary feeds
  (``earthquake.usgs.gov``): keyless, public domain, credit "U.S. Geological Survey".
* Active fires come from NASA FIRMS (``firms.modaps.eosdis.nasa.gov/api/area``), which needs a free
  MAP_KEY in the environment variable ``FIRMS_MAP_KEY`` (5,000 transactions per 10 minutes). NASA
  data carry no use restriction; NASA material may not imply NASA's endorsement.
* GDACS disaster alerts are not offered: its terms grant no licence, and the owner keeps it off
  until legal approves (Open Data Tools §6). Weather is not offered (Open-Meteo dropped).

Every fetch goes through the outbound fetch guard (``sajha/core/outbound.py``); results are cached
(``cache_ttl`` in each config).
"""

from __future__ import annotations

import csv
import io
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sajha.tools.impl.open_data_common import OpenDataTool, fetch, get_json, take_slot
from sajha.tools.impl.us_treasury_tools import parse_date

USGS = 'https://earthquake.usgs.gov'
USGS_SOURCE = 'U.S. Geological Survey (earthquake.usgs.gov)'
FIRMS = 'https://firms.modaps.eosdis.nasa.gov/api/area/csv'
FIRMS_SOURCE = 'NASA FIRMS (Fire Information for Resource Management System); no NASA endorsement implied'
FIRMS_KEY_ENV = 'FIRMS_MAP_KEY'
FIRMS_SOURCES = ('VIIRS_NOAA20_NRT', 'VIIRS_NOAA21_NRT', 'VIIRS_SNPP_NRT', 'MODIS_NRT', 'LANDSAT_NRT')


def _iso_ms(ms: Any) -> Optional[str]:
    if ms in (None, ''):
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _quake(feature: Dict[str, Any]) -> Dict[str, Any]:
    p = feature.get('properties') or {}
    coords = (feature.get('geometry') or {}).get('coordinates') or [None, None, None]
    coords = list(coords) + [None] * (3 - len(coords))
    return {
        'id': feature.get('id'), 'time': _iso_ms(p.get('time')), 'magnitude': p.get('mag'),
        'magnitude_type': p.get('magType'), 'place': p.get('place'),
        'latitude': coords[1], 'longitude': coords[0], 'depth_km': coords[2],
        'alert': p.get('alert'), 'tsunami_flag': bool(p.get('tsunami')), 'significance': p.get('sig'),
        'felt_reports': p.get('felt'), 'status': p.get('status'), 'url': p.get('url'),
    }


QUAKE_UNITS = ('magnitude on the reported scale (magnitude_type); depth_km in kilometres; time in UTC; '
               'alert is the USGS PAGER level (green, yellow, orange, red)')


def _bbox(value: Any, field: str = 'bbox') -> List[float]:
    if isinstance(value, str):
        value = [v for v in re.split(r'[,\s]+', value.strip()) if v]
    try:
        west, south, east, north = (float(v) for v in value)
    except (TypeError, ValueError):
        raise ValueError(f'{field} must be four numbers: west, south, east, north (degrees)')
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= north <= 90):
        raise ValueError(f'{field} is out of range: longitudes -180 to 180, latitudes -90 to 90, south <= north')
    return [west, south, east, north]


class HazardsEarthquakesTool(OpenDataTool):
    """hazards_earthquakes: earthquakes in a period, by region or around a point (USGS)."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        to = parse_date(arguments['to'], 'to') if arguments.get('to') else date.today()
        frm = parse_date(arguments['from'], 'from') if arguments.get('from') else to - timedelta(days=7)
        if frm > to:
            raise ValueError('from is after to')
        params: Dict[str, Any] = {
            'format': 'geojson', 'starttime': frm.isoformat(), 'endtime': (to + timedelta(days=1)).isoformat(),
            'minmagnitude': arguments.get('min_magnitude', 4.5), 'limit': int(arguments.get('limit') or 100),
            'orderby': 'magnitude' if arguments.get('order') == 'magnitude' else 'time'}
        if arguments.get('latitude') is not None or arguments.get('longitude') is not None:
            if arguments.get('latitude') is None or arguments.get('longitude') is None:
                raise ValueError('give both latitude and longitude (and radius_km) to search around a point')
            params.update({'latitude': arguments['latitude'], 'longitude': arguments['longitude'],
                           'maxradiuskm': arguments.get('radius_km', 500)})
        elif arguments.get('bbox') is not None:
            west, south, east, north = _bbox(arguments['bbox'])
            params.update({'minlongitude': west, 'minlatitude': south, 'maxlongitude': east, 'maxlatitude': north})
        body = get_json('USGS earthquake service', f'{USGS}/fdsnws/event/1/query', params=params)
        quakes = [_quake(f) for f in body.get('features') or []]
        return {'from': frm.isoformat(), 'to': to.isoformat(), 'min_magnitude': params['minmagnitude'],
                'units': QUAKE_UNITS, 'count': len(quakes), 'truncated': len(quakes) >= params['limit'],
                'earthquakes': quakes, 'source': USGS_SOURCE}


class HazardsSignificantEarthquakesTool(OpenDataTool):
    """hazards_significant_earthquakes: the USGS significant-earthquakes feed for the last hour to month."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        window = arguments.get('window') or 'week'
        if window not in ('hour', 'day', 'week', 'month'):
            raise ValueError('window must be hour, day, week or month')
        body = get_json('USGS earthquake feed', f'{USGS}/earthquakes/feed/v1.0/summary/significant_{window}.geojson')
        quakes = [_quake(f) for f in body.get('features') or []]
        quakes.sort(key=lambda q: q['time'] or '', reverse=True)
        meta = body.get('metadata') or {}
        return {'window': window, 'generated': _iso_ms(meta.get('generated')), 'units': QUAKE_UNITS,
                'count': len(quakes), 'earthquakes': quakes, 'source': USGS_SOURCE}


_VIIRS_CONFIDENCE = {'l': 'low', 'n': 'nominal', 'h': 'high'}


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class HazardsActiveFiresTool(OpenDataTool):
    """hazards_active_fires: satellite fire detections in a bounding box (NASA FIRMS, MAP_KEY)."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        key = os.environ.get(FIRMS_KEY_ENV, '').strip()
        if not key:
            raise ValueError(f'NASA FIRMS needs a free MAP_KEY: environment variable {FIRMS_KEY_ENV} is not set')
        source = arguments.get('source') or 'VIIRS_NOAA20_NRT'
        if source not in FIRMS_SOURCES:
            raise ValueError(f'source must be one of {", ".join(FIRMS_SOURCES)}')
        region = arguments.get('bbox', 'world')
        area = 'world' if region == 'world' else ','.join(f'{v:g}' for v in _bbox(region))
        days = int(arguments.get('days') or 1)
        if not 1 <= days <= 5:
            raise ValueError('days must be 1 to 5')
        path = f'{FIRMS}/{key}/{source}/{area}/{days}'
        if arguments.get('date'):
            path += '/' + parse_date(arguments['date'], 'date').isoformat()
        take_slot('opendata:firms:requests', 5000, 600.0, 10.0, 'NASA FIRMS')
        r = fetch('NASA FIRMS', 'GET', path, accept='text/csv', timeout=60)
        text = r.text
        if not text.strip() or 'latitude' not in text.split('\n', 1)[0]:
            msg = text.strip()[:200]
            if 'MAP_KEY' in msg:
                raise ValueError(f'NASA FIRMS refused the MAP_KEY in {FIRMS_KEY_ENV}: {msg}')
            raise ValueError(f'NASA FIRMS answered without data: {msg or "an empty response"}')
        limit = int(arguments.get('limit') or 500)
        min_conf = arguments.get('min_confidence')
        fires, total = [], 0
        for row in csv.DictReader(io.StringIO(text)):
            conf_raw = (row.get('confidence') or '').strip()
            conf = _VIIRS_CONFIDENCE.get(conf_raw.lower(), conf_raw)
            if min_conf and not _meets(conf, min_conf):
                continue
            total += 1
            if len(fires) >= limit:
                continue
            t = (row.get('acq_time') or '').strip().zfill(4)
            fires.append({
                'latitude': _num(row.get('latitude')), 'longitude': _num(row.get('longitude')),
                'acquired': f'{row.get("acq_date")}T{t[:2]}:{t[2:]}Z' if row.get('acq_date') else None,
                'satellite': row.get('satellite'), 'instrument': row.get('instrument'), 'confidence': conf,
                'frp_mw': _num(row.get('frp')),
                'brightness_k': _num(row.get('bright_ti4') or row.get('brightness')),
                'day_night': {'D': 'day', 'N': 'night'}.get((row.get('daynight') or '').strip(), row.get('daynight')),
            })
        return {'source_product': source, 'area': area, 'days': days,
                'units': 'frp_mw: fire radiative power in megawatts; brightness_k: brightness temperature in kelvin; '
                         'acquired in UTC; confidence low/nominal/high (VIIRS) or percent (MODIS)',
                'count': len(fires), 'total': total, 'truncated': total > len(fires), 'fires': fires,
                'source': FIRMS_SOURCE}


def _meets(conf: str, minimum: str) -> bool:
    order = {'low': 0, 'nominal': 1, 'high': 2}
    if conf in order:
        return order[conf] >= order.get(minimum, 0)
    pct = _num(conf)
    if pct is None:
        return True
    return pct >= {'low': 0, 'nominal': 30, 'high': 80}.get(minimum, 0)
