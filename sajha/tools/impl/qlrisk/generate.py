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

This module also holds the one table that turns qlrisk's fields into the tools' human inputs (FIELDS,
OVERRIDES, NOTIONAL): which name a field is shown under, its unit (rates in percent, spreads in basis
points), the conversion to qlrisk's own units (qlrisk takes decimals: 0.03 is 3%), bounds, defaults and
whether it sits in the tool's optional ``advanced`` object. tools/products.py builds the schemas and
converts the arguments from it; a qlrisk field the table does not name is passed as is and documented
as taking qlrisk's own units.
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
    # nested qlrisk objects: passed as is
    **{k: F(title=t, desc=f"{t}: qlrisk's own object, passed as is in qlrisk's units (rates as decimals: 0.03 = 3%).")
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
    "CollateralSwap": {},
}
for _p, (_ccy, _freq) in _BOND_MARKET.items():
    OVERRIDES[_p] = {"currency": {"default": _ccy}, "frequency": {"default": _freq}}

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
