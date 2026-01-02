"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Test Suite for MSDOC Search MCP Tools
Comprehensive tests for all Microsoft Document processing tools
"""

import unittest
import os
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

# Import all tools
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sajha.tools.impl.msdoc_tools_tool_refactored import (
    MsDocListFilesTool,
    MsDocReadWordTool,
    MsDocReadExcelTool,
    MsDocSearchWordTool,
    MsDocSearchExcelTool,
    MsDocGetWordMetadataTool,
    MsDocGetExcelMetadataTool,
    MsDocExtractTextTool,
    MsDocGetExcelSheetsTool,
    MsDocReadExcelSheetTool,
    MSDOC_TOOLS
)


class TestMsDocBaseSetup(unittest.TestCase):
    """Base test class with common setup and teardown"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        # Create temporary directory for test files
        cls.test_dir = tempfile.mkdtemp(prefix='msdoc_test_')
        cls.config = {
            'docs_directory': cls.test_dir,
            'enabled': True,
            'version': '1.0.0'
        }
        
        # Create mock Word document
        cls.mock_word_file = os.path.join(cls.test_dir, 'test_document.docx')
        
        # Create mock Excel file
        cls.mock_excel_file = os.path.join(cls.test_dir, 'test_spreadsheet.xlsx')
        
        # Create some dummy files
        open(cls.mock_word_file, 'w').close()
        open(cls.mock_excel_file, 'w').close()
        
    @classmethod
    def tearDownClass(cls):
        """Clean up test fixtures"""
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir)


class TestMsDocListFilesTool(TestMsDocBaseSetup):
    """Test cases for msdoc_list_files tool"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = MsDocListFilesTool(self.config)
    
    def test_tool_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'msdoc_list_files')
        self.assertEqual(self.tool.config['version'], '1.0.0')
        self.assertTrue(self.tool.config['enabled'])
        self.assertEqual(self.tool.docs_directory, self.test_dir)
    
    def test_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIn('properties', schema)
        self.assertIn('file_type', schema['properties'])
        self.assertEqual(
            schema['properties']['file_type']['enum'],
            ['all', 'word', 'excel']
        )
    
    def test_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        self.assertIn('properties', schema)
        self.assertIn('directory', schema['properties'])
        self.assertIn('file_type', schema['properties'])
        self.assertIn('count', schema['properties'])
        self.assertIn('files', schema['properties'])
    
    def test_list_all_files(self):
        """Test listing all files"""
        result = self.tool.execute({'file_type': 'all'})
        
        self.assertIn('directory', result)
        self.assertIn('file_type', result)
        self.assertIn('count', result)
        self.assertIn('files', result)
        self.assertEqual(result['file_type'], 'all')
        self.assertGreaterEqual(result['count'], 2)
    
    def test_list_word_files_only(self):
        """Test listing Word files only"""
        result = self.tool.execute({'file_type': 'word'})
        
        self.assertEqual(result['file_type'], 'word')
        for file in result['files']:
            self.assertIn(file['extension'], ['.docx', '.doc'])
    
    def test_list_excel_files_only(self):
        """Test listing Excel files only"""
        result = self.tool.execute({'file_type': 'excel'})
        
        self.assertEqual(result['file_type'], 'excel')
        for file in result['files']:
            self.assertIn(file['extension'], ['.xlsx', '.xls', '.xlsm'])
    
    def test_file_properties(self):
        """Test file properties in response"""
        result = self.tool.execute({'file_type': 'all'})
        
        if result['count'] > 0:
            file_info = result['files'][0]
            self.assertIn('filename', file_info)
            self.assertIn('path', file_info)
            self.assertIn('extension', file_info)
            self.assertIn('size', file_info)
            self.assertIn('modified', file_info)


class TestMsDocReadWordTool(TestMsDocBaseSetup):
    """Test cases for msdoc_read_word tool"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = MsDocReadWordTool(self.config)
    
    @patch('tools.impl.msdoc_tools_tool_refactored.Document')
    def test_read_word_document(self, mock_document):
        """Test reading Word document"""
        # Mock document structure
        mock_doc = MagicMock()
        mock_paragraph1 = MagicMock()
        mock_paragraph1.text = "First paragraph"
        mock_paragraph2 = MagicMock()
        mock_paragraph2.text = "Second paragraph"
        mock_doc.paragraphs = [mock_paragraph1, mock_paragraph2]
        
        # Mock table
        mock_table = MagicMock()
        mock_row = MagicMock()
        mock_cell1 = MagicMock()
        mock_cell1.text = "Cell 1"
        mock_cell2 = MagicMock()
        mock_cell2.text = "Cell 2"
        mock_row.cells = [mock_cell1, mock_cell2]
        mock_table.rows = [mock_row]
        mock_doc.tables = [mock_table]
        
        mock_document.return_value = mock_doc
        
        result = self.tool.execute({'filename': 'test_document.docx'})
        
        self.assertIn('filename', result)
        self.assertIn('paragraphs', result)
        self.assertIn('paragraph_count', result)
        self.assertIn('tables', result)
        self.assertIn('table_count', result)
        self.assertEqual(result['paragraph_count'], 2)
        self.assertEqual(result['table_count'], 1)
    
    def test_file_not_found_error(self):
        """Test error when file doesn't exist"""
        with self.assertRaises(ValueError) as context:
            self.tool.execute({'filename': 'nonexistent.docx'})
        self.assertIn('File not found', str(context.exception))
    
    def test_input_schema(self):
        """Test input schema"""
        schema = self.tool.get_input_schema()
        self.assertIn('filename', schema['properties'])
        self.assertIn('filename', schema['required'])
    
    def test_output_schema(self):
        """Test output schema"""
        schema = self.tool.get_output_schema()
        self.assertIn('paragraphs', schema['properties'])
        self.assertIn('tables', schema['properties'])
        self.assertEqual(
            schema['properties']['paragraphs']['type'],
            'array'
        )


