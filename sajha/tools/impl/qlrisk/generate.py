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

This module also holds the one table that turns qlrisk's fields into the tools' human inputs: which name a
field is shown under, its unit (rates, probabilities, haircuts and volatilities in percent, spreads in basis
points, horizons in years or days), the conversion to qlrisk's own units (qlrisk takes decimals: 0.03 is 3%),
bounds, warnings, defaults and whether it sits in the tool's optional ``advanced`` object:

    FIELDS / OVERRIDES / NOTIONAL     product fields of the per-product tools (and of trades in every tool)
    NESTED_*                          nested product objects (TRS / SFT terms, collateral), set in OVERRIDES
    CALC_INPUTS / CALC_CONFIG         calculator fields of qlrisk_credit_risk, qlrisk_xva, qlrisk_ccr_exposure
    SHOCK_UNITS / SHOCK_SIZES         shock sizes by factor kind and shock type (size_bp, size_pct, size)
    STRESS_DEFINITION, LIQUIDITY      stylised stresses (qlrisk_stress_test) and liquidity spreads (VaR)

tools/products.py and units.py build the schemas (from qlrisk's, read at load time) and convert the
arguments from it; a qlrisk field the table does not name is passed as is and documented as taking qlrisk's
own units (tests/tools/test_qlrisk_tools.py fails when a calculator field is not named).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[4]
OUT_DIR = ROOT / "config" / "tools" / "qlrisk"
IMPLEMENTATION = "sajha.tools.impl.qlrisk.qlrisk_tools.QlriskPriceProductTool"
EXAMPLE_DATE = "2026-10-09"          # the valuation date the examples are checked on (fixed: output is stable)

# ── the field table ─────────────────────────────────────────────────

_NO = object()                       # "no default given in the table"
PCT, BP = 0.01, 0.0001               # exposed value x scale = qlrisk value
NUM_FREQ = {"annual": 1, "semi-annual": 2, "quarterly": 4, "monthly": 12, "at maturity": 0}
CODE_FREQ = {"annual": "A", "semi-annual": "S", "quarterly": "Q", "monthly": "M", "weekly": "W", "daily": "D",
             "at maturity": "T"}


@dataclass(frozen=True)
class F:
    """How one qlrisk field is exposed. name None = qlrisk's name; hidden = not exposed (qlrisk default applies)."""
    name: Optional[str] = None
    title: str = ""
    desc: str = ""
    unit: str = ""                   # shown in the description: "percent", "basis points", ...
    scale: float = 1.0               # qlrisk value = exposed value x scale
    labels: Optional[Dict[str, Any]] = None     # exposed label -> qlrisk value (an enum of words)
    freq: bool = False               # a payment frequency: labels from NUM_FREQ or CODE_FREQ by qlrisk's type
    type: Optional[str] = None       # JSON type override (qlrisk's annotation is too loose)
    minimum: Optional[float] = None  # hard bounds, exposed units (a value outside is an error)
    maximum: Optional[float] = None
    positive: bool = False           # must be > 0
    warn: Optional[Tuple[float, float]] = None  # soft bounds: outside them the result carries a warning
    default: Any = _NO               # exposed-units default (else qlrisk's, converted)
    required: Optional[bool] = None  # override qlrisk's required-ness
    advanced: bool = False           # lives in the optional `advanced` object
    tenor: bool = False              # a date that also takes a tenor (3Y, 18M, 6W, 10D) from the valuation date
    future: bool = False             # must fall after the valuation date
    hidden: bool = False
    example: Any = _NO               # example value when the field is required
    offset: float = 0.0              # qlrisk value = exposed value x scale + offset (a multiplier shown as a % change)
    tiny: Optional[float] = None     # 0 < |value| < tiny prices with a "did you mean" warning (default: 0.2 for
                                     # percent, 0.5 for basis points; 0 turns it off)
    nested: Optional[Dict[str, "F"]] = None     # an object (or list of objects) whose own fields are in this table


def _rate(name, title, desc, example=4, lo=-10.0, hi=100.0, warn=(-2.0, 20.0), **kw):
    return F(name=name, title=f"{title} (%)", desc=desc, unit="percent", scale=PCT, minimum=lo, maximum=hi,
             warn=warn, example=example, **kw)


def _bp(name, title, desc, example=0, lo=-10000.0, hi=10000.0, warn=(-500.0, 2000.0), **kw):
    return F(name=name, title=f"{title} (bp)", desc=desc, unit="basis points", scale=BP, minimum=lo, maximum=hi,
             warn=warn, example=example, **kw)


_DIRECTION = "Direction of the position."
_CURVE_KEY = "a key of the market data's {0}"

# generic entries, by qlrisk field name
FIELDS: Dict[str, F] = {
    # trade identity and dates: advanced
    "trade_id": F(title="Trade id", desc="Defaults to <Product>-1.", advanced=True),
    "trade_date": F(title="Trade date", desc="Date or tenor; defaults to the valuation date.", advanced=True, tenor=True),
    "effective_date": F(title="Effective date", desc="Start date or forward-start tenor (e.g. 1Y); defaults to the "
                        "valuation date.", advanced=True, tenor=True),
    "counterparty_id": F(title="Counterparty id", advanced=True),
    "maturity_date": F(name="maturity", title="Maturity", desc="A tenor from the valuation date (3Y, 18M, 6W, 10D) or a "
                       "date YYYY-MM-DD.", tenor=True, future=True, example="5Y"),
    "currency": F(title="Currency", desc="Trade currency; the NPV is in it (and in the reporting currency).", default="USD"),
    # rates in percent
    "coupon": _rate("coupon_pct", "Annual coupon", "Annual coupon rate in percent: 3 means 3% a year (not 0.03).",
                    example=5, lo=0.0, hi=100.0, warn=(0.0, 20.0)),
    "rate": _rate("rate_pct", "Interest rate", "Simple annual interest rate in percent, paid at maturity: 4 means 4%; "
                  "0 for a pure discount instrument.", example=4),
    "fixed_rate": _rate("fixed_rate_pct", "Fixed rate", "Fixed rate in percent: 4 means 4%."),
    "fra_rate": _rate("fra_rate_pct", "FRA rate", "Agreed forward rate in percent: 4 means 4%."),
    "loan_rate": _rate("loan_rate_pct", "Loan rate", "Annual loan rate in percent."),
    "wac": _rate("wac_pct", "Weighted average coupon", "Pool WAC in percent; defaults to coupon + 0.5%.", lo=0.0),
    "bond_coupon": _rate("bond_coupon_pct", "Deliverable bond coupon", "Coupon of the cheapest-to-deliver bond in "
                         "percent.", example=6, lo=0.0, warn=(0.0, 20.0)),
    "domestic_coupon": _rate("domestic_coupon_pct", "Domestic leg coupon", "Fixed coupon of the domestic leg in "
                             "percent; defaults to the domestic curve rate."),
    "foreign_coupon": _rate("foreign_coupon_pct", "Foreign leg coupon", "Fixed coupon of the foreign leg in percent; "
                            "defaults to the foreign curve rate."),
    "convenience_yield": _rate("convenience_yield_pct", "Convenience yield", "Annual convenience yield in percent.",
                               lo=-50.0),
    "foreign_rate": _rate("foreign_rate_pct", "Foreign rate", "Flat foreign rate in percent, used only when "
                          "foreign_curve is not in the market data.", advanced=True),
    "recovery": _rate("recovery_pct", "Recovery rate", "Recovery on default in percent: 40 means 40%.", example=40,
                      lo=0.0, hi=99.0, warn=(5.0, 80.0)),
    "attachment": _rate("attachment_pct", "Attachment point", "Tranche attachment in percent of the pool.", example=3,
                        lo=0.0, hi=100.0, warn=(0.0, 100.0)),
    "detachment": _rate("detachment_pct", "Detachment point", "Tranche detachment in percent of the pool (above the "
                        "attachment).", example=7, lo=0.0, hi=100.0, warn=(0.0, 100.0)),
    "cpr": _rate("cpr_pct", "Prepayment speed (CPR)", "Constant prepayment rate, annual, in percent.", example=10,
                 lo=0.0, hi=100.0, warn=(0.0, 60.0)),
    "base_cpr": _rate("base_cpr_pct", "Base prepayment speed (CPR)", "Base CPR in percent before the refinancing "
                      "incentive.", example=6, lo=0.0, hi=100.0, warn=(0.0, 60.0)),
    "initial_margin_pct": _rate("initial_margin_pct", "Initial margin", "Initial margin in percent of notional.",
                                lo=0.0, hi=100.0, warn=(0.0, 50.0)),
    "collateral_haircut": _rate("collateral_haircut_pct", "Collateral haircut", "Haircut on the collateral in "
                                "percent; defaults by collateral type.", lo=0.0, hi=100.0, warn=(0.0, 50.0)),
    "volatility": _rate("volatility_pct", "Volatility", "Black (lognormal) volatility in percent: 20 means 20%. "
                        "Leave empty to use the market data's surface.", lo=0.01, hi=500.0, warn=(1.0, 150.0)),
    # spreads in basis points
    "spread": _bp("spread_bp", "Spread", "Spread in basis points: 25 means 0.25%."),
    "oas": _bp("oas_bp", "Option-adjusted spread", "OAS over the discount curve in basis points.", example=50),
    "rebate_rate": _bp("rebate_rate_bp", "Rebate rate", "Rebate on cash collateral in basis points (negative: the "
                       "borrower pays)."),
    "fee_rate": _bp("fee_rate_bp", "Fee", "Annual fee in basis points of notional (positive: we pay)."),
    # words instead of booleans and codes
    "is_long": F(name="position", title="Position", desc="Long or short.", labels={"long": True, "short": False},
                 advanced=True),
    "is_call": F(name="option_type", title="Option type", desc="Call or put.", labels={"call": True, "put": False}),
    "is_payer": F(name="pay_fixed", title="Pay fixed", desc="True: pay the fixed rate (payer); false: receive it."),
    "is_buyer": F(title="Protection buyer", desc=_DIRECTION, advanced=True),
    "is_receiver": F(title="Receive the total return", desc=_DIRECTION, advanced=True),
    "is_lender": F(title="Lender", desc=_DIRECTION, advanced=True),
    "is_cash_lender": F(title="Cash lender", desc=_DIRECTION, advanced=True),
    "is_buy_base": F(title="Buy the base currency", desc=_DIRECTION, advanced=True),
    "buy_base_near": F(title="Buy the base currency on the near leg", desc=_DIRECTION, advanced=True),
    "frequency": F(title="Payment frequency", freq=True),
    "fixed_frequency": F(title="Fixed leg frequency", freq=True),
    "float_frequency": F(title="Floating leg frequency", freq=True),
    "pay_frequency": F(title="Pay leg frequency", freq=True),
    "receive_frequency": F(title="Receive leg frequency", freq=True),
    "payment_frequency": F(title="Payment frequency", freq=True),
    "fee_payment_frequency": F(title="Fee payment frequency", freq=True),
    # names and keys
    "ticker": F(title="Ticker", type="string", desc="Underlying: " + _CURVE_KEY.format("equity_prices") + " (e.g. SPX)."),
    "quantity": F(title="Quantity", type="number", positive=True, desc="Number of units; defaults to the notional "
                  "divided by the price or strike."),
    "issuer": F(title="Issuer", type="string", advanced=True, desc="Issuer: " +
                _CURVE_KEY.format("credit_curves") + " (e.g. ACME); adds its credit spread."),
    "reference": F(title="Reference entity", type="string", desc="Reference entity: " +
                   _CURVE_KEY.format("credit_curves") + ", e.g. GLOBEX."),
    "pool": F(title="Reference pool", desc="Pool credit curve: " + _CURVE_KEY.format("credit_curves") + "."),
    "correlation": F(title="Default correlation (0 to 1)", unit="0 to 1", minimum=0.0, maximum=0.99),
    "spot": F(title="Fallback spot", advanced=True, desc="Used only when the market data has no price for the "
              "underlying."),
    "domestic_curve": F(title="Domestic curve", type="string", advanced=True, desc="Forward curve key for the "
                        "domestic rate; defaults to the discount curve."),
    "foreign_curve": F(title="Foreign curve", advanced=True, desc="Forward curve key for the foreign rate."),
    "day_count": F(title="Day count", advanced=True),
    "fixed_day_count": F(title="Fixed leg day count", advanced=True),
    "float_day_count": F(title="Floating leg day count", advanced=True),
    "amortization_schedule": F(title="Amortization schedule", advanced=True),
    "tenor": F(name="rate_period_years", title="Underlying rate period (years)", unit="years", positive=True,
               desc="Length of the rate the future settles on: 0.25 = 3 months."),
    "bond_maturity_years": F(title="Deliverable bond life after delivery (years)", unit="years", positive=True),
    "conversion_factor": F(title="Conversion factor", positive=True),
    "refi_multiplier": F(title="Refinancing multiplier", desc="CPR added per unit of refinancing incentive "
                         "(WAC above the 10-year rate)."),
    "initial_margin_ratio": F(title="Initial margin ratio", desc="Collateral / loan at inception: 1.5 = 150%.",
                              positive=True),
    "maintenance_margin_ratio": F(title="Maintenance margin ratio", desc="Collateral / loan that triggers a margin "
                                  "call: 1.25 = 125%.", positive=True),
    "margin_ratio": F(title="Margin ratio", desc="Collateral / securities value: 1.02 = 102%.", positive=True),
    "minimum_margin": F(title="Minimum margin ratio", desc="1.00 = 100%.", positive=True),
    # nested qlrisk objects: their fields are in NESTED_* below (set per product in OVERRIDES)
    **{k: F(title=t, desc=f"{t}: rates, haircuts and margins in percent, spreads and fees in basis points (each "
            "field's title gives its unit).")
       for k, t in (("terms", "Contract terms"), ("collateral_positions", "Collateral positions"),
                    ("borrowed_securities", "Borrowed securities"), ("receive_leg", "Collateral received"),
                    ("deliver_leg", "Collateral delivered"))},
    # dates of their own (they take tenors too)
    "settlement_date": F(name="settlement", title="Settlement", desc="Tenor or date YYYY-MM-DD.", tenor=True,
                         future=True, example="1Y"),
    "fixing_date": F(name="fixing", title="Fixing", desc="Tenor or date YYYY-MM-DD (on or before settlement).",
                     tenor=True, example="1Y"),
    "near_date": F(name="near_settlement", title="Near-leg settlement", desc="Tenor or date YYYY-MM-DD.", tenor=True,
                   example="3M"),
    "far_date": F(name="far_settlement", title="Far-leg settlement", desc="Tenor or date YYYY-MM-DD (after the near "
                  "leg).", tenor=True, future=True, example="1Y"),
    "option_expiry": F(name="expiry", title="Option expiry", desc="Tenor or date YYYY-MM-DD.", tenor=True, future=True,
                       example="1Y"),
    "swap_effective": F(name="swap_start", title="Underlying swap start", desc="Tenor from the valuation date or date "
                        "(normally the expiry).", tenor=True, example="1Y"),
    "swap_maturity": F(name="swap_end", title="Underlying swap end", desc="Tenor from the valuation date or date: 1Y "
                       "expiry into a 5Y swap is swap_start 1Y, swap_end 6Y.", tenor=True, future=True, example="6Y"),
    # FX amounts and rates (quoted as FX rates, not percent)
    "base_currency": F(title="Base currency", example="EUR"),
    "quote_currency": F(title="Quote currency", example="USD"),
    "base_notional": F(title="Base currency amount", positive=True, example=1_000_000),
    "forward_rate": F(title="Forward FX rate", desc="Agreed rate, quote currency per base unit.", positive=True,
                      example=1.10),
    "near_rate": F(title="Near-leg FX rate", positive=True, example=1.10),
    "far_rate": F(title="Far-leg FX rate", positive=True, example=1.11),
    "pair": F(title="Currency pair", desc="Six letters, base then quote, e.g. EURUSD."),
    # indices and names
    "floating_index": F(title="Floating index", desc="Index of the floating leg (its forward curve)."),
    "overnight_index": F(title="Overnight index", desc="Overnight index of the floating leg."),
    "pay_index": F(title="Pay-leg index"), "receive_index": F(title="Receive-leg index"),
    "index": F(title="Floating index", desc="Forward curve key of the index, e.g. SOFR."),
    "commodity": F(title="Commodity", desc="Underlying: " + _CURVE_KEY.format("commodity_prices") + " (e.g. WTI)."),
    "exercise_style": F(title="Exercise style"),
    "barrier_type": F(title="Barrier type"),
    "digital": F(title="Digital", desc="Pay a fixed amount (payout) instead of the vanilla payoff."),
    "is_future": F(title="Futures (not discounted)", desc="True: daily-margined future; false: forward."),
    "reference_rate": F(title="Reference rate"), "margin_call_frequency": F(title="Margin call frequency"),
    "loan_purpose": F(title="Loan purpose"), "is_committed": F(title="Committed facility"),
    "facility_limit": F(title="Facility limit", desc="Amount in the trade currency."),
    "collateral_type": F(title="Collateral type"),
    "collateral_value": F(title="Collateral value", desc="Amount in the trade currency."),
    "variation_margin": F(title="Variation margin"), "is_term": F(title="Term loan"),
    "vega_notional": F(title="Vega notional"), "initial_price": F(title="Initial price"),
    "conversion_ratio": F(title="Conversion ratio", desc="Shares per bond."),
    "foreign_notional": F(title="Foreign-leg notional"), "payout": F(title="Digital payout"),
    "rebate": F(title="Rebate"), "strike": F(title="Strike"),
}

# the notional's name and default, by pricer (then by product)
NOTIONAL: Dict[str, Tuple[str, str, float, str]] = {
    "price_fixed_bond": ("face_value", "Face value", 100, "Face (par) amount in the trade currency."),
    "price_frn": ("face_value", "Face value", 100, "Face (par) amount in the trade currency."),
    "price_convertible": ("face_value", "Face value", 100, "Face (par) amount in the trade currency."),
    "price_abs": ("face_value", "Face value", 100, "Original pool balance in the trade currency."),
    "price_mbs": ("face_value", "Face value", 100, "Original pool balance in the trade currency."),
    "price_tranche": ("face_value", "Face value", 100, "Tranche notional in the trade currency."),
    "price_clo_tranche": ("face_value", "Face value", 100, "Tranche notional in the trade currency."),
    "price_bond_future": ("face_value", "Face value", 100_000, "Contract face amount in the trade currency."),
    "price_deposit": ("principal", "Principal", 1_000_000, "Amount placed, in the trade currency."),
    "price_cash_equity": ("position_value", "Position value", 1_000_000, "Market value of the position in the trade "
                          "currency; sizes it when quantity is not given."),
    "*": ("notional", "Notional", 1_000_000, "Notional amount in the trade currency."),
}
NOTIONAL_BY_PRODUCT: Dict[str, Tuple[str, str, float, str]] = {
    p: ("face_value", "Face value", 100, "Face amount paid at maturity, in the trade currency.")
    for p in ("TreasuryBill", "CommercialPaper", "DiscountNote", "BankersAcceptance")
}
NOTIONAL_BY_PRODUCT.update({p: ("notional", "Notional", 1_000_000, "Notional in the base (foreign) currency of the pair.")
                            for p in ("FXOption", "FXDigitalOption", "FXBarrierOption", "NonDeliverableForward")})

_BOND_MARKET = {"GermanBund": ("EUR", "annual"), "FrenchOAT": ("EUR", "annual"), "UKGilt": ("GBP", "semi-annual"),
                "JGB": ("JPY", "semi-annual")}
_DEPOSIT_PRODUCTS = ("BankersAcceptance", "BuySellBack", "CertificateOfDeposit", "CommercialPaper", "DiscountNote",
                     "EurodollarDeposit", "FederalFunds", "Repo", "ReverseRepo", "SecuritiesLending", "TimeDeposit",
                     "TreasuryBill")

# ── nested qlrisk objects of the per-product tools (TRS / SFT terms, collateral) ──
# Each maps the object's qlrisk fields to the tools' names and units; a field it does not name is passed as is
# (titles say so). qlrisk's own units are in the comments of its dataclasses (bond_trs, equity_trs, sft/*).


def _p(name, title, desc, lo=0.0, hi=100.0, warn=None, **kw) -> F:
    """A percent field: qlrisk takes the decimal (0.25 = 25%)."""
    return F(name=name, title=f"{title} (%)", desc=desc, unit="percent", scale=PCT, minimum=lo, maximum=hi,
             warn=warn, **kw)


def _b(name, title, desc, lo=-10000.0, hi=10000.0, warn=(-500.0, 2000.0), scale=BP, **kw) -> F:
    """A basis-point field (scale BP: qlrisk takes the decimal; scale 1: qlrisk already takes basis points)."""
    return F(name=name, title=f"{title} (bp)", desc=desc, unit="basis points", scale=scale, minimum=lo, maximum=hi,
             warn=warn, **kw)


def _amt(title, desc="") -> F:
    return F(title=title, desc=desc or "An amount in the trade currency.", unit="amount")


def _same(title, desc="") -> F:
    return F(title=title, desc=desc)


_HAIRCUT = _p("haircut_pct", "Haircut", "Haircut on the market value in percent: 15 means the collateral counts "
              "at 85%.", warn=(0.0, 60.0))
_SEC_VOL = _p("volatility_pct", "Volatility", "Annual price volatility in percent: 25 means 25% a year.", lo=0.0,
              hi=500.0, warn=(1.0, 150.0))
_DIV_YIELD = _p("dividend_yield_pct", "Dividend yield", "Annual dividend yield in percent: 2 means 2%.", hi=50.0,
                warn=(0.0, 15.0))
_PRICE100 = "Price per 100 of face value (percent of par, not a decimal)."
NESTED_BOND_TRS = {
    "initial_price": F(title="Initial price (per 100)", desc=_PRICE100, unit="per 100 face"),
    "current_price": F(title="Current price (per 100)", desc=_PRICE100, unit="per 100 face"),
    "coupon_rate": _p("coupon_rate_pct", "Coupon rate", "Annual coupon of the bond underlying in percent: 5 means 5%.",
                      warn=(0.0, 20.0)),
    "spread_over_benchmark": _b("spread_over_benchmark_bp", "Spread over benchmark", "Bond spread over its benchmark "
                                "in basis points (qlrisk takes basis points; its pricer does not read it).", scale=1.0),
    "modified_duration": F(title="Modified duration (years)", unit="years", minimum=0.0,
                           desc="Modified duration of the underlying in years."),
    "dv01": _amt("DV01", "Value change per 1bp in the trade currency; 0 = notional x duration x 0.0001."),
    "financing_spread": _b("financing_spread_bp", "Financing spread", "Spread paid over the financing index in basis "
                           "points: 75 means index + 0.75% (qlrisk takes basis points).", scale=1.0),
    "initial_margin": _amt("Initial margin"), "variation_margin": _amt("Variation margin"),
    "recovery_rate": _p("recovery_pct", "Recovery rate", "Recovery on a credit event in percent: 40 means 40%.",
                        hi=99.0, warn=(5.0, 80.0)),
}
NESTED_EQUITY_TRS = {
    "initial_price": F(title="Initial price", desc="Underlying price at inception, in its price units.", unit="price"),
    "current_price": F(title="Current price", desc="Underlying price now; 0 = the market data's price.", unit="price"),
    "dividend_yield": _DIV_YIELD,
    "financing_spread": _b("financing_spread_bp", "Financing spread", "Spread paid over the financing index in basis "
                           "points: 50 means index + 0.50% (qlrisk takes basis points).", scale=1.0),
    "initial_margin": _amt("Initial margin"), "variation_margin": _amt("Variation margin"),
}
NESTED_COMMODITY_FUTURE = {
    "contract_size": F(title="Contract size", desc="Units per contract (1000 barrels for WTI).", unit="units"),
    "futures_price": F(title="Futures price", desc="Agreed futures price per unit; 0 = fair.", unit="price"),
    "spot_price": F(title="Spot price", desc="Spot price per unit; empty = the market data's price.", unit="price"),
    "storage_cost": _p("storage_cost_pct", "Storage cost", "Annual storage cost in percent of the price (added to "
                       "the carry): 2 means 2% a year.", lo=-50.0, warn=(0.0, 20.0)),
    "convenience_yield": _p("convenience_yield_pct", "Convenience yield", "Annual convenience yield in percent "
                            "(subtracted from the carry).", lo=-50.0, warn=(-10.0, 30.0)),
    "margin_initial": _amt("Initial margin per contract"), "margin_maintenance": _amt("Maintenance margin per contract"),
}
NESTED_MARGIN_LOAN_COLLATERAL = {
    "quantity": F(title="Quantity", type="number"), "market_value": _amt("Market value"),
    "haircut": _p("haircut_pct", "Haircut", "Haircut in percent; empty = qlrisk's default for the category.",
                  warn=(0.0, 60.0)),
}
NESTED_MARGIN_LOAN = {
    "loan_amount": _amt("Loan amount"),
    "interest_spread": _b("interest_spread_bp", "Interest spread", "Spread over the rate index in basis points: 150 "
                          "means index + 1.50% (qlrisk takes basis points).", scale=1.0),
    "collateral_positions": F(title="Collateral positions", nested=NESTED_MARGIN_LOAN_COLLATERAL,
                              desc="Pledged positions: security_id, security_name, category, quantity, market_value, "
                                   "haircut_pct, currency."),
    "total_collateral_value": _amt("Total collateral value"),
    "initial_margin_pct": _p("initial_margin_pct", "Initial margin", "Initial margin requirement in percent of the "
                             "collateral: 50 means 50% (qlrisk takes 0.50).", warn=(5.0, 90.0)),
    "maintenance_margin_pct": _p("maintenance_margin_pct", "Maintenance margin", "Maintenance margin requirement in "
                                 "percent: 35 means 35% (qlrisk takes 0.35).", warn=(5.0, 90.0)),
    "current_ltv": _p("current_ltv_pct", "Current loan-to-value", "Loan / collateral value in percent.", hi=1000.0),
    "margin_excess": _amt("Margin excess", "Excess margin (positive) or deficit, in the trade currency."),
}
NESTED_PB_POSITION = {"quantity": F(title="Quantity", type="number"), "market_value": _amt("Market value"),
                      "haircut": _HAIRCUT}
NESTED_PRIME_BROKERAGE = {
    "financing_rate_spread": _b("financing_rate_spread_bp", "Financing spread", "Long financing spread over the "
                                "benchmark rate in basis points (qlrisk takes basis points).", scale=1.0),
    "short_rebate_spread": _b("short_rebate_spread_bp", "Short rebate spread", "Short rebate spread over the benchmark "
                              "in basis points; negative is a cost (qlrisk takes basis points).", scale=1.0),
    "initial_margin_requirement": _p("initial_margin_requirement_pct", "Initial margin requirement", "In percent of "
                                     "the position value: 50 means 50% (Reg T).", warn=(5.0, 100.0)),
    "maintenance_margin": _p("maintenance_margin_pct", "Maintenance margin", "In percent: 25 means 25%.",
                             warn=(5.0, 100.0)),
    "house_margin_excess": _p("house_margin_excess_pct", "House margin excess", "Extra house requirement in percent of "
                              "the gross market value: 5 means 5%.", warn=(0.0, 50.0)),
    "positions": F(title="Positions", nested=NESTED_PB_POSITION, desc="Positions: security_id, security_type, quantity, "
                   "market_value, haircut_pct, is_long, is_rehypothecatable."),
    "gross_exposure_limit": _amt("Gross exposure limit"), "net_exposure_limit": _amt("Net exposure limit"),
    "concentration_limit": _p("concentration_limit_pct", "Concentration limit", "Largest share of one security in "
                              "percent: 10 means 10%."),
    "rehypothecation_limit": _p("rehypothecation_limit_pct", "Rehypothecation limit", "In percent of the debit "
                                "balance: 140 means 140%.", hi=1000.0),
    "custody_fee_bps": _b("custody_fee_bps", "Custody fee", "Annual custody fee in basis points of the gross value "
                          "(qlrisk takes basis points).", lo=0.0, scale=1.0, warn=(0.0, 100.0)),
    "execution_fee_bps": _b("execution_fee_bps", "Execution fee", "Execution fee in basis points (qlrisk takes basis "
                            "points).", lo=0.0, scale=1.0, warn=(0.0, 100.0)),
}
NESTED_STOCK_LOAN = {
    "quantity": F(title="Quantity (shares)"), "loan_value": _amt("Loan value", "Market value of the loaned stock."),
    "collateral_value": _amt("Collateral value"),
    "collateral_margin": _p("collateral_margin_pct", "Collateral margin", "Collateral in percent of the loan value: "
                            "102 means 102% (qlrisk takes 1.02).", lo=0.0, hi=1000.0, warn=(100.0, 150.0)),
    "rebate_rate": _b("rebate_rate_bp", "Rebate rate", "Annual rate paid on cash collateral in basis points; may be "
                      "negative."),
    "lending_fee": _b("lending_fee_bp", "Lending fee", "Annual lending fee in basis points of the stock value (non-cash "
                      "collateral); 0 with a 0 rebate lets qlrisk pick it by loan type.", lo=0.0, warn=(0.0, 5000.0)),
    "haircut": _p("haircut_pct", "Collateral haircut", "Haircut in percent; 0 lets qlrisk pick the regulatory one.",
                  warn=(0.0, 60.0)),
    "stock_volatility": _p("stock_volatility_pct", "Stock volatility", "Annual volatility in percent: 25 means 25%.",
                           lo=0.0, hi=500.0, warn=(1.0, 150.0)),
    "dividend_yield": _DIV_YIELD,
    "minimum_term_days": F(title="Minimum term (days)", unit="days"),
    "recall_notice_days": F(title="Recall notice (days)", unit="days"),
}
NESTED_TRI_PARTY = {
    "cash_amount": _amt("Cash amount"),
    "repo_rate": _p("repo_rate_pct", "Repo rate", "Fixed annual repo rate in percent: 4 means 4%.", lo=-10.0,
                    warn=(-2.0, 20.0)),
    "floating_spread": _b("floating_spread_bp", "Floating spread", "Spread over the floating index in basis points "
                          "(qlrisk takes basis points).", scale=1.0),
    "collateral_value": _amt("Collateral value"),
    "haircut": _p("haircut_pct", "Haircut", "Haircut in percent overriding the schedule's; empty = the schedule's.",
                  warn=(0.0, 60.0)),
}
NESTED_ML_COLLATERAL = {
    "quantity": F(title="Quantity"), "market_value": _amt("Market value"), "haircut": _HAIRCUT,
    "concentration_limit": _p("concentration_limit_pct", "Concentration limit", "Largest share of this security in "
                              "percent: 30 means 30%."),
    "volatility": _SEC_VOL,
}
NESTED_BORROWED = {
    "quantity": F(title="Quantity"), "market_value": _amt("Market value"), "haircut": _HAIRCUT,
    "volatility": _SEC_VOL, "dividend_yield": _DIV_YIELD,
    "special_rate": _p("special_rate_pct", "Special rate", "Borrow rate when hard to borrow, annual, in percent "
                       "(qlrisk's pricer does not read it).", lo=-10.0, hi=1000.0),
}
NESTED_COLLATERAL_LEG = {"market_value": _amt("Market value"), "haircut": _HAIRCUT, "volatility": _SEC_VOL}

# per pricer or per product: changes to the generic entry (a dict of F attributes), or hidden
OVERRIDES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "price_fixed_bond": {"coupon": {"required": True}, "frequency": {"default": "semi-annual"}},
    "price_deposit": {"coupon": {"hidden": True}, "frequency": {"advanced": True}},
    "ZeroCouponBond": {"coupon": {"hidden": True}, "frequency": {"hidden": True}},
    "price_cash_equity": {"maturity_date": {"advanced": True, "default": "1Y", "desc": "Horizon only (a cash position "
                                            "does not mature); tenor or date."}},
    "price_cds": {"coupon": dict(name="coupon_bp", title="Running coupon (bp)", unit="basis points", scale=BP,
                                 desc="Running premium in basis points a year: 100 means 1%.", minimum=0.0,
                                 maximum=10000.0, warn=(0.0, 2000.0), example=100)},
    "price_tranche": {"coupon": dict(name="coupon_bp", title="Tranche spread (bp)", unit="basis points", scale=BP,
                                     desc="Tranche spread over the curve in basis points.", minimum=0.0,
                                     maximum=10000.0, warn=(0.0, 3000.0), example=300)},
    "price_total_return": {"coupon": {"advanced": True, "required": False,
                                      "desc": "Coupon of the bond underlying in percent, used only with an issuer."},
                           "spread": {"desc": "Spread paid over the floating rate, in basis points."}},
    "price_equity_option": {"strike": {"desc": "Strike price in the underlying's price units; defaults to spot."}},
    "price_equity_forward": {"strike": {"desc": "Agreed forward price; defaults to the fair forward."}},
    "price_commodity_forward": {"strike": {"desc": "Agreed price per unit; defaults to the fair forward."}},
    "price_commodity_option": {"strike": {"desc": "Strike price per unit; defaults to the forward."}},
    "price_dividend_swap": {"strike": {"desc": "Fixed dividend amount per share; defaults to the fair value."}},
    "price_fx_option": {"strike": {"desc": "Strike FX rate (quote per base); defaults to the forward."},
                        "payout": {"title": "Digital payout", "desc": "Quote-currency payout of a digital; "
                                   "defaults to the notional."}},
    "price_fx_barrier": {"strike": {"desc": "Strike FX rate (quote per base); defaults to the forward."},
                         "barrier_type": {"labels": {"UpOut": "UpOut", "UpIn": "UpIn", "DownOut": "DownOut",
                                                     "DownIn": "DownIn"}},
                         "rebate": {"desc": "Rebate paid if knocked out, per unit of notional."}},
    "price_fx_ndf": {"forward_rate": {"required": False, "example": _NO,
                                      "desc": "Agreed NDF rate (quote per base); defaults to the fair forward."}},
    "price_ir_future": {"strike": {"name": "traded_price", "title": "Traded price", "positive": True,
                                   "desc": "Price traded at (100 minus the rate in percent); defaults to fair."}},
    "price_bond_future": {"strike": {"name": "traded_price", "title": "Traded price", "positive": True,
                                     "desc": "Futures price traded at, per 100 face; defaults to fair."}},
    "price_vix_future": {"strike": {"title": "Traded level", "desc": "VIX level traded at, in volatility points "
                                    "(18 = 18%); defaults to fair."}},
    "price_variance_swap": {"strike": dict(name="strike_vol_pct", title="Volatility strike (%)", unit="percent",
                                           scale=PCT, minimum=0.01, maximum=500.0, warn=(1.0, 150.0),
                                           desc="Strike as a volatility in percent: 20 means 20%; defaults to the "
                                           "at-the-money implied volatility."),
                            "vega_notional": {"desc": "Vega notional; defaults to the notional."}},
    "price_xccy_swap": {"frequency": {"default": "semi-annual"},
                        "foreign_curve": {"advanced": False},
                        "foreign_notional": {"desc": "Foreign-leg notional; defaults to notional / spot."}},
    "price_frn": {"spread": {"desc": "Quoted margin over the index in basis points."},
                  "index": {"title": "Floating index", "desc": "Forward curve key of the index, e.g. SOFR."}},
    "price_abs": {"spread": {"desc": "Discount spread in basis points, used when no issuer is given.",
                             "example": 100}},
    "InterestRateCap": {"strike": dict(name="strike_pct", title="Cap rate (%)", unit="percent", scale=PCT,
                                       minimum=-10.0, maximum=100.0, warn=(-2.0, 20.0), example=4,
                                       desc="Cap strike rate in percent: 4 means 4%.")},
    "InterestRateFloor": {"strike": dict(name="strike_pct", title="Floor rate (%)", unit="percent", scale=PCT,
                                         minimum=-10.0, maximum=100.0, warn=(-2.0, 20.0), example=3,
                                         desc="Floor strike rate in percent: 3 means 3%.")},
    "Swaption": {"strike": dict(name="strike_pct", title="Strike rate (%)", unit="percent", scale=PCT,
                                minimum=-10.0, maximum=100.0, warn=(-2.0, 20.0), example=4,
                                desc="Fixed rate of the underlying swap in percent: 4 means 4%."),
                 "is_payer": dict(name="swaption_type", title="Swaption type", labels={"payer": True, "receiver": False},
                                  desc="Payer (right to pay fixed) or receiver.")},
    "ForwardRateAgreement": {"maturity_date": {"desc": "End of the FRA period: tenor or date (after settlement).",
                                               "example": "18M"}},
    "FXForward": {"settlement_date": {"name": "maturity", "title": "Maturity (settlement)",
                                      "desc": "Settlement: a tenor (3M, 1Y) or a date YYYY-MM-DD."}},
    "MarginLending": {"spread": {"desc": "Spread over the reference rate in basis points.", "example": 200}},
    "CollateralSwap": {"receive_leg": {"nested": NESTED_COLLATERAL_LEG}, "deliver_leg": {"nested": NESTED_COLLATERAL_LEG}},
    "BondTRS": {"terms": {"nested": NESTED_BOND_TRS}},
    "EquityTRS": {"terms": {"nested": NESTED_EQUITY_TRS}},
    "CommodityFuture": {"terms": {"nested": NESTED_COMMODITY_FUTURE}},
    "MarginLoan": {"terms": {"nested": NESTED_MARGIN_LOAN}},
    "PrimeBrokerage": {"terms": {"nested": NESTED_PRIME_BROKERAGE}},
    "StockLoan": {"terms": {"nested": NESTED_STOCK_LOAN}},
    "TriPartyRepo": {"terms": {"nested": NESTED_TRI_PARTY}},
    "MarginLending": {"collateral_positions": {"nested": NESTED_ML_COLLATERAL}},
    "SecuritiesBorrowing": {"borrowed_securities": {"nested": NESTED_BORROWED}},
}
for _prod, (_ccy, _freq) in _BOND_MARKET.items():
    OVERRIDES[_prod] = {"currency": {"default": _ccy}, "frequency": {"default": _freq}}

