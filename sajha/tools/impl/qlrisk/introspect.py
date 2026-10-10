# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
What qlrisk offers, read from the installed qlrisk at runtime.

Product lists, product terms, calculator inputs and configuration, enumerations, stress scenarios,
stochastic processes and market-data fields all come from qlrisk's own classes, signatures,
dataclasses and enums, so upgrading qlrisk updates the tool schemas without a change here.

Product terms that qlrisk passes as keyword arguments are found in the source of the product's
pricer (``_p(product, "coupon", 0.05)`` and ``additional_params.get/setdefault("strike", ...)``).
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import re
import typing
from datetime import date
from enum import Enum
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

COMMON_PARAMS = ("trade_id", "trade_date", "effective_date", "maturity_date", "notional", "currency",
                 "counterparty_id")

# ── JSON Schema from Python annotations ─────────────────────────────


def _unwrap_optional(tp):
    origin = typing.get_origin(tp)
    if origin is typing.Union or (origin is not None and getattr(origin, "__name__", "") == "UnionType"):
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        return args
    import types as _types
    if isinstance(tp, _types.UnionType):
        return [a for a in tp.__args__ if a is not type(None)]
    return None


def annotation_schema(tp: Any, _depth: int = 0) -> Dict[str, Any]:
    """JSON Schema for a Python annotation (enums carry their values; dates are ISO strings)."""
    if tp is inspect.Parameter.empty or tp is Any or _depth > 4:
        return {}
    union = _unwrap_optional(tp)
    if union is not None:
        if len(union) == 1:
            inner = dict(annotation_schema(union[0], _depth + 1))
            if isinstance(inner.get("type"), str) and inner["type"] not in ("object", "array"):
                inner["type"] = [inner["type"], "null"]            # Optional[X]: null is a valid value
                if "enum" in inner:
                    inner["enum"] = inner["enum"] + [None]
            return inner
        dcs = [a for a in union if dataclasses.is_dataclass(a)]
        if dcs:
            return annotation_schema(dcs[0], _depth + 1)
        return {"anyOf": [annotation_schema(a, _depth + 1) or {} for a in union]}
    if inspect.isclass(tp):
        if issubclass(tp, Enum):
            return {"type": "string", "enum": [str(e.value) for e in tp]}
        if tp is bool:
            return {"type": "boolean"}
        if tp is int:
            return {"type": "integer"}
        if tp is float:
            return {"type": "number"}
        if tp is str:
            return {"type": "string"}
        if issubclass(tp, date):
            return {"type": "string", "format": "date"}
        if dataclasses.is_dataclass(tp):
            return dataclass_schema(tp, _depth + 1)
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin in (list, tuple, set, typing.List, typing.Sequence) or (origin is not None and getattr(origin, "__name__", "") in ("Sequence", "Iterable", "List")):
        item = annotation_schema(args[0], _depth + 1) if args else {}
        return {"type": "array", "items": item} if item else {"type": "array"}
    if origin in (dict, typing.Dict) or (origin is not None and getattr(origin, "__name__", "") == "Mapping"):
        val = annotation_schema(args[1], _depth + 1) if len(args) == 2 else {}
        return {"type": "object", "additionalProperties": val} if val else {"type": "object"}
    return {}


def _field_type(cls, f):
    try:
        return typing.get_type_hints(cls).get(f.name, f.type)
    except Exception:
        return f.type


def _default_of(f) -> Tuple[bool, Any]:
    if f.default is not dataclasses.MISSING:
        return True, f.default
    if f.default_factory is not dataclasses.MISSING:          # type: ignore[misc]
        try:
            return True, f.default_factory()                   # type: ignore[misc]
        except Exception:
            return True, None
    return False, None


def _json_default(value: Any) -> Any:
    from .jsonable import to_jsonable
    return to_jsonable(value)


