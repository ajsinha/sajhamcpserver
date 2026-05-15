# SAJHA MCP Server v5.0.0 — Exception Handling Audit

**Date:** May 12, 2026
**Auditor:** Code Quality Review
**Scope:** All Python files in sajha/ and clientsdk/
**Standard:** Every exception must be logged with full stack trace. No silent swallowing.

---

## Executive Summary

| Category | Count | Severity |
|----------|:-----:|:--------:|
| Total try/except blocks | 490 | — |
| **BARE except (no type)** | **42** | **Critical** |
| **SWALLOWED (pass/continue, no log)** | **22** | **Critical** |
| **Logged but NO stack trace** | **240** | **High** |
| Properly handled (log + traceback) | 11 | OK |
| **Total issues** | **304** | — |

Only **2.2%** of exception handlers follow best practice (log + traceback). **98%** need remediation.

---

## Issue Categories

### CRITICAL: Bare except (42 occurrences)

Catches ALL exceptions including SystemExit, KeyboardInterrupt, MemoryError. Never acceptable in production.

**Fix pattern:**
```python
# WRONG
except:
    pass

# RIGHT
except Exception as e:
    logger.error(f"Operation failed: {e}", exc_info=True)
```

**Top offenders:**
- `duckdb_olap_tools_refactored.py` — 6 bare excepts
- `yfinance_tools.py` — 6 bare excepts
- `webcrawler_tool_refactored.py` — 4 bare excepts
- `composite_routes.py` — 3 bare excepts
- `db_connection_pool.py` — 2 bare excepts

### CRITICAL: Swallowed exceptions (22 occurrences)

Exception caught, no logging, silently returns default value or continues. These hide bugs.

**Fix pattern:**
```python
# WRONG
except Exception:
    return False

# RIGHT
except Exception as e:
    logger.warning(f"Check failed: {e}", exc_info=True)
    return False
```

**Top offenders:**
- `observability/__init__.py` — 2 (metrics should never silently fail)
- `storage.py` — 2 (storage errors hidden)
- `ws_routes.py` — 1 (WebSocket errors hidden)
- `plugins.py` — 1 (plugin load failures hidden)
- `mcp_client.py` (SDK) — 4 (client errors hidden)

### HIGH: Logged without stack trace (240 occurrences)

Exception is logged via `logger.error(f"msg: {e}")` but without `exc_info=True`. This captures the error message but loses the stack trace — making debugging in production nearly impossible.

**Fix pattern:**
```python
# WRONG — message only, no stack trace
except Exception as e:
    logger.error(f"Tool execution failed: {e}")

# RIGHT — full stack trace in log file
except Exception as e:
    logger.error(f"Tool execution failed: {e}", exc_info=True)
```

**Top offenders (by file):**
- `world_bank_tool.py` — 11 occurrences
- `duckdb_olap_tools_refactored.py` — 16 occurrences
- `fbi_tool_refactored.py` — 11 occurrences
- `company_ir_scrapers.py` — 12 occurrences
- `auth_manager.py` — 7 occurrences
- `prompts_registry.py` — 6 occurrences
- `tools_registry.py` — 9 occurrences
- `app.py` — 7 occurrences

---

## Remediation Plan

### Phase 1: Critical fixes (bare + swallowed) — 64 locations

All bare excepts and swallowed exceptions must be fixed immediately. These hide production bugs.

### Phase 2: Add exc_info=True — 240 locations

Systematic pass through all `logger.error()` and `logger.warning()` calls in except blocks to add `exc_info=True`.

### Phase 3: Standardize pattern

Every except block in the codebase should follow this template:

```python
try:
    result = some_operation()
except SpecificError as e:
    logger.error(f"Descriptive message for {context}: {e}", exc_info=True)
    # appropriate fallback or re-raise
except Exception as e:
    logger.error(f"Unexpected error in {context}: {e}", exc_info=True)
    raise  # or return error dict for tool execution
```

---

*SAJHA MCP Server v5.0.0 — Exception Handling Audit*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