# the owner-facing example per product, where the generic one is not the clearest
EXAMPLES: Dict[str, Dict[str, Any]] = {
    "TreasuryBond": {"maturity": "3Y", "face_value": 100, "coupon_pct": 3, "currency": "USD"},
    "CorporateBond": {"maturity": "5Y", "face_value": 100, "coupon_pct": 5, "advanced": {"issuer": "ACME"}},
    "InterestRateSwap": {"maturity": "5Y", "notional": 10_000_000, "fixed_rate_pct": 4.4},
}

_ONE_YEAR = {"maturity": "1Y"}
# extra example inputs by pricer or product (merged over the generic example)
EXAMPLE_EXTRA: Dict[str, Dict[str, Any]] = {
    "price_deposit": {"maturity": "6M", "rate_pct": 4},
    **{p: {"maturity": "6M"} for p in ("TreasuryBill", "CommercialPaper", "DiscountNote", "BankersAcceptance")},
    "price_cash_equity": {"ticker": "AAPL"},
    "price_equity_option": {"maturity": "1Y", "ticker": "SPX"},
    "price_cds": {"reference": "GLOBEX"},
    **{p: _ONE_YEAR for p in ("price_equity_forward", "price_fx_option", "price_fx_digital", "price_fx_barrier",
                              "price_fx_ndf", "price_commodity_option", "price_commodity_forward",
                              "price_variance_swap", "price_vix_future", "price_ir_future", "price_bond_future",
                              "price_dividend_swap")},
}


