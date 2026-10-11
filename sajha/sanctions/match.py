"""
SAJHA MCP Server — sanctions name matching: normalisation, a phonetic key and token-set scoring.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Everything here is local and uses the standard library only: a name being screened never leaves
the machine. Design: docs/architecture/Open Data Tools.md (section 4, ``sanctions``); the tools
guide is docs/tools/public-data/Sanctions Tool Reference Guide.md.

* :func:`normalise` transliterates (Unicode decomposition, a few letters decomposition misses,
  Cyrillic and Greek to Latin), lower-cases, turns punctuation into spaces, drops honorifics and
  titles, and for organisations common legal forms. Word order is ignored later (token sets).
* :func:`phonetic` is a per-token key in the Soundex family, with the first letter coded too
  (so ``Qadhafi``, ``Kaddafi`` and ``Gaddafi`` agree) and ``kh``/``ph``/``dh``/``th``/``gh``
  folded first.
* :func:`score` is the token-set ratio (difflib) on 0 to 100, with a fifth weight on the
  token-sort ratio so that the exact name outranks a longer one containing it; spelling variants
  of a word (at least 4 letters, 85% similar) count as the same word; when the phonetic keys
  agree the score is lifted half way to 100.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import FrozenSet, Iterable, List, Tuple

#: letters NFKD does not decompose
_EXTRA = str.maketrans({'ø': 'o', 'Ø': 'O', 'ß': 'ss', 'æ': 'ae', 'Æ': 'AE', 'œ': 'oe', 'Œ': 'OE',
                        'đ': 'd', 'Đ': 'D', 'ł': 'l', 'Ł': 'L', 'ı': 'i', 'þ': 'th', 'Þ': 'Th',
                        'ð': 'd', 'Ð': 'D', 'ħ': 'h', 'Ħ': 'H', 'ŧ': 't', 'Ŧ': 'T',
                        'ʼ': '', '’': '', '‘': '', '`': '', "'": '', 'ʻ': '', 'ʿ': '', 'ʾ': ''})

_CYRILLIC = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'ґ': 'g', 'д': 'd', 'е': 'e', 'ё': 'e', 'є': 'ye', 'ж': 'zh',
    'з': 'z', 'и': 'i', 'і': 'i', 'ї': 'yi', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o',
    'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ў': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch',
    'ш': 'sh', 'щ': 'shch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
}
_GREEK = {
    'α': 'a', 'β': 'v', 'γ': 'g', 'δ': 'd', 'ε': 'e', 'ζ': 'z', 'η': 'i', 'θ': 'th', 'ι': 'i', 'κ': 'k',
    'λ': 'l', 'μ': 'm', 'ν': 'n', 'ξ': 'x', 'ο': 'o', 'π': 'p', 'ρ': 'r', 'σ': 's', 'ς': 's', 'τ': 't',
    'υ': 'y', 'φ': 'f', 'χ': 'ch', 'ψ': 'ps', 'ω': 'o',
}
_SCRIPT = str.maketrans({**_CYRILLIC, **{k.upper(): v for k, v in _CYRILLIC.items()},
                         **_GREEK, **{k.upper(): v for k, v in _GREEK.items()}})

#: honorifics and titles (lower case, after transliteration); dropped from names
HONORIFICS = frozenset('''
mr mrs ms miss mx dr prof professor sir dame lord lady madam madame mme mlle monsieur herr frau
sheikh shaikh shaykh sheik haji hajji hadji alhaji mullah mulla maulvi mawlawi maulana mawlana
imam ayatollah hojatoleslam
general gen lt col colonel maj major capt captain cmdr commander adm admiral brig brigadier sgt
rev reverend fr father bishop
'''.split())

#: legal forms of organisations (lower case); dropped from entity, vessel and aircraft names
LEGAL_FORMS = frozenset('''
ltd limited llc llp lp inc incorporated corp corporation co company plc gmbh ag sa sarl sas spa srl
bv nv oy ab as asa aps kft zao ooo oao pao pjsc ojsc cjsc jsc tov fze fzco fzc fzllc sdn bhd pte pvt
'''.split())

_PUNCT = re.compile(r"[^\w\s]|_", re.UNICODE)
_SPACE = re.compile(r'\s+')


def transliterate(text: str) -> str:
    """Latin letters without accents (Cyrillic and Greek mapped; other scripts kept)."""
    text = str(text or '').translate(_EXTRA).translate(_SCRIPT)
    decomposed = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in decomposed if not unicodedata.combining(c))


def tokens(name: str, organisation: bool = False) -> List[str]:
    """The normalised words of a name: transliterated, lower case, punctuation as spaces,
    honorifics (and, for organisations, legal forms) removed. Never empty for a non-empty name:
    when every word is a title, the words are kept."""
    text = _PUNCT.sub(' ', transliterate(name).lower())
    words = [w for w in _SPACE.split(text) if w]
    drop = HONORIFICS | LEGAL_FORMS if organisation else HONORIFICS
    kept = [w for w in words if w not in drop]
    return kept or words


def normalise(name: str, organisation: bool = False) -> str:
    """The normalised name, words in their original order."""
    return ' '.join(tokens(name, organisation))


_DIGRAPHS = (('kh', 'k'), ('ph', 'f'), ('dh', 'd'), ('th', 't'), ('gh', 'g'), ('sch', 's'), ('ck', 'k'),
             ('ou', 'u'), ('ee', 'i'), ('oo', 'u'))
_CODES = {**dict.fromkeys('bfpv', '1'), **dict.fromkeys('cgjkqsxz', '2'), **dict.fromkeys('dt', '3'),
          'l': '4', **dict.fromkeys('mn', '5'), 'r': '6'}


def phonetic(word: str) -> str:
    """A Soundex-family key for one normalised word, every letter coded (vowels, h, w and y
    separate equal codes but are not coded); at most 6 codes. Digits are kept as they are."""
    w = word.lower()
    if w.isdigit():
        return w
    for a, b in _DIGRAPHS:
        w = w.replace(a, b)
    out: List[str] = []
    prev = ''
    for ch in w:
        code = _CODES.get(ch)
        if code is None:
            if ch in 'aeiouy':
                prev = ''           # a vowel separates two equal codes
            elif ch.isdigit():
                out.append(ch)
                prev = ''
            continue                # h and w do not separate
        if code != prev:
            out.append(code)
        prev = code
    return ''.join(out[:6]) or w[:1]


def phonetic_keys(words: Iterable[str]) -> FrozenSet[str]:
    return frozenset(phonetic(w) for w in words)


def _ratio(a: str, b: str) -> float:
    if not a and not b:
        return 100.0
    return 100.0 * SequenceMatcher(None, a, b, autojunk=False).ratio()


def token_set_ratio(a: Iterable[str], b: Iterable[str]) -> float:
    """The token-set ratio (0 to 100): the shared words compared with each side's full sorted
    word list, so word order and words present on only one side cost little."""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    inter = ' '.join(sorted(sa & sb))
    da, db = ' '.join(sorted(sa - sb)), ' '.join(sorted(sb - sa))
    t1 = (inter + ' ' + da).strip()
    t2 = (inter + ' ' + db).strip()
    if inter:
        return max(_ratio(inter, t1), _ratio(inter, t2), _ratio(t1, t2))
    return _ratio(t1, t2)


def token_sort_ratio(a: Iterable[str], b: Iterable[str]) -> float:
    return _ratio(' '.join(sorted(a)), ' '.join(sorted(b)))


#: two words this similar (0 to 1) count as the same word in the token sets (moammar, muammar)
SAME_WORD = 0.85
#: shorter words must match exactly (al, ali, bin, abu)
MIN_FUZZY_LEN = 4


def _align(query: List[str], candidate: List[str]) -> List[str]:
    """The candidate's words, each replaced by the query word it nearly equals (spelling variants
    then count as shared words); words already shared are left alone."""
    qs, cs = set(query), set(candidate)
    free = [q for q in qs if q not in cs and len(q) >= MIN_FUZZY_LEN]
    out = []
    for c in candidate:
        if c in qs or not free or len(c) < MIN_FUZZY_LEN:
            out.append(c)
            continue
        best = max(free, key=lambda q: SequenceMatcher(None, q, c, autojunk=False).ratio())
        if SequenceMatcher(None, best, c, autojunk=False).ratio() >= SAME_WORD:
            out.append(best)
            free.remove(best)
        else:
            out.append(c)
    return out


def score(query: List[str], candidate: List[str]) -> Tuple[float, bool]:
    """(score 0 to 100, phonetic keys agree) for two token lists.

    A one-word query against a longer name is scored on whole sorted strings (token sort), not
    token sets, so a single common word does not match every name that contains it. Agreeing
    phonetic keys (every key of the shorter side found on the other side) lift the score half
    way to 100."""
    if not query or not candidate:
        return 0.0, False
    candidate = _align(query, candidate)
    if min(len(set(query)), len(set(candidate))) >= 2 or len(set(query)) == len(set(candidate)) == 1:
        # token set, with a fifth from token sort: words on one side only cost a little, so the
        # exact name ranks above a longer name that contains it
        text = 0.8 * token_set_ratio(query, candidate) + 0.2 * token_sort_ratio(query, candidate)
    else:
        text = token_sort_ratio(query, candidate)
    kq = phonetic_keys(w for w in query if len(w) > 2)            # 'al' and 'ali' are not one sound
    kc = phonetic_keys(w for w in candidate if len(w) > 2)
    small, big = (kq, kc) if len(kq) <= len(kc) else (kc, kq)
    same_sound = bool(small) and small <= big and (len(small) >= 2 or len(big) == 1)
    if same_sound and text < 100.0:
        text = (text + 100.0) / 2.0
    return round(text, 1), same_sound
