"""
Test script demonstrating the new PropertiesConfigurator methods
"""
import sys
import os
import json
from pathlib import Path

# Add the current directory to path to import the module
sys.path.insert(0, '/home/claude')

from .properties_configurator import PropertiesConfigurator


# Create sample property files for testing
def create_test_files():
    """Create test property and content files"""

    # Create properties file
    with open('/home/claude/test.properties', 'w') as f:
        f.write("""# Test properties file
app.name=MyApplication
app.version=1.0.0
database.host=localhost
database.port=5432
database.url=jdbc:postgresql://${database.host}:${database.port}/mydb
api.endpoint=https://api.example.com
api.key=secret123
api.full_url=${api.endpoint}/v1/users?key=${api.key}
""")

    # Create test text file with placeholders
    with open('/home/claude/test_template.txt', 'w') as f:
        f.write("""Application: ${app.name}
Version: ${app.version}
Database URL: ${database.url}
API Endpoint: ${api.full_url}
Unresolved: ${nonexistent.property}
Nested: The app ${app.name} version ${app.version} is running.
""")

    # Create test JSON file with placeholders
    json_content = {
        "application": {
            "name": "${app.name}",
            "version": "${app.version}"
        },
        "database": {
            "url": "${database.url}",
            "host": "${database.host}",
            "port": "${database.port}"
        },
        "api": {
            "endpoint": "${api.endpoint}",
            "full_url": "${api.full_url}"
        }
    }

    with open('/home/claude/test_config.json', 'w') as f:
        json.dump(json_content, f, indent=2)


def test_resolve_string_content():
    """Test resolve_string_content method"""
    print("=" * 60)
    print("TEST 1: resolve_string_content()")
    print("=" * 60)

    config = PropertiesConfigurator('/home/claude/test.properties')

    test_strings = [
        "App: ${app.name} v${app.version}",
        "Database: ${database.url}",
        "API: ${api.full_url}",
        "Mixed: ${app.name} connects to ${database.host}:${database.port}",
        "Unresolved: ${this.does.not.exist} should remain"
    ]

    for test_str in test_strings:
        resolved = config.resolve_string_content(test_str)
        print(f"\nOriginal:  {test_str}")
        print(f"Resolved:  {resolved}")


def test_load_and_resolve_file_content():
    """Test load_and_resolve_file_content method"""
    print("\n" + "=" * 60)
    print("TEST 2: load_and_resolve_file_content()")
    print("=" * 60)

    config = PropertiesConfigurator('/home/claude/test.properties')

    resolved_lines = config.load_and_resolve_file_content('/home/claude/test_template.txt')

    print("\nResolved file content:")
    print("-" * 60)
    for i, line in enumerate(resolved_lines, 1):
        print(f"{i:2d}: {line}")


def test_resolve_string_json_content():
    """Test resolve_string_json_content method"""
    print("\n" + "=" * 60)
    print("TEST 3: resolve_string_json_content()")
    print("=" * 60)

    config = PropertiesConfigurator('/home/claude/test.properties')

    json_string = '''{
    "app": "${app.name}",
    "version": "${app.version}",
    "db_url": "${database.url}",
    "api": "${api.full_url}"
}'''

    print("\nOriginal JSON string:")
    print(json_string)

    resolved_dict = config.resolve_string_json_content(json_string)

    print("\nResolved dictionary:")
    print(json.dumps(resolved_dict, indent=2))


def test_load_and_resolve_json_file_content():
    """Test load_and_resolve_json_file_content method"""
    print("\n" + "=" * 60)
    print("TEST 4: load_and_resolve_json_file_content()")
    print("=" * 60)

    config = PropertiesConfigurator('/home/claude/test.properties')

    resolved_dict = config.load_and_resolve_json_file_content('/home/claude/test_config.json')

    print("\nResolved JSON from file:")
    print(json.dumps(resolved_dict, indent=2))


def test_with_env_and_commandline():
    """Test with environment variables and command line args"""
    print("\n" + "=" * 60)
    print("TEST 5: Precedence Testing (file < env < commandline)")
    print("=" * 60)

    # Set environment variable
    os.environ['database.host'] = 'env-host.example.com'

    # Simulate command line arg by modifying sys.argv
    original_argv = sys.argv.copy()
    sys.argv.append('--app.version=2.0.0-cli')

    # Create new configurator instance to pick up env and cli args
    config = PropertiesConfigurator('/home/claude/test.properties')

    test_str = "App: ${app.name} v${app.version}, Host: ${database.host}"
    resolved = config.resolve_string_content(test_str)

    print(f"\nOriginal:  {test_str}")
    print(f"Resolved:  {resolved}")
    print("\nProperty sources:")
    print(f"  app.name (from {config.get_source('app.name')}): {config.get('app.name')}")
    print(f"  app.version (from {config.get_source('app.version')}): {config.get('app.version')}")
    print(f"  database.host (from {config.get_source('database.host')}): {config.get('database.host')}")

    # Restore original argv
    sys.argv = original_argv

    # Clean up environment
    del os.environ['database.host']


def main():
    """Run all tests"""
    print("\n" + "#" * 60)
    print("# PropertiesConfigurator New Methods Test Suite")
    print("#" * 60)

    # Create test files
    create_test_files()

    # Run tests
    test_resolve_string_content()
    test_load_and_resolve_file_content()
    test_resolve_string_json_content()
    test_load_and_resolve_json_file_content()
    test_with_env_and_commandline()

    print("\n" + "#" * 60)
    print("# All tests completed!")
    print("#" * 60)


if __name__ == '__main__':
    main()