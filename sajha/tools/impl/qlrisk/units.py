# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The unit layer over qlrisk's own objects: calculator inputs and configuration, nested product terms, shocks,
stylised stresses and liquidity spreads.

qlrisk takes decimals (0.03 is 3%, 0.0001 is 1bp). The tools take percent (``*_pct``) and basis points
(``*_bp``); which field gets which unit and conversion is the table in generate.py (CALC_INPUTS, CALC_CONFIG,
NESTED_*, SHOCK_UNITS, STRESS_DEFINITION, LIQUIDITY). This module only applies it: ``object_schema`` turns a
schema read from qlrisk into the presented one, ``to_qlrisk`` turns presented values back into qlrisk's names
and units with field-named errors for impossible values and warnings for unusual ones, and ``note_received``
records what qlrisk was given so each result can show it (``qlrisk_inputs``).
"""

from __future__ import annotations

import contextvars
import math
from typing import Any, Dict, List, Optional, Tuple

from .inputs import InvalidInput

_RECEIVED: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar("qlrisk_received", default=None)


def start_received() -> contextvars.Token:
    return _RECEIVED.set({})


def end_received(token: contextvars.Token) -> Dict[str, Any]:
    got = _RECEIVED.get() or {}
    _RECEIVED.reset(token)
    return got


def note_received(where: str, value: Any) -> None:
    """Record what qlrisk was given for one input (shown as the result's qlrisk_inputs[where])."""
    got = _RECEIVED.get()
    if got is not None:
        got[where] = value


# ── the table ───────────────────────────────────────────────────────


def _F():
    from .generate import F
    return F


def _blank():
    return _F()()


def _tiny(f) -> float:
    if f.tiny is not None:
        return f.tiny
    return {"percent": 0.2, "basis points": 0.5}.get(f.unit, 0.0)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def unit_note(f) -> str:
    """'percent, 2 = 2%' and the like, for descriptions."""
    if f.unit == "percent":
        return "percent"
    if f.unit == "basis points":
        return "basis points"
    return f.unit or ""


# ── schemas ─────────────────────────────────────────────────────────


def _number_schema(f, qs: Dict[str, Any]) -> Dict[str, Any]:
    s: Dict[str, Any] = {"type": "number"}
    if f.minimum is not None:
        s["minimum"] = f.minimum
    if f.maximum is not None:
        s["maximum"] = f.maximum
    if f.positive:
        s["exclusiveMinimum"] = 0
    return s


def _shape(qs: Dict[str, Any]) -> str:
    """'list', 'map' (tenor/name -> number), 'list_or_number', 'object', 'object_list' or 'scalar'."""
    if "anyOf" in qs:
        return "list_or_number"
    t = qs.get("type")
    t = [x for x in t if x != "null"][0] if isinstance(t, list) and len([x for x in t if x != "null"]) == 1 else t
    if t == "array":
        items = qs.get("items") or {}
        return "object_list" if items.get("type") == "object" or "properties" in items else "list"
    if t == "object":
        return "object" if "properties" in qs else "map"
    return "scalar"


def field_schema(f, qs: Dict[str, Any]) -> Dict[str, Any]:
    """The presented schema of one field (qs: its schema as read from qlrisk)."""
    shape = _shape(qs)
    converted = f.scale != 1.0 or f.offset or f.minimum is not None or f.maximum is not None or f.positive
    if f.nested is not None and shape in ("object", "object_list"):
        inner = qs["items"] if shape == "object_list" else qs
        obj = object_schema(f.nested, inner)
        s = {"type": "array", "items": obj} if shape == "object_list" else obj
        if "default" in qs and shape == "object_list":
            s["default"] = qs["default"]
    elif converted and shape in ("list", "map", "list_or_number", "scalar"):
        num = _number_schema(f, qs)
        if shape == "list":
            s = {"type": "array", "items": num}
        elif shape == "map":
            s = {"type": "object", "additionalProperties": num}
        elif shape == "list_or_number":
            s = {"anyOf": [num, {"type": "array", "items": num, "minItems": 2, "maxItems": 2}]}
        else:
            s = num
        d = qs.get("default")
        if _is_num(d) and shape in ("scalar", "list_or_number"):
            v = round((d - f.offset) / f.scale, 10)
            s["default"] = int(v) if v == int(v) else v
        elif isinstance(d, (list, dict)):
            s["default"] = d
    else:
        s = {k: v for k, v in qs.items() if k != "description"}
        if f.type:
            s["type"] = f.type
    if f.default is None:                     # the table says: no default shown (qlrisk's means "not given")
        s.pop("default", None)
    elif f.default is not _no():
        s["default"] = f.default
    s["title"] = f.title or ""
    desc = f.desc
    t = qs.get("type")
    if not desc and not f.title and (t == "number" or (isinstance(t, list) and "number" in t)):
        desc = "Passed to qlrisk as is, in qlrisk's own units."
    if desc:
        s["description"] = desc
    if not s["title"]:
        s.pop("title")
    return s


def _no():
    from .generate import _NO
    return _NO


def object_schema(table: Dict[str, Any], qschema: Dict[str, Any]) -> Dict[str, Any]:
    """A qlrisk object schema (properties read from qlrisk) under the table's names and units."""
    props: Dict[str, Any] = {}
    for q, qs in (qschema.get("properties") or {}).items():
        f = table.get(q) or _blank()
        s = field_schema(f, qs)
        s.setdefault("title", q.replace("_", " ").capitalize())
        props[f.name or q] = s
    out: Dict[str, Any] = {"type": "object", "properties": props, "additionalProperties": False}
    req = [(table.get(q) or _blank()).name or q for q in qschema.get("required") or []]
    if req:
        out["required"] = req
    return out


def fields_doc(schema: Dict[str, Any]) -> str:
    """'pd_pct* (percent), ead (amount, default 0)' for a description."""
    parts = []
    req = set(schema.get("required") or [])
    for name, s in (schema.get("properties") or {}).items():
        bits = []
        title = s.get("title", "")
        if "(" in title and title.endswith(")"):
            bits.append(title[title.rindex("(") + 1:-1])
        if "default" in s and not isinstance(s["default"], (list, dict)):
            d = s["default"]
            bits.append(f"default {str(d).lower() if isinstance(d, bool) else d}")
        parts.append(name + ("*" if name in req else "") + (f" ({', '.join(bits)})" if bits else ""))
    return ", ".join(parts)


# ── values ──────────────────────────────────────────────────────────


def check_number(f, value: Any, what: str, warnings: List[str]) -> Any:
    """One number in the table's units -> qlrisk's value; impossible values raise, unusual ones warn."""
    if not _is_num(value) or not math.isfinite(float(value)):
        raise InvalidInput(f"{what}: expected a number, got {value!r}")
    unit = f" {f.unit}" if f.unit in ("percent", "basis points") else ""
    hint = (" (it is in percent: 2 means 2%)" if f.unit == "percent" else
            " (it is in basis points: 25 means 0.25%)" if f.unit == "basis points" else "")
    if (f.minimum is not None and value < f.minimum) or (f.maximum is not None and value > f.maximum):
        lo = "-inf" if f.minimum is None else f"{f.minimum:g}"
        hi = "inf" if f.maximum is None else f"{f.maximum:g}"
        raise InvalidInput(f"{what}: {value:g} is outside {lo} to {hi}{unit}{hint}")
    if f.positive and value <= 0:
        raise InvalidInput(f"{what}: must be greater than 0, got {value:g}")
    if f.warn and not (f.warn[0] <= value <= f.warn[1]):
        warnings.append(f"{what} = {value:g}{unit} is outside the usual {f.warn[0]:g} to {f.warn[1]:g}{unit}; check it")
    tiny = _tiny(f)
    if tiny and 0 < abs(value) < tiny:
        if f.unit == "percent":
            warnings.append(f"{what} = {value:g} means {value:g}%; for {value * 100:g}% send {value * 100:g}")
        else:
            warnings.append(f"{what} = {value:g} means {value:g}bp; for {value * 10000:g}bp send {value * 10000:g}")
    if f.scale == 1.0 and not f.offset:
        return value
    return round(value * f.scale + f.offset, 12)


def convert(f, schema: Dict[str, Any], value: Any, what: str, warnings: List[str]) -> Any:
    """A presented value -> qlrisk's (schema: the presented schema of the field, which carries its shape)."""
    if value is None:
        return None
    if f.nested is not None:
        if isinstance(value, list):
            items = schema.get("items") or {}
            return [to_qlrisk(f.nested, items, v, f"{what}[{i}]", warnings) for i, v in enumerate(value)]
        if isinstance(value, dict):
            return to_qlrisk(f.nested, schema, value, what, warnings)
        raise InvalidInput(f"{what}: expected an object or a list of objects")
    numeric = f.scale != 1.0 or f.offset or f.minimum is not None or f.maximum is not None or f.positive
    if not numeric:
        return value
    if isinstance(value, list):
        return [check_number(f, v, f"{what}[{i}]", warnings) for i, v in enumerate(value)]
    if isinstance(value, dict):
        return {k: check_number(f, v, f"{what}.{k}", warnings) for k, v in value.items()}
    return check_number(f, value, what, warnings)


def renamed(table: Dict[str, Any]) -> Dict[str, Tuple[str, Any]]:
    """qlrisk name -> (presented name, entry) for the fields the table renames."""
    return {q: (f.name, f) for q, f in table.items() if f.name and f.name != q}


def to_qlrisk(table: Dict[str, Any], schema: Dict[str, Any], value: Any, where: str, warnings: List[str]) -> Dict[str, Any]:
    """A presented object (schema: the presented object schema) -> a dict under qlrisk's names, in its units."""
    if not isinstance(value, dict):
        raise InvalidInput(f"{where} must be an object; fields: {', '.join(schema.get('properties') or {})}")
    props = schema.get("properties") or {}
    back = {(f.name or q): q for q, f in table.items()}
    unknown = [k for k in value if k not in props]
    if unknown:
        moved = renamed(table)
        hints = [f"{k} is now {moved[k][0]} ({unit_note(moved[k][1])})" for k in unknown if k in moved]
        raise InvalidInput(f"{where}: unknown field(s) {sorted(unknown)}"
                           + (f"; {'; '.join(hints)}" if hints else "") + f"; fields: {', '.join(props)}")
    missing = [r for r in schema.get("required") or [] if r not in value]
    if missing:
        raise InvalidInput(f"{where}: missing {missing}")
    out = {}
    for k, v in value.items():
        q = back.get(k, k)
        out[q] = convert(table.get(q) or _blank(), props[k], v, f"{where}.{k}", warnings)
    return out


def from_qlrisk(table: Dict[str, Any], qvalues: Dict[str, Any]) -> Dict[str, Any]:
    """qlrisk's values -> the tools' names and units (for showing qlrisk's own presets, e.g. its stress library)."""
    def back(f, v):
        if f.scale == 1.0 and not f.offset or isinstance(v, (str, bool)) or v is None:
            return v
        if isinstance(v, (list, tuple)):
            return [back(f, x) for x in v]
        if isinstance(v, dict):
            return {k: back(f, x) for k, x in v.items()}
        r = round((v - f.offset) / f.scale, 9)
        return int(r) if r == int(r) else r
    return {((table.get(q) or _blank()).name or q): back(table.get(q) or _blank(), v) for q, v in qvalues.items()}


# ── calculators ─────────────────────────────────────────────────────


def calc_inputs_schema(measure: str) -> Dict[str, Any]:
    from . import introspect as I
    from .generate import CALC_INPUTS
    return object_schema(CALC_INPUTS.get(measure, {}), I.dataclass_schema(I.calculator_input_class(measure)))


def _calc_config_q(measure: str) -> Dict[str, Any]:
    from . import introspect as I
    from .generate import CALC_CONFIG_EXTRA
    return {"type": "object", "properties": {**I.calculator_config(measure), **CALC_CONFIG_EXTRA.get(measure, {})}}


def calc_config_schema(measure: str) -> Dict[str, Any]:
    from .generate import CALC_CONFIG
    return object_schema(CALC_CONFIG.get(measure, {}), _calc_config_q(measure))


def calc_to_qlrisk(measure: str, inputs: Any, config: Any, warnings: List[str], where: str = "inputs",
                   cwhere: str = "config") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Calculator inputs and configuration in the tools' units -> qlrisk's (names, decimals, years)."""
    from .generate import CALC_CONFIG, CALC_INPUTS
    ischema, cschema = calc_inputs_schema(measure), calc_config_schema(measure)
    q_in = to_qlrisk(CALC_INPUTS.get(measure, {}), ischema, inputs if inputs is not None else {},
                     f"{where} ({measure})", warnings)
    try:
        q_cfg = to_qlrisk(CALC_CONFIG.get(measure, {}), cschema, config or {}, f"{cwhere} ({measure})", warnings)
    except InvalidInput as exc:
        if "unknown field" in str(exc):
            raise InvalidInput(str(exc).replace("unknown field(s)", "unknown key(s)")) from None
        raise
    for k, spec in cschema["properties"].items():
        q = next((q for q, f in CALC_CONFIG.get(measure, {}).items() if (f.name or q) == k), k)
        if q in q_cfg and "enum" in spec and str(q_cfg[q]) not in spec["enum"]:
            raise InvalidInput(f"config.{k} must be one of {spec['enum']}")
    return q_in, q_cfg


# ── shocks ──────────────────────────────────────────────────────────


def shock_size_props(compact: bool = False) -> Dict[str, Any]:
    from .generate import SHOCK_SIZES
    out: Dict[str, Any] = {}
    out["size"] = {"type": "number", "title": "Size (factor units)"}
    if not compact:
        out["size"]["description"] = ("Absolute shock to a price or FX spot, in its own units (EQ.SPX -250 = 250 "
                                      "index points down).")
    for m, title in SHOCK_SIZES.items():
        for suffix, unit, text in (("_bp", "bp", "Basis points: absolute shocks to rates, credit spreads and dividend "
                                    "yields (25 = +0.25%)."),
                                   ("_pct", "%", "Percent: relative and log shocks (-10 = -10%) and absolute "
                                    "volatility shocks (5 = +5 vol points).")):
            p = {"type": "number", "title": f"{title} ({unit})"}
            if not compact:
                p["description"] = text
            out[m + suffix] = p
    return out


def _unit_for(kind: str, shock_type: str):
    from .generate import SHOCK_UNITS
    return SHOCK_UNITS[(kind, shock_type)]


def _check_size(u, value: Any, what: str, warnings: List[str]) -> float:
    if not _is_num(value) or not math.isfinite(float(value)):
        raise InvalidInput(f"{what}: expected a number, got {value!r}")
    word = {"_bp": "bp", "_pct": "%"}.get(u.suffix, "")
    if u.limit is not None and abs(value) > u.limit:
        raise InvalidInput(f"{what}: {value:g}{word} is beyond +/-{u.limit:g}{word} ({u.meaning})")
    if u.floor is not None and value < u.floor:
        raise InvalidInput(f"{what}: {value:g}{word} is below {u.floor:g}{word} ({u.meaning})")
    if u.usual is not None and abs(value) > u.usual:
        warnings.append(f"{what} = {value:g}{word} is a very large shock ({u.meaning}); check it")
    if u.suffix == "_bp" and 0 < abs(value) < 0.5:
        warnings.append(f"{what} = {value:g} means {value:g}bp; for {value * 10000:g}bp send {value * 10000:g}")
    if u.suffix == "_pct" and 0 < abs(value) < 0.2:
        warnings.append(f"{what} = {value:g} means {value:g}%; for {value * 100:g}% send {value * 100:g}")
    return round(float(value) * u.scale, 12)


def _size_fields(item: Dict[str, Any]) -> List[str]:
    from .generate import SHOCK_SIZES
    return [k for k in item if any(k == m or k.startswith(m + "_") for m in SHOCK_SIZES)]


def _a(word: str) -> str:
    return "an" if word[:1] in "aeiou" else "a"


def shock_kinds(item: Dict[str, Any], kinds: List[str], shock_type: str, what: str) -> List[str]:
    """The kinds of factor a curve shock moves: those whose unit is the one its size fields carry (a rates shock in
    basis points moves the rates of a risk class, not its volatilities, which take percent)."""
    from .generate import FACTOR_KINDS
    suffixes = {("_bp" if k.endswith("_bp") else "_pct" if k.endswith("_pct") else "") for k in _size_fields(item)}
    if len(suffixes) != 1:
        return kinds                          # shock_values reports what is missing or mixed
    (suffix,) = suffixes
    picked = [k for k in kinds if _unit_for(k, shock_type).suffix == suffix]
    if not picked:
        takes = "; ".join(f"{FACTOR_KINDS[k]} takes size{_unit_for(k, shock_type).suffix} "
                          f"({_unit_for(k, shock_type).meaning})" for k in kinds)
        raise InvalidInput(f"{what}: {', '.join(_size_fields(item))} fits none of the factors it reaches for "
                           f"{_a(shock_type)} {shock_type} shock: {takes}")
    return picked


def shock_values(item: Dict[str, Any], kinds: List[str], shock_type: str, needs: Tuple[str, ...], what: str,
                 warnings: List[str]) -> Tuple[Dict[str, float], Any]:
    """The sizes a shock needs (needs: 'size' or the shape's two), in qlrisk's units, for factors of these kinds."""
    from .generate import FACTOR_KINDS
    units = {_unit_for(k, shock_type).suffix: _unit_for(k, shock_type) for k in kinds}
    if len(units) > 1:
        raise InvalidInput(f"{what}: this shock reaches {', '.join(sorted(FACTOR_KINDS[k] for k in kinds))}, which take "
                           f"different units; split it by curve_field")
    (suffix, u), = units.items()
    want = [n + suffix for n in needs]
    given = _size_fields(item)
    wrong = [g for g in given if g not in want]
    missing = [w for w in want if w not in item]
    if wrong or missing:
        kind_text = " and ".join(sorted({FACTOR_KINDS[k] for k in kinds}))
        raise InvalidInput(f"{what}: {_a(shock_type)} {shock_type} shock to {kind_text} takes {' and '.join(want)} ({u.meaning})"
                           + (f", not {', '.join(wrong)}" if wrong else ""))
    return {n: _check_size(u, item[n + suffix], f"{what}.{n + suffix}", warnings) for n in needs}, u


def human_shock(shock) -> Dict[str, Any]:
    """A qlrisk Shock as a shock in the tools' units (reverse stress output; reusable as a custom shock)."""
    u = _unit_for(shock.factor.kind.value, shock.shock_type.value)
    v = shock.size / u.scale
    return {"factor": str(shock.factor), "shock_type": shock.shock_type.value, "size" + u.suffix: round(v, 6),
            "qlrisk_size": shock.size}


def qlrisk_shock(shock) -> Dict[str, Any]:
    return {"factor": str(shock.factor), "size": shock.size, "shock_type": shock.shock_type.value}


# ── stylised stress, liquidity ──────────────────────────────────────


def stress_definition_schema() -> Dict[str, Any]:
    from . import introspect as I
    from .generate import STRESS_DEFINITION
    return object_schema(STRESS_DEFINITION, I.stress_definition_schema())


def stress_definition_to_qlrisk(value: Any, where: str, warnings: List[str]) -> Dict[str, Any]:
    from .generate import STRESS_DEFINITION
    d = to_qlrisk(STRESS_DEFINITION, stress_definition_schema(), value, where, warnings)
    if isinstance(d.get("rates"), list):
        if len(d["rates"]) != 2:
            raise InvalidInput(f"{where}.rates_bp: a twist is [short_end, long_end]")
        d["rates"] = tuple(d["rates"])
    return d


def liquidity_schema(base: Dict[str, Any]) -> Dict[str, Any]:
    """base: the liquidity object in qlrisk's terms (spreads, horizon_days)."""
    from .generate import LIQUIDITY
    return object_schema(LIQUIDITY, base)


def liquidity_to_qlrisk(value: Any, base: Dict[str, Any], where: str, warnings: List[str]) -> Dict[str, Any]:
    from .generate import LIQUIDITY
    return to_qlrisk(LIQUIDITY, liquidity_schema(base), value, where, warnings)
