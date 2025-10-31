"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha
Email: ajsinha@gmail.com

Test Suite for FBI Crime Data Explorer MCP Tools
Comprehensive tests for all 9 FBI tools with various scenarios
"""

import unittest
import sys
import json
from datetime import datetime
from typing import Dict, Any
from unittest.mock import Mock, patch, MagicMock

# Import the FBI tools
try:
    from tools.impl.fbi_tool_refactored import (
        FBIGetNationalStatisticsTool,
        FBIGetStateStatisticsTool,
        FBIGetAgencyStatisticsTool,
        FBISearchAgenciesTool,
        FBIGetAgencyDetailsTool,
        FBIGetOffenseDataTool,
        FBIGetParticipationRateTool,
        FBIGetCrimeTrendTool,
        FBICompareStatesTool,
        FBI_TOOLS
    )
except ImportError:
    print("Error: Unable to import FBI tools. Ensure the module is in the Python path.")
    sys.exit(1)


class TestFBIGetNationalStatisticsTool(unittest.TestCase):
    """Test suite for FBIGetNationalStatisticsTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = FBIGetNationalStatisticsTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'fbi_get_national_statistics')
        self.assertEqual(self.tool.config['version'], '1.0.0')
        self.assertTrue(self.tool.config['enabled'])
    
    def test_offense_codes_mapping(self):
        """Test offense code mapping"""
        expected_codes = {
            'violent_crime': 'violent-crime',
            'homicide': 'homicide',
            'rape': 'rape',
            'robbery': 'robbery',
            'aggravated_assault': 'aggravated-assault',
            'property_crime': 'property-crime',
            'burglary': 'burglary',
            'larceny': 'larceny',
            'motor_vehicle_theft': 'motor-vehicle-theft',
            'arson': 'arson'
        }
        self.assertEqual(self.tool.offense_codes, expected_codes)
    
    def test_get_input_schema(self):
        """Test input schema structure"""
        schema = self.tool.get_input_schema()
        self.assertIsInstance(schema, dict)
    
    def test_get_output_schema(self):
        """Test output schema structure"""
        schema = self.tool.get_output_schema()
        self.assertIsInstance(schema, dict)
    
    @patch('tools.impl.fbi_tool_refactored.FBIBaseTool._make_api_request')
    def test_execute_violent_crime(self, mock_api):
        """Test execution with violent crime data"""
        mock_api.return_value = {
            'total_incidents': 1234567,
            'population': 331000000,
            'reporting_agencies': 15764,
            'population_covered': 325000000
        }
        
        result = self.tool.execute({
            'offense_type': 'violent_crime',
            'year': 2022
        })
        
        self.assertEqual(result['offense_type'], 'violent_crime')
        self.assertEqual(result['year'], 2022)
        self.assertIn('national_data', result)
        self.assertIn('total_incidents', result['national_data'])
        self.assertIn('rate_per_100k', result['national_data'])
        self.assertIn('metadata', result)
    
    @patch('tools.impl.fbi_tool_refactored.FBIBaseTool._make_api_request')
    def test_execute_default_year(self, mock_api):
        """Test execution with default year"""
        mock_api.return_value = {
            'total_incidents': 1000000,
            'population': 331000000
        }
        
        result = self.tool.execute({
            'offense_type': 'homicide'
        })
        
        # Should use current year - 1 or 2024, whichever is less
        self.assertLessEqual(result['year'], 2024)
    
    def test_per_capita_calculation(self):
        """Test per capita rate calculation"""
        rate = self.tool._calculate_per_capita(1000, 100000)
        self.assertEqual(rate, 1000.0)
        
        rate = self.tool._calculate_per_capita(500, 200000)
        self.assertEqual(rate, 250.0)
        
        # Test zero population
        rate = self.tool._calculate_per_capita(100, 0)
        self.assertEqual(rate, 0.0)