# ── calculator fields: qlrisk_credit_risk, qlrisk_xva, qlrisk_ccr_exposure (mode calculator) ──
# qlrisk's calculator dataclass fields (CALC_INPUTS) and configuration keys (CALC_CONFIG), by measure. The schemas
# are read from qlrisk when the tools load (introspect.calculator_input_class / calculator_config); this says
# which name, unit and conversion each field gets. Lists and tenor -> value objects convert element by element.
# A qlrisk field the table does not name is passed as is (and documented so); the tests fail when one appears.
# Semantics are from qlrisk's calculator code (calculator/python/*.py), noted where they matter.

_YRS = dict(unit="years", minimum=0.0)
_MPOR = F(name="margin_period_of_risk_days", title="Margin period of risk (business days)", unit="business days",
          scale=1 / 252, minimum=0.0, maximum=252.0, desc="Margin period of risk in business days: 10 means ten "
          "business days (qlrisk takes years, days / 252).")
_TIME_GRID = F(title="Time grid (years)", desc="Times in years from today, ascending, one per profile point.", **_YRS)
_NOT_READ = " (qlrisk's calculator declares it but does not read it.)"
_RECOVERY = _p("recovery_pct", "Recovery rate", "Recovery in percent of the exposure: 40 means 40% (not 0.4).",
               warn=(5.0, 80.0))
