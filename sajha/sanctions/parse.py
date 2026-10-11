"""
SAJHA MCP Server — parsers for the official sanctions list files.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Each parser turns one downloaded file into ``(publication_date, {entry_id: entry})`` in one shape
for every list, so screening, ``sanctions_entry`` and the change diff never look at a source format:

``{entry_id, list, type (individual | entity | vessel | aircraft), name, aliases: [{name, kind,
strength}], programmes, dates_of_birth, places_of_birth, countries (ISO alpha-2 where known),
addresses, identifiers: [{type, number, country}], remarks, listed_on, last_updated, reference}``

* OFAC SDN and consolidated lists: the "XML" export of the sanctions list service (``sdnList``).
* EU: the Financial Sanctions Files full list, XML v1.1 (``export`` / ``sanctionEntity``).
* UK: the UK Sanctions List XML (``Designations`` / ``Designation``).

XML is read with defusedxml (no entity expansion, no external entities).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from defusedxml import ElementTree as DET

from sajha.tools.impl.country_codes import COUNTRIES

Entries = Dict[str, Dict[str, Any]]

_MONTHS = {m: i for i, m in enumerate(('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct',
                                        'nov', 'dec'), 1)}

#: country names the lists use that are not the ISO short names in country_codes.py
_COUNTRY_ALIASES = {
    'russia': 'RU', 'iran': 'IR', 'syria': 'SY', 'north korea': 'KP', 'korea north': 'KP', 'dprk': 'KP',
    "democratic people's republic of korea": 'KP', 'south korea': 'KR', 'korea south': 'KR',
    'korea republic of': 'KR', 'burma': 'MM', 'myanmar': 'MM', 'venezuela': 'VE', 'bolivia': 'BO',
    'tanzania': 'TZ', 'vietnam': 'VN', 'viet nam': 'VN', 'laos': 'LA', 'moldova': 'MD', 'turkey': 'TR',
    'turkiye': 'TR', 'uk': 'GB', 'united kingdom': 'GB', 'great britain': 'GB', 'usa': 'US',
    'united states': 'US', 'czech republic': 'CZ', 'czechia': 'CZ', 'congo democratic republic of the': 'CD',
    'democratic republic of the congo': 'CD', 'congo republic of the': 'CG', 'republic of the congo': 'CG',
    'ivory coast': 'CI', "cote d'ivoire": 'CI', 'cote divoire': 'CI', 'palestinian': 'PS', 'palestine': 'PS',
    'west bank': 'PS', 'gaza': 'PS', 'taiwan': 'TW', 'macau': 'MO', 'macao': 'MO', 'hong kong': 'HK',
    'kosovo': 'XK', 'brunei': 'BN', 'cape verde': 'CV', 'swaziland': 'SZ', 'eswatini': 'SZ',
    'micronesia': 'FM', 'the gambia': 'GM', 'gambia': 'GM', 'the bahamas': 'BS', 'bahamas': 'BS',
    'netherlands': 'NL', 'the netherlands': 'NL', 'crimea': 'UA', 'virgin islands british': 'VG',
    'british virgin islands': 'VG', 'north macedonia the republic of': 'MK', 'north macedonia': 'MK',
    "cote d ivoire": 'CI', 'st kitts and nevis': 'KN', 'st lucia': 'LC', 'st vincent': 'VC',
    'congo (democratic republic)': 'CD', 'occupied palestinian territories': 'PS',
}


def _key(name: str) -> str:
    from sajha.sanctions.match import transliterate
    s = transliterate(name).lower().replace(',', ' ').replace('.', ' ')
    return re.sub(r'\s+', ' ', s).strip()


_BY_NAME: Dict[str, str] = {}


def country_code(value: Any) -> Optional[str]:
    """ISO alpha-2 for a code (alpha-2 or alpha-3) or a country name; None when unknown."""
    if not value:
        return None
    s = re.sub(r'^region:\s*', '', str(value).strip(), flags=re.I)
    if not s or s.lower() == 'unknown':
        return None
    if not _BY_NAME:
        for a3, (a2, _m49, nm) in COUNTRIES.items():
            _BY_NAME[_key(nm)] = a2
            base = re.sub(r'\s*\(.*\)\s*', ' ', nm).strip()
            _BY_NAME.setdefault(_key(base), a2)
        _BY_NAME.update({_key(k): v for k, v in _COUNTRY_ALIASES.items()})
    if len(s) == 2 and s.isalpha():
        up = s.upper()
        return up if any(v[0] == up for v in COUNTRIES.values()) or up == 'XK' else None
    if len(s) == 3 and s.isalpha() and s.upper() in COUNTRIES:
        return COUNTRIES[s.upper()][0]
    return _BY_NAME.get(_key(s))


def _countries(values) -> List[str]:
    out: List[str] = []
    for v in values:
        if not v:
            continue
        c = country_code(v) or str(v).strip()
        if str(v).strip().lower() == 'unknown':
            continue
        if c and c not in out:
            out.append(c)
    return out


def norm_date(raw: Any) -> Optional[str]:
    """A list's date as YYYY-MM-DD, YYYY-MM or YYYY (the precision the list gives); None when it
    carries no year. Ranges and circa dates keep their first year ('circa 1960' gives '1960')."""
    s = str(raw or '').strip()
    if not s:
        return None
    m = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', s)
    if m:
        return s
    m = re.fullmatch(r'(\d{1,2}|dd)/(\d{1,2}|mm)/(\d{4})', s)                # UK: DD/MM/YYYY, dd/mm masks
    if m:
        d, mo, y = m.groups()
        if mo == 'mm':
            return y
        if d == 'dd':
            return f'{y}-{int(mo):02d}'
        return f'{y}-{int(mo):02d}-{int(d):02d}'
    m = re.fullmatch(r'(\d{1,2}) ([A-Za-z]{3})[a-z]* (\d{4})', s)            # OFAC: 10 Dec 1948
    if m and m.group(2).lower() in _MONTHS:
        return f'{m.group(3)}-{_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}'
    m = re.fullmatch(r'([A-Za-z]{3})[a-z]* (\d{4})', s)                      # OFAC: Feb 1960
    if m and m.group(1).lower() in _MONTHS:
        return f'{m.group(2)}-{_MONTHS[m.group(1).lower()]:02d}'
    m = re.search(r'(\d{4})', s)                                             # 1960, circa 1960, 1960 to 1962
    return m.group(1) if m else None


def _us_date(s: str) -> Optional[str]:
    try:
        return datetime.strptime(s.strip(), '%m/%d/%Y').strftime('%Y-%m-%d')
    except (ValueError, AttributeError):
        return None


def _local(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]


def _kids(el, name: str):
    return [c for c in el if _local(c.tag) == name]


def _kid(el, name: str):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _text(el, name: str) -> str:
    c = _kid(el, name) if el is not None else None
    return (c.text or '').strip() if c is not None and c.text else ''


def _join(*parts: str) -> str:
    return ' '.join(p.strip() for p in parts if p and p.strip())


def _dedupe(values: List[str]) -> List[str]:
    out: List[str] = []
    for v in values:
        if v and v not in out:
            out.append(v)
    return out


def _unique_ids(ids: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out, seen = [], set()
    for i in ids:
        k = (i.get('type'), i.get('number'), i.get('country'))
        if i.get('number') and k not in seen:
            seen.add(k)
            out.append(i)
    return out


def _entry(list_id: str, entry_id: str, etype: str, name: str) -> Dict[str, Any]:
    return {'entry_id': entry_id, 'list': list_id, 'type': etype, 'name': name, 'aliases': [], 'programmes': [],
            'dates_of_birth': [], 'places_of_birth': [], 'countries': [], 'addresses': [], 'identifiers': [],
            'remarks': '', 'listed_on': None, 'last_updated': None, 'reference': None}


# ── OFAC ────────────────────────────────────────────────────────────────

_OFAC_TYPES = {'individual': 'individual', 'entity': 'entity', 'vessel': 'vessel', 'aircraft': 'aircraft'}
_OFAC_KINDS = {'a.k.a.': 'aka', 'f.k.a.': 'fka', 'n.k.a.': 'nka'}


def parse_ofac(content: bytes, list_id: str) -> Tuple[Optional[str], Entries]:
    """The OFAC SDN or consolidated (non-SDN) list in the service's XML export."""
    root = DET.fromstring(content)
    if _local(root.tag) != 'sdnList':
        raise ValueError(f'not an OFAC list file (root element {_local(root.tag)!r})')
    pub = _kid(root, 'publshInformation')
    published = _us_date(_text(pub, 'Publish_Date')) if pub is not None else None
    out: Entries = {}
    for e in _kids(root, 'sdnEntry'):
        uid = _text(e, 'uid')
        if not uid:
            continue
        etype = _OFAC_TYPES.get(_text(e, 'sdnType').lower(), 'entity')
        ent = _entry(list_id, uid, etype, _join(_text(e, 'firstName'), _text(e, 'lastName')))
        pl = _kid(e, 'programList')
        ent['programmes'] = _dedupe([(p.text or '').strip() for p in _kids(pl, 'program')] if pl is not None else [])
        al = _kid(e, 'akaList')
        for a in (_kids(al, 'aka') if al is not None else []):
            nm = _join(_text(a, 'firstName'), _text(a, 'lastName'))
            if nm:
                ent['aliases'].append({'name': nm, 'kind': _OFAC_KINDS.get(_text(a, 'type').lower(), 'aka'),
                                       'strength': _text(a, 'category').lower() or None})
        countries: List[str] = []
        for lst, item in (('nationalityList', 'nationality'), ('citizenshipList', 'citizenship')):
            lst_el = _kid(e, lst)
            for n in (_kids(lst_el, item) if lst_el is not None else []):
                countries.append(_text(n, 'country'))
        adl = _kid(e, 'addressList')
        for a in (_kids(adl, 'address') if adl is not None else []):
            line = _join(_text(a, 'address1'), _text(a, 'address2'), _text(a, 'address3'), _text(a, 'city'),
                         _text(a, 'stateOrProvince'), _text(a, 'postalCode'), _text(a, 'country'))
            if line:
                ent['addresses'].append(line)
            countries.append(_text(a, 'country'))
        dl = _kid(e, 'dateOfBirthList')
        for d in (_kids(dl, 'dateOfBirthItem') if dl is not None else []):
            v = norm_date(_text(d, 'dateOfBirth'))
            if v:
                ent['dates_of_birth'].append(v)
        bl = _kid(e, 'placeOfBirthList')
        for b in (_kids(bl, 'placeOfBirthItem') if bl is not None else []):
            if _text(b, 'placeOfBirth'):
                ent['places_of_birth'].append(_text(b, 'placeOfBirth'))
        il = _kid(e, 'idList')
        for i in (_kids(il, 'id') if il is not None else []):
            ent['identifiers'].append({'type': _text(i, 'idType').rstrip(':'), 'number': _text(i, 'idNumber'),
                                       'country': _text(i, 'idCountry') or None})
        vi = _kid(e, 'vesselInfo')
        if vi is not None:
            countries.append(_text(vi, 'vesselFlag'))
            for f in ('callSign', 'vesselType', 'vesselOwner'):
                if _text(vi, f):
                    ent['identifiers'].append({'type': f, 'number': _text(vi, f), 'country': None})
        ent['countries'] = _countries(countries)
        ent['dates_of_birth'] = _dedupe(ent['dates_of_birth'])
        ent['remarks'] = _text(e, 'remarks') or _text(e, 'title')
        ent['identifiers'] = _unique_ids(ent['identifiers'])
        out[uid] = ent
    return published, out


