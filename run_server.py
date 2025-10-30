#!/usr/bin/env python3
"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Main entry point for SAJHA MCP Server
"""

import os
import sys
import logging
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_root))

from core.properties_configurator import PropertiesConfigurator
from web.app import create_app

def setup_logging():
    """Setup logging configuration"""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('logs/server.log')
        ]
    )

def create_directories():
    """Create necessary directories"""
    dirs = ['logs', 'config', 'config/tools', 'data', 'temp']
    for dir_name in dirs:
        os.makedirs(dir_name, exist_ok=True)

def main():
    """Main entry point"""
    # Create necessary directories
    create_directories()
    
    # Setup logging
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Initialize properties configurator
    config_files = ['config/server.properties', 'config/application.properties']
    props = PropertiesConfigurator(config_files)
    
    # Get server configuration
    host = props.get('server.host', '0.0.0.0')
    port = props.get_int('server.port', 8000)
    debug = props.get('server.debug', 'false').lower() == 'true'
    
    logger.info(f"Starting SAJHA MCP Server on {host}:{port}")
    
    # Create and run Flask app
    app, socketio = create_app()
    #
    cert_file = props.get('server.cert.file', None)
    key_file = props.get('server.key.file', None)
    #
    # Run with SocketIO support
    if not cert_file and not key_file:
        socketio.run(app, host=host, port=port, debug=debug,allow_unsafe_werkzeug=True)
    else:
        socketio.run(app, host=host, port=port, debug=debug, ssl_context=(cert_file, key_file))


if __name__ == '__main__':
    main()