_PD = _p("pd_pct", "Probability of default", "Probability of default over the horizon in percent: 2 means 2% "
         "(not 0.02).")
_LGD = _p("lgd_pct", "Loss given default", "Loss given default in percent of EAD: 45 means 45%.")
_CONF = lambda d: _p("confidence_pct", "Confidence", f"Confidence level in percent: {d} means {d}%.", lo=50.0,
                     hi=99.999)
_EXPO_COMMON = {
    "current_mtm": _amt("Current mark-to-market", "Current MTM of the trade or netting set, in its currency."),
    "notional": _amt("Notional"),
    "remaining_maturity": F(name="remaining_maturity_years", title="Remaining maturity (years)", desc="Remaining "
                            "life in years; the profile runs to it.", positive=True, **_YRS),
    "volatility": _p("volatility_pct", "Exposure volatility", "Annual volatility of the MTM in percent of notional "
                     "(parametric: sigma(t) = volatility x notional x sqrt(t); Monte Carlo: the MTM's lognormal "
                     "volatility): 1 means 1% a year.", hi=500.0, warn=(0.0, 100.0)),
    "product_type": _same("Product type", "irs, fra, cds, fx_forward, fx_option, equity, commodity (sets the "
                          "profile shape)."),
    "collateral_held": _amt("Collateral held", "Collateral held against the exposure, in its currency."),
    "margin_period_of_risk": _MPOR,
    "num_simulations": _same("Monte Carlo paths"),
    "time_grid": _TIME_GRID,
    "exposure_paths": _amt("Exposure paths", "Your own simulated MTM paths (one list per path, one value per time "
                           "point); replaces the simulation."),
}
_EE = {**_EXPO_COMMON,
       "interest_rate": _p("interest_rate_pct", "Interest rate", "Annual rate in percent." + _NOT_READ, lo=-10.0,
                           warn=(-2.0, 20.0)),
       "drift": _p("drift_pct", "Drift", "Annual drift of the MTM in percent (Monte Carlo): 2 means 2% a year.",
                   lo=-100.0, warn=(-20.0, 20.0))}
