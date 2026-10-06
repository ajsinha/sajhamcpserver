# MCP Studio User Guide

MCP Studio is SAJHA's visual tool designer. Each creator turns a source you already have (a Python function, a REST endpoint, a SQL query, a script, a PowerBI report or dataset, an IBM LiveLink or SharePoint repository, an OLAP dataset) into an MCP tool: a JSON tool config plus, for most creators, a generated Python implementation that the tools registry loads like any built-in tool.

This guide covers what every creator has in common. The per-creator guides listed in [Creator guides](#creator-guides) cover only their own forms and options.

---

## Where Studio lives

All Studio pages are server-rendered under `/studio` (see `sajha/routes/studio_routes.py`).

| Page | Path | What it is |
|------|------|------------|
| Studio home | `/studio` | Cards for every creator, plus the Python Code Tool Creator itself (lower on the same page) |
| REST service tool | `/studio/rest` | REST Tool Creator |
| DB query tool | `/studio/dbquery` | Database Query Tool Creator |
| Script tool | `/studio/script` | Script Tool Creator |
| PowerBI report | `/studio/powerbi` | PowerBI Report Tool Creator |
| PowerBI DAX query | `/studio/powerbidax` | PowerBI DAX Query Tool Creator |
| IBM LiveLink | `/studio/livelink` | LiveLink Document Tool Creator |
| SharePoint | `/studio/sharepoint` | SharePoint Tool Creator |
| OLAP dataset | `/studio/olap` | OLAP Dataset Creator |
| Examples | `/studio/examples` | `@sajhamcptool` decorator reference and starter code for the Python creator |

How to get there in the UI:

- **Top navigation → MCP Studio** (shown to administrators). It lists Studio home, the Python, REST, DB query and script creators, the PowerBI, PowerBI DAX, LiveLink and OLAP creators, and the Composite builder.
- **Studio sub-navigation**: a row of chips at the top of each Studio page (Home, Python, REST, DB Query, Script, PowerBI, DAX, LiveLink, OLAP, Composite).
- **Studio home cards**: one card per creator. The SharePoint creator is reached from its card on Studio home; it is not in the top navigation or the sub-navigation.
- The **Dashboard** quick actions also link to `/studio`.

The Composite builder (`/composite/builder`) appears in the Studio menus but is a separate feature; see [Composition Framework](../architecture/Composition%20Framework.md).

---

## Common workflow

Every creator follows the same shape:

1. **Name the tool.** Tool names are lowercase letters, digits and underscores. The name becomes the tool's MCP name and the base of every generated file name, so it must not clash with an existing tool.
2. **Describe it.** Fill in the creator's form (or, for Python, write a decorated function). The description is what AI clients see when they list tools, so make it specific.
3. **Preview.** Most creators have a Preview (Python: **Analyze Code**) step that shows the generated JSON config and, where there is one, the generated Python before anything is written.
4. **Deploy.** Deploy writes the files listed in [Where generated tools are stored](#where-generated-tools-are-stored).
5. **Registration.** The tools registry picks the new config up without a restart (see [Hot reload and registration](#hot-reload-and-registration)). The tool then appears under **Tools** and in MCP `tools/list`.
6. **Test.** Run the tool from its page under **Tools** (`/tools/<tool_name>/execute`) before pointing an AI client at it.

To change a deployed tool, edit and deploy again under the same name (the Python creator has **Delete if Exists** for this), or edit the generated files directly.

### Known limitation: Studio action endpoints

The Studio pages render in this release, but their action buttons (Analyze, Preview, Deploy, Delete if Exists) post to `/admin/studio/...` endpoints, and the server does not register those endpoints. The buttons therefore fail. The SharePoint page posts to `/studio.deploy_sharepoint_tool`, which no route handles either. Until the endpoints return, you have two options:

- **Call the generators directly from Python.** The generator classes in `sajha.studio` (`ToolCodeGenerator`, `RESTToolGenerator`, `DBQueryToolGenerator`, `ScriptToolGenerator`, `PowerBIToolGenerator`, `PowerBIDAXToolGenerator`, `LiveLinkToolGenerator`, and `SharePointToolGenerator` in `sajha.studio.sharepoint_tool_generator`) write the same files that Deploy would. The module docstring in `sajha/studio/__init__.py` has a usage example for each one.
- **Write the files by hand.** Use the layout in the next section.

The OLAP creator has no generator class. For OLAP datasets, edit `config/olap/` directly (see the [OLAP creator guide](MCP%20Studio%20OLAP%20Tool%20Creator%20Guide.md)).

There is also a known issue with generated script tools: the config sets `implementation` to an object, but the registry expects a dotted class path, so the tool does not load. The [Script creator guide](MCP%20Studio%20Script%20Tool%20Creator%20Guide.md) gives a manual workaround.

---

## Where generated tools are stored

| Creator | Tool config | Generated implementation | Other files |
|---------|-------------|--------------------------|-------------|
| Python code | `config/tools/<name>.json` | `sajha/tools/impl/studio_<name>.py` | none |
| REST service | `config/tools/<name>.json` | `sajha/tools/impl/rest_<name>.py` | none |
| DB query | `config/tools/<name>.json` | `sajha/tools/impl/dbquery_<name>.py` | none |
| Script | `config/tools/<name>.json` | `sajha/tools/impl/<name>_script_tool.py` | the script itself, `config/scripts/<name>.<ext>` |
| PowerBI report | `config/tools/<name>.json` | `sajha/tools/impl/powerbi_<name>.py` | none |
| PowerBI DAX | `config/tools/<name>.json` | `sajha/tools/impl/powerbidax_<name>.py` | none |
| IBM LiveLink | `config/tools/<name>.json` | `sajha/tools/impl/livelink_<name>.py` | none |
| SharePoint | `config/tools/<name>.json` | none (points at the built-in `sajha.tools.impl.sharepoint_tool` classes) | none |
| OLAP dataset | none | none | dataset definitions under `config/olap/` |

Tool configs are written through the storage layer (`write_tool_config` in `sajha/core/storage`). They land at the storage key `config/tools/<name>.json` in whichever backend is configured: local disk, S3, Azure Blob or GCS. Generated `.py` files, and script files, are always written to the local filesystem of the instance that ran the generator, because Python has to import them from the package. In a multi-instance or cloud-storage deployment, every instance therefore needs those generated modules. See the [Storage Guide](../getting-started/Storage%20Guide.md).

---

## Hot reload and registration

- With the local storage backend, the tools registry (`sajha/tools/tools_registry.py`) polls `config/tools/*.json` every few seconds. It loads new configs, reloads changed ones and unregisters deleted ones. It also tracks changes to the modules in `sajha/tools/impl/`.
- With a cloud storage backend the local poller is disabled. Reloads come from the object-store sync manager instead (the backend's `sync_interval` under `storage` in `config/application.yml`).
- The separate hot-reload manager (`hot_reload` in `config/application.yml`) also watches tool configs and implementation modules.
- OLAP dataset definitions in `config/olap/` are not hot-reloaded. Use **Reload All** on the Tools admin page, or restart the server.
- When the registry changes, connected MCP clients that support it get a `tools/list_changed` notification.

---

## Permissions

- Every `/studio` page requires a signed-in user (`require_auth`).
- The **MCP Studio** menu in the top navigation is shown only to administrators. In practice, Studio is an administrator feature.
- The permission model (`sajha/db/models`) uses a `studio` resource type, for example a `studio_dev` role, only as an illustration. The Studio routes do not check it.
- Deploying writes to `config/tools/`, `sajha/tools/impl/` and, for scripts, `config/scripts/`. The server process needs write access to those paths, and to the configured storage backend.

Generated tools are ordinary tools once registered. Who can see and run them is governed by the normal tool permissions and API-key scopes.

---

## Creator guides

| Creator | Page | Guide |
|---------|------|-------|
| Python code (`@sajhamcptool`) | `/studio` | [Python Code Tool Creator Guide](MCP%20Studio%20Python%20Code%20Tool%20Creator%20Guide.md) |
| REST service | `/studio/rest` | [REST Tool Creator Guide](MCP%20Studio%20REST%20Tool%20Creator%20Guide.md) |
| Database query | `/studio/dbquery` | [DBQuery Tool Creator Guide](MCP%20Studio%20DBQuery%20Tool%20Creator%20Guide.md) |
| Script | `/studio/script` | [Script Tool Creator Guide](MCP%20Studio%20Script%20Tool%20Creator%20Guide.md) |
| PowerBI report | `/studio/powerbi` | [PowerBI Tool Creator Guide](MCP%20Studio%20PowerBI%20Tool%20Creator%20Guide.md) |
| PowerBI DAX query | `/studio/powerbidax` | [PowerBI DAX Tool Creator Guide](MCP%20Studio%20PowerBI%20DAX%20Tool%20Creator%20Guide.md) |
| IBM LiveLink | `/studio/livelink` | [LiveLink Tool Creator Guide](MCP%20Studio%20LiveLink%20Tool%20Creator%20Guide.md) |
| SharePoint | `/studio/sharepoint` | [SharePoint Tool Creator Guide](MCP%20Studio%20SharePoint%20Tool%20Creator%20Guide.md) |
| OLAP dataset | `/studio/olap` | [OLAP Tool Creator Guide](MCP%20Studio%20OLAP%20Tool%20Creator%20Guide.md) |

---

## Related documentation

- [Architecture](../architecture/Architecture.md): tools registry, storage and hot reload in context
- [Composition Framework](../architecture/Composition%20Framework.md): composite tools built with the Composite builder
- [Storage Guide](../getting-started/Storage%20Guide.md): where configs live for each storage backend
- [API Reference](../protocol/API%20Reference.md)
- [Glossary](../../GLOSSARY.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