def dataclass_schema(cls, _depth: int = 0, exclude: Tuple[str, ...] = ()) -> Dict[str, Any]:
    props, required = {}, []
    for f in dataclasses.fields(cls):
        if f.name in exclude or not f.init:
            continue
        s = dict(annotation_schema(_field_type(cls, f), _depth + 1))
        has_default, default = _default_of(f)
        if has_default:
            if default is not None and not callable(default):
                s["default"] = _json_default(default)
        else:
            required.append(f.name)
        props[f.name] = s
    out = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        out["required"] = required
    return out


def field_summary(cls, exclude: Tuple[str, ...] = ()) -> str:
    """'name (type, default x)' list for a description."""
    parts = []
    schema = dataclass_schema(cls, exclude=exclude)
    for name, s in schema["properties"].items():
        t = s.get("type") or ("object" if "properties" in s else "any")
        bit = f"{name} ({t}"
        if "enum" in s:
            bit += " " + "|".join(s["enum"])
        if name in schema.get("required", []):
            bit += ", required"
        elif "default" in s and s["default"] not in ({}, []):
            bit += f", default {s['default']}"
        parts.append(bit + ")")
    return "; ".join(parts)


# ── products ────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def product_classes() -> Dict[str, type]:
    import qlrisk.products.python as P
    from qlrisk.products.base import BaseProduct
    out = {}
    for name in getattr(P, "__all__", dir(P)):
        obj = getattr(P, name, None)
        if inspect.isclass(obj) and issubclass(obj, BaseProduct) and obj is not BaseProduct:
            out[name] = obj
    return dict(sorted(out.items()))


_TERM_PATTERNS = (
    re.compile(r"_p\(\s*product\s*,\s*[\"'](\w+)[\"']\s*(?:,\s*([^()]*?(?:\([^()]*\))?[^()]*?))?\)"),
    re.compile(r"additional_params\.(?:get|setdefault)\(\s*[\"'](\w+)[\"']\s*(?:,\s*([^()]*?(?:\([^()]*\))?[^()]*?))?\)"),
    re.compile(r"kwargs\.(?:get|pop)\(\s*[\"'](\w+)[\"']\s*(?:,\s*([^()]*?(?:\([^()]*\))?[^()]*?))?\)"),
)
_HELPER = re.compile(r"\b(_[a-z]\w*)\(\s*product\b")


def _literal(text: Optional[str]) -> Tuple[bool, Any]:
    if text is None or not text.strip():
        return True, None
    try:
        return True, ast.literal_eval(text.strip().replace("_", "") if re.fullmatch(r"[\d_.eE+-]+", text.strip()) else text.strip())
    except Exception:
        return False, None


def _scan_terms(src: str, terms: Dict[str, Dict[str, Any]]) -> None:
    for pat in _TERM_PATTERNS:
        for m in pat.finditer(src):
            name, default_text = m.group(1), m.group(2)
            if name in terms or name in COMMON_PARAMS:
                continue
            ok, default = _literal(default_text)
            entry: Dict[str, Any] = {}
            if ok and default is not None:
                if isinstance(default, bool):
                    entry["type"] = "boolean"
                elif isinstance(default, (int, float)):
                    entry["type"] = "number"
                elif isinstance(default, str):
                    entry["type"] = "string"
                entry["default"] = default
            elif default_text and not ok:
                text = default_text.strip()
                # a computed default: numeric unless it is built from a string (f-string, quotes)
                entry["type"] = "string" if re.search(r"^f?[\"']|[\"']", text) else "number"
                entry["description"] = f"default computed by qlrisk: {text}"
            else:
                entry["type"] = ["string", "number", "boolean"]
            terms[name] = entry


