#!/usr/bin/env python3
"""
SAJHA MCP Server - Document & SQL Tools Client v2.1.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Example client for Document and SQL tools:

MS Document Tools:
- msdoc_list_files: List document files
- msdoc_read_word: Read Word documents
- msdoc_read_excel: Read Excel files
- msdoc_extract_text: Extract text content
- msdoc_search_word: Search in Word docs
- msdoc_search_excel: Search in Excel files
- msdoc_get_word_metadata: Get Word metadata
- msdoc_get_excel_metadata: Get Excel metadata
- msdoc_get_excel_sheets: List Excel sheets
- msdoc_read_excel_sheet: Read specific sheet

SQL Select Tools:
- sqlselect_list_sources: List data sources
- sqlselect_describe_source: Describe source schema
- sqlselect_execute_query: Execute SQL query
- sqlselect_get_schema: Get schema
- sqlselect_count_rows: Count rows
- sqlselect_sample_data: Get sample data

Usage:
    export SAJHA_API_KEY="sja_your_key_here"
    python -m sajha.examples.document_sql_client
"""

from .base_client import SajhaClient, SajhaAPIError, pretty_print, run_example


class DocumentSQLClient(SajhaClient):
    """Client for Document and SQL tools."""
    
    # ============= MS Document Tools =============
    def list_files(self, path: str = None, file_type: str = None) -> dict:
        """
        List document files.
        
        Args:
            path: Directory path
            file_type: Filter by type (word, excel, all)
        """
        args = {}
        if path:
            args['path'] = path
        if file_type:
            args['file_type'] = file_type
        return self.execute_tool('msdoc_list_files', args)
    
    def read_word(self, file_path: str) -> dict:
        """
        Read Word document.
        
        Args:
            file_path: Path to .docx file
        """
        return self.execute_tool('msdoc_read_word', {'file_path': file_path})
    
    def read_excel(self, file_path: str, sheet: str = None) -> dict:
        """
        Read Excel file.
        
        Args:
            file_path: Path to .xlsx file
            sheet: Specific sheet name
        """
        args = {'file_path': file_path}
        if sheet:
            args['sheet'] = sheet
        return self.execute_tool('msdoc_read_excel', args)
    
    def extract_text(self, file_path: str) -> dict:
        """Extract text from document."""
        return self.execute_tool('msdoc_extract_text', {'file_path': file_path})
    
    def search_word(self, file_path: str, query: str) -> dict:
        """Search in Word document."""
        return self.execute_tool('msdoc_search_word', {
            'file_path': file_path,
            'query': query
        })
    
    def search_excel(self, file_path: str, query: str) -> dict:
        """Search in Excel file."""
        return self.execute_tool('msdoc_search_excel', {
            'file_path': file_path,
            'query': query
        })
    
    def get_word_metadata(self, file_path: str) -> dict:
        """Get Word document metadata."""
        return self.execute_tool('msdoc_get_word_metadata', {'file_path': file_path})
    
    def get_excel_metadata(self, file_path: str) -> dict:
        """Get Excel file metadata."""
        return self.execute_tool('msdoc_get_excel_metadata', {'file_path': file_path})
    
    def get_excel_sheets(self, file_path: str) -> dict:
        """List Excel sheets."""
        return self.execute_tool('msdoc_get_excel_sheets', {'file_path': file_path})
    
    def read_excel_sheet(self, file_path: str, sheet_name: str) -> dict:
        """Read specific Excel sheet."""
        return self.execute_tool('msdoc_read_excel_sheet', {
            'file_path': file_path,
            'sheet_name': sheet_name
        })
    
    # ============= SQL Select Tools =============
    def sql_list_sources(self) -> dict:
        """List available data sources."""
        return self.execute_tool('sqlselect_list_sources', {})
    
    def sql_describe_source(self, source: str) -> dict:
        """Describe a data source."""
        return self.execute_tool('sqlselect_describe_source', {'source': source})
    
    def sql_execute_query(self, 
                          source: str, 
                          query: str, 
                          limit: int = 100) -> dict:
        """
        Execute SQL query on a source.
        
        Args:
            source: Data source name
            query: SQL query
            limit: Maximum rows
        """
        return self.execute_tool('sqlselect_execute_query', {
            'source': source,
            'query': query,
            'limit': limit
        })
    
    def sql_get_schema(self, source: str) -> dict:
        """Get schema for a data source."""
        return self.execute_tool('sqlselect_get_schema', {'source': source})
    
    def sql_count_rows(self, source: str, table: str) -> dict:
        """Count rows in a table."""
        return self.execute_tool('sqlselect_count_rows', {
            'source': source,
            'table': table
        })
    
    def sql_sample_data(self, source: str, table: str, limit: int = 10) -> dict:
        """Get sample data from a table."""
        return self.execute_tool('sqlselect_sample_data', {
            'source': source,
            'table': table,
            'limit': limit
        })


