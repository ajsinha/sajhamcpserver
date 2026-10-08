# SAJHA Documentation

> New here? Read **[How SAJHA Fits Together](getting-started/How%20SAJHA%20Fits%20Together.md)**
> first: it is the map, and it names the one document that owns each topic. Then the
> [Quick Start](getting-started/Quick%20Start.md), the tutorials in order, and the guide
> for whatever you are building.

Every guide's file name is unique across `docs/`, so a guide can be found by name
alone. Definitions live in the root [GLOSSARY](../GLOSSARY.md); release history in the
[CHANGELOG](../CHANGELOG.md); the conventions for writing docs in [CLAUDE.md](../CLAUDE.md).

## Reading order

1. [How SAJHA Fits Together](getting-started/How%20SAJHA%20Fits%20Together.md)
2. [Quick Start](getting-started/Quick%20Start.md)
3. The [tutorials](#tutorials)
4. [MCP Protocol Guide](protocol/MCP%20Protocol%20Guide.md)
5. Before you deploy: [Configuration Reference](getting-started/Configuration%20Reference.md),
   [Database Setup](getting-started/Database%20Setup.md),
   [Security Model](security/Security%20Model.md) and
   [Policy and Audit](architecture/Policy%20and%20Audit.md)
6. The [architecture](#architecture) guide for each subsystem you use

## How this folder is organised

| Folder | What is in it |
|---|---|
| `getting-started/` | The map, quick start, configuration reference, database setup, storage, Kubernetes |
| `protocol/` | MCP protocol guide, the two compliance reports, API reference, OAuth, MCP Apps and headers |
| `architecture/` | How the server is built, and one design guide per subsystem: composition, the intelligence layer, federation, connected accounts, API import, tool generation, data connectors, policy and audit, sandbox, scaling, observability, workflows, tool quality; the roadmap |
| `studio/` | MCP Studio and its creators |
| `tools/` | One reference guide per tool provider, by category; prompts |
| `tutorials/` | Step-by-step walkthroughs, numbered |
| `clients/` | The Python client SDK; the `sajha` command line and desktop (stdio) clients |
| `security/` | The security model |
| `archive/` | Point-in-time reports, not maintained |
| `requirements/` | The original requirements document |

## Getting started

- [How SAJHA Fits Together](getting-started/How%20SAJHA%20Fits%20Together.md)
- [Quick Start](getting-started/Quick%20Start.md)
- [Configuration Reference](getting-started/Configuration%20Reference.md)
- [Database Setup](getting-started/Database%20Setup.md): SQLite for development; PostgreSQL from one schema file an operator runs; upgrades
- [Storage Guide](getting-started/Storage%20Guide.md)
- [Python Playground](getting-started/Python%20Playground.md)
- [Kubernetes Deployment](getting-started/Kubernetes%20Deployment.md): the image, the Helm chart, Kustomize manifests, several replicas

## Protocol

- [MCP Protocol Guide](protocol/MCP%20Protocol%20Guide.md): the two eras, transports, streaming, MRTR, tasks
- [MCP 2026-07-28 Compliance](protocol/MCP%202026-07-28%20Compliance.md)
- [MCP 2025-11-25 Compliance](protocol/MCP%202025-11-25%20Compliance.md)
- [OAuth Guide](protocol/OAuth%20Guide.md)
- [MCP Apps and Headers Guide](protocol/MCP%20Apps%20and%20Headers%20Guide.md)
- [API Reference](protocol/API%20Reference.md)
- [SAJHA Net Protocol](protocol/SAJHA%20Net%20Protocol.md): specification (not built) of the `io.sajha/net` extension that SAJHA Net participants speak: endpoints, signed requests, gossip, key directory, call forwarding, errors, conformance tests

## Architecture

- [Architecture](architecture/Architecture.md)
- [Composition Framework](architecture/Composition%20Framework.md)
- [Intelligence Layer](architecture/Intelligence%20Layer.md)
- [Extending the Intelligence Layer](architecture/Extending%20the%20Intelligence%20Layer.md): writing a provider, a model and a planner
- [Federation](architecture/Federation.md): other MCP servers' tools behind SAJHA's governance
- [API Import](architecture/API%20Import.md): an OpenAPI, Swagger or GraphQL description to a reviewed set of tools
- [Data Connectors](architecture/Data%20Connectors.md): databases, warehouses, vector stores and search clusters as governed, read-only tools: the statement guard, limits, masking, curated views, per-user credentials
- [Tool Generation](architecture/Tool%20Generation.md): Describe a tool, from a sentence to a checked, tested tool an administrator approves
- [Connected Accounts](architecture/Connected%20Accounts.md): users link GitHub, Slack, Google, Microsoft 365 and other accounts once; tools and federated servers act as them
- [Sandbox](architecture/Sandbox.md): where user code (Studio Python and script tools, the shell) runs, and what each backend guarantees
- [Scaling and State](architecture/Scaling%20and%20State.md): several workers or hosts; the state store (memory, Redis, database), durable tasks, and what stays per process
- [Observability](architecture/Observability.md): Prometheus `/metrics`, OpenTelemetry traces over OTLP, the usage and cost dashboard, alert rules
- [Workflows](architecture/Workflows.md): DAGs of tools, composites and Ask SAJHA steps; cron, webhook, file and event triggers; durable runs that resume after a crash; re-run from a step; publish as a tool
- [Tool Quality](architecture/Tool%20Quality.md): test cases with recorded HTTP cassettes and JUnit output, the schema linter, health probes, evals for Ask SAJHA, tool versions with canary routing, rollback and sunset dates
- [Policy and Audit](architecture/Policy%20and%20Audit.md): declarative rules on every tool call (deny, approval, argument constraints, rate limits, quotas, redaction, injection screening); the hash-chained, signed audit and SIEM export
- [LLM Tools](architecture/LLM%20Tools.md): tools whose work is done by a model, configured like any tool and governed the same way (modes, memory, resource safety, sampling, the OpenAI-compatible endpoint and configurable planners built)
- [Planner Reference](architecture/Planner%20Reference.md): the reference for planner files (`config/planners`): keys, the stage library, transitions and bounded loops, the `when` expression language, verify checks, validation messages, a JSON Schema and every shipped strategy in full
- [SAJHA Net](architecture/SAJHA%20Net.md): design (not built) for several SAJHA servers sharing tools while each keeps its own data, policy, AI and memory
- [System Notices](architecture/System%20Notices.md): what needs attention, from every subsystem: the console banner, the dashboard System status panel, the navbar badge, acknowledgement and the admin API
- [Implementation Plan](architecture/Implementation%20Plan.md): the build order for LLM tools, SAJHA Net and open roadmap items, in five waves
- [Roadmap](architecture/Roadmap.md): what is not built yet and what should come next, by horizon (now, next, later), each item linked to the guide that records the gap

## MCP Studio

- [MCP Studio User Guide](studio/MCP%20Studio%20User%20Guide.md), which links each creator guide:
  [Python code](studio/MCP%20Studio%20Python%20Code%20Tool%20Creator%20Guide.md) ·
  [REST](studio/MCP%20Studio%20REST%20Tool%20Creator%20Guide.md) ·
  [DB query](studio/MCP%20Studio%20DBQuery%20Tool%20Creator%20Guide.md) ·
  [Script](studio/MCP%20Studio%20Script%20Tool%20Creator%20Guide.md) ·
  [Power BI](studio/MCP%20Studio%20PowerBI%20Tool%20Creator%20Guide.md) ·
  [Power BI DAX](studio/MCP%20Studio%20PowerBI%20DAX%20Tool%20Creator%20Guide.md) ·
  [LiveLink](studio/MCP%20Studio%20LiveLink%20Tool%20Creator%20Guide.md) ·
  [SharePoint](studio/MCP%20Studio%20SharePoint%20Tool%20Creator%20Guide.md) ·
  [OLAP](studio/MCP%20Studio%20OLAP%20Tool%20Creator%20Guide.md) ·
  [LLM tool](studio/MCP%20Studio%20LLM%20Tool%20Creator%20Guide.md);
  Import an API is [API Import](architecture/API%20Import.md) and Describe a tool is
  [Tool Generation](architecture/Tool%20Generation.md)

## Tools

The live catalog is whatever the server has loaded (`tools/list`, or the Tools page).
These guides document each provider's tools, parameters and API keys.

- **Market data:** [Alpha Vantage](tools/market-data/Alpha%20Vantage%20Tool%20Reference%20Guide.md) ·
  [CoinGecko](tools/market-data/CoinGecko%20Tool%20Reference%20Guide.md) ·
  [FMP](tools/market-data/FMP%20Tool%20Reference%20Guide.md) ·
  [FRED](tools/market-data/FRED%20Tool%20Reference%20Guide.md) ·
  [OpenBB](tools/market-data/OpenBB%20Tool%20Reference%20Guide.md) ·
  [Yahoo Finance](tools/market-data/Yahoo%20Finance%20Tool%20Reference%20Guide.md)
- **Central banks:** [Bank of Canada](tools/central-banks/Bank%20of%20Canada%20Tool%20Reference%20Guide.md) ·
  [Bank of Japan](tools/central-banks/Bank%20of%20Japan%20Tool%20Reference%20Guide.md) ·
  [Banque de France](tools/central-banks/Banque%20de%20France%20Tool%20Reference%20Guide.md) ·
  [European Central Bank](tools/central-banks/European%20Central%20Bank%20Tool%20Reference%20Guide.md) ·
  [Federal Reserve](tools/central-banks/Federal%20Reserve%20Tool%20Reference%20Guide.md) ·
  [People's Bank of China](tools/central-banks/Peoples%20Bank%20of%20China%20Tool%20Reference%20Guide.md) ·
  [Reserve Bank of India](tools/central-banks/Reserve%20Bank%20of%20India%20Tool%20Reference%20Guide.md)
- **Public data:** [FBI](tools/public-data/FBI%20Tool%20Reference%20Guide.md) ·
  [IMF](tools/public-data/IMF%20Tool%20Reference%20Guide.md) ·
  [United Nations](tools/public-data/United%20Nations%20Tool%20Reference%20Guide.md) ·
  [World Bank](tools/public-data/World%20Bank%20Tool%20Reference%20Guide.md)
- **Filings:** [SEC EDGAR](tools/filings/SEC%20EDGAR%20Tool%20Reference%20Guide.md) ·
  [Investor Relations](tools/filings/Investor%20Relations%20Tool%20Reference%20Guide.md)
- **Search:** [Google Search](tools/search/Google%20Search%20Tool%20Reference%20Guide.md) ·
  [MSDOC Search](tools/search/MSDOC%20Search%20Tool%20Reference%20Guide.md) ·
  [Tavily Search](tools/search/Tavily%20Search%20Tool%20Reference%20Guide.md) ·
  [Web Crawler](tools/search/Web%20Crawler%20Tool%20Reference%20Guide.md) ·
  [Wikipedia Search](tools/search/Wikipedia%20Search%20Tool%20Reference%20Guide.md)
- **Analytics:** [DuckDB](tools/analytics/DuckDB%20Tool%20Reference%20Guide.md) ·
  [Financial Calculators](tools/analytics/Financial%20Calculators%20Tool%20Reference%20Guide.md) ·
  [OLAP Analytics](tools/analytics/OLAP%20Analytics%20Tool%20Reference%20Guide.md) ·
  [SQL Select](tools/analytics/SQL%20Select%20Tool%20Reference%20Guide.md)
- **Enterprise:** [SharePoint](tools/enterprise/SharePoint%20Tool%20Reference%20Guide.md), [Connected account tools](tools/enterprise/Connected%20Account%20Tools%20Reference%20Guide.md) (GitHub, Slack, Google Drive, Outlook, as the user), [Data connectors](tools/enterprise/Data%20Connectors%20Reference%20Guide.md) (setup per database, warehouse and vector store)
- **Prompts:** [Prompts Management Guide](tools/prompts/Prompts%20Management%20Guide.md)

## Tutorials

1. [Tutorial 1: Getting Started — Browse, Execute and Connect](tutorials/TUTORIAL_01_getting_started.md)
2. [Tutorial 2: Create a Custom Tool](tutorials/TUTORIAL_02_create_a_custom_tool.md)
3. [Tutorial 3: Build a Composite Tool](tutorials/TUTORIAL_03_build_a_composite_tool.md)
4. [Tutorial 4: Create a Plugin](tutorials/TUTORIAL_04_create_a_plugin.md)
5. [Tutorial 5: Connect the Python SDK](tutorials/TUTORIAL_05_connect_the_python_sdk.md)
6. [Tutorial 6: Configure Tool Caching](tutorials/TUTORIAL_06_configure_tool_caching.md)
7. [Tutorial 7: Submit Async Tool Execution](tutorials/TUTORIAL_07_submit_async_tool_execution.md)
8. [Tutorial 8: Custom Configuration](tutorials/TUTORIAL_08_custom_configuration.md)
9. [Tutorial 9: Call SAJHA from the Standard MCP Client](tutorials/TUTORIAL_09_call_sajha_from_the_standard_mcp_client.md)
10. [Tutorial 10: Ask SAJHA](tutorials/TUTORIAL_10_ask_sajha.md)
11. [Tutorial 11: Federate an MCP Server](tutorials/TUTORIAL_11_federate_an_mcp_server.md)
12. [Tutorial 12: Analyse a Tool's Result in the Python Playground](tutorials/TUTORIAL_12_python_playground.md)
13. [Tutorial 13: Run SAJHA on Several Workers](tutorials/TUTORIAL_13_run_sajha_on_several_workers.md)
14. [Tutorial 14: Sandboxed Studio Tools](tutorials/TUTORIAL_14_sandboxed_studio_tools.md)
15. [Tutorial 15: The sajha CLI and Claude Desktop](tutorials/TUTORIAL_15_sajha_cli_and_claude_desktop.md)
16. [Tutorial 16: Metrics, Costs and Alerts](tutorials/TUTORIAL_16_metrics_costs_and_alerts.md)
17. [Tutorial 17: Deploy SAJHA on Kubernetes](tutorials/TUTORIAL_17_deploy_sajha_on_kubernetes.md)
18. [Tutorial 18: Connect Your Accounts](tutorials/TUTORIAL_18_connect_your_accounts.md)
19. [Tutorial 19: Import an OpenAPI Spec](tutorials/TUTORIAL_19_import_an_openapi_spec.md)
20. [Tutorial 20: Policies, Approvals and a Tamper-Evident Audit](tutorials/TUTORIAL_20_policies_approvals_and_audit.md)
21. [Tutorial 21: Planners, Conversation Memory and Document Search](tutorials/TUTORIAL_21_planners_memory_and_rag.md)
22. [Tutorial 22: Schedule a Workflow](tutorials/TUTORIAL_22_schedule_a_workflow.md)
23. [Tutorial 23: Test and Canary Your Tools](tutorials/TUTORIAL_23_test_and_canary_your_tools.md)
24. [Tutorial 24: Describe a Tool](tutorials/TUTORIAL_24_describe_a_tool.md)
25. [Tutorial 25: Connect a Database](tutorials/TUTORIAL_25_connect_a_database.md)
26. [Tutorial 26: Build an LLM Tool](tutorials/TUTORIAL_26_build_an_llm_tool.md)
27. [Tutorial 27: Write a Planner](tutorials/TUTORIAL_27_write_a_planner.md)
28. [Tutorial 28: Build a SAJHA Net](tutorials/TUTORIAL_28_build_a_sajha_net.md)

## Clients and security

- [Client SDK Guide](clients/Client%20SDK%20Guide.md)
- [Command Line](clients/Command%20Line.md): the `sajha` CLI, and SAJHA over stdio for desktop clients
- [SAJHA Net Agent](clients/SAJHA%20Net%20Agent.md): any MCP server as a SAJHA Net participant, the reference library and the conformance suite
- [Security Model](security/Security%20Model.md)

## Elsewhere in the repository

- [Deployment recipes](../deployment/README.md): AWS CDK, Hetzner, bare metal, Kubernetes
- [Archive](archive/README.md): old audits and notes, not maintained
- How SAJHA compares with other MCP products: the server's `/comparison` page (data in `sajha/web/competitive.py`)
- [The deck](../tools/deck/GUIDE.md): `docs/publications/SAJHA-MCP-Server.pptx`, rebuilt from source with every number derived at build time