# ── EU ──────────────────────────────────────────────────────────────────

_EU_TYPES = {'person': 'individual', 'enterprise': 'entity'}


def parse_eu(content: bytes, list_id: str = 'eu') -> Tuple[Optional[str], Entries]:
    """The EU Financial Sanctions Files full list, XML v1.1."""
    root = DET.fromstring(content)
    if _local(root.tag) != 'export':
        raise ValueError(f'not an EU sanctions file (root element {_local(root.tag)!r})')
    published = (root.get('generationDate') or '')[:10] or None
    out: Entries = {}
    for e in _kids(root, 'sanctionEntity'):
        lid = e.get('logicalId') or ''
        if not lid:
            continue
        st = _kid(e, 'subjectType')
        etype = _EU_TYPES.get((st.get('code') if st is not None else '') or '', 'entity')
        names = [n.get('wholeName') or _join(n.get('firstName', ''), n.get('middleName', ''), n.get('lastName', ''))
                 for n in _kids(e, 'nameAlias')]
        strong = [n.get('strong', 'true') for n in _kids(e, 'nameAlias')]
        names = [n.strip() for n in names]
        primary = next((n for n in names if n), '')
        ent = _entry(list_id, lid, etype, primary)
        ent['reference'] = e.get('euReferenceNumber') or None
        seen = {primary}
        for nm, st_ in zip(names, strong):
            if nm and nm not in seen:
                seen.add(nm)
                ent['aliases'].append({'name': nm, 'kind': 'alias',
                                       'strength': 'strong' if st_ != 'false' else 'weak'})
        regs = _kids(e, 'regulation')
        ent['programmes'] = _dedupe([r.get('programme') or '' for r in regs])
        dates = [r.get('entryIntoForceDate') or r.get('publicationDate') or '' for r in regs]
        dates = sorted(d for d in dates if d)
        ent['listed_on'] = dates[0] if dates else None
        countries: List[str] = []
        for c in _kids(e, 'citizenship'):
            countries.append(c.get('countryIso2Code') or c.get('countryDescription') or '')
        for b in _kids(e, 'birthdate'):
            v = norm_date(b.get('birthdate') or b.get('year'))
            if v:
                ent['dates_of_birth'].append(v)
            place = _join(b.get('city', ''), b.get('place', ''), b.get('countryDescription', ''))
            if place:
                ent['places_of_birth'].append(place)
        for a in _kids(e, 'address'):
            line = _join(a.get('street', ''), a.get('city', ''), a.get('region', ''), a.get('zipCode', ''),
                         a.get('countryDescription', ''))
            if line:
                ent['addresses'].append(line)
            countries.append(a.get('countryIso2Code') or '')
        for i in _kids(e, 'identification'):
            ent['identifiers'].append({'type': i.get('identificationTypeDescription') or i.get('identificationTypeCode'),
                                       'number': i.get('number') or '', 'country': i.get('countryIso2Code') or None})
        ent['countries'] = _countries([c if c not in ('00', '') else '' for c in countries])
        ent['dates_of_birth'] = _dedupe(ent['dates_of_birth'])
        ent['places_of_birth'] = _dedupe(ent['places_of_birth'])
        ent['remarks'] = ' '.join((r.text or '').strip() for r in _kids(e, 'remark') if r.text)
        ent['identifiers'] = _unique_ids(ent['identifiers'])
        out[lid] = ent
    return published, out


