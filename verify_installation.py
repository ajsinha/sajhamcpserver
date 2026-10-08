#!/usr/bin/env python3
"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Verification script for SAJHA MCP Server installation
"""

import os
import sys
import json
from pathlib import Path

def check_file(path, description):
    """Check if a file exists"""
    if Path(path).exists():
        print(f"✓ {description}: {path}")
        return True
    else:
        print(f"✗ {description}: {path} NOT FOUND")
        return False

def check_directory(path, description):
    """Check if a directory exists"""
    if Path(path).is_dir():
        print(f"✓ {description}: {path}")
        return True
    else:
        print(f"✗ {description}: {path} NOT FOUND")
        return False

def verify_json_file(path, description):
    """Verify JSON file is valid"""
    try:
        with open(path, 'r') as f:
            json.load(f)
        print(f"✓ {description}: Valid JSON")
        return True
    except Exception as e:
        print(f"✗ {description}: Invalid JSON - {str(e)}")
        return False

def main():
    print("=" * 60)
    print("SAJHA MCP Server - Installation Verification")
    print("=" * 60)
    
    all_ok = True
    
    # Check main files
    print("\n[1] Checking main files...")
    all_ok &= check_file("run_sajha_web.py", "Main entry point")
    all_ok &= check_file("requirements.txt", "Dependencies file")
    all_ok &= check_file("README.md", "Documentation")
    all_ok &= check_file("start.sh", "Quick start script")
    
    # Check directories
    print("\n[2] Checking directories...")
    all_ok &= check_directory("core", "Core module")
    all_ok &= check_directory("tools", "Tools module")
    all_ok &= check_directory("tools/impl", "Tool implementations")
    all_ok &= check_directory("web", "Web module")
    all_ok &= check_directory("web/templates", "HTML templates")
    all_ok &= check_directory("web/static", "Static files")
    all_ok &= check_directory("config", "Configuration")
    all_ok &= check_directory("config/tools", "Tool configs")
    
    # Check core module files
    print("\n[3] Checking core module...")
    all_ok &= check_file("core/__init__.py", "Core init")
    all_ok &= check_file("core/properties_configurator.py", "Properties configurator")
    all_ok &= check_file("sajha/auth/__init__.py", "Auth manager")
    all_ok &= check_file("core/mcp_handler.py", "MCP handler")
    
    # Check tools module files
    print("\n[4] Checking tools module...")
    all_ok &= check_file("tools/__init__.py", "Tools init")
    all_ok &= check_file("tools/base_mcp_tool.py", "Base tool class")
    all_ok &= check_file("tools/tools_registry.py", "Tools registry")
    
    # Check tool implementations
    print("\n[5] Checking tool implementations...")
    all_ok &= check_file("tools/impl/__init__.py", "Impl init")
    all_ok &= check_file("tools/impl/wikipedia_tool.py", "Wikipedia tool")
    all_ok &= check_file("tools/impl/yahoo_finance_tool.py", "Yahoo Finance tool")
    all_ok &= check_file("tools/impl/google_search_tool.py", "Google Search tool")
    all_ok &= check_file("tools/impl/fed_reserve_tool.py", "Fed Reserve tool")
    
    # Check web module files
    print("\n[6] Checking web module...")
    all_ok &= check_file("web/__init__.py", "Web init")
    all_ok &= check_file("web/app.py", "Flask application")
    
    # Check templates
    print("\n[7] Checking templates...")
    templates = [
        "base.html", "login.html", "dashboard.html", "tools_list.html",
        "tool_execute.html", "admin_tools.html", "admin_users.html",
        "monitoring_tools.html", "monitoring_users.html", "error.html"
    ]
    for template in templates:
        all_ok &= check_file(f"web/templates/{template}", f"Template {template}")
    
    # Check static files
    print("\n[8] Checking static files...")
    all_ok &= check_file("web/static/css/style.css", "CSS styles")
    all_ok &= check_file("web/static/js/main.js", "JavaScript")
    
    # Check configuration files
    print("\n[9] Checking configuration...")
    all_ok &= check_file("config/server.properties", "Server properties")
    all_ok &= check_file("config/application.properties", "Application properties")
    
    # Check tool configurations
    print("\n[10] Checking tool configurations...")
    tool_configs = [
        "wikipedia.json", "yahoo_finance.json", 
        "google_search.json", "fed_reserve.json"
    ]
    for config in tool_configs:
        if check_file(f"config/tools/{config}", f"Tool config {config}"):
            all_ok &= verify_json_file(f"config/tools/{config}", f"  → {config}")
    
    # Try to import modules
    print("\n[11] Testing Python imports...")
    try:
        sys.path.insert(0, os.getcwd())
        from core.properties_configurator import PropertiesConfigurator
        print("✓ PropertiesConfigurator import successful")
    except Exception as e:
        print(f"✗ PropertiesConfigurator import failed: {e}")
        all_ok = False
    
    try:
        from sajha.auth import AuthManager
        print("✓ AuthManager import successful")
    except Exception as e:
        print(f"✗ AuthManager import failed: {e}")
        all_ok = False
    
    try:
        from core.mcp_handler import MCPHandler
        print("✓ MCPHandler import successful")
    except Exception as e:
        print(f"✗ MCPHandler import failed: {e}")
        all_ok = False
    
    try:
        from tools.tools_registry import ToolsRegistry
        print("✓ ToolsRegistry import successful")
    except Exception as e:
        print(f"✗ ToolsRegistry import failed: {e}")
        all_ok = False
    
    # Summary
    print("\n" + "=" * 60)
    if all_ok:
        print("✓ VERIFICATION SUCCESSFUL - All components are properly installed!")
        print("\nTo start the server, run:")
        print("  python run_sajha_web.py")
        print("\nOr use the quick start script:")
        print("  ./start.sh")
    else:
        print("✗ VERIFICATION FAILED - Some components are missing or invalid")
        print("\nPlease check the errors above and fix them before running the server")
    print("=" * 60)
    
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