@lru_cache(maxsize=None)
def product_spec(name: str) -> Dict[str, Any]:
    """Constructor parameters and keyword terms of one product class."""
    from qlrisk.products.base import AssetClass, BaseProduct, ProductType
    from qlrisk.products.python import _pricing
    cls = product_classes()[name]
    try:
        src = inspect.getsource(cls)
    except (OSError, TypeError):
        src = ""
    try:
        hints = typing.get_type_hints(cls.__init__)
    except Exception:
        hints = {}
    params, required, takes_kwargs = {}, [], False
    for p in list(inspect.signature(cls.__init__).parameters.values())[1:]:
        if p.kind is inspect.Parameter.VAR_KEYWORD:
            takes_kwargs = True
            continue
        if p.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        s = dict(annotation_schema(hints.get(p.name, p.annotation)))
        if p.default is inspect.Parameter.empty:
            required.append(p.name)
        elif p.default is not None and not callable(p.default):
            s["default"] = _json_default(p.default)
        params[p.name] = s
    m = re.search(r"return (price_\w+)\(self, market_data\)", src)
    pricer = m.group(1) if m else "custom"
    terms: Dict[str, Dict[str, Any]] = {}
    if m and hasattr(_pricing, pricer):
        fn_src = inspect.getsource(getattr(_pricing, pricer))
        _scan_terms(fn_src, terms)
        seen = set()
        for helper in _HELPER.findall(fn_src):
            if helper in seen or not hasattr(_pricing, helper):
                continue
            seen.add(helper)
            _scan_terms(inspect.getsource(getattr(_pricing, helper)), terms)
    _scan_terms(src, terms)
    for p in params:
        terms.pop(p, None)
    terms.pop("netting_set_id", None)
    terms.pop("csa_id", None)
    pt = re.search(r"product_type\s*=\s*ProductType\.(\w+)", src)
    ac = re.search(r"asset_class\s*=\s*AssetClass\.(\w+)", src)
    module = cls.__module__.split(".")
    category = module[3] if len(module) > 3 else module[-1]
    doc = (inspect.getdoc(cls) or "").strip().splitlines()
    return {
        "name": name,
        "category": category,
        "product_type": ProductType[pt.group(1)].value if pt and pt.group(1) in ProductType.__members__ else None,
        "asset_class": AssetClass[ac.group(1)].value if ac and ac.group(1) in AssetClass.__members__ else None,
        "description": doc[0] if doc else name,
        "pricer": pricer,
        "parameters": params,
        "required": required,
        "terms": terms,
        "accepts_extra_terms": takes_kwargs,
    }


def product_schema(name: str) -> Dict[str, Any]:
    spec = product_spec(name)
    props = {"product": {"const": name}}
    props.update(spec["parameters"])
    props.update(spec["terms"])
    req = [r for r in spec["required"] if r not in ("trade_id", "trade_date", "effective_date", "counterparty_id",
                                                     "currency", "maturity_date")]
    return {"type": "object", "properties": props, "required": ["product", *req]}


# ── calculators ─────────────────────────────────────────────────────

# tool measure -> (CalculatorType member, input dataclass name, post-processing tag)
CALCULATORS: Dict[str, Tuple[str, str]] = {
    "pd": ("PD", "PDInput"),
    "lgd": ("LGD", "LGDInput"),
    "ead": ("EAD", "EADInput"),
    "el": ("EL", "ELInput"),
    "economic_capital": ("EC", "ECInput"),
    "raroc": ("RAROC", "RAROCInput"),
    "ce": ("CE", "CEInput"),
    "ee": ("EE", "EEInput"),
    "eee": ("EE", "EEInput"),
    "pfe": ("PFE", "PFEInput"),
    "peak": ("PEAK_EXPOSURE", "PeakExposureInput"),
    "stressed": ("STRESSED_EXPOSURE", "StressedExposureInput"),
    "cva": ("CVA", "CVAInput"),
    "dva": ("DVA", "DVAInput"),
    "fva": ("FVA", "FVAInput"),
    "kva": ("KVA", "KVAInput"),
    "mva": ("MVA", "MVAInput"),
    "initial_margin": ("IM", "IMInput"),
    "saccr": ("SACCR", "SACCRInput"),
}

