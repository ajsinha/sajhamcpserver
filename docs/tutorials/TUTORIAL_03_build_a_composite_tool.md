# Tutorial 3: Build a Composite Tool

Combine several existing tools into one composite tool with the Composite Builder.

## What you'll learn

- How the two arrangements, **Sibling** and **Parent → Child**, run their steps
- How step parameter mappings work
- How to save a composite and preview its generated schemas

## Prerequisites

- A running server, signed in as an administrator. Saving, updating and deleting composites requires the admin role.
- The calculator tools `calc_percentage_change` and `calc_future_value`. They need no external API keys.

> Saving a composite registers it as a tool straight away: it appears in MCP `tools/list` and can be called with `tools/call`. Deleting it unregisters it.

## How a composite runs

Every composite has a **master tool**. The master runs first, with the composite's own arguments, and its result is stored under the **master output key**. Then the steps run:

| Arrangement | What the steps receive | Output shape |
|-------------|------------------------|--------------|
| **Sibling (parallel)** | The composite's input arguments, merged with each step's mapped and static parameters. Steps run in parallel after the master. | `{<master key>: …, <step output key>: …, …}` |
| **Parent → Child (fan-out)** | One call per record of the array found at **Record path** in the master's output. Parameters come from each record. | `{<master key>: …, children: [{_record, <step output key>: …}, …]}` |

Parameter mapping is a JSON object of the form `{"<step param>": "<source>"}`:

- `"$input.<field>"` or `"$.input.<field>"` takes a field from the composite's input. Both work in both arrangements.
- `"$.<field>"` takes a field from the master's output: in Parent → Child, from the current record; in Sibling, from the master tool's whole result. A dotted path (`"$.quote.price"`) reads a nested field. A missing field resolves to an empty string.
- Any other value is passed through as a literal.

**Static params** are fixed values merged into every call of the step.

The result also carries a `_composition` block: per-step trace, duration, confidence and entropy guard.

## Steps

### 1. Open the builder

Go to **MCP Studio → Composite builder** (`/composite/builder`).

### 2. Name the composite and choose the arrangement

Enter a name, for example `growth_snapshot`, and a description. Set **Arrangement** to **Sibling (parallel)**. Choosing **Parent → Child (fan-out)** shows the extra **Record path** field: a dot path such as `rows` or `result.data` to the array in the master output.

### 3. Set the master tool

Set **Master tool** to `calc_percentage_change` and **Master output key** to `change`. The default key is `master`.

### 4. Add a step

Click **Add Step** and fill in the row:

| Field | Value |
|-------|-------|
| Tool | `calc_future_value` |
| Output key | `projection` |
| Mode | Parallel |
| Param mapping | `{"present_value": "$.input.new_value"}` |
| Static params | `{"rate": 5, "years": 10}` |

The **Flow Diagram** redraws as you change the master, the arrangement or the steps. You can drag step rows to reorder them, and remove a step with its **×** button.

### 5. Save and preview the schemas

Click **Save**. The builder posts the definition to `POST /api/composite-tools`, or to `PUT /api/composite-tools/<name>` when you are editing an existing one. It then shows the generated schemas. You can also click **Preview Schema**, which calls `GET /api/composite-tools/<name>/preview-schema`. The composite must be saved first.

- **Input schema:** the master tool's input schema. Here that is `old_value` and `new_value`.
- **Output schema:** `change` (the master's output schema) and `projection` (the step's output schema).

When the composite runs with `{"old_value": 100, "new_value": 125}`, its result is:

```json
{
  "change":     {"old_value": 100, "new_value": 125, "percentage_change": 25.0},
  "projection": {"present_value": 125, "rate": 5, "years": 10, "future_value": 203.61},
  "_composition": {"steps_executed": 2, "guard_passed": true, "...": "..."}
}
```

Call it like any other tool: MCP `tools/call` with `{"name": "<composite name>", "arguments": {"old_value": 100, "new_value": 125}}`.

### 6. Manage composites over the API

| Method and path | Purpose |
|-----------------|---------|
| `GET /api/composite-tools` | List all composites |
| `GET /api/composite-tools/<name>` | One definition |
| `POST /api/composite-tools` | Create (admin) |
| `PUT /api/composite-tools/<name>` | Update (admin) |
| `DELETE /api/composite-tools/<name>` | Delete (admin) |

The saved list appears in the left-hand panel of the builder. Click an entry to load it for editing.

## What next

- [Composition Framework](../architecture/Composition%20Framework.md): the step, lens and entropy-guard model behind composites
- [MCP Studio User Guide](../studio/MCP%20Studio%20User%20Guide.md)
- Next tutorial: [Create a Plugin](TUTORIAL_04_create_a_plugin.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
