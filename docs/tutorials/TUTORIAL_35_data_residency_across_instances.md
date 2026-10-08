# Tutorial 35: Data Residency Across Instances

Some data may only go to some places: EU customer data stays in the EU, a desk's margins are not shown
to another entity. SAJHA Net enforces this with **data classes** (labels on a tool's input and output
fields) and **residency rules** (policy rules that match classes, a direction and a destination). The
home checks a call's arguments before they leave; the host checks its result before it goes back, and
may refuse or redact. This tutorial does both on the [local test lab](TUTORIAL_29_local_test_lab.md):
`risk-eu` keeps EU customer data away from `cust-na` (region `na`), and `treasury-eu` masks a figure in
results going outside the EU. The design is [SAJHA Net](../architecture/SAJHA%20Net.md) section 12; the
rule language is [Policy and Audit](../architecture/Policy%20and%20Audit.md) section 3.5.

## What you'll learn

- The three places data classes come from, and how to classify a tool without editing it
- How a residency rule on arguments makes a home refuse a host, and how a call by plain name then finds
  a host the data may go to
- How a host redacts classified fields in a result for one destination and not another
- Where the decisions show: refusals, `_meta`, the audit chain and the Net overview

## Prerequisites

- The local test lab running ([Tutorial 29](TUTORIAL_29_local_test_lab.md)), freshly reset. Its
  regions: `risk-eu` and `treasury-eu` are `eu`, `cust-na` is `na`

## Steps

### 1. Where data classes come from

A tool's fields get classes from, merged:

- `x-sajha-data-class` marks on properties of its `inputSchema` and `outputSchema` (nested objects and
  array items too); the marks are part of the contract hash;
- the tool's own `data_classes: {arguments: [...], results: [...]}`, for the whole tool;
- `sajhanet.data_classes.tools` in configuration: `{<tool or glob>: {arguments: {<field path>: <class>},
  results: {<field path>: <class>}}}` (`*` for the whole value), which classifies a tool without editing
  it. A home's configuration applies to the remote tools it calls, a host's to the tools it offers.

An exported tool carries a summary of its classes in its net metadata, so a home knows them too.

### 2. Arguments: EU customer data stays in the EU

On `risk-eu`, classify the `principal` of `calc_loan_amortization` and refuse to send that class outside
the EU. Create `run/risk-eu/local.yml`:

```yaml
sajhanet:
  data_classes:
    tools:
      calc_loan_amortization: {arguments: {principal: eu-customer}}
```

and `run/risk-eu/config/policies/50-lab-residency.yaml`:

```yaml
name: lab-residency
description: EU customer data stays in the EU
enabled: true
rules:
  - id: eu-customer-stays-in-eu
    match: {data_classes: [eu-customer], flow: arguments, destination: {region: {ne: eu}}}
    effect: deny
    reason: EU customer data stays in the EU
```

A rule is a residency rule because its match names `data_classes`, `flow` or `destination`. The
destination facts are the other instance's `net`, `instance`, `region` and `labels.<key>` from its member
record, plus `here` and `differs_from_here`. Restart `risk-eu` (`lab.sh stop risk-eu`, then
`lab.sh start risk-eu`), then call both ways:

```bash
K='X-API-Key: sja_test_admin_dev_key_0001'
for t in calc_loan_amortization lab-net__cust-na__calc_loan_amortization; do
  curl -s -X POST http://127.0.0.1:3002/api/tools/execute -H "$K" -H 'Content-Type: application/json' \
    -d "{\"tool\": \"$t\", \"arguments\": {\"principal\": 1000, \"annual_rate\": 5, \"months\": 3}}" \
    | python3 -c "import json,sys; r=json.load(sys.stdin)['result']; print(r['_meta']['io.sajha/net'])"
done
```

```text
{'instance': 'treasury-eu', 'net': 'lab-net', 'qualified_name': 'lab-net__treasury-eu__calc_loan_amortization', ...}
{'refusal': {'reason': 'residency_arguments', 'side': 'home', 'instance': 'risk-eu', 'executed': False, ...}}
```