_DISCOUNT = _p("discount_curve_pct", "Discount curve", "Tenor -> zero rate in percent, continuously compounded: "
               "{\"1Y\": 4, \"5Y\": 4.2}; empty = 5% flat.", lo=-10.0, warn=(-2.0, 20.0))
_FUNDING = _b("funding_spread_bp", "Funding spread", "Own funding spread over the risk-free rate in basis points a "
              "year: 100 means 1%.", lo=-1000.0, warn=(-100.0, 1000.0))

CALC_INPUTS: Dict[str, Dict[str, F]] = {
    "pd": {
        "asset_value": _amt("Asset value", "Market value of the firm's assets (structural model)."),
        "debt_value": _amt("Debt value", "Debt due at the horizon (structural model)."),
        "asset_volatility": _p("asset_volatility_pct", "Asset volatility", "Annual volatility of the asset value in "
                               "percent (structural model): 25 means 25% a year.", hi=500.0, warn=(1.0, 150.0)),
        "risk_free_rate": _p("risk_free_rate_pct", "Risk-free rate", "Annual risk-free rate in percent, continuously "
                             "compounded (structural model): 4 means 4%.", lo=-10.0, warn=(-2.0, 20.0)),
        "time_horizon": F(name="time_horizon_years", title="Horizon (years)", desc="PD horizon in years.",
                          positive=True, **_YRS),
        "hazard_rate": _p("hazard_rate_pct", "Hazard rate", "Constant default intensity in percent a year (reduced "
                          "form: PD = 1 - exp(-hazard x T)): 2 means 2% a year.", hi=1000.0, warn=(0.0, 50.0)),
        "credit_rating": _same("Credit rating", "AAA, AA, A, BBB, BB, B or CCC (transition-matrix model)."),
        "rating_pd": _p("rating_pd_pct", "Rating PD", "A known probability of default in percent: 2 means 2%."),
        "financial_ratios": _same("Financial ratios", "Ratio name -> value (logistic model), passed as is."),
        "model_coefficients": _same("Model coefficients", "Coefficient name -> value (logistic model), passed as is."),
    },
    "lgd": {
        "exposure": _amt("Exposure", "Exposure at default, in its currency."),
        "recovery_rate": _RECOVERY,
        "collateral": F(title="Collateral", nested={"value": _amt("Value"), "haircut": _HAIRCUT},
                        desc="Collateral items: collateral_type, value, haircut_pct, currency."),
        "recovery_history": _p("recovery_history_pct", "Historical recoveries", "Observed recovery rates in percent, "
                               "one per default (workout model): [35, 42, 50]."),
        "bond_price": F(title="Defaulted bond price (per 100)", unit="per 100 of par", minimum=0.0, maximum=200.0,
                        desc="Market price of the defaulted bond per 100 of par (market model: recovery = price / 100)."),
        "lgd_mean": _p("lgd_mean_pct", "Mean LGD", "Mean LGD in percent (stochastic model)."),
        "lgd_std": _p("lgd_std_pct", "LGD standard deviation", "Standard deviation of the LGD in percentage points "
                      "(stochastic model)."),
        "is_senior": _same("Senior"), "is_secured": _same("Secured"),
    },
    "ead": {
        "current_exposure": _amt("Current exposure"), "notional": _amt("Notional"),
        "credit_conversion_factor": _p("credit_conversion_factor_pct", "Credit conversion factor", "CCF in percent: "
                                       "100 means the full amount counts."),
        "add_on_factor": _p("add_on_factor_pct", "Add-on factor", "Potential future exposure add-on in percent of "
                            "notional (CEM): 0.5 means 0.5%.", warn=(0.0, 15.0), tiny=0.0),
        "collateral_value": _amt("Collateral value"),
        "collateral_haircut": _p("collateral_haircut_pct", "Collateral haircut", "Haircut on the collateral in "
                                 "percent: 10 means it counts at 90%."),
        "netting_benefit": _p("netting_benefit_pct", "Netting benefit", "Share of the gross exposure removed by netting, "
                              "in percent: 30 means 30%."),
        "margin_period_of_risk": _MPOR,
        "replacement_cost": _amt("Replacement cost"), "pfe_add_on": _amt("PFE add-on"),
    },
    "el": {
        "pd": _PD, "lgd": _LGD, "ead": _amt("Exposure at default"),
        "time_horizon": F(name="time_horizon_years", title="Horizon (years)", desc="EL horizon in years; with "
                          "annualize the EL is also given per year.", positive=True, **_YRS),
        "maturity": F(name="maturity_years", title="Maturity (years)", desc="Maturity in years." + _NOT_READ, **_YRS),
        "recovery_rate": _RECOVERY,
        "pd_term_structure": _p("pd_term_structure_pct", "PD term structure", "Marginal PD of each period in percent, "
                                "one per time point (with config use_term_structure)."),
        "time_points": F(title="Time points (years)", desc="End of each PD period in years.", **_YRS),
    },
    "economic_capital": {
        "exposures": _amt("Exposures", "EAD per obligor."),
        "pds": _p("pds_pct", "PDs", "One-year PD per obligor in percent: [1, 2] means 1% and 2%."),
        "lgds": _p("lgds_pct", "LGDs", "LGD per obligor in percent: [45, 45]."),
        "asset_correlation": F(title="Asset correlation (0 to 1)", unit="0 to 1", minimum=0.0, maximum=1.0,
                               desc="Vasicek asset correlation: 0.2 means 20%."),
        "correlation_matrix": _same("Correlation matrix", "Obligor correlations (0 to 1)." + _NOT_READ),
        "ead": _amt("Exposure at default (single obligor)"),
        "pd": _p("pd_pct", "PD (single obligor)", "In percent: 2 means 2%."),
        "lgd": _p("lgd_pct", "LGD (single obligor)", "In percent: 45 means 45%."),
        "confidence_level": _CONF("99.9"),
        "time_horizon": F(name="time_horizon_years", title="Horizon (years)", desc="Horizon in years." + _NOT_READ,
                          **_YRS),
    },
    "raroc": {
        **{k: _amt(k.replace("_", " ").capitalize()) for k in (
            "revenue", "fee_income", "spread_income", "trading_income", "operating_cost", "funding_cost",
            "hedging_cost", "expected_loss", "economic_capital", "regulatory_capital", "cva", "fva", "kva")},
        "tax_rate": _p("tax_rate_pct", "Tax rate", "Tax rate in percent: 25 means 25%."),
        "hurdle_rate": _p("hurdle_rate_pct", "Hurdle rate", "Required return on capital in percent a year: 15 means "
                          "15%; empty = config hurdle_rate_pct.", lo=-100.0, hi=1000.0, warn=(0.0, 50.0)),
    },
    "ce": {
        "mark_to_market": _amt("Mark-to-market"), "collateral_held": _amt("Collateral held"),
        "collateral_posted": _amt("Collateral posted"),
        "collateral_haircut": _p("collateral_haircut_pct", "Collateral haircut", "Haircut on collateral held in "
                                 "percent: 10 means it counts at 90%."),
        "threshold": _amt("Threshold"),
        "minimum_transfer_amount": _amt("Minimum transfer amount", "Minimum transfer amount." + _NOT_READ),
        "independent_amount": _amt("Independent amount"),
        "netting_set_id": _same("Netting set id", "Netting set id." + _NOT_READ),
        "trades_in_netting_set": _amt("Trade MTMs in the netting set", "One MTM per trade, netted when config "
                                      "apply_netting is true."),
    },
    "ee": _EE,
    "eee": _EE,
    "pfe": {**_EXPO_COMMON,
            "interest_rate": _p("interest_rate_pct", "Interest rate", "Annual rate in percent, the Monte Carlo drift: "
                                "5 means 5%.", lo=-10.0, warn=(-2.0, 20.0)),
            "fx_rate": _same("FX rate", "FX rate." + _NOT_READ),
            "credit_spread": _b("credit_spread_bp", "Credit spread", "Counterparty credit spread in basis points."
                                + _NOT_READ, lo=0.0, warn=(0.0, 2000.0))},
    "peak": {**{k: _EXPO_COMMON[k] for k in ("current_mtm", "notional", "remaining_maturity", "volatility",
                                             "product_type", "num_simulations", "time_grid", "collateral_held")},
             "ee_profile": _amt("EE profile", "Expected exposure per time point (ee_based)."),
             "pfe_profile": _amt("PFE profile", "PFE per time point (pfe_based)."),
             "confidence_level": _CONF("95")},
    "stressed": {**{k: _EXPO_COMMON[k] for k in ("current_mtm", "notional", "remaining_maturity", "volatility",
                                                 "product_type")},
                 "stress_type": _same("Stress type", "historical (a named scenario, or the shocks below when "
                                      "stress_scenario is not one), hypothetical (the shocks below; zeros take "
                                      "qlrisk's regulatory defaults) or reverse."),
                 "stress_scenario": _same("Stress scenario", "2008_crisis, covid_2020, ... (qlrisk's exposure "
                                          "scenarios); empty = config default_scenario."),
                 "rate_shock": _b("rate_shock_bp", "Rate shock", "Absolute rate move in basis points: -200 means "
                                  "-2% (affects irs and fra; qlrisk takes basis points).", lo=-5000.0, hi=5000.0,
                                  warn=(-1000.0, 1000.0), scale=1.0),
                 "fx_shock": _p("fx_shock_pct", "FX shock", "Relative FX move in percent: 20 means 20% (affects "
                                "fx_forward and fx_option).", lo=-100.0, hi=1000.0, warn=(-50.0, 100.0)),
                 "credit_shock": _b("credit_shock_bp", "Credit shock", "Absolute credit-spread move in basis points: "
                                    "300 means +3% (affects cds; qlrisk takes basis points).", lo=-5000.0,
                                    warn=(-1000.0, 3000.0), scale=1.0),
                 "volatility_shock": _p("volatility_shock_pct", "Volatility shock", "Relative volatility move in "
                                        "percent: 150 means volatility x 2.5 (qlrisk takes the multiplier, 1 + "
                                        "percent / 100); omit for qlrisk's default.", lo=-100.0, hi=1000.0,
                                        warn=(0.0, 500.0), offset=1.0, default=None),
                 "correlation_shock": F(title="Correlation shock (-1 to 1)", unit="-1 to 1", minimum=-1.0,
                                        maximum=1.0, desc="Absolute change in correlation: 0.3 means +0.3."),
                 "historical_returns": _same("Historical returns", "Return series." + _NOT_READ),
                 "lookback_period": F(title="Lookback (days)", unit="days", desc="Lookback in days." + _NOT_READ)},
    "cva": {
        "ee_profile": _amt("EE profile", "Expected (positive) exposure per time point, in the trade currency."),
        "time_grid": _TIME_GRID,
        "credit_spread": _b("credit_spread_bp", "Credit spread", "Counterparty credit spread in basis points a year: "
                            "120 means 1.2% (hazard = spread / (1 - recovery)).", lo=0.0, warn=(0.0, 2000.0)),
        "recovery_rate": _RECOVERY,
        "spread_term_structure": _b("spread_term_structure_bp", "Spread term structure", "Credit spread per time point "
                                    "in basis points, overriding credit_spread_bp.", lo=0.0, warn=(0.0, 2000.0)),
        "discount_rates": _p("discount_rates_pct", "Discount rates", "Zero rate per time point in percent, continuously "
                             "compounded; empty = risk_free_rate_pct.", lo=-10.0, warn=(-2.0, 20.0)),
        "risk_free_rate": _p("risk_free_rate_pct", "Risk-free rate", "Flat zero rate in percent, continuously "
                             "compounded: 5 means 5%.", lo=-10.0, warn=(-2.0, 20.0)),
        "own_credit_spread": _b("own_credit_spread_bp", "Own credit spread", "Own spread in basis points (bilateral "
                                "CVA, with config bilateral).", lo=0.0, warn=(0.0, 2000.0)),
        "own_recovery_rate": _p("own_recovery_pct", "Own recovery rate", "Own recovery in percent (bilateral CVA).",
                                warn=(5.0, 80.0)),
        "notional": _amt("Notional", "Notional for cva_pct (CVA as a percentage of it)."),
    },
    "dva": {
        "exposure_profile": _amt("Exposure profile", "Exposure per time point; negative values (what we owe) give DVA."),
        "time_grid": _TIME_GRID,
        "own_pd_curve": _p("own_pd_curve_pct", "Own default curve", "Tenor -> own default probability per year in "
                           "percent (an intensity): {\"1Y\": 1, \"5Y\": 1.5}; empty = 1% a year."),
        "own_lgd": _p("own_lgd_pct", "Own LGD", "Own loss given default in percent: 60 means 60%."),
        "discount_curve": _DISCOUNT,
    },
    "fva": {
        "exposure_profile": _amt("Exposure profile", "Exposure per time point: positive is funded (cost), negative "
                                 "gives a benefit."),
        "time_grid": _TIME_GRID, "funding_spread": _FUNDING, "discount_curve": _DISCOUNT,
        "counterparty_survival_curve": _p("counterparty_survival_curve_pct", "Counterparty survival curve",
                                          "Tenor -> counterparty survival probability in percent: {\"5Y\": 95}; "
                                          "empty = 99%.", tiny=0.0),
    },
    "kva": {
        "ead_profile": _amt("EAD profile", "Exposure at default per time point."),
        "time_grid": _TIME_GRID,
        "counterparty_pd": _p("counterparty_pd_pct", "Counterparty PD", "One-year PD in percent: 1 means 1%."),
        "counterparty_lgd": _p("counterparty_lgd_pct", "Counterparty LGD", "LGD in percent: 45 means 45%."),
        "cost_of_capital": _p("cost_of_capital_pct", "Cost of capital", "Annual cost of capital in percent: 10 means 10%.",
                              warn=(0.0, 30.0)),
        "discount_curve": _DISCOUNT,
        "capital_floor": _p("capital_floor_pct", "Capital floor", "Minimum capital in percent of EAD: 0.03 means 0.03%.",
                            tiny=0.0),
    },
    "mva": {
        "initial_margin_profile": _amt("Initial margin profile", "Initial margin posted per time point."),
        "time_grid": _TIME_GRID, "funding_spread": _FUNDING, "discount_curve": _DISCOUNT,
    },
}
_HORIZON_CFG = F(name="time_horizon_years", title="Horizon (years)", desc="Horizon in years.", positive=True, **_YRS)
CALC_CONFIG: Dict[str, Dict[str, F]] = {
    "pd": {"model": _same("Model"), "time_horizon": _HORIZON_CFG},
    "lgd": {"model": _same("Model"),
            "default_lgd": _p("default_lgd_pct", "Default LGD", "LGD in percent when the model has no inputs."),
            "floor": _p("floor_pct", "LGD floor", "Lowest LGD in percent."),
            "cap": _p("cap_pct", "LGD cap", "Highest LGD in percent.")},
    "ead": {"method": _same("Method"), "alpha": _same("Alpha", "EAD multiplier; Basel uses 1.4."),
            "include_margin": _same("Include margin")},
    "el": {"time_horizon": _HORIZON_CFG, "annualize": _same("Annualize"),
           "use_term_structure": _same("Use the PD term structure")},
    "economic_capital": {"method": _same("Method"), "confidence_level": _CONF("99.9"),
                         "num_simulations": _same("Monte Carlo paths")},
    "raroc": {"hurdle_rate": _p("hurdle_rate_pct", "Hurdle rate", "Required return on capital in percent: 15 means "
                                "15%.", lo=-100.0, hi=1000.0, warn=(0.0, 50.0)),
              "include_xva": _same("Include XVA"), "use_regulatory_capital": _same("Use regulatory capital")},
    "ce": {"apply_netting": _same("Apply netting"), "apply_collateral": _same("Apply collateral"),
           "include_threshold": _same("Include threshold")},
    "ee": {"method": _same("Method"), "num_simulations": _same("Monte Carlo paths"),
           "calculate_effective": _same("Calculate effective EE")},
    "pfe": {"method": _same("Method"), "num_simulations": _same("Monte Carlo paths"), "time_horizon": _HORIZON_CFG,
            "confidence_level": _CONF("95")},
    "peak": {"method": _same("Method"), "num_simulations": _same("Monte Carlo paths")},
    "stressed": {"stress_type": _same("Stress type"), "default_scenario": _same("Default scenario")},
    "cva": {"method": _same("Method"), "bilateral": _same("Bilateral"), "wrong_way_risk": _same("Wrong-way risk"),
            "wwr_correlation": F(title="Wrong-way correlation (-1 to 1)", unit="-1 to 1", minimum=-1.0, maximum=1.0)},
}
CALC_CONFIG["eee"] = CALC_CONFIG["ee"]
# configuration keys qlrisk reads in a base class, which introspect.calculator_config (the subclass __init__) misses:
# ExposureCalculator reads confidence_level (default 0.95); of the exposure calculators only PFE uses it.
CALC_CONFIG_EXTRA: Dict[str, Dict[str, Dict[str, Any]]] = {
    "pfe": {"confidence_level": {"type": "number", "default": 0.95}},
}

