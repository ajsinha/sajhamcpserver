# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Request inputs shared by the tools: market data, shocks, trades and factor histories.

Each comes with its JSON Schema fragment (enums from qlrisk) and a parser that turns the JSON a
model sends into qlrisk objects, raising InvalidInput with a message that says what to fix.
"""

from __future__ import annotations

import copy
import dataclasses
import inspect
import typing
from datetime import date, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import introspect as I
from .options import Limits


class InvalidInput(ValueError):
    """The request cannot be run as given; the message says why and what to send instead."""


# ── schema fragments ────────────────────────────────────────────────

TENOR_MAP = {"type": "object", "additionalProperties": {"type": "number"}}


def market_data_schema() -> Dict[str, Any]:
    props: Dict[str, Any] = {"base": {"type": "string", "enum": ["sample", "empty"], "default": "sample"}}
    for name, shape in I.market_data_fields().items():
        if shape == "date":
            props[name] = {"type": "string", "format": "date"}
        elif shape == "curve":
            props[name] = dict(TENOR_MAP)
        elif shape == "named_curves":
            props[name] = {"type": "object", "additionalProperties": TENOR_MAP}
        elif shape == "scalars":
            props[name] = {"type": "object", "additionalProperties": {"type": "number"}}
        elif shape == "surfaces":
            props[name] = {"type": "object", "additionalProperties": {"anyOf": [{"type": "number"}, TENOR_MAP]}}
        elif shape == "matrix":
            props[name] = {"type": "array", "items": {"type": "array", "items": {"type": "number"}}}
    props["shocks"] = {"type": "array", "items": shock_schema(compact=True)}
    return {"type": "object", "properties": props, "additionalProperties": False,
            "description": "Market data; omit for qlrisk's sample snapshot valued today. base 'sample' (default) overlays what you "
                           "send on the sample (USD discount curve; SOFR/ESTR/SONIA; EURUSD, GBPUSD, USDJPY; AAPL, MSFT, SPX; "
                           "credit curves ACME, GLOBEX, INITECH; WTI, BRENT, GOLD, NATGAS); 'empty' uses only what you send. "
                           "Curves are tenor -> value with tenor keys in years ('5') or labels ('6M', '5Y'); a named curve "
                           "you send replaces that curve; vol surfaces are flat numbers or tenor -> vol. valuation_date "
                           "defaults to today. shocks (same shape as stress_test shocks) are applied after the overlay."}


def shock_schema(compact: bool = False) -> Dict[str, Any]:
    d = (lambda text: {}) if compact else (lambda text: {"description": text})
    return {
        "type": "object",
        "properties": {
            "factor": {"type": "string", **d("Risk-factor key, e.g. 'EQ.SPX', 'FX.EURUSD', 'IR.FWD.SOFR.5Y', 'CR.ACME.5Y' (qlrisk_catalog topic 'market_data' lists them).")},
            "size": {"type": "number", **d("Absolute shocks in decimals (0.0025 = 25bp); relative 0.1 = +10%.")},
            "shock_type": {"type": "string", "enum": I.enum_values("ShockType"), "default": "absolute"},
            "curve_field": {"type": "string", "enum": [k for k, v in I.market_data_fields().items() if v in ("curve", "named_curves", "surfaces")],
                            **d("Shock a whole curve (with curve_name and shape) instead of one factor.")},
            "curve_name": {"type": "string", **d("Curve within curve_field, e.g. 'SOFR'.")},
            "risk_classes": {"type": "array", "items": {"type": "string", "enum": I.enum_values("RiskClass")},
                             **d("Shock every tenored curve of these risk classes with the shape.")},
            "shape": {"type": "string", "enum": ["parallel", "twist", "butterfly"], "default": "parallel"},
            "short_end": {"type": "number"}, "long_end": {"type": "number"},
            "wings": {"type": "number"}, "belly": {"type": "number"},
        },
        "additionalProperties": False,
        **d("One factor (factor, size) or a curve shape: parallel (size), twist (short_end, long_end at 2y/10y), "
            "butterfly (wings, belly)."),
    }


def trade_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "product": {"type": "string", "enum": list(I.product_classes()),
                        "description": "qlrisk product class (qlrisk_catalog topic 'products' lists each with its inputs)."},
            "maturity": {"type": "string", "description": "A tenor (3Y, 18M, 6W, 10D) or a date YYYY-MM-DD."},
            "trade_id": {"type": "string"},
            "counterparty_id": {"type": "string"},
            "netting_set_id": {"type": "string"},
        },
        "required": ["product"],
        "additionalProperties": True,
        "description": "A trade: product plus the inputs of its qlrisk_price_<product> tool, flat, in the same units: "
                       "rates in percent (fixed_rate_pct 4.4 = 4.4%), spreads in basis points, maturity as a tenor or "
                       "a date, the amount named for the product (face_value, notional ...), and its trade fields "
                       "(trade_id, counterparty_id, issuer, position ...) at the same level. trade_id defaults to "
                       "<product>-<n>, trade and effective dates to the valuation date, netting_set_id to "
                       "counterparty_id. Each trade is checked against its product's inputs.",
    }


def trades_schema(limits: Limits) -> Dict[str, Any]:
    return {"type": "array", "items": trade_schema(), "minItems": 1, "maxItems": limits.max_trades}


def history_schema(limits: Limits) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "source": {"type": "string", "enum": ["synthetic", "supplied"], "default": "synthetic"},
            "seed": {"type": "integer", "default": 7},
            "num_days": {"type": "integer", "minimum": 30, "maximum": limits.max_history_days, "default": 750},
            "stress_start": {"type": "integer", "minimum": 0, "default": 300},
            "stress_days": {"type": "integer", "minimum": 0, "default": 60},
            "dates": {"type": "array", "items": {"type": "string", "format": "date"}},
            "factors": {"type": "array", "items": {"type": "string"}},
            "values": {"type": "array", "items": {"type": "array", "items": {"type": ["number", "null"]}}},
        },
        "additionalProperties": False,
        "description": "Risk-factor history. Omit for qlrisk's synthetic, correlated, fat-tailed 750-day history ending at "
                       "the market data, with a 60-day stress regime from row 300. 'supplied': dates (oldest first), factor "
                       "keys and one row of levels (not returns) per date.",
    }


# ── parsing helpers ─────────────────────────────────────────────────

def parse_date(value: Any, what: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise InvalidInput(f"{what}: {value!r} is not a date; use YYYY-MM-DD") from None


def parse_tenor(key: Any) -> float:
    from qlrisk.riskfactors import parse_tenor as _pt
    if isinstance(key, (int, float)):
        return float(key)
    text = str(key).strip()
    try:
        return float(text)
    except ValueError:
        pass
    try:
        return float(_pt(text.upper()))
    except Exception:
        raise InvalidInput(f"tenor {key!r} is neither a number of years nor a label like '6M' or '5Y'") from None


def _curve(value: Any, what: str) -> Dict[float, float]:
    if not isinstance(value, dict):
        raise InvalidInput(f"{what} must be an object of tenor -> value")
    return {parse_tenor(k): float(v) for k, v in value.items()}


def build_market_data(spec: Optional[Dict[str, Any]], default_date: Optional[date] = None):
    """MarketData from the request (sample snapshot overlaid by what was sent, then shocked)."""
    import numpy as np
    from qlrisk.data import create_sample_market_data
    from qlrisk.products.base import MarketData
    spec = dict(spec or {})
    vd = parse_date(spec["valuation_date"], "market_data.valuation_date") if spec.get("valuation_date") else (default_date or date.today())
    base = spec.get("base", "sample")
    md = create_sample_market_data(vd) if base == "sample" else MarketData(valuation_date=vd)
    for name, shape in I.market_data_fields().items():
        if name not in spec or name == "valuation_date":
            continue
        value = spec[name]
        where = f"market_data.{name}"
        if shape == "curve":
            setattr(md, name, _curve(value, where))
        elif shape == "named_curves":
            if not isinstance(value, dict):
                raise InvalidInput(f"{where} must be an object of name -> curve")
            target = getattr(md, name)
            for k, v in value.items():
                target[k] = _curve(v, f"{where}.{k}")
        elif shape == "scalars":
            if not isinstance(value, dict):
                raise InvalidInput(f"{where} must be an object of name -> number")
            getattr(md, name).update({k: float(v) for k, v in value.items()})
        elif shape == "surfaces":
            target = getattr(md, name)
            for k, v in (value or {}).items():
                target[k] = float(v) if isinstance(v, (int, float)) else _curve(v, f"{where}.{k}")
        elif shape == "matrix":
            md.correlation_matrix = np.array(value, dtype=float)
    if spec.get("shocks"):
        md = apply_shock_list(md, spec["shocks"], "market_data.shocks")
    return md


def parse_shocks(md, items: Sequence[Dict[str, Any]], where: str = "shocks") -> list:
    """Shock objects (single-factor or whole-curve) for a market snapshot."""
    from qlrisk.riskfactors import RiskClass, Shock, ShockType, as_key, butterfly, curve_shocks, parallel, twist
    out = []
    for i, item in enumerate(items or []):
        w = f"{where}[{i}]"
        try:
            st = ShockType(item.get("shock_type", "absolute"))
        except ValueError:
            raise InvalidInput(f"{w}.shock_type must be one of {I.enum_values('ShockType')}") from None
        if item.get("factor"):
            if "size" not in item:
                raise InvalidInput(f"{w}: a factor shock needs 'size'")
            try:
                key = as_key(item["factor"])
            except Exception as exc:
                raise InvalidInput(f"{w}.factor {item['factor']!r} is not a risk-factor key ({exc})") from None
            out.append(Shock(key, float(item["size"]), st))
            continue
        if not (item.get("curve_field") or item.get("risk_classes")):
            raise InvalidInput(f"{w}: give 'factor' (one factor) or 'curve_field' / 'risk_classes' (a curve shape)")
        shape = item.get("shape", "parallel")
        if shape == "parallel":
            if "size" not in item:
                raise InvalidInput(f"{w}: a parallel shock needs 'size'")
            fn = parallel(float(item["size"]))
        elif shape == "twist":
            if "short_end" not in item or "long_end" not in item:
                raise InvalidInput(f"{w}: a twist needs 'short_end' and 'long_end'")
            fn = twist(float(item["short_end"]), float(item["long_end"]))
        elif shape == "butterfly":
            if "wings" not in item or "belly" not in item:
                raise InvalidInput(f"{w}: a butterfly needs 'wings' and 'belly'")
            fn = butterfly(float(item["wings"]), float(item["belly"]))
        else:
            raise InvalidInput(f"{w}.shape must be parallel, twist or butterfly")
        rcs = [RiskClass(r) for r in item["risk_classes"]] if item.get("risk_classes") else None
        shocks = curve_shocks(md, item.get("curve_field"), item.get("curve_name"), fn, st, risk_classes=rcs)
        if not shocks:
            raise InvalidInput(f"{w}: no factors match curve_field={item.get('curve_field')!r} curve_name={item.get('curve_name')!r}")
        out.extend(shocks)
    return out


def apply_shock_list(md, items, where="shocks"):
    from qlrisk.riskfactors import apply_shocks
    shocks = parse_shocks(md, items, where)
    if not shocks:
        return md
    try:
        return apply_shocks(md, shocks)
    except KeyError as exc:
        raise InvalidInput(f"{where}: factor not in the market data: {exc}") from None


# ── trades ──────────────────────────────────────────────────────────

def _coerce(value: Any, tp: Any, what: str) -> Any:
    if value is None:
        return None
    union = I._unwrap_optional(tp)
    if union is not None:
        last = None
        for alt in union:
            try:
                return _coerce(value, alt, what)
            except InvalidInput as exc:
                last = exc
        raise last or InvalidInput(f"{what}: unexpected value {value!r}")
    if inspect.isclass(tp):
        if issubclass(tp, Enum):
            if isinstance(value, tp):
                return value
            for e in tp:
                if str(value) == str(e.value) or str(value).upper() == e.name:
                    return e
            raise InvalidInput(f"{what}: {value!r} is not one of {[str(e.value) for e in tp]}")
        if tp is bool:
            if isinstance(value, bool):
                return value
            raise InvalidInput(f"{what}: expected true or false, got {value!r}")
        if tp in (int, float):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                try:
                    return tp(value)
                except (TypeError, ValueError):
                    raise InvalidInput(f"{what}: expected a number, got {value!r}") from None
            return tp(value)
        if tp is str:
            return str(value)
        if issubclass(tp, date):
            return parse_date(value, what)
        if dataclasses.is_dataclass(tp):
            if not isinstance(value, dict):
                raise InvalidInput(f"{what}: expected an object with fields {[f.name for f in dataclasses.fields(tp)]}")
            hints = typing.get_type_hints(tp)
            names = {f.name for f in dataclasses.fields(tp)}
            unknown = set(value) - names
            if unknown:
                raise InvalidInput(f"{what}: unknown field(s) {sorted(unknown)}; allowed {sorted(names)}")
            return tp(**{k: _coerce(v, hints.get(k), f"{what}.{k}") for k, v in value.items()})
        return value
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin in (list, tuple, set) or getattr(origin, "__name__", "") in ("Sequence", "Iterable", "List"):
        if not isinstance(value, list):
            raise InvalidInput(f"{what}: expected a list")
        return [_coerce(v, args[0] if args else Any, f"{what}[{i}]") for i, v in enumerate(value)]
    if origin is dict or getattr(origin, "__name__", "") == "Mapping":
        if not isinstance(value, dict):
            raise InvalidInput(f"{what}: expected an object")
        vt = args[1] if len(args) == 2 else Any
        return {k: _coerce(v, vt, f"{what}.{k}") for k, v in value.items()}
    return value


def build_trades(items: Sequence[Dict[str, Any]], md, limits: Limits, warnings: Optional[List[str]] = None,
                 human: bool = True) -> list:
    """qlrisk product objects from trade dicts (dates default to the valuation date). With human (the tools'
    trades), each trade is in the units of its qlrisk_price_<product> tool and is converted first."""
    if not items:
        raise InvalidInput("trades: send at least one trade")
    if len(items) > limits.max_trades:
        raise InvalidInput(f"trades: {len(items)} trades exceeds the bound max_trades={limits.max_trades}")
    classes = I.product_classes()
    vd = md.valuation_date
    out, seen = [], set()
    if human:
        from .tools.products import human_trade
        items = [human_trade(raw, f"trades[{i}]", vd, warnings if warnings is not None else [])
                 for i, raw in enumerate(items)]
    for i, raw in enumerate(items):
        w = f"trades[{i}]"
        if not isinstance(raw, dict) or "product" not in raw:
            raise InvalidInput(f"{w}: each trade is an object with 'product' (one of qlrisk_catalog's products)")
        item = dict(raw)
        name = item.pop("product")
        if name not in classes:
            lowered = {c.lower(): c for c in classes}
            by_type = {I.product_spec(c)["product_type"]: c for c in classes}
            name = lowered.get(str(name).lower()) or by_type.get(str(name).lower()) or name
            if name not in classes:
                raise InvalidInput(f"{w}.product {raw['product']!r} is not a qlrisk product; call qlrisk_catalog with topic 'products'")
        cls = classes[name]
        spec = I.product_spec(name)
        try:
            hints = typing.get_type_hints(cls.__init__)
        except Exception:
            hints = {}
        tenor = item.pop("tenor_years", None)
        item.setdefault("trade_id", f"{name}-{i + 1}")
        params = spec["parameters"]
        if "maturity_date" in params and "maturity_date" not in item and tenor is not None:
            item["maturity_date"] = (vd + timedelta(days=round(float(tenor) * 365.25))).isoformat()
        for dname in ("trade_date", "effective_date"):
            if dname in params:
                item.setdefault(dname, vd.isoformat())
        if "counterparty_id" in params:
            item.setdefault("counterparty_id", "CP-1")
        if "currency" in params:
            item.setdefault("currency", "USD")
        missing = [p for p in spec["required"] if p not in item]
        if missing:
            hint = " (or tenor_years)" if "maturity_date" in missing else ""
            raise InvalidInput(f"{w} ({name}): missing {missing}{hint}")
        if item["trade_id"] in seen:
            raise InvalidInput(f"{w}: duplicate trade_id {item['trade_id']!r}")
        seen.add(item["trade_id"])
        kwargs = {}
        for k, v in item.items():
            if k in params:
                kwargs[k] = _coerce(v, hints.get(k, Any), f"{w}.{k}")
            elif k in ("netting_set_id", "csa_id"):
                kwargs[k] = str(v)
            else:
                if k not in spec["terms"] and warnings is not None:
                    warnings.append(f"{w} ({name}): term {k!r} is not one qlrisk's pricer reads "
                                    f"(known: {sorted(spec['terms']) or 'none'}); passed through")
                kwargs[k] = _coerce_term(v, f"{w}.{k}")
        try:
            out.append(cls(**kwargs))
        except InvalidInput:
            raise
        except Exception as exc:
            raise InvalidInput(f"{w} ({name}): qlrisk rejected the trade: {type(exc).__name__}: {exc}") from None
    return out


def _coerce_term(value: Any, what: str) -> Any:
    """A keyword term keeps its JSON type; ISO date strings become dates only when the name says so."""
    if isinstance(what, str) and what.endswith("_date") and isinstance(value, str):
        return parse_date(value, what)
    return value


# ── histories ───────────────────────────────────────────────────────

def build_history(spec: Optional[Dict[str, Any]], md, limits: Limits):
    from qlrisk.data import MarketHistoryGenerator
    from qlrisk.riskfactors import RiskFactorTimeSeries
    spec = dict(spec or {})
    source = spec.get("source", "synthetic")
    if source == "supplied":
        dates, factors, values = spec.get("dates"), spec.get("factors"), spec.get("values")
        if not (dates and factors and values):
            raise InvalidInput("history: a supplied history needs dates, factors and values")
        if len(dates) > limits.max_history_days:
            raise InvalidInput(f"history: {len(dates)} dates exceeds max_history_days={limits.max_history_days}")
        if len(values) != len(dates) or any(len(r) != len(factors) for r in values):
            raise InvalidInput("history: values needs one row per date and one column per factor")
        import numpy as np
        vals = np.array([[np.nan if v is None else float(v) for v in row] for row in values])
        try:
            return RiskFactorTimeSeries([parse_date(d, "history.dates") for d in dates], factors, vals)
        except Exception as exc:
            raise InvalidInput(f"history: {exc}") from None
    num_days = int(spec.get("num_days", 750))
    if num_days > limits.max_history_days:
        raise InvalidInput(f"history.num_days {num_days} exceeds max_history_days={limits.max_history_days}")
    stress_start = spec.get("stress_start", 300 if num_days > 400 else None)
    stress_days = int(spec.get("stress_days", 60 if stress_start is not None else 0))
    if stress_start is not None and int(stress_start) + stress_days > num_days:
        raise InvalidInput("history: stress_start + stress_days must not exceed num_days")
    return MarketHistoryGenerator(seed=int(spec.get("seed", 7))).generate(
        md, num_days=num_days, stress_start=stress_start, stress_days=stress_days)


def check_paths(n: int, limits: Limits, what: str = "paths") -> int:
    n = int(n)
    if n < 1:
        raise InvalidInput(f"{what} must be at least 1")
    if n > limits.max_mc_paths:
        raise InvalidInput(f"{what}={n} exceeds the bound max_mc_paths={limits.max_mc_paths}")
    return n


def pv_in(trade, md, ccy: Optional[str]) -> Tuple[float, str, float]:
    """(PV in trade currency, that currency, PV in the reporting currency)."""
    from qlrisk.sensitivities import fx_convert
    res = trade.price(md)
    native = float(res.npv)
    if not ccy or res.currency == ccy:
        return native, res.currency, native
    return native, res.currency, float(fx_convert(md, native, res.currency, ccy))


def deep(obj):
    return copy.deepcopy(obj)
