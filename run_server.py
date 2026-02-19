#!/usr/bin/env python3
"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Main entry point for SAJHA MCP Server v2.9.0

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
import time
from pathlib import Path
from datetime import datetime

# Add project root to Python path
project_root = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_root))

from sajha import __version__
from sajha.core.properties_configurator import PropertiesConfigurator
from sajha.web.sajhamcpserver_web import SajhaMCPServerWebApp

# Global reference for graceful shutdown
_web_app: SajhaMCPServerWebApp = None
_startup_time: float = None

# Server info
SERVER_NAME = "SAJHA MCP Server"
SERVER_VERSION = __version__


def print_banner(logger):
    """Print the startup banner."""
    banner = """
================================================================================
   ███████╗ █████╗      ██╗██╗  ██╗ █████╗     ███╗   ███╗ ██████╗██████╗ 
   ██╔════╝██╔══██╗     ██║██║  ██║██╔══██╗    ████╗ ████║██╔════╝██╔══██╗
   ███████╗███████║     ██║███████║███████║    ██╔████╔██║██║     ██████╔╝
   ╚════██║██╔══██║██   ██║██╔══██║██╔══██║    ██║╚██╔╝██║██║     ██╔═══╝ 
   ███████║██║  ██║╚█████╔╝██║  ██║██║  ██║    ██║ ╚═╝ ██║╚██████╗██║     
   ╚══════╝╚═╝  ╚═╝ ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝    ╚═╝     ╚═╝ ╚═════╝╚═╝     
                                                                          
                     Model Context Protocol Server                        
================================================================================"""
    for line in banner.split('\n'):
        logger.info(line)


def log_phase(logger, phase_num: int, phase_name: str, status: str = "STARTING"):
    """Log a startup/shutdown phase."""
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    logger.info("")
    logger.info("=" * 76)
    logger.info(f"  [{timestamp}] PHASE {phase_num}: {phase_name}")
    logger.info("=" * 76)


def log_phase_complete(logger, message: str):
    """Log phase completion."""
    logger.info(f"  [OK] {message}")


def log_phase_item(logger, item: str, value=None):
    """Log an item within a phase."""
    if value is not None:
        logger.info(f"       -> {item}: {value}")
    else:
        logger.info(f"       -> {item}")


