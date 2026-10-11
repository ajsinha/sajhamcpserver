"""
SAJHA MCP Server — the official sanctions lists SAJHA downloads, and their terms.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Verified live on 2026-10-11 (docs/architecture/Open Data Tools.md, section 2). The UN Security
Council list is known but disabled: the owner keeps it off until legal approves its terms of use
(section 6), so ``un`` is refused wherever a list is named.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

OFAC_EXPORTS = 'https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/'
EU_RSS = 'https://webgate.ec.europa.eu/fsd/fsf/public/rss'
EU_XML = ('https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content'
          '?token=dG9rZW4tMjAxNw')
UK_XML = 'https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.xml'

NOT_A_DETERMINATION = ('Screening aid, not a determination: a candidate match is for a person to review against '
                       'the official list entry; it does not establish that anyone is or is not sanctioned.')


@dataclass(frozen=True)
class ListSource:
    id: str
    title: str
    url: str
    source: str                 # the attribution line every result carries
    enabled: bool = True
    disabled_reason: str = ''


LISTS: Dict[str, ListSource] = {s.id: s for s in (
    ListSource('ofac_sdn', 'OFAC Specially Designated Nationals and Blocked Persons List (SDN)',
               OFAC_EXPORTS + 'SDN.XML',
               'Source: U.S. Department of the Treasury, Office of Foreign Assets Control (OFAC), SDN List'),
    ListSource('ofac_consolidated', 'OFAC Consolidated Sanctions List (non-SDN lists)',
               OFAC_EXPORTS + 'CONSOLIDATED.XML',
               'Source: U.S. Department of the Treasury, Office of Foreign Assets Control (OFAC), '
               'Consolidated (non-SDN) Sanctions List'),
    ListSource('eu', 'EU consolidated list of persons, groups and entities subject to financial sanctions',
               EU_XML,
               'Source: European Commission, EU Financial Sanctions Files (consolidated list); reuse under '
               'Commission Decision 2011/833/EU; only the Official Journal of the EU is authentic'),
    ListSource('uk', 'UK Sanctions List (FCDO)', UK_XML,
               'Source: UK Sanctions List, Foreign, Commonwealth and Development Office; contains public sector '
               'information licensed under the Open Government Licence v3.0'),
    ListSource('un', 'UN Security Council Consolidated List',
               'https://scsanctions.un.org/resources/xml/en/consolidated.xml',
               'Source: United Nations Security Council Consolidated List',
               enabled=False,
               disabled_reason='the UN list is off until legal approves its terms of use (owner decision)'),
)}

ENABLED = tuple(k for k, v in LISTS.items() if v.enabled)


def check_list(name: Optional[str]) -> str:
    """The list id, or ValueError naming the lists (and why ``un`` is refused)."""
    key = str(name or '').strip().lower()
    src = LISTS.get(key)
    if src is None:
        raise ValueError(f'unknown list {name!r}: one of {", ".join(ENABLED)}')
    if not src.enabled:
        raise ValueError(f'list {key!r} is not available: {src.disabled_reason}')
    return key