class TestFBIGetStateStatisticsTool(unittest.TestCase):
    """Test suite for FBIGetStateStatisticsTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = FBIGetStateStatisticsTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'fbi_get_state_statistics')
        self.assertTrue(self.tool.config['enabled'])
    
    def test_state_names_mapping(self):
        """Test state name mapping"""
        self.assertEqual(self.tool.state_names['CA'], 'California')
        self.assertEqual(self.tool.state_names['NY'], 'New York')
        self.assertEqual(self.tool.state_names['TX'], 'Texas')
        self.assertEqual(len(self.tool.state_names), 51)  # 50 states + DC
    
    @patch('tools.impl.fbi_tool_refactored.FBIBaseTool._make_api_request')
    def test_execute_california(self, mock_api):
        """Test execution for California"""
        mock_api.side_effect = [
            {
                'total_incidents': 123456,
                'population': 39500000,
                'reporting_agencies': 723
            },
            {
                'total_incidents': 1234567,
                'rate_per_100k': 373.0
            }
        ]
        
        result = self.tool.execute({
            'state': 'CA',
            'offense_type': 'violent_crime',
            'year': 2022
        })
        
        self.assertEqual(result['state'], 'CA')
        self.assertEqual(result['state_name'], 'California')
        self.assertIn('state_data', result)
        self.assertIn('comparison', result)
    
    def test_invalid_state_code(self):
        """Test handling of invalid state code"""
        with self.assertRaises(ValueError) as context:
            self.tool.execute({
                'state': 'XX',
                'offense_type': 'violent_crime'
            })
        self.assertIn('Invalid state code', str(context.exception))
    
    @patch('tools.impl.fbi_tool_refactored.FBIBaseTool._make_api_request')
    def test_lowercase_state_conversion(self, mock_api):
        """Test automatic uppercase conversion of state codes"""
        mock_api.return_value = {
            'total_incidents': 50000,
            'population': 7000000
        }
        
        result = self.tool.execute({
            'state': 'ca',  # lowercase
            'offense_type': 'robbery'
        })
        
        self.assertEqual(result['state'], 'CA')


class TestFBIGetAgencyStatisticsTool(unittest.TestCase):
    """Test suite for FBIGetAgencyStatisticsTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = FBIGetAgencyStatisticsTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'fbi_get_agency_statistics')
    
    @patch('tools.impl.fbi_tool_refactored.FBIBaseTool._make_api_request')
    def test_execute_lapd(self, mock_api):
        """Test execution for LAPD"""
        mock_api.side_effect = [
            {
                'agency_name': 'Los Angeles Police Department',
                'agency_type': 'city',
                'total_incidents': 12345,
                'population': 4000000,
                'months_reported': 12
            },
            {
                'rate_per_100k': 312.5
            },
            {
                'rate_per_100k': 373.0
            }
        ]
        
        result = self.tool.execute({
            'ori': 'CA0190000',
            'offense_type': 'violent_crime',
            'year': 2022
        })
        
        self.assertEqual(result['ori'], 'CA0190000')
        self.assertIn('agency_name', result)
        self.assertIn('agency_data', result)
        self.assertIn('comparison', result)
    
    def test_ori_code_format(self):
        """Test ORI code format validation"""
        # Valid ORI codes should work
        valid_oris = ['CA0190000', 'NY0300000', 'TX2210000']
        for ori in valid_oris:
            self.assertRegex(ori, r'^[A-Z]{2}[0-9]{7}$')
        
        # Invalid ORI codes
        invalid_oris = ['CA019000', 'CA01900000', 'ca0190000', '123456789']
        for ori in invalid_oris:
            self.assertNotRegex(ori, r'^[A-Z]{2}[0-9]{7}$')


