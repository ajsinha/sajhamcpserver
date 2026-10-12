# Tutorial 54: How a Figure Was Computed

When a quantitative planner answers, every figure it computed can show where it came from: the
operation and its inputs, down to the tool calls, each with its tool, call id, arguments, JSON path,
as-of date and unit. On the Ask SAJHA page the figures are buttons that open that lineage under the
answer. Units, the part that most often goes wrong, can come from the tool itself: a tool declares the
unit of a result field with `x-sajha-unit` in its `outputSchema`, and a planner that reads that field
takes the tool's word over the model's. This tutorial reads the lineage the page draws, follows it to
tool calls, and shows `x-sajha-unit` at work on a real tool result. The design is
[Quantitative Planners](../architecture/Quantitative%20Planners.md) §2.1 (quantities and lineage) and
§2.2 (units); the event and result fields are in
[Intelligence Layer](../architecture/Intelligence%20Layer.md), "POST /api/ai/ask".

**What was verified.** Every step below was run as written against a server started from a checkout
on a scratch database (`SAJHA_DB_PATH`), cache directory (`SAJHA_CACHE_DIR`) and scratch directory
(`SAJHA_BI_SCRATCH_DIR`), with the default offline mock provider, and the outputs are from that run.
Step 4 calls the ECB's public data API (no key; it needs internet access), so its figures are the
ECB's on the day you run it. Step 6 was also checked in a headless browser with Playwright.

## What you'll learn

- Which figures of an answer are marked, and what the `workspace` event carries
- How to read a lineage from a figure down to constants and tool calls
- What `x-sajha-unit` declares, how a planner finds the unit for a read path, and what `unit_from`
  records
- How lint checks a declared unit

## Prerequisites

- A SAJHA checkout and its environment; [Tutorial 45](TUTORIAL_45_quantitative_planners.md) introduces
  the quantitative planners used here (`calc_graph`, `reconcile`)
- An administrator credential (choosing the planner per ask is for administrators): the development
  key from `config/apikeys.json`

```bash
P=/tmp/t54; mkdir -p $P
SAJHA_DB_PATH=$P/t54.db SAJHA_CACHE_DIR=$P/cache SAJHA_BI_SCRATCH_DIR=$P/scratch \
  .venv/bin/python run_sajha_web.py --host 127.0.0.1 --port 3197
```

In a second shell, a helper that asks with a chosen planner, prints the answer, and then prints each
marked figure's lineage from the stream's `workspace` event, the way the page lays it out:

```bash
K='X-API-Key: sja_test_admin_dev_key_0001'; B=http://127.0.0.1:3197
lineage() {  # lineage QUESTION PLANNER-JSON
  body=$(python3 -c "import json,sys; print(json.dumps({'question': sys.argv[1], 'planner': json.loads(sys.argv[2])}))" "$1" "$2")
  curl -s -N -X POST "$B/api/ai/ask?stream=1" -H "$K" -H 'Content-Type: application/json' -d "$body" | python3 -c "
import json,sys
ws=None
for line in sys.stdin:
    if not line.startswith('data: '): continue
    e=json.loads(line[6:])
    if e['type']=='answer': print('answer:', e['text'])
    if e['type']=='workspace': ws=e
def show(name, depth):
    q=ws['quantities'][name]; s=q['source']; pad='  '*depth
    if s['kind']=='operation':
        print(f\"{pad}{name} = {q['value']:.10g} {q['unit']}: {q['op']}({', '.join(q['inputs'])}) {q['args'] or ''}\")
        for i in q['inputs']: show(i, depth+1)
    elif s['kind']=='tool':
        print(f\"{pad}{name} = {q['value']:.10g} {q['unit']} (unit from {s['unit_from']}): {s['tool']} {s['call_id']} {s['arguments']} at {s['path']}, as of {q['as_of'] or 'not stated'}\")
    else:
        print(f\"{pad}{name} = {q['value']:.10g} {q['unit']}: {s.get('text')}\")
for f in (ws or {}).get('figures', []):
    print(f\"figure {f['text']!r} at {f['start']}-{f['end']}:\"); show(f['quantity'], 1)
"
}
```

## 1. The `workspace` event

Ask `calc_graph` for a growth rate and look at the raw event the page receives after the answer:

