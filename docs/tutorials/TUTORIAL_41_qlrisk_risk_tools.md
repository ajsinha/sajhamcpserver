# Tutorial 41: qlrisk Risk Tools

qlrisk is a risk-analytics library (pricing, sensitivities, VaR and ES, stress, FRTB, SA-CCR, exposure, XVA).
SAJHA ships its tools as native tools in `config/tools/qlrisk/`, named `qlrisk_<tool>`; they load once
qlrisk is installed into SAJHA's environment. This tutorial installs it, watches the tools appear, prices a
swap, runs VaR and ES, a stress test, SA-CCR and CVA, and asks Ask SAJHA a risk question that uses the
tools. Every tool, input and output is in the
[QLRisk Tool Reference Guide](../tools/qlrisk/QLRisk%20Tool%20Reference%20Guide.md).

## What you'll learn

- How an optional dependency switches a set of tools on (`"requires"` in a tool config)
- How to describe a trade and a market to the tools, and what comes back
- How to read VaR, ES, a stress run, an SA-CCR EAD and a CVA from the results
- How Ask SAJHA chooses a risk tool from its description

## Prerequisites

- A SAJHA instance you administer (the [Quick Start](../getting-started/Quick%20Start.md)), or the
  [local test lab](TUTORIAL_29_local_test_lab.md)
- The qlrisk wheel (`qlrisk-<version>-py3-none-any.whl`), from its owner; it brings QuantLib, numpy and scipy
- An API key in `$SAJHA_KEY` ([Tutorial 1](TUTORIAL_01_getting_started.md))

## Steps

### 1. Before: the tools are skipped