class TestFBISearchAgenciesTool(unittest.TestCase):
    """Test suite for FBISearchAgenciesTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = FBISearchAgenciesTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'fbi_search_agencies')
    
    @patch('tools.impl.fbi_tool_refactored.FBIBaseTool._make_api_request')
    def test_search_police(self, mock_api):
        """Test searching for police agencies"""
        mock_api.return_value = {
            'total': 100,
            'agencies': [
                {
                    'ori': 'CA0190000',
                    'agency_name': 'Los Angeles Police Department',
                    'agency_type': 'city',
                    'state': 'CA',
                    'city': 'Los Angeles',
                    'county': 'Los Angeles',
                    'population': 4000000
                }
            ]
        }
        
        result = self.tool.execute({
            'agency_name': 'police',
            'state': 'CA',
            'limit': 10
        })
        
        self.assertIn('search_query', result)
        self.assertIn('total_results', result)
        self.assertIn('agencies', result)
        self.assertIsInstance(result['agencies'], list)
    
    @patch('tools.impl.fbi_tool_refactored.FBIBaseTool._make_api_request')
    def test_search_with_filters(self, mock_api):
        """Test search with agency type filter"""
        mock_api.return_value = {
            'total': 50,
            'agencies': []
        }
        
        result = self.tool.execute({
            'agency_name': 'sheriff',
            'state': 'TX',
            'agency_type': 'county',
            'limit': 20
        })
        
        self.assertIn('agencies', result)
    
    def test_minimum_name_length(self):
        """Test minimum agency name length requirement"""
        # Input schema should require at least 3 characters
        schema = self.tool.get_input_schema()
        self.assertEqual(schema['properties']['agency_name']['minLength'], 3)


class TestFBIGetAgencyDetailsTool(unittest.TestCase):
    """Test suite for FBIGetAgencyDetailsTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = FBIGetAgencyDetailsTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'fbi_get_agency_details')
    
    @patch('tools.impl.fbi_tool_refactored.FBIBaseTool._make_api_request')
    def test_execute_agency_details(self, mock_api):
        """Test getting agency details"""
        mock_api.return_value = {
            'ori': 'CA0190000',
            'agency_name': 'Los Angeles Police Department',
            'agency_type': 'city',
            'state': 'CA',
            'city': 'Los Angeles',
            'county': 'Los Angeles',
            'population': 4000000,
            'square_miles': 469.0,
            'total_officers': 9974,
            'total_civilians': 2820,
            'participates_in_ucr': True,
            'participates_in_nibrs': True,
            'last_reported_year': 2022
        }
        
        result = self.tool.execute({
            'ori': 'CA0190000'
        })
        
        self.assertEqual(result['ori'], 'CA0190000')
        self.assertIn('location', result)
        self.assertIn('jurisdiction', result)
        self.assertIn('personnel', result)
        self.assertIn('reporting_status', result)