```bash
body='{"question": "What is the CAGR of revenue that grew from 120 to 180 over 5 years?", "planner": "calc_graph"}'
curl -s -N -X POST "$B/api/ai/ask?stream=1" -H "$K" -H 'Content-Type: application/json' -d "$body" \
  | grep -A1 '^event: workspace' | sed -n 2p | cut -c7-
```

```text
{"type": "workspace", "seq": 18, "figures": [{"start": 10, "end": 28, "text": "8.44717712 percent", "quantity": "growth"}], "quantities": {"growth": {"value": 8.447177119769854, "cells": 1, "unit": "percent", "as_of": null, "source": {"kind": "operation", "op": "cagr"}, "op": "cagr", "args": {"years": 5.0}, "inputs": ["start", "end", "years"]}, "start": {"value": 120.0, "cells": 1, "unit": "unitless", "as_of": null, "source": {"kind": "constant", "text": "stated in the question"}}, "end": {"value": 180.0, "cells": 1, "unit": "unitless", "as_of": null, "source": {"kind": "constant", "text": "stated in the question"}}, "years": {"value": 5.0, "cells": 1, "unit": "years", "as_of": null, "source": {"kind": "constant", "text": "stated in the question"}}}}
```

`figures` are the spans of the answer that match a
workspace quantity, by the numbers validator's rules (offsets in code points); `quantities` holds each
marked quantity and everything its lineage reaches. A JSON (not streamed) ask carries the same
`figures` in its result, beside the whole `workspace`. A figure no quantity matches is not marked.

## 2. Read a lineage

```bash
lineage "What is the CAGR of revenue that grew from 120 to 180 over 5 years?" '"calc_graph"'
```

```text
answer: growth is 8.44717712 percent.
figure '8.44717712 percent' at 10-28:
  growth = 8.44717712 percent: cagr(start, end, years) {'years': 5.0}
    start = 120 unitless: stated in the question
    end = 180 unitless: stated in the question
    years = 5 years: stated in the question
```

This is what the page shows when you select the figure: the operation, then its inputs. Here they
are constants the question stated; nothing came from a tool.

## 3. Down to the tool calls

`reconcile` reads one figure from two tools and compares them. Each reading is a tool quantity, and
the difference is an operation over them:

```bash
lineage 'Do calc_future_value and calc_compound_interest agree on the future value? present value 5000, principal 5000, rate 7, years 20, compounds_per_year 12' '"reconcile"'
```

```text
answer: undated: calc_compound_interest 20,193.69; calc_future_value 19,348.42; calc_future_value − calc_compound_interest -845.27 (-4.19%) BEYOND TOLERANCE.
figure '20,193.69' at 32-41:
  compare.future_value.calc_compound_in = 20193.69 unitless (unit from declared): calc_compound_interest call_1_3e9a4cda {'principal': 5000, 'rate': 7, 'years': 20, 'compounds_per_year': 12} at $.future_value, as of not stated
figure '19,348.42' at 61-70:
  compare.future_value.calc_future_valu = 19348.42 unitless (unit from declared): calc_future_value call_2_91248c16 {'present_value': 5000, 'rate': 7, 'years': 20} at $.future_value, as of not stated
figure '-845.27' at 115-122:
  compare.future_value.calc_future_valu.diff = -845.27 unitless: diff(compare.future_value.calc_future_valu, compare.future_value.calc_compound_in) 
    compare.future_value.calc_future_valu = 19348.42 unitless (unit from declared): calc_future_value call_2_91248c16 {'present_value': 5000, 'rate': 7, 'years': 20} at $.future_value, as of not stated
    compare.future_value.calc_compound_in = 20193.69 unitless (unit from declared): calc_compound_interest call_1_3e9a4cda {'principal': 5000, 'rate': 7, 'years': 20, 'compounds_per_year': 12} at $.future_value, as of not stated
figure '-4.19%' at 124-130:
  compare.future_value.calc_future_valu.diff_pct = -4.185812499 percent: pct_change(compare.future_value.calc_compound_in, compare.future_value.calc_future_valu) 
    compare.future_value.calc_compound_in = 20193.69 unitless (unit from declared): calc_compound_interest call_1_3e9a4cda {'principal': 5000, 'rate': 7, 'years': 20, 'compounds_per_year': 12} at $.future_value, as of not stated
    compare.future_value.calc_future_valu = 19348.42 unitless (unit from declared): calc_future_value call_2_91248c16 {'present_value': 5000, 'rate': 7, 'years': 20} at $.future_value, as of not stated
```