# ── UK ──────────────────────────────────────────────────────────────────

_UK_TYPES = {'individual': 'individual', 'entity': 'entity', 'ship': 'vessel'}


def _uk_date(s: str) -> Optional[str]:
    return norm_date(s) if s else None


def parse_uk(content: bytes, list_id: str = 'uk') -> Tuple[Optional[str], Entries]:
    """The UK Sanctions List (FCDO) XML."""
    root = DET.fromstring(content)
    if _local(root.tag) != 'Designations':
        raise ValueError(f'not a UK sanctions list file (root element {_local(root.tag)!r})')
    published = _uk_date(_text(root, 'DateGenerated'))
    out: Entries = {}
    for d in _kids(root, 'Designation'):
        uid = _text(d, 'UniqueID')
        if not uid:
            continue
        etype = _UK_TYPES.get(_text(d, 'IndividualEntityShip').lower(), 'entity')
        primary, aliases = '', []
        names_el = _kid(d, 'Names')
        for n in (_kids(names_el, 'Name') if names_el is not None else []):
            nm = _join(*(_text(n, f'Name{i}') for i in range(1, 7)))
            if not nm:
                continue
            kind = _text(n, 'NameType').lower()
            if kind == 'primary name' and not primary:
                primary = nm
            else:
                aliases.append({'name': nm, 'kind': 'alias' if kind.startswith('alias') else 'name_variation',
                                'strength': (_text(n, 'AliasStrength') or '').lower() or None})
        nl = _kid(d, 'NonLatinNames')
        for n in (_kids(nl, 'NonLatinName') if nl is not None else []):
            if _text(n, 'NameNonLatinScript'):
                aliases.append({'name': _text(n, 'NameNonLatinScript'), 'kind': 'non_latin', 'strength': None})
        if not primary and aliases:
            primary = aliases.pop(0)['name']
        ent = _entry(list_id, uid, etype, primary)
        seen = {primary}
        for a in aliases:
            if a['name'] not in seen:
                seen.add(a['name'])
                ent['aliases'].append(a)
        ent['programmes'] = [_text(d, 'RegimeName')] if _text(d, 'RegimeName') else []
        ent['listed_on'] = _uk_date(_text(d, 'DateDesignated'))
        ent['last_updated'] = _uk_date(_text(d, 'LastUpdated'))
        ent['reference'] = _text(d, 'UNReferenceNumber') or None
        countries: List[str] = []
        for ind in d.iter():
            tag = _local(ind.tag)
            if tag == 'DOB':
                v = norm_date((ind.text or '').strip())
                if v:
                    ent['dates_of_birth'].append(v)
            elif tag in ('Nationality', 'AddressCountry', 'CurrentBelievedFlagOfShip'):
                countries.append((ind.text or '').strip())
            elif tag == 'Location':
                place = _join(_text(ind, 'TownOfBirth'), _text(ind, 'CountryOfBirth'))
                if place:
                    ent['places_of_birth'].append(place)
            elif tag == 'Address':
                line = _join(*(_text(ind, f'AddressLine{i}') for i in range(1, 7)), _text(ind, 'AddressCountry'))
                if line:
                    ent['addresses'].append(line)
            elif tag in ('PassportNumber', 'NationalIdentifierNumber', 'IMONumber', 'BusinessRegistrationNumber'):
                if (ind.text or '').strip():
                    ent['identifiers'].append({'type': tag, 'number': ind.text.strip(), 'country': None})
        ent['countries'] = _countries(countries)
        ent['dates_of_birth'] = _dedupe(ent['dates_of_birth'])
        ent['places_of_birth'] = _dedupe(ent['places_of_birth'])
        ent['remarks'] = _text(d, 'OtherInformation')
        ent['identifiers'] = _unique_ids(ent['identifiers'])
        out[uid] = ent
    return published, out