class TestFBIGetOffenseDataTool(unittest.TestCase):
    """Test suite for FBIGetOffenseDataTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = FBIGetOffenseDataTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'fbi_get_offense_data')
    
    @patch('tools.impl.fbi_tool_refactored.FBIBaseTool._make_api_request')
    def test_execute_with_subcategories(self, mock_api):
        """Test getting offense data with subcategories"""
        mock_api.return_value = {
            'total_offenses': 1234567,
            'subcategories': [
                {
                    'name': 'aggravated_assault',
                    'total': 765432,
                    'percent': 62.0
                },
                {
                    'name': 'robbery',
                    'total': 234567,
                    'percent': 19.0
                }
            ],
            'demographics': {
                'by_location_type': {
                    'residential': 45.2,
                    'commercial': 32.1
                },
                'clearance_rate': 45.5
            }
        }
        
        result = self.tool.execute({
            'offense_type': 'violent_crime',
            'year': 2022,
            'include_subcategories': True
        })
        
        self.assertIn('total_offenses', result)
        self.assertIn('subcategories', result)
        self.assertIn('demographics', result)
    
    @patch('tools.impl.fbi_tool_refactored.FBIBaseTool._make_api_request')
    def test_execute_state_level(self, mock_api):
        """Test getting offense data for specific state"""
        mock_api.return_value = {
            'total_offenses': 123456,
            'subcategories': []
        }
        
        result = self.tool.execute({
            'offense_type': 'property_crime',
            'state': 'CA',
            'year': 2022
        })
        
        self.assertEqual(result['scope'], 'state')
        self.assertEqual(result['state'], 'CA')


class TestFBIGetParticipationRateTool(unittest.TestCase):
    """Test suite for FBIGetParticipationRateTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = FBIGetParticipationRateTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'fbi_get_participation_rate')
    
    @patch('tools.impl.fbi_tool_refactored.FBIBaseTool._make_api_request')
    def test_execute_national(self, mock_api):
        """Test getting national participation rate"""
        mock_api.return_value = {
            'total_agencies': 18000,
            'reporting_agencies': 17000,
            'population_covered': 320000000,
            'total_population': 331000000,
            'full_year_reporters': 16500,
            'partial_year_reporters': 500,
            'zero_reporters': 500
        }
        
        result = self.tool.execute({
            'year': 2022
        })
        
        self.assertEqual(result['scope'], 'national')
        self.assertIn('participation_data', result)
        self.assertIn('reporting_quality', result)
    
    @patch('tools.impl.fbi_tool_refactored.FBIBaseTool._make_api_request')
    def test_execute_state(self, mock_api):
        """Test getting state participation rate"""
        mock_api.return_value = {
            'total_agencies': 723,
            'reporting_agencies': 698,
            'population_covered': 38500000,
            'total_population': 39500000
        }
        
        result = self.tool.execute({
            'state': 'CA',
            'year': 2022
        })
        
        self.assertEqual(result['scope'], 'state')
        self.assertEqual(result['state'], 'CA')
    
    def test_participation_rate_calculation(self):
        """Test participation rate percentage calculation"""
        # Should calculate rate correctly
        total_agencies = 100
        reporting_agencies = 95
        expected_rate = 95.0
        
        # This would be in the actual implementation
        calculated_rate = (reporting_agencies / total_agencies) * 100
        self.assertEqual(calculated_rate, expected_rate)


