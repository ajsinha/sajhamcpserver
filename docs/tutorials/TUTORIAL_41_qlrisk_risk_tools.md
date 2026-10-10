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

A trade is an object with `product` (a qlrisk product class) and its terms. Market data defaults to
qlrisk's sample snapshot; here it is valued on 9 October 2026:

```bash
SWAP='{"product": "InterestRateSwap", "trade_id": "IRS-5Y", "notional": 10000000, "tenor_years": 5, "fixed_rate": 0.044, "counterparty_id": "BANK-A"}'
MD='{"valuation_date": "2026-10-09"}'
call qlrisk_price_trades "{\"trades\": [$SWAP], \"market_data\": $MD}"
call qlrisk_sensitivities "{\"trades\": [$SWAP], \"market_data\": $MD, \"ladder_vertices\": \"frtb_girr\"}"
```

```text
1 trade(s) priced on 2026-10-09: total NPV -22,834.98 USD
Sensitivities in USD for 1 trade(s): DV01 4,561.84
```

The payer swap pays 4.40% against a par rate of about 4.35% (`components.par_rate`), so it is slightly
under water, and it gains about 4,562 USD per basis point of higher rates, almost all of it in the 5-year
SOFR bucket of the ladder. To see what the tools know, call `qlrisk_catalog` with
`{"topic": "products"}`, or `{"topic": "products", "name": "CorporateBond"}` for one product's terms.

### 4. Price a bond with its own tool

Every qlrisk product also has a pricing tool of its own, `qlrisk_price_<product>`, whose inputs are only
that product's fields ([Per-product pricing tools](../tools/qlrisk/QLRisk%20Tool%20Reference%20Guide.md#per-product-pricing-tools)).
A 5-year corporate bond paying 5%:

```bash
call qlrisk_price_corporate_bond "{\"notional\": 5000000, \"tenor_years\": 5, \"coupon\": 0.05, \"issuer\": \"ACME\", \"market_data\": $MD}"
```

```text
CorporateBond CorporateBond-1 on 2026-10-09: NPV 4,886,813.03 USD
```

The bond is worth about 97.7% of par: the coupon is discounted at the curve plus ACME's credit spread
(`components.credit_spread`, 1.2%). Send a field the bond does not have, such as `strike`, and the call is
rejected with the field named; `tools/list` shows each tool's fields.

### 5. VaR and Expected Shortfall

Add a short SPX put and ask for 10-day VaR and ES, with stressed VaR. History defaults to a 750-day
synthetic history ending at the market data, with a stress regime:

```bash
PUT='{"product": "EquityOption", "trade_id": "SPX-P", "notional": 1000000, "tenor_years": 0.5, "ticker": "SPX", "strike": 5000, "is_call": false, "counterparty_id": "BANK-B"}'
call qlrisk_value_at_risk "{\"trades\": [$SWAP, $PUT], \"market_data\": $MD, \"method\": \"historical\", \"horizon_days\": 10, \"include_stressed_var\": true}"
```

```text
historical VaR 99.0% 10d 204,168.67 USD; ES 97.5% 193,300.83; SVaR 561,506.31
```

`var.contributions` splits the VaR by trade (here 186,413 for the swap and 17,755 for the put); try
`"method": "monte_carlo"` or `"parametric"`, and `qlrisk_backtest` on the same trades for the
traffic-light zone.

### 6. A stress test

Revalue the book under qlrisk's crisis library, then under a scenario of your own:

```bash
call qlrisk_stress_test "{\"trades\": [$SWAP, $PUT], \"market_data\": $MD}"
call qlrisk_stress_test "{\"trades\": [$SWAP], \"market_data\": $MD, \"mode\": \"custom\", \"custom_scenarios\": [{\"name\": \"rates +100bp\", \"shocks\": [{\"risk_classes\": [\"IR\"], \"shape\": \"parallel\", \"size\": 0.01}]}]}"
```

```text
9 stress scenario(s); worst 2008_gfc_lehman P&L -423,225.11 USD
1 stress scenario(s); worst rates +100bp P&L 445,355.39 USD
```

`results` lists every scenario, worst first, with the P&L of each trade. `"mode": "reverse"` with
`"target_loss": 500000` asks the opposite question: the most plausible market move that loses that much.

### 7. SA-CCR

The swap faces `BANK-A` under a margined CSA with no threshold:

```bash
call qlrisk_saccr "{\"trades\": [$SWAP], \"market_data\": $MD, \"csa\": {\"BANK-A\": {\"margined\": true, \"threshold\": 0}}}"
```

```text
SA-CCR EAD 78,272.06 USD across 1 netting set(s)
```

The netting set has no replacement cost (the swap is under water), an interest-rate add-on of 66,352 and a
multiplier of 0.84, from the negative MTM; EAD = 1.4 × (RC + multiplier × add-on).

### 8. CVA

From an expected-exposure profile and a 120bp credit spread:

```bash
call qlrisk_xva '{"measure": "cva", "inputs": {"ee_profile": [2e6, 3e6, 3.5e6, 3e6, 2e6, 1e6], "time_grid": [0.5, 1, 2, 3, 4, 5], "credit_spread": 0.012}}'
```

```text
CVA: 118,737.19
```

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
- This is the last tutorial; the [documentation index](../README.md) lists every guide

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