# ── shocks: market_data.shocks, qlrisk_pnl_explain end_shocks, qlrisk_stress_test custom scenarios ──
# A shock's size is in the unit its factor's kind and shock type call for, and the field name says which:
# size_bp (basis points), size_pct (percent) or size (the factor's own units). Keyed by qlrisk's FactorKind and
# ShockType values (riskfactors/taxonomy.py, shocks.py): absolute is v + s, relative v x (1 + s), log v x exp(s).


@dataclass(frozen=True)
class ShockUnit:
    suffix: str                      # "_bp", "_pct" or "" (the factor's own units)
    scale: float                     # qlrisk size = exposed size x scale
    meaning: str                     # how the number applies, for descriptions and errors
    limit: Optional[float] = None    # |size| above it is an error (exposed units)
    usual: Optional[float] = None    # |size| above it prices with a warning
    floor: Optional[float] = None    # sizes below it are an error (a relative move below -100%)


FACTOR_KINDS = {"rate": "a rate", "spread": "a credit spread", "dividend": "a dividend yield", "vol": "a volatility",
                "spot": "an FX spot", "price": "a price", "scalar": "a scalar"}
_REL = ShockUnit("_pct", PCT, "percent of the level: -10 means the level x 0.90", 1000.0, 50.0, floor=-100.0)
_LOG = ShockUnit("_pct", PCT, "a log move in percent: -10 means the level x exp(-0.10)", 500.0, 50.0)
SHOCK_UNITS: Dict[Tuple[str, str], ShockUnit] = {
    ("rate", "absolute"): ShockUnit("_bp", BP, "basis points added to the rate: 25 means +0.25%", 5000.0, 1000.0),
    ("spread", "absolute"): ShockUnit("_bp", BP, "basis points added to the spread: 100 means +1%", 10000.0, 3000.0),
    ("dividend", "absolute"): ShockUnit("_bp", BP, "basis points added to the dividend yield", 5000.0, 1000.0),
    ("vol", "absolute"): ShockUnit("_pct", PCT, "volatility points in percent, added: 5 means 20% -> 25%", 200.0, 50.0),
    ("spot", "absolute"): ShockUnit("", 1.0, "quote currency per base unit, added to the spot"),
    ("price", "absolute"): ShockUnit("", 1.0, "price units, added to the price"),
    ("scalar", "absolute"): ShockUnit("", 1.0, "the factor's own units, added"),
    **{(k, "relative"): _REL for k in FACTOR_KINDS},
    **{(k, "log"): _LOG for k in FACTOR_KINDS},
}
SHOCK_SIZES = {"size": "Size", "short_end": "Short end (2y and in)", "long_end": "Long end (10y and out)",
               "wings": "Wings (2y and 10y)", "belly": "Belly (5y)"}