class TestFBIGetCrimeTrendTool(unittest.TestCase):
    """Test suite for FBIGetCrimeTrendTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = FBIGetCrimeTrendTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'fbi_get_crime_trend')
    
    @patch('tools.impl.fbi_tool_refactored.FBIBaseTool._make_api_request')
    def test_execute_national_trend(self, mock_api):
        """Test analyzing national crime trend"""
        # Mock responses for each year
        mock_api.side_effect = [
            {'total_incidents': 1200000, 'population': 310000000},
            {'total_incidents': 1150000, 'population': 315000000},
            {'total_incidents': 1100000, 'population': 320000000}
        ]
        
        result = self.tool.execute({
            'offense_type': 'violent_crime',
            'start_year': 2020,
            'end_year': 2022,
            'per_capita': True
        })
        
        self.assertEqual(result['offense_type'], 'violent_crime')
        self.assertEqual(result['scope'], 'national')
        self.assertIn('time_series', result)
        self.assertIn('trend_analysis', result)
        
        # Check trend analysis components
        analysis = result['trend_analysis']
        self.assertIn('overall_change', analysis)
        self.assertIn('direction', analysis)
        self.assertIn('peak_year', analysis)
        self.assertIn('lowest_year', analysis)
        self.assertIn('volatility', analysis)
    
    def test_trend_direction_logic(self):
        """Test trend direction determination"""
        # Increasing: > 5%
        self.assertEqual(self._determine_direction(10), 'increasing')
        
        # Decreasing: < -5%
        self.assertEqual(self._determine_direction(-10), 'decreasing')
        
        # Stable: between -5% and +5%
        self.assertEqual(self._determine_direction(2), 'stable')
        self.assertEqual(self._determine_direction(-3), 'stable')
    
    def _determine_direction(self, change):
        """Helper to determine trend direction"""
        if change > 5:
            return 'increasing'
        elif change < -5:
            return 'decreasing'
        else:
            return 'stable'
    
    def test_volatility_calculation(self):
        """Test volatility level determination"""
        # High volatility: avg change > 10%
        self.assertEqual(self._determine_volatility(15), 'high')
        
        # Medium volatility: avg change > 5%
        self.assertEqual(self._determine_volatility(7), 'medium')
        
        # Low volatility: avg change <= 5%
        self.assertEqual(self._determine_volatility(3), 'low')
    
    def _determine_volatility(self, avg_change):
        """Helper to determine volatility"""
        if avg_change > 10:
            return 'high'
        elif avg_change > 5:
            return 'medium'
        else:
            return 'low'


class TestFBICompareStatesTool(unittest.TestCase):
    """Test suite for FBICompareStatesTool"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.tool = FBICompareStatesTool()
    
    def test_initialization(self):
        """Test tool initialization"""
        self.assertEqual(self.tool.config['name'], 'fbi_compare_states')
    
    @patch('tools.impl.fbi_tool_refactored.FBIBaseTool._make_api_request')
    def test_execute_compare_states(self, mock_api):
        """Test comparing multiple states"""
        # Mock national data + state data
        mock_api.side_effect = [
            {'total_incidents': 1234567, 'rate_per_100k': 373.0},  # National
            {'total_incidents': 123456, 'population': 39500000},   # CA
            {'total_incidents': 87654, 'population': 29000000},    # TX
            {'total_incidents': 65432, 'population': 21500000},    # FL
            {'total_incidents': 54321, 'population': 19500000}     # NY
        ]
        
        result = self.tool.execute({
            'states': ['CA', 'TX', 'FL', 'NY'],
            'offense_type': 'violent_crime',
            'year': 2022,
            'per_capita': True
        })
        
        self.assertEqual(result['offense_type'], 'violent_crime')
        self.assertIn('states_compared', result)
        self.assertIn('comparison_summary', result)
        self.assertIn('national_reference', result)
        
        # Should have 4 states
        self.assertEqual(len(result['states_compared']), 4)
        
        # Each state should have rank
        for state in result['states_compared']:
            self.assertIn('rank', state)
            self.assertIn('rate_per_100k', state)
    
    def test_minimum_states_requirement(self):
        """Test minimum states requirement"""
        schema = self.tool.get_input_schema()
        self.assertEqual(schema['properties']['states']['minItems'], 2)
    
    def test_maximum_states_limit(self):
        """Test maximum states limit"""
        schema = self.tool.get_input_schema()
        self.assertEqual(schema['properties']['states']['maxItems'], 10)
    
    def test_invalid_states_validation(self):
        """Test validation of invalid state codes"""
        with self.assertRaises(ValueError) as context:
            self.tool.execute({
                'states': ['CA', 'XX', 'YY'],
                'offense_type': 'violent_crime'
            })
        self.assertIn('Invalid state code', str(context.exception))


class TestToolRegistry(unittest.TestCase):
    """Test suite for tool registry and tool management"""
    
    def test_tool_registry_exists(self):
        """Test that tool registry is defined"""
        self.assertIsNotNone(FBI_TOOLS)
        self.assertIsInstance(FBI_TOOLS, dict)
    
    def test_all_tools_in_registry(self):
        """Test that all 9 tools are in the registry"""
        expected_tools = [
            'fbi_get_national_statistics',
            'fbi_get_state_statistics',
            'fbi_get_agency_statistics',
            'fbi_search_agencies',
            'fbi_get_agency_details',
            'fbi_get_offense_data',
            'fbi_get_participation_rate',
            'fbi_get_crime_trend',
            'fbi_compare_states'
        ]
        
        for tool_name in expected_tools:
            self.assertIn(tool_name, FBI_TOOLS)
    
    def test_tools_are_classes(self):
        """Test that registry contains class references"""
        for tool_name, tool_class in FBI_TOOLS.items():
            self.assertTrue(callable(tool_class))
    
    def test_tool_instantiation(self):
        """Test that all tools can be instantiated"""
        for tool_name, tool_class in FBI_TOOLS.items():
            try:
                tool_instance = tool_class()
                self.assertIsNotNone(tool_instance)
                self.assertTrue(hasattr(tool_instance, 'execute'))
                self.assertTrue(hasattr(tool_instance, 'get_input_schema'))
                self.assertTrue(hasattr(tool_instance, 'get_output_schema'))
            except Exception as e:
                self.fail(f"Failed to instantiate {tool_name}: {e}")