_CFG_GET = re.compile(r"config\.get\(\s*[\"'](\w+)[\"']\s*,\s*([^)\n]+?)\)\s*\)?\s*(?:#.*)?$", re.M)


@lru_cache(maxsize=None)
def calculator_class(measure: str):
    from qlrisk.calculator import CalculatorFactory, CalculatorType, ImplementationType
    ct_name, _ = CALCULATORS[measure]
    ct = CalculatorType[ct_name]
    factory = CalculatorFactory.get_instance()
    cls = factory._registry.get((ct, ImplementationType.PYTHON))
    if cls is None:
        raise LookupError(f"qlrisk has no Python calculator for {ct.value}")
    return ct, cls


@lru_cache(maxsize=None)
def calculator_input_class(measure: str):
    _, cls = calculator_class(measure)
    module = inspect.getmodule(cls)
    return getattr(module, CALCULATORS[measure][1])


@lru_cache(maxsize=None)
def calculator_config(measure: str) -> Dict[str, Dict[str, Any]]:
    """Configuration keys a calculator reads (config.get('key', default)), with enums where the code has them."""
    _, cls = calculator_class(measure)
    module = inspect.getmodule(cls)
    src = inspect.getsource(cls)
    init_src = inspect.getsource(cls.__init__)
    out: Dict[str, Dict[str, Any]] = {}
    for m in _CFG_GET.finditer(init_src):
        key, default_text = m.group(1), m.group(2).strip()
        entry: Dict[str, Any] = {}
        enum_ref = re.search(r"(\w+)\.(\w+)\.value$", default_text)
        wrapper = re.search(rf"(\w+)\(\s*config\.get\(\s*[\"']{key}[\"']", init_src)
        enum_cls = None
        for cand in ((wrapper.group(1) if wrapper else None), (enum_ref.group(1) if enum_ref else None)):
            obj = getattr(module, cand, None) if cand else None
            if inspect.isclass(obj) and issubclass(obj, Enum):
                enum_cls = obj
                break
        if enum_cls is not None:
            entry = {"type": "string", "enum": [str(e.value) for e in enum_cls]}
            if enum_ref:
                entry["default"] = str(enum_cls[enum_ref.group(2)].value)
        else:
            ok, default = _literal(default_text)
            if ok and default is not None:
                entry["default"] = default
                entry["type"] = ("boolean" if isinstance(default, bool) else "number" if isinstance(default, (int, float))
                                 else "string")
                if isinstance(default, str):
                    attr = re.search(rf"self\.(_?\w+)\s*=\s*config\.get\(\s*[\"']{key}[\"']", init_src)
                    vals = set()
                    if attr:
                        for v in re.findall(rf"self\.{attr.group(1)}\s*==\s*[\"']([\w\-]+)[\"']", src):
                            vals.add(v)
                    if vals:
                        vals.add(default)
                        entry["enum"] = sorted(vals)
            else:
                entry["type"] = ["number", "string", "boolean"]
        out[key] = entry
    return out


def calculator_summary(measure: str) -> Dict[str, Any]:
    ct, cls = calculator_class(measure)
    inp = calculator_input_class(measure)
    return {
        "measure": measure,
        "calculator_type": ct.value,
        "calculator": cls.__name__,
        "description": (inspect.getdoc(cls) or "").strip().splitlines()[0] if inspect.getdoc(cls) else cls.__name__,
        "input_schema": dataclass_schema(inp),
        "config": calculator_config(measure),
    }


# ── enumerations, stress scenarios, processes, market data ──────────


