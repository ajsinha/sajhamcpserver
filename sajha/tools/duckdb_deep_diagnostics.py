#!/usr/bin/env python3
"""
DuckDB OLAP Tools - Setup and Diagnostic Script

This script helps diagnose and fix issues with the DuckDB data directory.
"""

import os
import sys
import json
from pathlib import Path

# Import the tool
try:
    from tools.impl.duckdb_olap_tools_refactored import DUCKDB_TOOLS, DuckDbBaseTool
except ImportError:
    print("Error: Could not import duckdb_olap_tools_refactored.py")
    print("Make sure it's in the current directory or Python path")
    sys.exit(1)


def print_header(text):
    """Print a formatted header"""
    print(f"\n{'=' * 70}")
    print(f"  {text}")
    print(f"{'=' * 70}\n")


def check_directory(directory_path):
    """Check if directory exists and show its contents"""
    print_header(f"Checking Directory: {directory_path}")

    abs_path = os.path.abspath(directory_path)
    print(f"Absolute path: {abs_path}")
    print(f"Exists: {os.path.exists(abs_path)}")
    print(f"Is directory: {os.path.isdir(abs_path)}")
    print(f"Is readable: {os.access(abs_path, os.R_OK) if os.path.exists(abs_path) else 'N/A'}")

    if os.path.exists(abs_path) and os.path.isdir(abs_path):
        try:
            files = os.listdir(abs_path)
            print(f"\nContains {len(files)} items:")

            if len(files) == 0:
                print("  (empty directory)")
            else:
                # Group by type
                data_files = []
                other_files = []

                for f in files:
                    full_path = os.path.join(abs_path, f)
                    ext = os.path.splitext(f)[1].lower()

                    if ext in ['.csv', '.parquet', '.pq', '.json', '.jsonl', '.tsv']:
                        size = os.path.getsize(full_path)
                        data_files.append((f, ext, size))
                    else:
                        other_files.append(f)

                if data_files:
                    print(f"\n  ✓ Data files ({len(data_files)}):")
                    for name, ext, size in data_files:
                        size_str = format_size(size)
                        print(f"    • {name} ({ext}, {size_str})")
                else:
                    print("\n  ✗ No data files found")

                if other_files:
                    print(f"\n  Other files ({len(other_files)}):")
                    for f in other_files[:5]:  # Show first 5
                        print(f"    • {f}")
                    if len(other_files) > 5:
                        print(f"    ... and {len(other_files) - 5} more")

        except PermissionError:
            print("  ✗ Permission denied - cannot read directory")
        except Exception as e:
            print(f"  ✗ Error reading directory: {e}")