Every figure ends at a tool call you can find in the Ask result's `steps` by its call id, with the
arguments it was called with and the JSON path read. `unit from declared` means the unit is the
planner's (the model's) declaration: `future_value` has no fixed unit (its currency is the caller's),
so the calculators do not declare one.

## 4. A unit the tool declares: `x-sajha-unit`

A field whose unit is fixed says so in the tool's `outputSchema`. `calc_percentage_change` declares
its result in percent:

```bash
python3 -c "import json; print(json.dumps(json.load(open('config/tools/calc/calc_percentage_change.json'))['outputSchema']['properties']['percentage_change']))"
```

```text
{"type": "number", "description": "(new - old) / |old| * 100", "x-sajha-unit": "percent"}
```

The rate tools of `fred`, `ecb`, `bank_of_canada`, `bank_of_japan`, `bis` and `us_treasury` declare
theirs too. Call the ECB's deposit facility rate (keyless):

```bash
curl -s -X POST $B/api/tools/execute -H "$K" -H 'Content-Type: application/json' \
  -d '{"tool": "ecb_get_interest_rate", "arguments": {"rate_type": "deposit_facility_rate", "start_date": "2026-01-01"}}' > $P/ecb.json
python3 -c "import json,sys; r=json.load(open(sys.argv[1]))['result']; print(r['label'], '|', r['unit']); print(r['observations'])" $P/ecb.json
```

```text
Deposit facility - date of changes (raw data) - Level | PCPA
[{'date': '2026-06-17', 'value': 2.25}, {'date': '2026-09-16', 'value': 2.5}]
```

The ECB's own unit code (`PCPA`) means nothing to a planner. The schema does. When a planner reads a
value at a JSONPath, `schema_unit` finds the unit the schema declares for that path, and the quantity
records that the unit came from the schema. The same steps in Python, on that result:

```bash
.venv/bin/python - $P/ecb.json <<'EOF'
import json, sys
from sajha.ai.quant import Quantity, schema_unit
schema = json.load(open('config/tools/ecb/ecb_get_interest_rate.json'))['outputSchema']
for path in ('$.observations[0].value', '$.observations[*].value', '$.observation_count'):
    print(path, '->', schema_unit(schema, path))
result = json.load(open(sys.argv[1]))['result']
path = '$.observations[1].value'
obs = result['observations'][1]
unit = schema_unit(schema, path)
q = Quantity.from_tool(obs['value'], unit, call_id='call_1', tool='ecb_get_interest_rate', path=path,
                       as_of=obs['date'], unit_from='schema')
print(q.value, q.unit, q.as_of, q.source['unit_from'])
print(q.to('bp').value, q.to('bp').unit)
EOF
```

```text
$.observations[0].value -> percent
$.observations[*].value -> percent
$.observation_count -> None
2.5 percent 2026-09-16 schema
250.0 bp
```

One observation and the whole column both resolve to `percent`; a field that declares nothing gives
none, and the model's declaration stands. In a run, `calc_graph` applies the schema's unit before its
unit check (so a read may leave `unit` out), `scenario` applies it to its grid's `value_path`, and
`reconcile` to each reading and FX rate; the lineage then says `unit from schema`. Because the unit is
known, SAJHA converts it as §2.2 allows (here to basis points) and refuses conversions it does not
allow, such as a rate to a level.

## 5. Lint checks the unit

JSON Schema validation ignores `x-` keywords, so a misspelt unit would pass silently; lint's `unit`
rule catches it. The shipped tool is clean; a copy with a typo is not:

```bash
.venv/bin/python - <<'EOF'
import json
from sajha.quality.lint import lint_tool
t = json.load(open('config/tools/calc/calc_percentage_change.json'))
print([f for f in lint_tool(t['name'], t) if f.rule == 'unit'])
t['outputSchema']['properties']['percentage_change']['x-sajha-unit'] = 'percents'
for f in lint_tool(t['name'], t):
    if f.rule == 'unit': print(f.level, f.rule, f.message)
EOF
```

```text
[]
error unit output properties/percentage_change: x-sajha-unit 'percents' is not a unit SAJHA knows: unit 'percents' is not one SAJHA knows: use a currency code with an optional scale ('USD', 'USD mn'), 'count', 'percent', 'pp', 'bp', 'ratio', 'index', 'days', 'years' or 'unitless'
```

`python -m sajha.quality lint --tool <glob>` runs the same over loaded tools
([Tool Quality](../architecture/Tool%20Quality.md) §3).

## 6. On the page

The page has no planner picker: it asks with the server's planner, `ai.ask.planner` (`react` by
default), which computes no workspace. Restart the server with `auto`, which sends a question like
this one to `calc_graph`:

