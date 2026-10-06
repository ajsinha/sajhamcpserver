# Tutorial 3: Build a Composite Tool

Combine several existing tools into one composite tool with the Composite Builder.

## What you'll learn

- How the two arrangements, **Sibling** and **Parent → Child**, run their steps
- How step parameter mappings work
- How to save a composite and preview its generated schemas

## Prerequisites

- A running server, signed in as an administrator. Saving, updating and deleting composites requires the admin role.
- The calculator tools `calc_percentage_change` and `calc_future_value`. They need no external API keys.

> **Known issue in the current build:** A saved composite is stored in the database and its schema preview works. However, it is **not registered as a callable tool**. `CompositeToolEngine.load_from_db` (`sajha/tools/composite_tool.py`) calls `ToolsRegistry.register_tool(name, tool)`, but `register_tool` takes only the tool. The call fails with a `TypeError`, which is logged as `Failed to build composite tool <name>`. Until that is fixed, `tools/call` on a composite returns "Tool not found". To chain tools today, see the client-side `ClientPipeline` in [Tutorial 5](TUTORIAL_05_connect_the_python_sdk.md).

## How a composite runs

Every composite has a **master tool**. The master runs first, with the composite's own arguments, and its result is stored under the **master output key**. Then the steps run:

| Arrangement | What the steps receive | Output shape |
|-------------|------------------------|--------------|
| **Sibling (parallel)** | The composite's input arguments, merged with each step's mapped and static parameters. Steps run in parallel after the master. | `{<master key>: …, <step output key>: …, …}` |
| **Parent → Child (fan-out)** | One call per record of the array found at **Record path** in the master's output. Parameters come from each record. | `{<master key>: …, children: [{_record, <step output key>: …}, …]}` |

Parameter mapping is a JSON object of the form `{"<step param>": "<source>"}`:

- `"$.input.<field>"` takes a field from the composite's input. It works in both arrangements.
- `"$.<field>"` takes a field from the current master-output record. It applies to Parent → Child only; in a Sibling step it resolves to an empty string.
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

(This output came from running the composite engine directly. See the known issue above about calling it through MCP.)

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
