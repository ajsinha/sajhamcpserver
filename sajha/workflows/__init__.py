"""
SAJHA MCP Server — workflows: DAGs of tool, composite and Ask SAJHA steps, with schedules,
triggers and durable run history. Design: docs/architecture/Workflows.md.

    model     the definition (JSON or YAML): steps, triggers, delivery, publish
    expr      parameter mapping ($input, $steps, $item) and conditions
    cron      timezone-aware cron schedules
    store     the workflows / workflow_runs / workflow_run_steps tables
    identity  "run as": the owner's identity and tool policy
    engine    one run of the DAG (retries, timeouts, waits, approvals, resume)
    service   the per-process service and scheduler (cron, files, events, webhooks, recovery)
    tool      a workflow published as an MCP tool

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from sajha.workflows.model import WorkflowError  # noqa: F401
from sajha.workflows.service import (WorkflowService, get_service, init_workflows, set_service,  # noqa: F401
                                     shutdown_workflows)