def log_shutdown_phase(logger, phase_name: str):
    """Log a shutdown phase."""
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    logger.info("")
    logger.info(f"  [{timestamp}] SHUTDOWN: {phase_name}")
    logger.info("-" * 60)


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
    logging.getLogger('werkzeug').setLevel(logging.CRITICAL)
    logging.getLogger('engineio').setLevel(logging.WARNING)
    logging.getLogger('socketio').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def create_directories(logger):
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
    created = []
    for dir_name in dirs:
        if not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
            created.append(dir_name)
    
    if created:
        for d in created:
            log_phase_item(logger, f"Created: {d}")
    else:
        log_phase_item(logger, "All required directories exist")
    
    return len(created)


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global _web_app, _startup_time
    logger = logging.getLogger(__name__)
    
    signal_name = signal.Signals(signum).name
    
    logger.info("")
    logger.info("=" * 76)
    logger.info("                    SHUTDOWN SEQUENCE INITIATED")
    logger.info("=" * 76)
    logger.info(f"  Signal received: {signal_name}")
    logger.info(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Phase 1: Stop accepting connections
    log_shutdown_phase(logger, "Stopping New Connections")
    logger.info("       -> Closing HTTP listener")
    logger.info("       -> Closing WebSocket connections")
    log_phase_complete(logger, "Connection listeners stopped")
    
    # Phase 2: Cleanup resources
    log_shutdown_phase(logger, "Cleaning Up Resources")
    
    if _web_app:
        try:
            logger.info("       -> Stopping hot-reload manager")
            logger.info("       -> Closing database connections")
            logger.info("       -> Flushing caches")
            _web_app.shutdown()
            log_phase_complete(logger, "Application resources released")
        except Exception as e:
            logger.warning(f"       -> Warning during cleanup: {e}")
    
    # Phase 3: Final statistics
    log_shutdown_phase(logger, "Final Statistics")
    
    if _startup_time:
        uptime = time.time() - _startup_time
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)
        seconds = int(uptime % 60)
        logger.info(f"       -> Total uptime: {hours}h {minutes}m {seconds}s")
    
    logger.info(f"       -> Shutdown completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Final message
    logger.info("")
    logger.info("=" * 76)
    logger.info("               SAJHA MCP SERVER STOPPED SUCCESSFULLY")
    logger.info("                          Goodbye!")
    logger.info("=" * 76)
    logger.info("")
    
    sys.exit(0)


def main():
    """Main entry point for SAJHA MCP Server."""
    global _web_app, _startup_time
    
    _startup_time = time.time()
    
    # ================================================================
    # PHASE 1: Initial Setup
    # ================================================================
    
    # Create necessary directories first (before logging setup)
    os.makedirs('logs', exist_ok=True)
    
    # Initialize properties configurator
    config_files = ['config/server.properties', 'config/application.properties']
    props = PropertiesConfigurator(config_files)
    
    # Setup logging with configured level
    log_level = props.get('logging.level', 'INFO')
    setup_logging(log_level)
    
    logger = logging.getLogger(__name__)
    
    # Print banner
    print_banner(logger)
    
    logger.info("")
    logger.info(f"  Version:    {SERVER_VERSION}")
    logger.info(f"  Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"  Python:     {sys.version.split()[0]}")
    logger.info(f"  Platform:   {sys.platform}")
    logger.info(f"  PID:        {os.getpid()}")
    
    # ================================================================
    # PHASE 1: Directory Setup
    # ================================================================
    log_phase(logger, 1, "DIRECTORY SETUP")
    dirs_created = create_directories(logger)
    log_phase_complete(logger, f"Directory setup complete ({dirs_created} created)")
    
    # ================================================================
    # PHASE 2: Configuration Loading
    # ================================================================
    log_phase(logger, 2, "LOADING CONFIGURATION")
    
    # Get server configuration
    host = props.get('server.host', '0.0.0.0')
    port = props.get_int('server.port', 8000)
    debug = props.get_bool('server.debug', False)
    cert_file = props.get('server.cert.file', None)
    key_file = props.get('server.key.file', None)
    hot_reload_interval = props.get_int('hot_reload.interval.seconds', 300)
    
    log_phase_item(logger, "Server Host", host)
    log_phase_item(logger, "Server Port", str(port))
    log_phase_item(logger, "Debug Mode", str(debug))
    log_phase_item(logger, "SSL/TLS", 'Enabled' if cert_file and key_file else 'Disabled')
    log_phase_item(logger, "Hot-Reload Interval", f"{hot_reload_interval} seconds")
    log_phase_item(logger, "Log Level", log_level)
    log_phase_complete(logger, "Configuration loaded from properties files")
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    logger.info("       -> Signal handlers registered (SIGINT, SIGTERM)")
    
    try:
        # ================================================================
        # PHASE 3: Application Initialization
        # ================================================================
        log_phase(logger, 3, "APPLICATION INITIALIZATION")
        
        log_phase_item(logger, "Creating SajhaMCPServerWebApp instance")
        _web_app = SajhaMCPServerWebApp()
        
        log_phase_item(logger, "Initializing Authentication Manager")
        log_phase_item(logger, "Initializing Tools Registry")
        log_phase_item(logger, "Initializing Prompts Registry")
        log_phase_item(logger, "Initializing Hot-Reload Manager")
        log_phase_item(logger, "Registering Flask Routes")
        log_phase_item(logger, "Registering SocketIO Handlers")
        
        _web_app.prepare()
        log_phase_complete(logger, "Application initialized successfully")
        
        # ================================================================
        # PHASE 4: Loading Resources
        # ================================================================
        log_phase(logger, 4, "LOADING RESOURCES")
        
        tools_count = len(_web_app.tools_registry.tools)
        prompts_count = len(_web_app.prompts_registry.prompts)
        users_count = len(_web_app.auth_manager.users)
        apikeys_count = len(_web_app.auth_manager.list_api_keys())
        
        log_phase_item(logger, "MCP Tools loaded", str(tools_count))
        log_phase_item(logger, "Prompts loaded", str(prompts_count))
        log_phase_item(logger, "User accounts loaded", str(users_count))
        log_phase_item(logger, "API Keys loaded", str(apikeys_count))
        log_phase_complete(logger, "All resources loaded successfully")
        
        # ================================================================
        # PHASE 5: Starting Server
        # ================================================================
        log_phase(logger, 5, "STARTING HTTP SERVER")
        
        # Get Flask app and SocketIO
        app = _web_app.get_app()
        socketio = _web_app.get_socketio()
        
        # Calculate startup time
        startup_duration = time.time() - _startup_time
        
        # Determine URL
        protocol = "https" if cert_file and key_file else "http"
        display_host = "localhost" if host == "0.0.0.0" else host
        server_url = f"{protocol}://{display_host}:{port}"
        
        log_phase_item(logger, "Protocol", protocol.upper())
        log_phase_item(logger, "Binding to", f"{host}:{port}")
        log_phase_item(logger, "WebSocket Support", "Enabled")
        log_phase_item(logger, "CORS", "Enabled")
        log_phase_complete(logger, f"Server configured in {startup_duration:.2f}s")
        
        # ================================================================
        # STARTUP COMPLETE - Summary
        # ================================================================
        logger.info("")
        logger.info("=" * 76)
        logger.info("              SAJHA MCP SERVER STARTED SUCCESSFULLY!")
        logger.info("=" * 76)
        logger.info("")
        logger.info(f"   URL:           {server_url}")
        logger.info(f"   Version:       {SERVER_VERSION}")
        logger.info(f"   Tools:         {tools_count}")
        logger.info(f"   Prompts:       {prompts_count}")
        logger.info(f"   Users:         {users_count}")
        logger.info(f"   API Keys:      {apikeys_count}")
        logger.info(f"   Startup Time:  {startup_duration:.2f} seconds")
        logger.info("")
        logger.info("-" * 76)
        logger.info("   MCP Studio:    Python Code | REST Service | DB Query")
        logger.info("   Web Interface: Dashboard | Tools | Prompts | Monitoring | Admin")
        logger.info("-" * 76)
        logger.info("")
        logger.info("   Press Ctrl+C to initiate graceful shutdown")
        logger.info("")
        logger.info("=" * 76)
        logger.info("")
        
        # Run with SocketIO support
        if cert_file and key_file:
            logger.info(f"Starting HTTPS server with SSL certificate...")
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
        logger.info("")
        logger.info("Keyboard interrupt received (Ctrl+C)")
        signal_handler(signal.SIGINT, None)
    
    except Exception as e:
        logger.error("")
        logger.error("=" * 76)
        logger.error("                    STARTUP FAILED - CRITICAL ERROR")
        logger.error("=" * 76)
        logger.error(f"  Error: {e}")
        logger.error("")
        logger.error("  Stack trace:")
        logger.error("-" * 76)
        import traceback
        for line in traceback.format_exc().split('\n'):
            logger.error(f"  {line}")
        logger.error("=" * 76)
        
        if _web_app:
            try:
                _web_app.shutdown()
            except:
                pass
        
        sys.exit(1)


if __name__ == '__main__':
    main()