@run_example
def example_list_files():
    """Example: List document files"""
    client = DocumentSQLClient()
    
    print("\n📁 Listing document files...")
    files = client.list_files()
    pretty_print(files, "Document Files")


@run_example
def example_sql_list_sources():
    """Example: List SQL data sources"""
    client = DocumentSQLClient()
    
    print("\n💾 Listing SQL data sources...")
    sources = client.sql_list_sources()
    pretty_print(sources, "Data Sources")


@run_example
def example_sql_describe():
    """Example: Describe data source"""
    client = DocumentSQLClient()
    
    # First get sources
    sources = client.sql_list_sources()
    
    if sources.get('sources'):
        source = sources['sources'][0].get('name', '')
        if source:
            print(f"\n📋 Describing source: {source}")
            schema = client.sql_describe_source(source)
            pretty_print(schema, f"Schema: {source}")


@run_example
def example_sql_query():
    """Example: Execute SQL query"""
    client = DocumentSQLClient()
    
    # First get sources
    sources = client.sql_list_sources()
    
    if sources.get('sources'):
        source = sources['sources'][0].get('name', '')
        if source:
            print(f"\n🔍 Querying source: {source}")
            # Get sample data
            sample = client.sql_sample_data(source, source, limit=5)
            pretty_print(sample, "Sample Data")


@run_example
def example_document_analysis():
    """Example: Document analysis workflow"""
    client = DocumentSQLClient()
    
    print("\n📄 Document Analysis Workflow")
    print("=" * 50)
    
    # List available documents
    print("\n1️⃣ Available documents:")
    files = client.list_files()
    
    if files.get('files'):
        for f in files['files'][:5]:
            print(f"   • {f.get('name')}: {f.get('type')}")
        
        # If Word docs exist, show metadata
        word_files = [f for f in files['files'] if f.get('type') == 'word']
        if word_files:
            print(f"\n2️⃣ Word document metadata:")
            metadata = client.get_word_metadata(word_files[0]['path'])
            pretty_print(metadata, "")


@run_example  
def example_data_exploration():
    """Example: Data exploration workflow"""
    client = DocumentSQLClient()
    
    print("\n🔬 Data Exploration Workflow")
    print("=" * 50)
    
    # List sources
    print("\n1️⃣ Data sources:")
    sources = client.sql_list_sources()
    
    if sources.get('sources'):
        for src in sources['sources'][:3]:
            print(f"   • {src.get('name')}: {src.get('type')}")
        
        # Explore first source
        if sources['sources']:
            source = sources['sources'][0]['name']
            
            print(f"\n2️⃣ Schema for {source}:")
            schema = client.sql_get_schema(source)
            if schema.get('tables'):
                for t in schema['tables'][:3]:
                    print(f"   • {t.get('name')}: {t.get('row_count', 'N/A')} rows")


if __name__ == '__main__':
    print("=" * 60)
    print(" SAJHA MCP Server - Document & SQL Tools Examples v2.1.0")
    print("=" * 60)
    
    example_list_files()
    example_sql_list_sources()
    example_sql_describe()
    example_sql_query()
    example_document_analysis()
    example_data_exploration()
