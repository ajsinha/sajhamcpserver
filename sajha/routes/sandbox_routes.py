"""
SAJHA MCP Server — Sandbox status route.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

``GET /api/sandbox/status`` (admin): the active sandbox backend, every backend's
availability on this host, and what the active one guarantees, from a live probe
of the runner. Design: docs/architecture/Sandbox.md.
"""

import asyncio

from fastapi import APIRouter, Depends

from sajha.auth import AuthContext, require_admin

router = APIRouter(tags=['sandbox'])


@router.get('/api/sandbox/status')
async def sandbox_status(auth: AuthContext = Depends(require_admin)):
    from sajha.sandbox import status
    return await asyncio.to_thread(status, True)