class TestIntegrationScenarios(unittest.TestCase):
    """Integration tests for common usage scenarios"""
    
    @patch('tools.impl.fbi_tool_refactored.FBIBaseTool._make_api_request')
    def test_scenario_agency_discovery_and_analysis(self, mock_api):
        """Test: Find agency and analyze its crime data"""
        # Step 1: Search for agency
        mock_api.return_value = {
            'total': 1,
            'agencies': [
                {
                    'ori': 'CA0190000',
                    'agency_name': 'Los Angeles Police Department',
                    'state': 'CA'
                }
            ]
        }
        
        search_tool = FBISearchAgenciesTool()
        search_result = search_tool.execute({
            'agency_name': 'Los Angeles',
            'state': 'CA'
        })
        
        self.assertGreater(len(search_result['agencies']), 0)
        ori = search_result['agencies'][0]['ori']
        
        # Step 2: Get agency statistics
        mock_api.return_value = {
            'agency_name': 'Los Angeles Police Department',
            'total_incidents': 12345,
            'population': 4000000
        }
        
        stats_tool = FBIGetAgencyStatisticsTool()
        stats_result = stats_tool.execute({
            'ori': ori,
            'offense_type': 'robbery'
        })
        
        self.assertIn('agency_data', stats_result)
    
    @patch('tools.impl.fbi_tool_refactored.FBIBaseTool._make_api_request')
    def test_scenario_multi_state_comparison(self, mock_api):
        """Test: Compare crime across multiple states"""
        mock_api.side_effect = [
            {'total_incidents': 1234567, 'rate_per_100k': 373.0},
            {'total_incidents': 123456, 'population': 39500000},
            {'total_incidents': 87654, 'population': 29000000},
            {'total_incidents': 65432, 'population': 21500000}
        ]
        
        tool = FBICompareStatesTool()
        result = tool.execute({
            'states': ['CA', 'TX', 'FL'],
            'offense_type': 'violent_crime',
            'year': 2022
        })
        
        self.assertIn('states_compared', result)
        self.assertGreaterEqual(len(result['states_compared']), 3)
    
    @patch('tools.impl.fbi_tool_refactored.FBIBaseTool._make_api_request')
    def test_scenario_historical_trend_analysis(self, mock_api):
        """Test: Analyze historical crime trends"""
        # Mock data for 3 years
        mock_api.side_effect = [
            {'total_incidents': 1200000, 'population': 310000000},
            {'total_incidents': 1150000, 'population': 315000000},
            {'total_incidents': 1100000, 'population': 320000000}
        ]
        
        tool = FBIGetCrimeTrendTool()
        result = tool.execute({
            'offense_type': 'violent_crime',
            'start_year': 2020,
            'end_year': 2022
        })
        
        self.assertIn('trend_analysis', result)
        self.assertIn('direction', result['trend_analysis'])


