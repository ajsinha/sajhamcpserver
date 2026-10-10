# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Generate the per-product pricing tool configs (config/tools/qlrisk/qlrisk_price_<product>.json).

    python -m sajha.tools.impl.qlrisk.generate            # write the configs, remove stale ones
    python -m sajha.tools.impl.qlrisk.generate --check    # exit 1 if the files differ from what it would write

It reads qlrisk's product registry at run time (introspect.product_classes / product_spec), builds a small
example trade for each product and prices it on qlrisk's sample market valued EXAMPLE_DATE. A product whose
example cannot be priced standalone is skipped and listed with the reason. Every config declares
"requires": ["qlrisk"] and names its product; the input schema is built from qlrisk when the tool loads.
tests/tools/test_qlrisk_tools.py fails when the files on disk differ from what this would write now
(a qlrisk upgrade that changes products): run it again to regenerate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[4]
OUT_DIR = ROOT / "config" / "tools" / "qlrisk"
IMPLEMENTATION = "sajha.tools.impl.qlrisk.qlrisk_tools.QlriskPriceProductTool"
EXAMPLE_DATE = "2026-10-09"          # the valuation date the examples are checked on (fixed: output is stable)

# example values for required fields, by name; dates are after EXAMPLE_DATE
EXAMPLE_VALUES: Dict[str, Any] = {
    "fixed_rate": 0.04, "fra_rate": 0.04, "strike": 0.04, "forward_rate": 1.10, "near_rate": 1.10,
    "far_rate": 1.11, "base_currency": "EUR", "quote_currency": "USD", "base_notional": 1_000_000,
    "fixing_date": "2027-10-07", "settlement_date": "2027-10-11", "near_date": "2027-01-11",
    "far_date": "2027-10-11", "option_expiry": "2027-10-11", "swap_effective": "2027-10-13",
    "swap_maturity": "2032-10-13",
}
OPTIONAL_EXAMPLE_TERMS = {"coupon": 0.05}     # shown when the product reads it, for a realistic example


def _example(product: str) -> Dict[str, Any]:
    from .tools.products import required_fields, trade_properties
    props = trade_properties(product)
    ex: Dict[str, Any] = {}
    if "notional" in props:
        ex["notional"] = 1_000_000
    if "tenor_years" in props:
        ex["tenor_years"] = 5
    for name, value in OPTIONAL_EXAMPLE_TERMS.items():
        t = props.get(name, {}).get("type")
        if t == "number" or (isinstance(t, list) and "number" in t):
            ex[name] = value
    for name in required_fields(product):
        if name in ex:
            continue
        if name in EXAMPLE_VALUES:
            ex[name] = EXAMPLE_VALUES[name]
        elif "enum" in props.get(name, {}):
            ex[name] = props[name]["enum"][0]
        elif "default" in props.get(name, {}):
            ex[name] = props[name]["default"]
        else:
            raise ValueError(f"no example value for the required field {name!r}")
    return ex


def _describe(product: str, example: Dict[str, Any]) -> str:
    from . import introspect as I
    from .tools.products import required_fields, trade_properties
    spec = I.product_spec(product)
    req = required_fields(product)
    terms = sorted(spec["terms"])
    where = ", ".join(x for x in (spec["category"], spec["asset_class"]) if x)
    text = (f"Price one qlrisk {product} ({spec['description'].rstrip('.')}; {where}): NPV in the trade currency and "
            f"the reporting currency, pricing components, analytic Greeks where the pricer gives them, and optional "
            f"cash flows. Inputs are this product's fields only")
    text += f"; required: {', '.join(req)}" if req else "; none required"
    if "tenor_years" in trade_properties(product):
        text += " (maturity_date or tenor_years)"
    if terms:
        text += f"; pricer terms: {', '.join(terms)}"
    text += (". Market data defaults to qlrisk's sample snapshot valued today; override curves, spots and vols, or "
             "apply shocks, with market_data as in qlrisk_price_trades. For a book of several products use "
             f"qlrisk_price_trades. Example: {json.dumps(example)}.")
    return text