class TestMsDocReadExcelTool(TestMsDocBaseSetup):
    """Test cases for msdoc_read_excel tool"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = MsDocReadExcelTool(self.config)
    
    @patch('tools.impl.msdoc_tools_tool_refactored.load_workbook')
    def test_read_excel_document(self, mock_load_workbook):
        """Test reading Excel document"""
        # Mock workbook and worksheet
        mock_wb = MagicMock()
        mock_sheet = MagicMock()
        mock_sheet.title = "Sheet1"
        mock_sheet.iter_rows.return_value = [
            ('Header1', 'Header2', 'Header3'),
            ('Value1', 'Value2', 'Value3'),
            ('Value4', 'Value5', 'Value6')
        ]
        mock_wb.active = mock_sheet
        mock_load_workbook.return_value = mock_wb
        
        result = self.tool.execute({
            'filename': 'test_spreadsheet.xlsx',
            'max_rows': 10
        })
        
        self.assertIn('filename', result)
        self.assertIn('sheet_name', result)
        self.assertIn('data', result)
        self.assertIn('row_count', result)
        self.assertIn('column_count', result)
        self.assertEqual(result['sheet_name'], 'Sheet1')
    
    @patch('tools.impl.msdoc_tools_tool_refactored.load_workbook')
    def test_read_excel_with_formulas(self, mock_load_workbook):
        """Test reading Excel with formulas"""
        mock_wb = MagicMock()
        mock_sheet = MagicMock()
        mock_sheet.title = "Sheet1"
        
        # Mock cell with formula
        mock_cell = MagicMock()
        mock_cell.value = "=SUM(A1:A10)"
        mock_cell.coordinate = "A11"
        
        mock_row = MagicMock()
        mock_row.__iter__ = lambda self: iter([mock_cell])
        mock_sheet.iter_rows.return_value = [mock_row]
        
        mock_wb.active = mock_sheet
        mock_load_workbook.return_value = mock_wb
        
        result = self.tool.execute({
            'filename': 'test_spreadsheet.xlsx',
            'include_formulas': True
        })
        
        self.assertIn('formulas', result)
    
    def test_input_schema(self):
        """Test input schema"""
        schema = self.tool.get_input_schema()
        self.assertIn('filename', schema['properties'])
        self.assertIn('sheet_name', schema['properties'])
        self.assertIn('sheet_index', schema['properties'])
        self.assertIn('max_rows', schema['properties'])
        self.assertIn('include_formulas', schema['properties'])
    
    def test_max_rows_limit(self):
        """Test max_rows parameter"""
        schema = self.tool.get_input_schema()
        max_rows_prop = schema['properties']['max_rows']
        self.assertEqual(max_rows_prop['minimum'], 1)
        self.assertEqual(max_rows_prop['maximum'], 10000)
        self.assertEqual(max_rows_prop['default'], 100)


class TestMsDocSearchWordTool(TestMsDocBaseSetup):
    """Test cases for msdoc_search_word tool"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = MsDocSearchWordTool(self.config)
    
    @patch('tools.impl.msdoc_tools_tool_refactored.Document')
    def test_search_word_document(self, mock_document):
        """Test searching in Word document"""
        mock_doc = MagicMock()
        mock_p1 = MagicMock()
        mock_p1.text = "This contains the search term"
        mock_p2 = MagicMock()
        mock_p2.text = "This does not contain it"
        mock_p3 = MagicMock()
        mock_p3.text = "Another SEARCH term here"
        mock_doc.paragraphs = [mock_p1, mock_p2, mock_p3]
        mock_doc.tables = []
        
        mock_document.return_value = mock_doc
        
        result = self.tool.execute({
            'filename': 'test_document.docx',
            'search_term': 'search'
        })
        
        self.assertIn('filename', result)
        self.assertIn('search_term', result)
        self.assertIn('matches', result)
        self.assertIn('match_count', result)
        self.assertEqual(result['match_count'], 2)
        self.assertEqual(len(result['matches']), 2)
    
    @patch('tools.impl.msdoc_tools_tool_refactored.Document')
    def test_case_insensitive_search(self, mock_document):
        """Test case-insensitive search"""
        mock_doc = MagicMock()
        mock_p1 = MagicMock()
        mock_p1.text = "UPPERCASE search term"
        mock_p2 = MagicMock()
        mock_p2.text = "lowercase search term"
        mock_doc.paragraphs = [mock_p1, mock_p2]
        mock_doc.tables = []
        
        mock_document.return_value = mock_doc
        
        result = self.tool.execute({
            'filename': 'test_document.docx',
            'search_term': 'Search'
        })
        
        self.assertEqual(result['match_count'], 2)
    
    def test_input_schema_required_fields(self):
        """Test required input fields"""
        schema = self.tool.get_input_schema()
        self.assertIn('filename', schema['required'])
        self.assertIn('search_term', schema['required'])