def format_size(bytes):
    """Format bytes to human readable"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes < 1024.0:
            return f"{bytes:.1f} {unit}"
        bytes /= 1024.0
    return f"{bytes:.1f} TB"


def test_tool_with_config(config):
    """Test the list_files tool with a configuration"""
    print_header("Testing DuckDB List Files Tool")

    try:
        # Initialize tool
        tool = DUCKDB_TOOLS['duckdb_list_files'](config)

        print(f"Tool initialized successfully")
        print(f"Data directory: {tool.data_directory}")

        # Execute
        result = tool.execute({
            'file_type': 'all',
            'include_metadata': True
        })

        print(f"\n✓ Tool executed successfully!")
        print(f"Files found: {result['total_files']}")

        if result['total_files'] > 0:
            print("\nFiles:")
            for f in result['files']:
                print(f"  • {f['filename']} ({f['file_type']}, {f.get('file_size_human', 'unknown size')})")
        else:
            print("\n✗ No files found")

            if 'diagnostic' in result:
                print("\nDiagnostic Information:")
                print(f"  Directory checked: {result['diagnostic']['directory_checked']}")
                print(f"  Directory exists: {result['diagnostic']['directory_exists']}")

                if result['diagnostic'].get('all_files_in_directory'):
                    print(f"  Files in directory: {result['diagnostic']['all_files_in_directory']}")

                print("\nSuggestions:")
                for suggestion in result['diagnostic']['suggestions']:
                    print(f"  • {suggestion}")

        return True

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def create_sample_data(directory):
    """Create sample CSV data for testing"""
    print_header("Creating Sample Data")

    try:
        os.makedirs(directory, exist_ok=True)

        # Create sample CSV
        csv_path = os.path.join(directory, 'sample_sales.csv')
        with open(csv_path, 'w') as f:
            f.write("date,product,amount,quantity\n")
            f.write("2024-01-01,Widget A,100.50,5\n")
            f.write("2024-01-02,Widget B,200.75,3\n")
            f.write("2024-01-03,Widget A,150.25,7\n")
            f.write("2024-01-04,Widget C,300.00,2\n")

        print(f"✓ Created: {csv_path}")

        # Create sample JSON
        json_path = os.path.join(directory, 'sample_customers.json')
        with open(json_path, 'w') as f:
            json.dump([
                {"id": 1, "name": "Alice", "city": "New York"},
                {"id": 2, "name": "Bob", "city": "Los Angeles"},
                {"id": 3, "name": "Charlie", "city": "Chicago"}
            ], f, indent=2)

        print(f"✓ Created: {json_path}")

        print(f"\n✓ Sample data created successfully in: {directory}")
        return True

    except Exception as e:
        print(f"✗ Error creating sample data: {e}")
        return False


def main():
    """Main diagnostic routine"""
    print_header("DuckDB OLAP Tools - Diagnostic Script")

    print("This script will help you:")
    print("  1. Diagnose data directory issues")
    print("  2. Set up the correct configuration")
    print("  3. Create sample data for testing")
    print("  4. Verify the tools are working")

    # Check current working directory
    print(f"\nCurrent working directory: {os.getcwd()}")

    # Option 1: Check default directory
    default_dir = 'data/duckdb'
    check_directory(default_dir)

    # Option 2: Check absolute path
    abs_default = os.path.abspath(default_dir)
    if abs_default != default_dir:
        check_directory(abs_default)

    # Ask user what they want to do
    print("\n" + "=" * 70)
    print("What would you like to do?")
    print("  1. Use current directory (data/duckdb)")
    print("  2. Specify a different directory")
    print("  3. Create sample data in default directory")
    print("  4. Exit")

    try:
        choice = input("\nEnter choice (1-4): ").strip()

        if choice == '1':
            data_dir = default_dir
        elif choice == '2':
            data_dir = input("Enter directory path: ").strip()
        elif choice == '3':
            if create_sample_data(abs_default):
                data_dir = default_dir
            else:
                return
        elif choice == '4':
            print("Exiting...")
            return
        else:
            print("Invalid choice")
            return

        # Load or create config
        config = {
            'name': 'duckdb_list_files',
            'data_directory': data_dir
        }

        # Test the tool
        success = test_tool_with_config(config)

        if success:
            print("\n" + "=" * 70)
            print("Configuration to use in your code:")
            print("=" * 70)
            print(json.dumps(config, indent=2))
            print("\nOr set it programmatically:")
            print(f"config['data_directory'] = '{data_dir}'")

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


def show_usage_examples():
    """Show usage examples"""
    print_header("Usage Examples")

    print("Example 1: Basic usage with default directory")
    print("-" * 70)
    print("""
import json
from duckdb_olap_tools_refactored import DUCKDB_TOOLS

# Load config
with open('duckdb_list_files.json') as f:
    config = json.load(f)

# Initialize tool
tool = DUCKDB_TOOLS['duckdb_list_files'](config)

# List files
result = tool.execute({'file_type': 'all'})
print(f"Found {result['total_files']} files")
    """)

    print("\nExample 2: Using a custom directory")
    print("-" * 70)
    print("""
import json
from duckdb_olap_tools_refactored import DUCKDB_TOOLS

# Load config
with open('duckdb_list_files.json') as f:
    config = json.load(f)

# Override data directory
config['data_directory'] = '/absolute/path/to/your/data'

# Initialize tool
tool = DUCKDB_TOOLS['duckdb_list_files'](config)

# List files
result = tool.execute({'file_type': 'csv'})
    """)

    print("\nExample 3: Setting directory via environment variable")
    print("-" * 70)
    print("""
# In your shell:
export DUCKDB_DATA_DIR="/path/to/data"

# In Python:
import os
import json
from duckdb_olap_tools_refactored import DUCKDB_TOOLS

with open('duckdb_list_files.json') as f:
    config = json.load(f)

config['data_directory'] = os.environ.get('DUCKDB_DATA_DIR', 'data/duckdb')

tool = DUCKDB_TOOLS['duckdb_list_files'](config)
    """)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--examples':
        show_usage_examples()
    else:
        main()