The plain name went to `treasury-eu`, the only host the class may go to. The qualified name names
`cust-na`, so the call is refused before it leaves (`-32012 residency_arguments`, `executed: false`),
with words that tell a planner to use a tool where the data may go. Because `principal` is required,
every call sends the class, so the plain name resolves only to `treasury-eu`; the qualified name stays in
the catalog and is refused when called. Allowed decisions on classified data are `net.residency` audit records and are
counted on the Net overview under Residency decisions.

Undo: delete both files and restart `risk-eu`.

### 3. Results: margins masked outside the EU

Now the host side. On `treasury-eu`, classify the `total_interest` in the result of
`calc_loan_amortization` and redact it for destinations outside the EU.
`run/treasury-eu/local.yml`:

```yaml
sajhanet:
  data_classes:
    tools:
      calc_loan_amortization: {results: {total_interest: treasury-margin}}
```

`run/treasury-eu/config/policies/50-lab-residency.yaml`:

```yaml
name: lab-residency
description: Treasury margins are masked outside the EU
enabled: true
rules:
  - id: margins-masked-outside-eu
    match: {data_classes: [treasury-margin], flow: results, destination: {region: {ne: eu}}}
    redact: {data_classes: [treasury-margin]}
    reason: Treasury margins are not shown outside the EU
```

Restart `treasury-eu`, wait a few seconds for the others to see it again, and call its tool from
`cust-na` (`na`) and from `risk-eu` (`eu`):

```bash
K='X-API-Key: sja_test_admin_dev_key_0001'
for h in 127.0.0.2:3003 127.0.0.1:3002; do
  curl -s -X POST http://$h/api/tools/execute -H "$K" -H 'Content-Type: application/json' \
    -d '{"tool": "lab-net__treasury-eu__calc_loan_amortization", "arguments": {"principal": 300000, "annual_rate": 5, "months": 12}}' \
    | python3 -c "import json,sys; r=json.load(sys.stdin)['result']; print(r['structuredContent']['total_interest'], r['_meta']['io.sajha/net'].get('redacted'), r['_meta']['io.sajha/net'].get('data_classes'))"
done
```

```text
[REDACTED:treasury-margin] ['total_interest'] {'results': ['treasury-margin']}
8186.93 None {'results': ['treasury-margin']}
```

To `cust-na` the field arrives as `[REDACTED:treasury-margin]` and `_meta["io.sajha/net"].redacted` lists
it; to `risk-eu` it arrives intact, and both answers say which classes they hold. A `deny` instead of
`redact` refuses the result (`-32012 residency_result`, `executed: true`: the tool did run). Redaction
also rewrites JSON text blocks and quoted values in text; in the run behind this tutorial it also
replaced the digits of the removed value where they appeared inside other numbers of the text block
(`structuredContent` was exact).

Undo: delete both files and restart `treasury-eu`.

### 4. The stricter default

`sajhanet.residency.default_effect: deny` makes every classified field need an `allow` rule to cross;
unclassified data is unaffected. A home also applies its own rules to results as they arrive
(`flow: results, destination: {here: true}`), and conversation memory keeps answers that used remote
results with their figures removed, or not at all, by class (`sajhanet.memory.remote_results`,
`sajhanet.memory.by_class`). The [Configuration Reference](../getting-started/Configuration%20Reference.md#sajha-net)
lists the keys.

## What you learned

- Data classes come from schema marks, a tool's own declaration or configuration, and travel with the
  tool's net metadata
- A residency rule on `flow: arguments` makes a home refuse a host before the call leaves, and a plain
  name resolves only to hosts the data may go to
- A rule on `flow: results` lets a host refuse or redact for one destination and not another
- Every decision on classified data is audited, without values

## Next

- [Tutorial 36: Planners and LLM Tools Across the Net](TUTORIAL_36_planners_and_llm_tools_across_the_net.md)
- Policies in general: [Tutorial 20](TUTORIAL_20_policies_approvals_and_audit.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