def _priceable(product: str, example: Dict[str, Any]) -> None:
    """Raise when the example does not fit the tool's schema or does not price standalone on the sample market."""
    import jsonschema
    from .options import Limits
    from .tools import Ctx
    from .tools.products import price_one, product_tool
    jsonschema.validate(example, product_tool(product, Limits()).input_schema)
    price_one(product, {**example, "market_data": {"valuation_date": EXAMPLE_DATE}}, Ctx(Limits()))


def build() -> Tuple[Dict[str, Dict[str, Any]], List[Tuple[str, str]]]:
    """(file name -> config, [(product, reason skipped)])."""
    from . import introspect as I
    from .qlrisk_tools import quiet_qlrisk
    from .tools.products import tool_name
    quiet_qlrisk()
    configs: Dict[str, Dict[str, Any]] = {}
    skipped: List[Tuple[str, str]] = []
    for product in I.product_classes():
        name = tool_name(product)
        if "__" in name or f"{name}.json" in configs:
            skipped.append((product, f"tool name {name} is not unique or contains '__'"))
            continue
        try:
            example = _example(product)
            _priceable(product, example)
        except Exception as exc:
            skipped.append((product, f"{type(exc).__name__}: {exc}"))
            continue
        spec = I.product_spec(product)
        configs[f"{name}.json"] = {
            "name": name,
            "implementation": IMPLEMENTATION,
            "product": product,
            "title": f"Price a {product}",
            "description": _describe(product, example),
            "version": "1.0.0",
            "enabled": True,
            "requires": ["qlrisk"],
            "outputSchema": {"type": "object"},
            "annotations": {"title": f"Price a {product}", "readOnlyHint": True, "destructiveHint": False,
                            "idempotentHint": True, "openWorldHint": False},
            "metadata": {"author": "Ashutosh Sinha", "email": "ajsinha@gmail.com",
                         "copyright": "Copyright All rights Reserved 2025-2030, Ashutosh Sinha",
                         "category": "Risk Analytics", "provider": "qlrisk",
                         "tags": ["qlrisk", "pricing", spec["category"]], "generated_by": "sajha.tools.impl.qlrisk.generate",
                         "example": example},
        }
    return configs, skipped


def render(config: Dict[str, Any]) -> str:
    return json.dumps(config, indent=2) + "\n"


def existing(out_dir: Path = OUT_DIR) -> Dict[str, str]:
    """The generated configs on disk (file name -> text): those whose implementation is the product tool."""
    out = {}
    for f in sorted(out_dir.glob("*.json")):
        text = f.read_text(encoding="utf-8")
        try:
            if json.loads(text).get("implementation") == IMPLEMENTATION:
                out[f.name] = text
        except ValueError:
            continue
    return out


def differences(out_dir: Path = OUT_DIR) -> List[str]:
    configs, _ = build()
    want = {n: render(c) for n, c in configs.items()}
    have = existing(out_dir)
    diffs = [f"missing {n}" for n in sorted(set(want) - set(have))]
    diffs += [f"stale {n}" for n in sorted(set(have) - set(want))]
    diffs += [f"changed {n}" for n in sorted(set(want) & set(have)) if want[n] != have[n]]
    return diffs


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m sajha.tools.impl.qlrisk.generate",
                                description="Generate the qlrisk per-product pricing tool configs")
    p.add_argument("--check", action="store_true", help="report differences and exit 1 if any; write nothing")
    p.add_argument("--out", default=str(OUT_DIR), help="output folder (default config/tools/qlrisk)")
    args = p.parse_args(argv)
    out_dir = Path(args.out)
    configs, skipped = build()
    for product, reason in skipped:
        print(f"skipped {product}: {reason}")
    if args.check:
        diffs = differences(out_dir)
        for d in diffs:
            print(d)
        print("up to date" if not diffs else f"{len(diffs)} difference(s); run without --check to regenerate")
        return 1 if diffs else 0
    out_dir.mkdir(parents=True, exist_ok=True)
    have = existing(out_dir)
    for name in sorted(set(have) - set(configs)):
        (out_dir / name).unlink()
        print(f"removed {name}")
    written = 0
    for name, cfg in configs.items():
        text = render(cfg)
        if have.get(name) != text:
            (out_dir / name).write_text(text, encoding="utf-8")
            written += 1
    print(f"{len(configs)} product tool config(s) in {out_dir}; {written} written; {len(skipped)} product(s) skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