# a stylised stress (qlrisk StressDefinition; scenarios/stress_library.py stress_shocks): rates move every rate
# factor absolutely (a twist when two numbers), credit and vol move spreads and vols relatively, equity / commodity
# prices and FX spots relatively.
STRESS_DEFINITION: Dict[str, F] = {
    "description": _same("Description", "Defaults to the scenario name."),
    "equity": _p("equity_pct", "Equity move", "Relative move of every equity price in percent: -20 means -20%.",
                 lo=-100.0, hi=1000.0, warn=(-80.0, 100.0)),
    "vol": _p("vol_pct", "Volatility move", "Relative move of every implied volatility in percent: 100 means "
              "volatilities double.", lo=-100.0, hi=1000.0, warn=(-80.0, 400.0)),
    "rates": F(name="rates_bp", title="Rates move (bp)", unit="basis points", scale=BP, minimum=-5000.0, maximum=5000.0,
               warn=(-1000.0, 1000.0), desc="Absolute move of every interest rate in basis points: -50 means -0.50% "
               "at every tenor; or [short_end, long_end] for a twist from 2y to 10y."),
    "credit": _p("credit_pct", "Credit spread move", "Relative move of every credit spread in percent: 100 means "
                 "spreads double (qlrisk moves spreads relatively, not by basis points).", lo=-100.0, hi=2000.0,
                 warn=(-80.0, 500.0)),
    "fx_usd": _p("fx_usd_pct", "FX move against USD", "Relative move of every currency against USD in percent: -10 "
                 "means each currency loses 10% against USD (USD strengthens).", lo=-100.0, hi=1000.0,
                 warn=(-50.0, 100.0)),
    "commodity": _p("commodity_pct", "Commodity move", "Relative move of every commodity price in percent: -30 means "
                    "-30%.", lo=-100.0, hi=1000.0, warn=(-80.0, 200.0)),
    "fx": _p("fx_pct", "FX move by currency", "Currency -> relative move against USD in percent, overriding "
             "fx_usd_pct: {\"EUR\": -14}.", lo=-100.0, hi=1000.0, warn=(-50.0, 100.0)),
}