class TestMsDocSearchExcelTool(TestMsDocBaseSetup):
    """Test cases for msdoc_search_excel tool"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = MsDocSearchExcelTool(self.config)
    
    @patch('tools.impl.msdoc_tools_tool_refactored.load_workbook')
    def test_search_excel_document(self, mock_load_workbook):
        """Test searching in Excel document"""
        mock_wb = MagicMock()
        mock_sheet = MagicMock()
        mock_sheet.title = "Sheet1"
        mock_sheet.iter_rows.return_value = [
            ('Header1', 'Header2', 'Header3'),
            ('Apple', 'Banana', 'Cherry'),
            ('Dog', 'Cat', 'Bird'),
            ('Apple Pie', 'Orange', 'Grape')
        ]
        mock_wb.active = mock_sheet
        mock_load_workbook.return_value = mock_wb
        
        result = self.tool.execute({
            'filename': 'test_spreadsheet.xlsx',
            'search_term': 'apple'
        })
        
        self.assertIn('filename', result)
        self.assertIn('sheet_name', result)
        self.assertIn('search_term', result)
        self.assertIn('matches', result)
        self.assertIn('match_count', result)
        self.assertEqual(result['match_count'], 2)
    
    @patch('tools.impl.msdoc_tools_tool_refactored.load_workbook')
    def test_search_with_sheet_name(self, mock_load_workbook):
        """Test search with specific sheet name"""
        mock_wb = MagicMock()
        mock_sheet = MagicMock()
        mock_sheet.title = "CustomSheet"
        mock_sheet.iter_rows.return_value = [
            ('Value1', 'Value2'),
            ('Test', 'Data')
        ]
        mock_wb.__getitem__ = lambda self, key: mock_sheet
        mock_load_workbook.return_value = mock_wb
        
        result = self.tool.execute({
            'filename': 'test_spreadsheet.xlsx',
            'search_term': 'test',
            'sheet_name': 'CustomSheet'
        })
        
        self.assertEqual(result['sheet_name'], 'CustomSheet')
    
    def test_match_structure(self):
        """Test match data structure"""
        schema = self.tool.get_output_schema()
        match_schema = schema['properties']['matches']['items']
        self.assertIn('row_index', match_schema['properties'])
        self.assertIn('column_index', match_schema['properties'])
        self.assertIn('value', match_schema['properties'])


class TestMsDocGetWordMetadataTool(TestMsDocBaseSetup):
    """Test cases for msdoc_get_word_metadata tool"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = MsDocGetWordMetadataTool(self.config)
    
    @patch('tools.impl.msdoc_tools_tool_refactored.Document')
    def test_get_word_metadata(self, mock_document):
        """Test extracting Word metadata"""
        mock_doc = MagicMock()
        mock_props = MagicMock()
        mock_props.author = "John Doe"
        mock_props.title = "Test Document"
        mock_props.subject = "Testing"
        mock_props.created = datetime(2025, 1, 1, 12, 0, 0)
        mock_props.modified = datetime(2025, 1, 2, 14, 30, 0)
        mock_doc.core_properties = mock_props
        
        mock_document.return_value = mock_doc
        
        result = self.tool.execute({
            'filename': 'test_document.docx'
        })
        
        self.assertIn('filename', result)
        self.assertIn('metadata', result)
        self.assertEqual(result['metadata']['author'], 'John Doe')
        self.assertEqual(result['metadata']['title'], 'Test Document')
        self.assertEqual(result['metadata']['subject'], 'Testing')
    
    @patch('tools.impl.msdoc_tools_tool_refactored.Document')
    def test_metadata_with_empty_fields(self, mock_document):
        """Test metadata with empty fields"""
        mock_doc = MagicMock()
        mock_props = MagicMock()
        mock_props.author = None
        mock_props.title = None
        mock_props.subject = None
        mock_props.created = None
        mock_props.modified = None
        mock_doc.core_properties = mock_props
        
        mock_document.return_value = mock_doc
        
        result = self.tool.execute({
            'filename': 'test_document.docx'
        })
        
        self.assertEqual(result['metadata']['author'], '')
        self.assertEqual(result['metadata']['title'], '')
        self.assertEqual(result['metadata']['subject'], '')
    
    def test_metadata_schema(self):
        """Test metadata schema structure"""
        schema = self.tool.get_output_schema()
        metadata_props = schema['properties']['metadata']['properties']
        self.assertIn('author', metadata_props)
        self.assertIn('title', metadata_props)
        self.assertIn('subject', metadata_props)
        self.assertIn('created', metadata_props)
        self.assertIn('modified', metadata_props)


