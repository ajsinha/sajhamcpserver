#!/usr/bin/env python3
"""
SAJHA MCP Server - FBI Crime Data Tools Client v2.2.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Example client for FBI Crime Data tools:
- fbi_get_national_statistics: National crime stats
- fbi_get_state_statistics: State-level stats
- fbi_get_agency_statistics: Agency-level stats
- fbi_get_crime_trend: Crime trends over time
- fbi_get_offense_data: Offense-specific data
- fbi_search_agencies: Search law enforcement agencies
- fbi_get_agency_details: Agency details
- fbi_compare_states: Compare crime across states
- fbi_get_participation_rate: Agency participation rates

Usage:
    export SAJHA_API_KEY="sja_your_key_here"
    python -m sajha.examples.fbi_client
"""

from .base_client import SajhaClient, SajhaAPIError, pretty_print, run_example


class FBIClient(SajhaClient):
    """Client for FBI Crime Data tools."""
    
    def get_national_statistics(self, year: int = None, offense: str = None) -> dict:
        """
        Get national crime statistics.
        
        Args:
            year: Specific year
            offense: Offense type filter
        """
        args = {}
        if year:
            args['year'] = year
        if offense:
            args['offense'] = offense
        return self.execute_tool('fbi_get_national_statistics', args)
    
    def get_state_statistics(self, 
                             state: str,
                             year: int = None,
                             offense: str = None) -> dict:
        """
        Get state-level crime statistics.
        
        Args:
            state: State abbreviation (e.g., 'CA', 'NY')
            year: Specific year
            offense: Offense type
        """
        args = {'state': state}
        if year:
            args['year'] = year
        if offense:
            args['offense'] = offense
        return self.execute_tool('fbi_get_state_statistics', args)
    
    def get_agency_statistics(self,
                              ori: str,
                              year: int = None) -> dict:
        """
        Get agency-level crime statistics.
        
        Args:
            ori: Agency ORI code
            year: Specific year
        """
        args = {'ori': ori}
        if year:
            args['year'] = year
        return self.execute_tool('fbi_get_agency_statistics', args)
    
    def get_crime_trend(self,
                        offense: str,
                        start_year: int = None,
                        end_year: int = None,
                        state: str = None) -> dict:
        """
        Get crime trend over time.
        
        Args:
            offense: Offense type
            start_year: Start year
            end_year: End year
            state: State filter
        """
        args = {'offense': offense}
        if start_year:
            args['start_year'] = start_year
        if end_year:
            args['end_year'] = end_year
        if state:
            args['state'] = state
        return self.execute_tool('fbi_get_crime_trend', args)
    
    def get_offense_data(self,
                         offense: str,
                         year: int = None,
                         state: str = None) -> dict:
        """
        Get offense-specific data.
        
        Args:
            offense: Offense type
            year: Specific year
            state: State filter
        """
        args = {'offense': offense}
        if year:
            args['year'] = year
        if state:
            args['state'] = state
        return self.execute_tool('fbi_get_offense_data', args)
    
    def search_agencies(self,
                        query: str = None,
                        state: str = None,
                        agency_type: str = None,
                        limit: int = 20) -> dict:
        """
        Search law enforcement agencies.
        
        Args:
            query: Search term
            state: State filter
            agency_type: Type filter
            limit: Maximum results
        """
        args = {'limit': limit}
        if query:
            args['query'] = query
        if state:
            args['state'] = state
        if agency_type:
            args['agency_type'] = agency_type
        return self.execute_tool('fbi_search_agencies', args)
    
    def get_agency_details(self, ori: str) -> dict:
        """
        Get detailed agency information.
        
        Args:
            ori: Agency ORI code
        """
        return self.execute_tool('fbi_get_agency_details', {'ori': ori})
    
    def compare_states(self,
                       states: list,
                       offense: str = None,
                       year: int = None) -> dict:
        """
        Compare crime statistics across states.
        
        Args:
            states: List of state abbreviations
            offense: Offense type
            year: Specific year
        """
        args = {'states': states}
        if offense:
            args['offense'] = offense
        if year:
            args['year'] = year
        return self.execute_tool('fbi_compare_states', args)
    
    def get_participation_rate(self, year: int = None, state: str = None) -> dict:
        """
        Get agency participation rates in crime reporting.
        
        Args:
            year: Specific year
            state: State filter
        """
        args = {}
        if year:
            args['year'] = year
        if state:
            args['state'] = state
        return self.execute_tool('fbi_get_participation_rate', args)


@run_example
def example_national_stats():
    """Example: Get national crime statistics"""
    client = FBIClient()
    
    print("\n🇺🇸 Getting national crime statistics...")
    stats = client.get_national_statistics()
    pretty_print(stats, "National Crime Statistics")


@run_example
def example_state_stats():
    """Example: Get state-level statistics"""
    client = FBIClient()
    
    state = 'CA'
    print(f"\n📊 Getting {state} crime statistics...")
    stats = client.get_state_statistics(state)
    pretty_print(stats, f"{state} Crime Statistics")


@run_example
def example_crime_trend():
    """Example: Get crime trend"""
    client = FBIClient()
    
    print("\n📈 Getting violent crime trend...")
    trend = client.get_crime_trend(
        offense='violent-crime',
        start_year=2015,
        end_year=2022
    )
    pretty_print(trend, "Violent Crime Trend")


@run_example
def example_search_agencies():
    """Example: Search law enforcement agencies"""
    client = FBIClient()
    
    print("\n🔍 Searching for agencies in California...")
    agencies = client.search_agencies(state='CA', limit=10)
    pretty_print(agencies, "California Agencies")


@run_example
def example_compare_states():
    """Example: Compare crime across states"""
    client = FBIClient()
    
    states = ['CA', 'TX', 'NY', 'FL']
    print(f"\n📊 Comparing crime: {', '.join(states)}")
    
    comparison = client.compare_states(states)
    pretty_print(comparison, "State Crime Comparison")


@run_example
def example_crime_dashboard():
    """Example: Crime statistics dashboard"""
    client = FBIClient()
    
    print("\n🚔 Crime Statistics Dashboard")
    print("=" * 50)
    
    # National overview
    print("\n📊 National Overview:")
    try:
        national = client.get_national_statistics()
        print(f"   Total Crimes: {national.get('total', 'N/A')}")
        print(f"   Violent: {national.get('violent', 'N/A')}")
        print(f"   Property: {national.get('property', 'N/A')}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Top states comparison
    print("\n📈 Major States:")
    states = ['CA', 'TX', 'FL', 'NY']
    for state in states:
        try:
            stats = client.get_state_statistics(state)
            print(f"   {state}: {stats.get('total', 'N/A')} crimes")
        except:
            pass


if __name__ == '__main__':
    print("=" * 60)
    print(" SAJHA MCP Server - FBI Crime Data Tools Examples v2.2.0")
    print("=" * 60)
    
    example_national_stats()
    example_state_stats()
    example_crime_trend()
    example_search_agencies()
    example_compare_states()
    example_crime_dashboard()