```bash
SAJHA_AI_ASK_PLANNER=auto SAJHA_DB_PATH=$P/t54.db SAJHA_CACHE_DIR=$P/cache SAJHA_BI_SCRATCH_DIR=$P/scratch \
  .venv/bin/python run_sajha_web.py --host 127.0.0.1 --port 3197
```

Sign in, open **Ask SAJHA** (`/ask`) and ask the question of step 2. The figure `8.44717712 percent` is
underlined, with a note under the answer that underlined figures were computed by SAJHA: it is a
button. Select it (click, or Tab to it and press Enter) and the lineage of step 2 opens under the
answer; for a tool read it shows the tool, call id, arguments, JSON path, as-of date ("not stated"
when the source gives none), unit and whether the tool's schema or the model declared it. **Close**,
or Escape while focus is in the panel, shuts it and puts focus back on the figure. The page's script
is `static/js/ask_lineage.js`; it builds the panel with `textContent` only, so nothing in a tool result
is ever parsed as markup.

The same from a script, with [Playwright](https://playwright.dev/python/) and its Chromium installed
(`pip install playwright && playwright install chromium`; not part of SAJHA's requirements):

```python
from playwright.sync_api import sync_playwright
B = 'http://127.0.0.1:3197'
with sync_playwright() as p:
    browser = p.chromium.launch()
    pg = browser.new_page()
    pg.goto(B + '/login')
    pg.fill('input[name=user_id]', 'testadmin'); pg.fill('input[name=password]', 'testadmin-dev-1')
    pg.click('button[type=submit]')
    pg.goto(B + '/ask')
    pg.fill('textarea', 'What is the CAGR of revenue that grew from 120 to 180 over 5 years?')
    pg.keyboard.press('Enter')
    fig = pg.wait_for_selector('button.ask-fig')
    pg.wait_for_timeout(2000)                          # let the answer finish streaming
    print('figure:', fig.inner_text(), '|', fig.get_attribute('aria-label'))
    pg.focus('button.ask-fig'); pg.keyboard.press('Enter')
    print(pg.wait_for_selector('.ask-lineage').inner_text())
    pg.focus('.ask-lineage-close'); pg.keyboard.press('Escape')
    print('panel open:', pg.is_visible('.ask-lineage'),
          '| focus back on:', pg.evaluate('document.activeElement.textContent'))
    browser.close()
```

```text
figure: 8.44717712 percent | 8.44717712 percent: show how it was computed
How 8.44717712 percent was computed
Close
growth = 8.447177 percent · cagr {"years":5}
start = 120
A constant: stated in the question
end = 180
A constant: stated in the question
years = 5 years
A constant: stated in the question
panel open: False | focus back on: 8.44717712 percent
```

## Summary

- A quantitative planner's answer marks the figures that match workspace quantities; the stream's
  `workspace` event (and the result's `figures`) carry them and their lineage
- A lineage runs from the figure through operations to constants and tool calls, with call ids,
  arguments, paths, as-of dates and units
- `x-sajha-unit` on an `outputSchema` property declares a field's unit; a planner reading it records
  `unit_from: schema`, otherwise `declared`
- Lint's `unit` rule rejects a unit outside SAJHA's grammar

## Next

- Quantities, units and lineage: [Quantitative Planners](../architecture/Quantitative%20Planners.md) §2
- This is the last tutorial; the [documentation index](../README.md) lists every guide

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
