#!/usr/bin/env python3
"""
SAJHA MCP Server v3 — Main Entry Point
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Run this file directly in PyCharm (Right-click → Run/Debug)
or from the command line:

    python run_server.py
    python run_server.py --host 0.0.0.0 --port 3002
    python run_server.py --reload
"""

import os
import sys
import signal
import logging
import argparse
from pathlib import Path

# ── Ensure project root on path (PyCharm + CLI compatible) ───────
project_root = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_root))
os.chdir(project_root)


def setup_logging(level: str = 'INFO'):
    os.makedirs('logs', exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format='%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('logs/server.log', encoding='utf-8'),
        ],
    )
    logging.getLogger('uvicorn.access').setLevel(logging.WARNING)


def print_banner():
    print(r"""
================================================================================
   ███████╗ █████╗      ██╗██╗  ██╗ █████╗     ███╗   ███╗ ██████╗██████╗
   ██╔════╝██╔══██╗     ██║██║  ██║██╔══██╗    ████╗ ████║██╔════╝██╔══██╗
   ███████╗███████║     ██║███████║███████║    ██╔████╔██║██║     ██████╔╝
   ╚════██║██╔══██║██   ██║██╔══██║██╔══██║    ██║╚██╔╝██║██║     ██╔═══╝
   ███████║██║  ██║╚█████╔╝██║  ██║██║  ██║    ██║ ╚═╝ ██║╚██████╗██║
   ╚══════╝╚═╝  ╚═╝ ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝    ╚═╝     ╚═╝ ╚═════╝╚═╝

              Model Context Protocol Server  v3.0
         FastAPI · SQLAlchemy · JWT · SSE · A2A
================================================================================
""")


def signal_handler(signum, frame):
    logging.getLogger(__name__).info(f'Shutdown signal ({signal.Signals(signum).name})')
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description='SAJHA MCP Server v3')
    parser.add_argument('--host', default=None, help='Host to bind to')
    parser.add_argument('--port', type=int, default=None, help='Port to listen on')
    parser.add_argument('--reload', action='store_true', help='Enable auto-reload (dev mode)')
    parser.add_argument('--workers', type=int, default=1, help='Number of workers')
    parser.add_argument('--log-level', default=None, help='Log level')
    args = parser.parse_args()

    # Ensure directories exist
    for d in ['logs', 'config', 'config/tools', 'config/prompts', 'data', 'temp']:
        os.makedirs(d, exist_ok=True)

    # Load settings
    from sajha.core.config import get_settings
    settings = get_settings()

    host = args.host or settings.server_host
    port = args.port or settings.server_port
    log_level = args.log_level or settings.logging_level

    setup_logging(log_level)
    logger = logging.getLogger(__name__)

    print_banner()
    logger.info(f'  Python:  {sys.version.split()[0]}')
    logger.info(f'  CWD:     {os.getcwd()}')
    logger.info(f'  Config:  {settings.config_source}')
    logger.info(f'  DB:      {settings.db_type} → {settings.db_path}')
    logger.info(f'  Server:  http://{host}:{port}')
    logger.info('')

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # ── Start via SajhaMCPServerWebApp ───────────────────────────
    # In --reload mode, uvicorn needs a factory string.
    # Without --reload, we can pass the app object directly.

    import uvicorn

    if args.reload:
        # Factory mode: uvicorn imports and calls create_app()
        uvicorn.run(
            'sajha.app:create_app',
            host=host, port=port,
            reload=True,
            log_level=log_level.lower(),
            factory=True,
        )
    else:
        # Direct mode: instantiate SajhaMCPServerWebApp here
        from sajha.app import SajhaMCPServerWebApp
        webapp = SajhaMCPServerWebApp()
        uvicorn.run(
            webapp.app,
            host=host, port=port,
            workers=args.workers,
            log_level=log_level.lower(),
        )


if __name__ == '__main__':
    main()