# liquidity-adjusted VaR (calculator/python/liquidity_var.py: cost = 0.5 x |value| x proportional spread)
LIQUIDITY: Dict[str, F] = {
    "spreads": F(name="spreads_bp", title="Bid-ask spreads (bp)", unit="basis points", scale=BP, minimum=0.0,
                 maximum=10000.0, warn=(0.0, 2000.0), desc="Trade id -> full bid-ask spread in basis points of the "
                 "position value: 20 means 0.20%; the exit cost is half the spread."),
    "horizon_days": F(title="Liquidity horizon (days)", unit="days", desc="Days to exit; VaR is scaled by its square "
                      "root."),
}


def field_spec(product: str, pricer: str, qname: str) -> F:
    """The table entry for one qlrisk field of one product (generic, then pricer, then product changes)."""
    f = FIELDS.get(qname, F())
    for key in (pricer, product):
        change = OVERRIDES.get(key, {}).get(qname)
        if change:
            f = replace(f, **change)
    return f


def notional_spec(product: str, pricer: str) -> Tuple[str, str, float, str]:
    return NOTIONAL_BY_PRODUCT.get(product) or NOTIONAL.get(pricer) or NOTIONAL["*"]


# ── examples and descriptions ───────────────────────────────────────


def _example(product: str) -> Dict[str, Any]:
    from . import introspect as I
    from .tools.products import exposed_fields
    if product in EXAMPLES:
        return dict(EXAMPLES[product])
    pricer = I.product_spec(product)["pricer"]
    ex: Dict[str, Any] = {}
    for e in exposed_fields(product):
        if e.advanced:
            continue
        if e.qname == "notional":
            ex[e.name] = e.schema["default"]
        elif e.required:
            if e.spec.example is not _NO:
                ex[e.name] = e.spec.example
            elif "enum" in e.schema:
                ex[e.name] = e.schema["enum"][0]
            else:
                raise ValueError(f"no example value for the required field {e.name!r}")
    ex.update(EXAMPLE_EXTRA.get(product) or EXAMPLE_EXTRA.get(pricer) or {})
    return ex


def _unit_text(e) -> str:
    """'coupon_pct* (percent, 3 = 3%)', 'frequency (annual/semi-annual/...; default semi-annual)'."""
    s, f = e.schema, e.spec
    bits = []
    if f.unit == "percent":
        bits.append("percent, 3 = 3%")
    elif f.unit == "basis points":
        bits.append("basis points, 25 = 0.25%")
    elif f.unit:
        bits.append(f.unit)
    elif f.tenor:
        bits.append("tenor like 3Y or date")
    elif e.qname in ("notional", "base_notional"):
        bits.append("amount")
    if "enum" in s:
        bits.append("/".join(str(v) for v in s["enum"]) if len(s["enum"]) <= 8 else "see the schema's list")
    if "default" in s:
        d = s["default"]
        bits.append(f"default {str(d).lower() if isinstance(d, bool) else d}")
    return e.name + ("*" if e.required else "") + (f" ({'; '.join(bits)})" if bits else "")


def _describe(product: str, example: Dict[str, Any], result: Dict[str, Any]) -> str:
    """Three lines: what it prices; the inputs with units; the worked example with its real result."""
    from . import introspect as I
    from .jsonable import rounded
    from .tools.products import exposed_fields
    spec = I.product_spec(product)
    fields = exposed_fields(product)
    main = [_unit_text(e) for e in fields if not e.advanced]
    adv = [e.name for e in fields if e.advanced] + ["market_data", "reporting_currency", "include_cash_flows"]
    what = spec["description"].rstrip(".")
    return (f"Price one {what} (qlrisk {product}): NPV, pricing components and Greeks where the pricer gives them.\n"
            f"Inputs (* required): {', '.join(main) if main else 'none'}. Rates are in percent, spreads in basis "
            f"points, maturities a tenor (3Y, 18M, 6W, 10D) or a date YYYY-MM-DD. Optional `advanced`: "
            f"{', '.join(adv)}; market data defaults to qlrisk's sample snapshot valued today.\n"
            f"Example: {json.dumps(example)} gives NPV {rounded(result['npv'])} {result['currency']} on the sample "
            f"market valued {EXAMPLE_DATE}. For several trades at once use qlrisk_price_trades.")


def _priceable(product: str, example: Dict[str, Any]) -> Dict[str, Any]:
    """Price the example on the sample market valued EXAMPLE_DATE; raise when it does not fit the schema or price."""
    import jsonschema
    from .options import Limits
    from .tools import Ctx
    from .tools.products import price_one, product_tool
    jsonschema.validate(example, product_tool(product, Limits()).input_schema)
    adv = {**example.get("advanced", {}), "market_data": {"valuation_date": EXAMPLE_DATE}}
    result, _ = price_one(product, {**example, "advanced": adv}, Ctx(Limits()))
    return result


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
            result = _priceable(product, example)
        except Exception as exc:
            skipped.append((product, f"{type(exc).__name__}: {exc}"))
            continue
        spec = I.product_spec(product)
        configs[f"{name}.json"] = {
            "name": name,
            "implementation": IMPLEMENTATION,
            "product": product,
            "title": f"Price a {product}",
            "description": _describe(product, example, result),
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
                         "example": example,
                         "example_result": {"valuation_date": EXAMPLE_DATE, "npv": round(result["npv"], 2),
                                            "currency": result["currency"]}},
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