class TestMsDocGetExcelMetadataTool(TestMsDocBaseSetup):
    """Test cases for msdoc_get_excel_metadata tool"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = MsDocGetExcelMetadataTool(self.config)
    
    @patch('tools.impl.msdoc_tools_tool_refactored.load_workbook')
    def test_get_excel_metadata(self, mock_load_workbook):
        """Test extracting Excel metadata"""
        mock_wb = MagicMock()
        mock_props = MagicMock()
        mock_props.creator = "Jane Smith"
        mock_props.title = "Test Workbook"
        mock_props.subject = "Data Analysis"
        mock_props.created = datetime(2025, 1, 1, 10, 0, 0)
        mock_props.modified = datetime(2025, 1, 3, 16, 45, 0)
        mock_wb.properties = mock_props
        
        mock_load_workbook.return_value = mock_wb
        
        result = self.tool.execute({
            'filename': 'test_spreadsheet.xlsx'
        })
        
        self.assertIn('filename', result)
        self.assertIn('metadata', result)
        self.assertEqual(result['metadata']['creator'], 'Jane Smith')
        self.assertEqual(result['metadata']['title'], 'Test Workbook')
    
    def test_output_schema(self):
        """Test output schema"""
        schema = self.tool.get_output_schema()
        metadata_props = schema['properties']['metadata']['properties']
        self.assertIn('creator', metadata_props)
        self.assertIn('title', metadata_props)
        self.assertIn('subject', metadata_props)
        self.assertIn('created', metadata_props)
        self.assertIn('modified', metadata_props)


class TestMsDocExtractTextTool(TestMsDocBaseSetup):
    """Test cases for msdoc_extract_text tool"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = MsDocExtractTextTool(self.config)
    
    @patch('tools.impl.msdoc_tools_tool_refactored.Document')
    def test_extract_text_from_word(self, mock_document):
        """Test extracting text from Word document"""
        mock_doc = MagicMock()
        mock_p1 = MagicMock()
        mock_p1.text = "First paragraph"
        mock_p2 = MagicMock()
        mock_p2.text = "Second paragraph"
        mock_doc.paragraphs = [mock_p1, mock_p2]
        mock_doc.tables = []
        
        mock_document.return_value = mock_doc
        
        result = self.tool.execute({
            'filename': 'test_document.docx'
        })
        
        self.assertIn('filename', result)
        self.assertIn('text', result)
        self.assertIn('character_count', result)
        self.assertIn('First paragraph', result['text'])
        self.assertIn('Second paragraph', result['text'])
        self.assertGreater(result['character_count'], 0)
    
    @patch('tools.impl.msdoc_tools_tool_refactored.load_workbook')
    def test_extract_text_from_excel(self, mock_load_workbook):
        """Test extracting text from Excel document"""
        mock_wb = MagicMock()
        mock_sheet = MagicMock()
        mock_sheet.iter_rows.return_value = [
            ('Col1', 'Col2', 'Col3'),
            ('A1', 'A2', 'A3'),
            ('B1', 'B2', 'B3')
        ]
        mock_wb.active = mock_sheet
        mock_load_workbook.return_value = mock_wb
        
        result = self.tool.execute({
            'filename': 'test_spreadsheet.xlsx'
        })
        
        self.assertIn('text', result)
        self.assertIn('character_count', result)
        self.assertGreater(result['character_count'], 0)
    
    def test_unsupported_file_type(self):
        """Test error on unsupported file type"""
        # Create a text file
        txt_file = os.path.join(self.test_dir, 'test.txt')
        with open(txt_file, 'w') as f:
            f.write('test')
        
        with self.assertRaises(ValueError) as context:
            self.tool.execute({'filename': 'test.txt'})
        self.assertIn('Unsupported file type', str(context.exception))


