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
5. [Configuration Reference](getting-started/Configuration%20Reference.md) and
   [Security Model](security/Security%20Model.md) before you deploy

## How this folder is organised

| Folder | What is in it |
|---|---|
| `getting-started/` | The map, quick start, configuration reference, storage, Kubernetes |
| `protocol/` | MCP protocol guide, the two compliance reports, API reference, OAuth, MCP Apps and headers |
| `architecture/` | How the server is built; the composition framework; the intelligence layer and how to extend it |
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

## Architecture

- [Architecture](architecture/Architecture.md)
- [Composition Framework](architecture/Composition%20Framework.md)
- [Intelligence Layer](architecture/Intelligence%20Layer.md)
- [Extending the Intelligence Layer](architecture/Extending%20the%20Intelligence%20Layer.md): writing a provider, a model and a planner
- [Federation](architecture/Federation.md): other MCP servers' tools behind SAJHA's governance
- [Sandbox](architecture/Sandbox.md): where user code (Studio Python and script tools, the shell) runs, and what each backend guarantees
- [Scaling and State](architecture/Scaling%20and%20State.md): several workers or hosts; the state store (memory, Redis, database), durable tasks, and what stays per process
- [Observability](architecture/Observability.md): Prometheus `/metrics`, OpenTelemetry traces over OTLP, the usage and cost dashboard, alert rules

## MCP Studio

- [MCP Studio User Guide](studio/MCP%20Studio%20User%20Guide.md), which links each creator guide

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

## Clients and security

- [Client SDK Guide](clients/Client%20SDK%20Guide.md)
- [Command Line](clients/Command%20Line.md): the `sajha` CLI, and SAJHA over stdio for desktop clients
- [Security Model](security/Security%20Model.md)

## Elsewhere in the repository

- [Deployment recipes](../deployment/README.md): AWS CDK, Hetzner, bare metal, Kubernetes
- [Archive](archive/README.md): old audits and notes, not maintained