@lru_cache(maxsize=1)
def enumerations() -> Dict[str, List[str]]:
    from qlrisk.calculator import CalculatorType
    from qlrisk.mathlib import ProcessType
    from qlrisk.models.limit import LimitStatus
    from qlrisk.products import base as B
    from qlrisk.riskfactors import FactorKind, RiskClass, ShockType
    from qlrisk.sensitivities import SensitivityMeasure
    enums = {
        "Currency": B.Currency, "AssetClass": B.AssetClass, "ProductType": B.ProductType,
        "DayCountConvention": B.DayCountConvention, "PaymentFrequency": B.PaymentFrequency,
        "BusinessDayConvention": B.BusinessDayConvention, "OptionType": B.OptionType, "OptionStyle": B.OptionStyle,
        "BarrierType": B.BarrierType, "SettlementType": B.SettlementType, "FloatingRateIndex": B.FloatingRateIndex,
        "CreditEventType": B.CreditEventType, "RiskClass": RiskClass, "FactorKind": FactorKind, "ShockType": ShockType,
        "SensitivityMeasure": SensitivityMeasure, "CalculatorType": CalculatorType, "ProcessType": ProcessType,
        "LimitStatus": LimitStatus,
    }
    return {k: [str(e.value) for e in v] for k, v in enums.items()}


def enum_values(name: str) -> List[str]:
    return enumerations()[name]


@lru_cache(maxsize=1)
def stress_library() -> Dict[str, Any]:
    from qlrisk.scenarios import STRESS_LIBRARY
    from .jsonable import to_jsonable
    return {k: to_jsonable(v) for k, v in STRESS_LIBRARY.items()}


@lru_cache(maxsize=1)
def stress_definition_schema() -> Dict[str, Any]:
    from qlrisk.scenarios import StressDefinition
    schema = dataclass_schema(StressDefinition, exclude=("name",))
    schema.pop("required", None)              # description defaults to the scenario name
    return schema


@lru_cache(maxsize=1)
def supported_processes() -> List[str]:
    """Stochastic processes the Python path generator actually supports (probed with a 2-path run)."""
    from qlrisk.mathlib import MathFactory, PathGenerationParams, ProcessType
    gen = MathFactory.get_instance().create_path_generator(implementation="python")
    ok = []
    for p in ProcessType:
        try:
            gen.generate_paths(PathGenerationParams(initial_value=0.03, num_steps=1, num_paths=2, seed=1,
                                                    long_term_mean=0.03), p)
            ok.append(str(p.value))
        except Exception:
            continue
    return ok


@lru_cache(maxsize=1)
def path_params_schema() -> Dict[str, Any]:
    from qlrisk.mathlib import PathGenerationParams
    return dataclass_schema(PathGenerationParams)


@lru_cache(maxsize=1)
def market_data_fields() -> Dict[str, str]:
    """MarketData field -> shape: 'curve' (tenor -> value), 'named_curves', 'scalars', 'surfaces' or 'date'."""
    from qlrisk.products.base import MarketData
    out = {}
    for f in dataclasses.fields(MarketData):
        t = str(_field_type(MarketData, f)).replace("typing.", "")
        if f.name == "valuation_date":
            out[f.name] = "date"
        elif f.name == "correlation_matrix":
            out[f.name] = "matrix"
        elif f.name == "volatility_surfaces":
            out[f.name] = "surfaces"
        elif "Dict[str, Dict[float, float]]" in t or "dict[str, dict[float, float]]" in t:
            out[f.name] = "named_curves"
        elif "Dict[float, float]" in t or "dict[float, float]" in t:
            out[f.name] = "curve"
        elif "Dict[str, float]" in t or "dict[str, float]" in t:
            out[f.name] = "scalars"
        else:
            out[f.name] = "object"
    return out


@lru_cache(maxsize=1)
def report_measures() -> Dict[str, List[str]]:
    from qlrisk.engine import ALL_MEASURES, DEFAULT_MEASURES
    return {"all": list(ALL_MEASURES), "default": list(DEFAULT_MEASURES)}


@lru_cache(maxsize=1)
def ba_cva_sectors() -> List[str]:
    from qlrisk.regulatory.cva_capital import BA_CVA_RW
    return list(BA_CVA_RW)


@lru_cache(maxsize=1)
def dataclass_by_path(path: str):
    module, _, name = path.rpartition(".")
    import importlib
    return getattr(importlib.import_module(module), name)