class TestMsDocGetExcelSheetsTool(TestMsDocBaseSetup):
    """Test cases for msdoc_get_excel_sheets tool"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = MsDocGetExcelSheetsTool(self.config)
    
    @patch('tools.impl.msdoc_tools_tool_refactored.load_workbook')
    def test_get_excel_sheets(self, mock_load_workbook):
        """Test getting list of Excel sheets"""
        mock_wb = MagicMock()
        mock_sheet1 = MagicMock()
        mock_sheet1.title = "Sheet1"
        mock_sheet2 = MagicMock()
        mock_sheet2.title = "Sheet2"
        mock_sheet3 = MagicMock()
        mock_sheet3.title = "Data"
        
        mock_wb.worksheets = [mock_sheet1, mock_sheet2, mock_sheet3]
        mock_load_workbook.return_value = mock_wb
        
        result = self.tool.execute({
            'filename': 'test_spreadsheet.xlsx'
        })
        
        self.assertIn('filename', result)
        self.assertIn('sheets', result)
        self.assertIn('count', result)
        self.assertEqual(result['count'], 3)
        self.assertEqual(len(result['sheets']), 3)
        self.assertEqual(result['sheets'][0]['name'], 'Sheet1')
        self.assertEqual(result['sheets'][1]['name'], 'Sheet2')
        self.assertEqual(result['sheets'][2]['name'], 'Data')
    
    def test_sheet_structure(self):
        """Test sheet data structure"""
        schema = self.tool.get_output_schema()
        sheet_schema = schema['properties']['sheets']['items']['properties']
        self.assertIn('index', sheet_schema)
        self.assertIn('name', sheet_schema)


class TestMsDocReadExcelSheetTool(TestMsDocBaseSetup):
    """Test cases for msdoc_read_excel_sheet tool"""
    
    def setUp(self):
        """Set up test tool"""
        self.tool = MsDocReadExcelSheetTool(self.config)
    
    @patch('tools.impl.msdoc_tools_tool_refactored.load_workbook')
    def test_read_sheet_by_name(self, mock_load_workbook):
        """Test reading sheet by name"""
        mock_wb = MagicMock()
        mock_sheet = MagicMock()
        mock_sheet.title = "CustomSheet"
        mock_sheet.iter_rows.return_value = [
            ('Header1', 'Header2'),
            ('Value1', 'Value2')
        ]
        mock_wb.__getitem__ = lambda self, key: mock_sheet
        mock_load_workbook.return_value = mock_wb
        
        result = self.tool.execute({
            'filename': 'test_spreadsheet.xlsx',
            'sheet_name': 'CustomSheet',
            'max_rows': 100
        })
        
        self.assertIn('sheet_name', result)
        self.assertIn('data', result)
        self.assertEqual(result['sheet_name'], 'CustomSheet')
    
    @patch('tools.impl.msdoc_tools_tool_refactored.load_workbook')
    def test_read_sheet_by_index(self, mock_load_workbook):
        """Test reading sheet by index"""
        mock_wb = MagicMock()
        mock_sheet = MagicMock()
        mock_sheet.title = "Sheet2"
        mock_sheet.iter_rows.return_value = [
            ('Data1', 'Data2'),
            ('Row1', 'Row2')
        ]
        mock_wb.worksheets = [MagicMock(), mock_sheet]
        mock_load_workbook.return_value = mock_wb
        
        result = self.tool.execute({
            'filename': 'test_spreadsheet.xlsx',
            'sheet_index': 1
        })
        
        self.assertEqual(result['sheet_name'], 'Sheet2')
    
    def test_input_schema_oneof(self):
        """Test input schema oneOf constraint"""
        schema = self.tool.get_input_schema()
        self.assertIn('oneOf', schema)
        self.assertEqual(len(schema['oneOf']), 2)


class TestMsDocToolRegistry(unittest.TestCase):
    """Test cases for tool registry"""
    
    def test_registry_completeness(self):
        """Test that all tools are registered"""
        expected_tools = [
            'msdoc_list_files',
            'msdoc_read_word',
            'msdoc_read_excel',
            'msdoc_search_word',
            'msdoc_search_excel',
            'msdoc_get_word_metadata',
            'msdoc_get_excel_metadata',
            'msdoc_extract_text',
            'msdoc_get_excel_sheets',
            'msdoc_read_excel_sheet'
        ]
        
        for tool_name in expected_tools:
            self.assertIn(tool_name, MSDOC_TOOLS)
    
    def test_registry_instantiation(self):
        """Test that all registered tools can be instantiated"""
        config = {'docs_directory': tempfile.mkdtemp()}
        
        try:
            for tool_name, tool_class in MSDOC_TOOLS.items():
                tool = tool_class(config)
                self.assertIsNotNone(tool)
                self.assertTrue(hasattr(tool, 'execute'))
                self.assertTrue(hasattr(tool, 'get_input_schema'))
                self.assertTrue(hasattr(tool, 'get_output_schema'))
        finally:
            if os.path.exists(config['docs_directory']):
                shutil.rmtree(config['docs_directory'])


class TestErrorHandling(TestMsDocBaseSetup):
    """Test cases for error handling"""
    
    def test_missing_library_error_word(self):
        """Test ImportError for missing python-docx"""
        tool = MsDocReadWordTool(self.config)
        
        with patch('tools.impl.msdoc_tools_tool_refactored.Document',
                   side_effect=ImportError("No module named 'docx'")):
            with self.assertRaises(ValueError) as context:
                tool.execute({'filename': 'test_document.docx'})
            self.assertIn('python-docx', str(context.exception).lower())
    
    def test_missing_library_error_excel(self):
        """Test ImportError for missing openpyxl"""
        tool = MsDocReadExcelTool(self.config)
        
        with patch('tools.impl.msdoc_tools_tool_refactored.load_workbook',
                   side_effect=ImportError("No module named 'openpyxl'")):
            with self.assertRaises(ValueError) as context:
                tool.execute({'filename': 'test_spreadsheet.xlsx'})
            self.assertIn('openpyxl', str(context.exception).lower())
    
    def test_file_not_found_error(self):
        """Test ValueError for non-existent files"""
        tool = MsDocReadWordTool(self.config)
        
        with self.assertRaises(ValueError) as context:
            tool.execute({'filename': 'does_not_exist.docx'})
        self.assertIn('File not found', str(context.exception))
    
    def test_corrupt_file_handling(self):
        """Test handling of corrupt files"""
        tool = MsDocReadWordTool(self.config)
        
        with patch('tools.impl.msdoc_tools_tool_refactored.Document',
                   side_effect=Exception("Corrupt file")):
            with self.assertRaises(ValueError) as context:
                tool.execute({'filename': 'test_document.docx'})
            self.assertIn('Failed to read', str(context.exception))


class TestSchemaValidation(TestMsDocBaseSetup):
    """Test cases for schema validation"""
    
    def test_all_tools_have_schemas(self):
        """Test that all tools have valid schemas"""
        for tool_name, tool_class in MSDOC_TOOLS.items():
            tool = tool_class(self.config)
            
            # Test input schema
            input_schema = tool.get_input_schema()
            self.assertIsInstance(input_schema, dict)
            self.assertIn('type', input_schema)
            self.assertIn('properties', input_schema)
            
            # Test output schema
            output_schema = tool.get_output_schema()
            self.assertIsInstance(output_schema, dict)
            self.assertIn('type', output_schema)
            self.assertIn('properties', output_schema)
    
    def test_schema_property_types(self):
        """Test schema property types are valid"""
        valid_types = ['string', 'integer', 'boolean', 'array', 'object']
        
        for tool_name, tool_class in MSDOC_TOOLS.items():
            tool = tool_class(self.config)
            schema = tool.get_input_schema()
            
            for prop_name, prop_schema in schema['properties'].items():
                if 'type' in prop_schema:
                    self.assertIn(prop_schema['type'], valid_types,
                                f"Invalid type in {tool_name}.{prop_name}")


class TestPerformanceAndLimits(TestMsDocBaseSetup):
    """Test cases for performance and limits"""
    
    def test_max_rows_limit_respected(self):
        """Test that max_rows limit is respected"""
        tool = MsDocReadExcelTool(self.config)
        schema = tool.get_input_schema()
        
        max_rows_prop = schema['properties']['max_rows']
        self.assertEqual(max_rows_prop['maximum'], 10000)
        self.assertEqual(max_rows_prop['minimum'], 1)
    
    @patch('tools.impl.msdoc_tools_tool_refactored.load_workbook')
    def test_large_file_row_limiting(self, mock_load_workbook):
        """Test row limiting for large files"""
        # Create mock with many rows
        mock_wb = MagicMock()
        mock_sheet = MagicMock()
        mock_sheet.title = "Sheet1"
        
        # Generate 1000 rows
        mock_rows = [(f'R{i}C1', f'R{i}C2') for i in range(1000)]
        mock_sheet.iter_rows.return_value = mock_rows
        mock_wb.active = mock_sheet
        mock_load_workbook.return_value = mock_wb
        
        tool = MsDocReadExcelTool(self.config)
        
        # Request only 50 rows
        result = tool.execute({
            'filename': 'test_spreadsheet.xlsx',
            'max_rows': 50
        })
        
        # Should get only 50 rows
        self.assertLessEqual(result['row_count'], 50)


def suite():
    """Create test suite"""
    test_suite = unittest.TestSuite()
    
    # Add all test classes
    test_classes = [
        TestMsDocListFilesTool,
        TestMsDocReadWordTool,
        TestMsDocReadExcelTool,
        TestMsDocSearchWordTool,
        TestMsDocSearchExcelTool,
        TestMsDocGetWordMetadataTool,
        TestMsDocGetExcelMetadataTool,
        TestMsDocExtractTextTool,
        TestMsDocGetExcelSheetsTool,
        TestMsDocReadExcelSheetTool,
        TestMsDocToolRegistry,
        TestErrorHandling,
        TestSchemaValidation,
        TestPerformanceAndLimits
    ]
    
    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        test_suite.addTests(tests)
    
    return test_suite


if __name__ == '__main__':
    # Run tests with verbose output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite())
    
    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Tests Run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    print(f"Success Rate: {(result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100:.2f}%")
    print("=" * 70)
    
    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
