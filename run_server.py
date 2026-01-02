#!/usr/bin/env python3
"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Main entry point for SAJHA MCP Server v2.2.0

This script initializes and runs the SAJHA MCP Server web application.
It handles:
- Directory setup
- Logging configuration
- Properties loading
- Application instantiation and startup
- Graceful shutdown
"""

import os
import sys
import signal
import logging
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_root))

from sajha.core.properties_configurator import PropertiesConfigurator
from sajha.web.sajhamcpserver_web import SajhaMCPServerWebApp

# Global reference for graceful shutdown
_web_app: SajhaMCPServerWebApp = None


def setup_logging(log_level: str = 'INFO'):
    """
    Setup logging configuration with proper timestamp format.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    # Ensure logs directory exists
    os.makedirs('logs', exist_ok=True)
    
    # Standard log format with ISO timestamp
    log_format = '%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s'
    date_format = '%Y-%m-%d %H:%M:%S'
    
    # Create formatter
    formatter = logging.Formatter(log_format, datefmt=date_format)
    
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # Clear existing handlers to avoid duplicates
    root_logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler
    file_handler = logging.FileHandler('logs/server.log', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    # Reduce verbosity of noisy loggers
    logging.getLogger('werkzeug').setLevel(logging.CRITICAL)  # Suppress WebSocket disconnect errors
    logging.getLogger('engineio').setLevel(logging.WARNING)
    logging.getLogger('socketio').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def create_directories():
    """Create necessary directories for the application."""
    dirs = [
        'logs',
        'config',
        'config/tools',
        'config/prompts',
        'data',
        'data/flask_session',
        'temp'
    ]
    for dir_name in dirs:
        os.makedirs(dir_name, exist_ok=True)


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global _web_app
    logger = logging.getLogger(__name__)
    
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name}, initiating graceful shutdown...")
    
    if _web_app:
        _web_app.shutdown()
    
    sys.exit(0)


def main():
    """Main entry point for SAJHA MCP Server."""
    global _web_app
    
    # Create necessary directories
    create_directories()
    
    # Initialize properties configurator
    config_files = ['config/server.properties', 'config/application.properties']
    props = PropertiesConfigurator(config_files)
    
    # Setup logging with configured level
    log_level = props.get('logging.level', 'INFO')
    setup_logging(log_level)
    
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("SAJHA MCP Server v2.2.0 Starting...")
    logger.info("=" * 60)
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Get server configuration
    host = props.get('server.host', '0.0.0.0')
    port = props.get_int('server.port', 8000)
    debug = props.get_bool('server.debug', False)
    
    # SSL configuration
    cert_file = props.get('server.cert.file', None)
    key_file = props.get('server.key.file', None)
    
    # Hot-reload interval
    hot_reload_interval = props.get_int('hot_reload.interval.seconds', 300)
    
    logger.info(f"Configuration:")
    logger.info(f"  Host: {host}")
    logger.info(f"  Port: {port}")
    logger.info(f"  Debug: {debug}")
    logger.info(f"  SSL: {'Enabled' if cert_file and key_file else 'Disabled'}")
    logger.info(f"  Hot-Reload Interval: {hot_reload_interval}s")
    
    try:
        # Create the web application
        logger.info("Creating SAJHA MCP Server Web Application...")
        _web_app = SajhaMCPServerWebApp()
        
        # Prepare the application (initializes managers, registers routes)
        logger.info("Preparing application...")
        _web_app.prepare()
        
        # Log startup summary
        logger.info("-" * 60)
        logger.info(f"Tools loaded: {len(_web_app.tools_registry.tools)}")
        logger.info(f"Prompts loaded: {len(_web_app.prompts_registry.prompts)}")
        logger.info(f"Users loaded: {len(_web_app.auth_manager.users)}")
        logger.info(f"API Keys loaded: {len(_web_app.auth_manager.list_api_keys())}")
        logger.info("-" * 60)
        
        # Get Flask app and SocketIO
        app = _web_app.get_app()
        socketio = _web_app.get_socketio()
        
        logger.info(f"Starting server on {host}:{port}...")
        
        # Run with SocketIO support
        if cert_file and key_file:
            logger.info(f"SSL enabled with cert: {cert_file}")
            socketio.run(
                app,
                host=host,
                port=port,
                debug=debug,
                ssl_context=(cert_file, key_file)
            )
        else:
            socketio.run(
                app,
                host=host,
                port=port,
                debug=debug,
                allow_unsafe_werkzeug=True
            )
    
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        if _web_app:
            _web_app.shutdown()
    
    except Exception as e:
        logger.error(f"Error starting server: {e}", exc_info=True)
        if _web_app:
            _web_app.shutdown()
        sys.exit(1)
    
    finally:
        logger.info("SAJHA MCP Server stopped")


if __name__ == '__main__':
    main()