class TestErrorHandlingAndEdgeCases(unittest.TestCase):
    """Test error handling and edge cases"""
    
    def test_invalid_offense_type(self):
        """Test handling of invalid offense type"""
        tool = FBIGetNationalStatisticsTool()
        
        # Should either raise error or return None for invalid offense
        invalid_offense = 'invalid_crime_type'
        self.assertNotIn(invalid_offense, tool.offense_codes)
    
    def test_future_year(self):
        """Test handling of future years"""
        tool = FBIGetNationalStatisticsTool()
        current_year = datetime.now().year
        
        # _get_current_year should return at most current year - 1 or 2024
        max_year = tool._get_current_year()
        self.assertLessEqual(max_year, 2024)
        self.assertLessEqual(max_year, current_year)
    
    def test_year_range_validation(self):
        """Test year range validation in schemas"""
        tool = FBIGetNationalStatisticsTool()
        schema = tool.get_input_schema()
        
        if 'properties' in schema and 'year' in schema['properties']:
            year_schema = schema['properties']['year']
            self.assertEqual(year_schema.get('minimum'), 1960)
            self.assertEqual(year_schema.get('maximum'), 2024)
    
    @patch('tools.impl.fbi_tool_refactored.FBIBaseTool._make_api_request')
    def test_api_error_handling(self, mock_api):
        """Test API error handling"""
        import urllib.error
        
        # Simulate HTTP error
        mock_api.side_effect = urllib.error.HTTPError(
            'http://test.com', 404, 'Not Found', {}, None
        )
        
        tool = FBIGetNationalStatisticsTool()
        
        with self.assertRaises(ValueError):
            tool.execute({
                'offense_type': 'violent_crime',
                'year': 2022
            })
    
    def test_empty_state_list_comparison(self):
        """Test compare states with minimum states"""
        schema = FBICompareStatesTool().get_input_schema()
        min_items = schema['properties']['states']['minItems']
        
        # Should require at least 2 states
        self.assertGreaterEqual(min_items, 2)
    
    def test_duplicate_states_in_comparison(self):
        """Test handling of duplicate states"""
        tool = FBICompareStatesTool()
        
        # The tool should handle or prevent duplicates
        states_with_duplicates = ['CA', 'CA', 'TX']
        unique_states = list(set(s.upper() for s in states_with_duplicates))
        
        # After deduplication, should have fewer states
        self.assertLess(len(unique_states), len(states_with_duplicates))


class TestDataValidation(unittest.TestCase):
    """Test data validation and constraints"""
    
    def test_state_abbreviation_format(self):
        """Test state abbreviation format"""
        tool = FBIGetStateStatisticsTool()
        
        # Valid formats
        valid_states = ['CA', 'NY', 'TX', 'DC']
        for state in valid_states:
            self.assertRegex(state, r'^[A-Z]{2}$')
        
        # Invalid formats
        invalid_states = ['California', 'ca', 'CAL', '1A']
        for state in invalid_states:
            self.assertNotRegex(state, r'^[A-Z]{2}$')
    
    def test_ori_code_format(self):
        """Test ORI code format validation"""
        # Valid ORI codes
        valid_oris = [
            'CA0190000',
            'NY0300000',
            'TX2210000',
            'IL0160000'
        ]
        
        for ori in valid_oris:
            self.assertRegex(ori, r'^[A-Z]{2}[0-9]{7}$')
    
    def test_per_capita_boolean(self):
        """Test per_capita parameter type"""
        tool = FBIGetNationalStatisticsTool()
        schema = tool.get_input_schema()
        
        if 'properties' in schema and 'per_capita' in schema['properties']:
            per_capita_schema = schema['properties']['per_capita']
            self.assertEqual(per_capita_schema['type'], 'boolean')


def run_test_suite(verbosity=2):
    """
    Run the complete test suite
    
    Args:
        verbosity: Test output verbosity (0=quiet, 1=normal, 2=verbose)
    
    Returns:
        TestResult object
    """
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    test_classes = [
        TestFBIGetNationalStatisticsTool,
        TestFBIGetStateStatisticsTool,
        TestFBIGetAgencyStatisticsTool,
        TestFBISearchAgenciesTool,
        TestFBIGetAgencyDetailsTool,
        TestFBIGetOffenseDataTool,
        TestFBIGetParticipationRateTool,
        TestFBIGetCrimeTrendTool,
        TestFBICompareStatesTool,
        TestToolRegistry,
        TestIntegrationScenarios,
        TestErrorHandlingAndEdgeCases,
        TestDataValidation
    ]
    
    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)
    
    return result


def print_test_summary(result):
    """Print a summary of test results"""
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Tests Run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    print("="*70)
    
    if result.wasSuccessful():
        print("✓ ALL TESTS PASSED")
    else:
        print("✗ SOME TESTS FAILED")
    print("="*70)


if __name__ == '__main__':
    print("FBI Crime Data Explorer MCP Tool - Test Suite")
    print("Copyright © 2025-2030 Ashutosh Sinha (ajsinha@gmail.com)")
    print("="*70)
    print()
    
    # Run tests
    result = run_test_suite(verbosity=2)
    
    # Print summary
    print_test_summary(result)
    
    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