Without qlrisk the tools are not loaded. Open the system status panel on the dashboard (`/dashboard#system-status`): an
info notice says "qlrisk is not installed: N qlrisk tools are skipped" and names them. They are not failed
tools and are not in `tools/list`; each config in `config/tools/qlrisk/` declares
`"requires": ["qlrisk"]`, and the registry skips a tool whose required module is not importable
([Architecture](../architecture/Architecture.md#tool-config-files-and-folders), "Optional dependencies").

### 2. Install qlrisk and watch the tools appear

Install the wheel into the Python environment SAJHA runs in, either directly or through
`requirements-qlrisk.txt` after putting your wheel's path in it:

```bash
pip install /path/to/qlrisk-<version>-py3-none-any.whl       # with SAJHA's python / virtualenv active
python -c "import qlrisk; print(qlrisk.__version__)"
```

No restart: the registry re-checks skipped tools every `tools.retry_failed_seconds` (default 300), so
within one interval the tools load and the notice clears. Then:

```bash
curl -s http://localhost:3002/api/tools/list -H "X-API-Key: $SAJHA_KEY" \
  | python3 -c "import json,sys; n=[t['name'] for t in json.load(sys.stdin)['tools'] if t['name'].startswith('qlrisk_')]; print(sorted(x for x in n if not x.startswith('qlrisk_price_') or x == 'qlrisk_price_trades')); print(sum(x.startswith('qlrisk_price_') and x != 'qlrisk_price_trades' for x in n), 'per-product pricing tools')"
```

```text
['qlrisk_backtest', 'qlrisk_basel25_capital', 'qlrisk_catalog', 'qlrisk_ccr_exposure', 'qlrisk_check_limits',
 'qlrisk_credit_risk', 'qlrisk_frtb_ima_capital', 'qlrisk_frtb_sa_capital', 'qlrisk_initial_margin',
 'qlrisk_pnl_explain', 'qlrisk_price_trades', 'qlrisk_risk_report', 'qlrisk_saccr', 'qlrisk_sensitivities',
 'qlrisk_simulate_paths', 'qlrisk_stress_test', 'qlrisk_value_at_risk', 'qlrisk_xva']
<N> per-product pricing tools
```

The second line counts the per-product pricing tools, one per qlrisk product (step 4).

**On the local lab:** install the wheel into the lab's virtualenv (the python that runs the instances) and
use an instance's address and the lab's key in the calls below.

A helper for the rest of the tutorial calls a tool over MCP (2026-07-28, one stateless POST) and prints the
first line of the text block, the summary; the full result is in `structuredContent`:

```bash
call() { curl -s -X POST http://localhost:3002/mcp -H "X-API-Key: $SAJHA_KEY" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: tools/call' -H "Mcp-Name: $1" \
  -d "{\"jsonrpc\": \"2.0\", \"id\": 1, \"method\": \"tools/call\", \"params\": {\"name\": \"$1\", \"arguments\": $2,
       \"_meta\": {\"io.modelcontextprotocol/protocolVersion\": \"2026-07-28\", \"io.modelcontextprotocol/clientCapabilities\": {},
                 \"io.modelcontextprotocol/clientInfo\": {\"name\": \"curl\", \"version\": \"1\"}}}}" \
  | python3 -c "import json,sys; r=json.load(sys.stdin); r=r.get('result', r); print(r['content'][0]['text'].splitlines()[0] if 'content' in r else r)"; }
```

The same tools answer `POST /api/tools/execute`, which returns the result object as `result`.

### 3. Price a swap

A trade is an object with `product` (a qlrisk product class) and its terms in human units: a maturity as a
tenor, rates in percent (`fixed_rate_pct` 4.4 is 4.40%). Market data defaults to qlrisk's sample snapshot;
here it is valued on 9 October 2026, sent in the optional `advanced` object with the other technical
settings:

```bash
SWAP='{"product": "InterestRateSwap", "trade_id": "IRS-5Y", "maturity": "5Y", "notional": 10000000, "fixed_rate_pct": 4.4, "counterparty_id": "BANK-A"}'
MD='{"valuation_date": "2026-10-09"}'
ADV="{\"market_data\": $MD}"
call qlrisk_price_trades "{\"trades\": [$SWAP], \"advanced\": $ADV}"
call qlrisk_sensitivities "{\"trades\": [$SWAP], \"ladder_vertices\": \"frtb_girr\", \"advanced\": $ADV}"
```

```text
1 trade(s) priced on 2026-10-09: total NPV -22,834.98 USD
Sensitivities in USD for 1 trade(s): DV01 4,561.84
```

The payer swap pays 4.40% against a par rate of about 4.35% (`components.par_rate`), so it is slightly
under water, and it gains about 4,562 USD per basis point of higher rates, almost all of it in the 5-year
SOFR bucket of the ladder. To see what the tools know, call `qlrisk_catalog` with
`{"topic": "products"}`, or `{"topic": "products", "name": "CorporateBond"}` for one product's inputs.

### 4. Price a bond with its own tool

Every qlrisk product also has a pricing tool of its own, `qlrisk_price_<product>`, whose inputs are only
that product's terms in human units ([Per-product pricing tools](../tools/qlrisk/QLRisk%20Tool%20Reference%20Guide.md#per-product-pricing-tools)):
rates in percent, spreads in basis points, a maturity as a tenor or a date. A 3-year US treasury paying 3%,
face 100:

```bash
call qlrisk_price_treasury_bond "{\"maturity\": \"3Y\", \"face_value\": 100, \"coupon_pct\": 3, \"advanced\": {\"market_data\": $MD}}"
```

```text
TreasuryBond on 2026-10-09: NPV 97.85 USD
```

`coupon_pct` 3 means 3%; the result's `qlrisk_terms` shows what qlrisk received (`"coupon": 0.03`,
`"maturity_date": "2029-10-09"`). Send `coupon_pct` 300 and the call is rejected with the field named. A
5-year corporate bond paying 5% on ACME's credit curve puts the issuer in `advanced`:

```bash
call qlrisk_price_corporate_bond "{\"maturity\": \"5Y\", \"face_value\": 5000000, \"coupon_pct\": 5, \"advanced\": {\"issuer\": \"ACME\", \"market_data\": $MD}}"
```

```text
CorporateBond on 2026-10-09: NPV 4,886,813.03 USD
```

The bond is worth about 97.7% of par: the coupon is discounted at the curve plus ACME's credit spread
(`components.credit_spread`, 1.2%). On `/tools/qlrisk_price_treasury_bond/execute` the form shows only
maturity, face value, coupon, frequency and currency; the rest is under **Advanced (optional)**.

### 5. VaR and Expected Shortfall

Add a short SPX put and ask for 10-day VaR and ES at 99% (`confidence_pct` is in percent), with stressed
VaR. History defaults to a 750-day synthetic history ending at the market data, with a stress regime:

```bash
PUT='{"product": "EquityOption", "trade_id": "SPX-P", "maturity": "6M", "notional": 1000000, "ticker": "SPX", "strike": 5000, "option_type": "put", "counterparty_id": "BANK-B"}'
call qlrisk_value_at_risk "{\"trades\": [$SWAP, $PUT], \"method\": \"historical\", \"confidence_pct\": 99, \"horizon_days\": 10, \"advanced\": {\"market_data\": $MD, \"include_stressed_var\": true}}"
```

```text
historical VaR 99.0% 10d 204,153.91 USD; ES 97.5% 193,288.73; SVaR 561,570.24
```

`var.contributions` splits the VaR by trade (here 186,413 for the swap and 17,741 for the put); try
`"method": "monte_carlo"` or `"parametric"`, and `qlrisk_backtest` on the same trades for the
traffic-light zone.

### 6. A stress test

Revalue the book under qlrisk's crisis library, then under a scenario of your own:

```bash
call qlrisk_stress_test "{\"trades\": [$SWAP, $PUT], \"advanced\": $ADV}"
call qlrisk_stress_test "{\"trades\": [$SWAP], \"advanced\": $ADV, \"mode\": \"custom\", \"custom_scenarios\": [{\"name\": \"rates +100bp\", \"shocks\": [{\"risk_classes\": [\"IR\"], \"shape\": \"parallel\", \"size_bp\": 100}]}]}"
```

```text
9 stress scenario(s); worst 2008_gfc_lehman P&L -423,260.25 USD
1 stress scenario(s); worst rates +100bp P&L 445,355.39 USD
```

A shock's size field names its unit: `size_bp` for an absolute move of rates or spreads (100 = +1%),
`size_pct` for a relative move (`{"factor": "EQ.SPX", "shock_type": "relative", "size_pct": -20}`), `size`
for an absolute move of a price in its own units. A stylised scenario takes relative moves in percent and
rates in basis points: `{"name": "risk off", "definition": {"equity_pct": -20, "vol_pct": 50, "credit_pct":
50, "rates_bp": -50}}`. The result's `qlrisk_inputs` shows each scenario as qlrisk received it (`"size":
0.01`).

`results` lists every scenario, worst first, with the P&L of each trade. `"mode": "reverse"` with
`"target_loss": 500000` asks the opposite question: the most plausible market move that loses that much.

### 7. SA-CCR

The swap faces `BANK-A` under a margined CSA with no threshold:

```bash
call qlrisk_saccr "{\"trades\": [$SWAP], \"advanced\": $ADV, \"csa\": {\"BANK-A\": {\"margined\": true, \"threshold\": 0}}}"
```

```text
SA-CCR EAD 78,272.06 USD across 1 netting set(s)
```

The netting set has no replacement cost (the swap is under water), an interest-rate add-on of 66,352 and a
multiplier of 0.84, from the negative MTM; EAD = 1.4 × (RC + multiplier × add-on).

### 8. CVA

From an expected-exposure profile and a 120bp credit spread (calculator inputs take the same units as
everything else: spreads in basis points, probabilities, recoveries and rates in percent):

```bash
call qlrisk_xva '{"measure": "cva", "inputs": {"ee_profile": [2e6, 3e6, 3.5e6, 3e6, 2e6, 1e6], "time_grid": [0.5, 1, 2, 3, 4, 5], "credit_spread_bp": 120}}'
```

```text
CVA: 118,737.19
```

`qlrisk_inputs.inputs` in the result shows `"credit_spread": 0.012`, what qlrisk received. A recovery is
`recovery_pct` (40 by default); `qlrisk_credit_risk` reads the same way (`{"measure": "el", "inputs":
{"pd_pct": 2, "lgd_pct": 45, "ead": 1000000}}` gives `EL: 9,000.00`).

The same tool gives DVA, FVA, KVA and MVA, their total, and CVA capital: `"measure": "sa_cva"` (the
counterparty's credit curve from the market data, optional hedges) or `"ba_cva"`.

### 9. Ask SAJHA a risk question

With the intelligence layer configured ([Intelligence Layer](../architecture/Intelligence%20Layer.md)),
open **AI > Ask SAJHA** and ask:

> What is the 10-day 99% VaR of a 10 million 5-year payer swap at 4.4% fixed against SOFR?

Or from the shell:

```bash
curl -s -X POST http://localhost:3002/api/ai/ask -H "X-API-Key: $SAJHA_KEY" -H 'Content-Type: application/json' \
  -d '{"question": "What is the 10-day 99% VaR of a 10 million 5-year payer swap at 4.4% fixed against SOFR?"}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['answer']); print([s['name'] for s in d['steps']])"
```

The steps should show `qlrisk_value_at_risk`: the model chose it from its description, built the trade
from the description's example, SAJHA checked access and policy and ran the tool, and the model
wrote the answer from the result. The figure depends on the day (the sample market is valued today when the
question gives no date). A small local model may need the question to be explicit, or a call to
`qlrisk_catalog` first.

## What you learned

- The risk tools are native SAJHA tools that need qlrisk; `"requires": ["qlrisk"]` skips them until it is
  installed, and the retry loop loads them without a restart
- A trade is `product` plus terms; market data and history default to qlrisk's sample and a synthetic
  history, and every part can be overridden
- Each result has a one-line summary and the full JSON in `structuredContent`
- Ask SAJHA picks a risk tool from its description and fills its arguments from the question

## Next

- Every tool, mode, input, output and bound: the
  [QLRisk Tool Reference Guide](../tools/qlrisk/QLRisk%20Tool%20Reference%20Guide.md)
- Tool configs, folders and `requires`: [Architecture](../architecture/Architecture.md#tool-config-files-and-folders)
- Next tutorial: [Tutorial 42: Per-User Sign-In for Proxied Servers](TUTORIAL_42_per_user_sign_in.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
