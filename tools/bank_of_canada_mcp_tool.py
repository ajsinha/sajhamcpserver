"""
Bank of Canada MCP Tool implementation with comprehensive capabilities
"""
import os
import requests
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import os

if 'SSE_ENABLED' in os.environ:
    print('SSE Enabled - will use SSE enabled tool')
    from .base_mcp_tool_stateful import BaseMCPTool
else:
    from .base_mcp_tool import BaseMCPTool


class BankOfCanadaMCPTool(BaseMCPTool):
    """Comprehensive MCP Tool for Bank of Canada data operations"""

    def _initialize(self):
        """Initialize Bank of Canada specific components"""
        self.boc_base_url = "https://www.bankofcanada.ca/valet"
        self.statscan_base_url = "https://www150.statcan.gc.ca/t1/wds/rest"

        # Bank of Canada Valet API doesn't require API key
        self.headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

    def handle_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Handle Bank of Canada tool calls"""
        try:
            if self.check_rate_limit():
                error_msg = "Rate limit exceeded"
                self.record_call(tool_name, arguments, error=error_msg)
                return {"error": error_msg, "status": 429}

            # Comprehensive tool method mapping
            tool_methods = {
                # Interest Rates & Monetary Policy
                "get_policy_rate": self._get_policy_rate,
                "get_overnight_rate": self._get_overnight_rate,
                "get_bank_rate": self._get_bank_rate,
                "get_prime_rate": self._get_prime_rate,
                "get_corra": self._get_corra,
                "get_cdor": self._get_cdor,
                "get_ba_rates": self._get_ba_rates,
                "get_treasury_bills": self._get_treasury_bills,
                "get_monetary_conditions": self._get_monetary_conditions,
                "get_lvts_data": self._get_lvts_data,

                # Economic Indicators
                "get_gdp_data": self._get_gdp_data,
                "get_gdp_by_industry": self._get_gdp_by_industry,
                "get_cpi_data": self._get_cpi_data,
                "get_core_inflation": self._get_core_inflation,
                "get_inflation_targets": self._get_inflation_targets,
                "get_output_gap": self._get_output_gap,
                "get_potential_output": self._get_potential_output,

                # Exchange Rates
                "get_exchange_rates": self._get_exchange_rates,
                "get_cad_usd": self._get_cad_usd,
                "get_effective_exchange_rate": self._get_effective_exchange_rate,
                "get_currency_cross_rates": self._get_currency_cross_rates,
                "get_noon_rates": self._get_noon_rates,
                "get_closing_rates": self._get_closing_rates,

                # Canadian Bonds & Securities
                "get_government_bonds": self._get_government_bonds,
                "get_yield_curve": self._get_yield_curve,
                "get_real_return_bonds": self._get_real_return_bonds,
                "get_provincial_bonds": self._get_provincial_bonds,
                "get_corporate_bonds": self._get_corporate_bonds,
                "get_bond_spreads": self._get_bond_spreads,

                # Labor Market
                "get_employment_data": self._get_employment_data,
                "get_unemployment_rate": self._get_unemployment_rate,
                "get_job_vacancies": self._get_job_vacancies,
                "get_wage_growth": self._get_wage_growth,
                "get_hours_worked": self._get_hours_worked,
                "get_labour_force": self._get_labour_force,
                "get_employment_by_province": self._get_employment_by_province,
                "get_employment_by_industry": self._get_employment_by_industry,

                # Banking & Financial System
                "get_chartered_bank_assets": self._get_chartered_bank_assets,
                "get_bank_deposits": self._get_bank_deposits,
                "get_bank_loans": self._get_bank_loans,
                "get_mortgage_credit": self._get_mortgage_credit,
                "get_consumer_credit": self._get_consumer_credit,
                "get_business_credit": self._get_business_credit,
                "get_money_supply": self._get_money_supply,
                "get_financial_institutions_data": self._get_financial_institutions_data,
                "get_payment_systems": self._get_payment_systems,

                # Housing Market
                "get_housing_starts": self._get_housing_starts,
                "get_housing_prices": self._get_housing_prices,
                "get_mls_data": self._get_mls_data,
                "get_mortgage_rates": self._get_mortgage_rates,
                "get_housing_affordability": self._get_housing_affordability,
                "get_rental_market": self._get_rental_market,
                "get_construction_data": self._get_construction_data,

                # Trade & International
                "get_trade_balance": self._get_trade_balance,
                "get_exports": self._get_exports,
                "get_imports": self._get_imports,
                "get_current_account": self._get_current_account,
                "get_international_investment": self._get_international_investment,
                "get_commodity_prices": self._get_commodity_prices,
                "get_energy_prices": self._get_energy_prices,

                # Business & Industry
                "get_business_outlook_survey": self._get_business_outlook_survey,
                "get_senior_loan_officer_survey": self._get_senior_loan_officer_survey,
                "get_capacity_utilization": self._get_capacity_utilization,
                "get_industrial_production": self._get_industrial_production,
                "get_manufacturing_sales": self._get_manufacturing_sales,
                "get_retail_sales": self._get_retail_sales,
                "get_wholesale_trade": self._get_wholesale_trade,
                "get_business_investment": self._get_business_investment,

                # Consumer & Household
                "get_consumer_confidence": self._get_consumer_confidence,
                "get_household_debt": self._get_household_debt,
                "get_household_wealth": self._get_household_wealth,
                "get_savings_rate": self._get_savings_rate,
                "get_disposable_income": self._get_disposable_income,
                "get_consumer_spending": self._get_consumer_spending,

                # Provincial & Regional Data
                "get_provincial_gdp": self._get_provincial_gdp,
                "get_provincial_employment": self._get_provincial_employment,
                "get_provincial_cpi": self._get_provincial_cpi,
                "get_provincial_retail": self._get_provincial_retail,
                "get_major_cities_data": self._get_major_cities_data,

                # Financial Markets
                "get_tsx_data": self._get_tsx_data,
                "get_equity_indices": self._get_equity_indices,
                "get_derivatives_data": self._get_derivatives_data,
                "get_foreign_exchange_volume": self._get_foreign_exchange_volume,

                # Financial Stability
                "get_financial_system_review": self._get_financial_system_review,
                "get_systemic_risk_indicators": self._get_systemic_risk_indicators,
                "get_credit_conditions": self._get_credit_conditions,
                "get_financial_stress_index": self._get_financial_stress_index,

                # Surveys & Projections
                "get_monetary_policy_report": self._get_monetary_policy_report,
                "get_consumer_expectations": self._get_consumer_expectations,
                "get_market_expectations": self._get_market_expectations,
                "get_staff_projections": self._get_staff_projections,

                # Historical Data
                "get_historical_statistics": self._get_historical_statistics,
                "get_historical_exchange_rates": self._get_historical_exchange_rates,
                "get_historical_interest_rates": self._get_historical_interest_rates,

                # Search & Metadata
                "search_series": self._search_series,
                "get_series_metadata": self._get_series_metadata,
                "get_data_availability": self._get_data_availability
            }

            if tool_name in tool_methods:
                result = tool_methods[tool_name](arguments)
            else:
                result = {"error": f"Unknown tool: {tool_name}"}

            self.record_call(tool_name, arguments, result=result)
            return result

        except Exception as e:
            error_msg = str(e)
            self.record_call(tool_name, arguments, error=error_msg)
            return {"error": error_msg, "status": 500}

    # ==================== HELPER METHODS ====================

    def _fetch_boc_series(self, series_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Centralized Bank of Canada Valet API fetching"""
        try:
            # Build URL for series observations
            url = f"{self.boc_base_url}/observations/{series_name}"

            # Build query parameters
            query_params = {}
            if params.get('start_date'):
                query_params['start_date'] = params['start_date']
            if params.get('end_date'):
                query_params['end_date'] = params['end_date']
            if params.get('recent'):
                query_params['recent'] = params['recent']

            response = requests.get(url, params=query_params, headers=self.headers)

            if response.status_code != 200:
                return {"error": f"API request failed with status {response.status_code}"}

            data = response.json()

            # Parse observations
            observations = data.get('observations', [])

            # Get series metadata
            series_detail = data.get('seriesDetail', {})
            if series_name in series_detail:
                metadata = series_detail[series_name]
            else:
                metadata = {}

            # Format observations
            formatted_obs = []
            for obs in observations:
                if series_name in obs:
                    formatted_obs.append({
                        'date': obs.get('d'),
                        'value': obs.get(series_name, {}).get('v')
                    })

            # Calculate changes
            changes = []
            if len(formatted_obs) > 1:
                for i in range(len(formatted_obs) - 1):
                    if formatted_obs[i]['value'] and formatted_obs[i + 1]['value']:
                        current = float(formatted_obs[i]['value'])
                        previous = float(formatted_obs[i + 1]['value'])
                        if previous != 0:
                            change = ((current - previous) / previous) * 100
                            changes.append({
                                'date': formatted_obs[i]['date'],
                                'change_pct': round(change, 2)
                            })

            return {
                "series_name": series_name,
                "metadata": {
                    "label": metadata.get('label'),
                    "description": metadata.get('description'),
                    "dimension": metadata.get('dimension')
                },
                "latest_value": formatted_obs[0]['value'] if formatted_obs else None,
                "latest_date": formatted_obs[0]['date'] if formatted_obs else None,
                "observations": formatted_obs,
                "changes": changes[:5] if changes else [],
                "count": len(formatted_obs)
            }

        except Exception as e:
            return {"error": str(e)}

    def _fetch_multiple_series(self, series_list: List[str], params: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch multiple series at once"""
        try:
            series_names = ','.join(series_list)
            url = f"{self.boc_base_url}/observations/{series_names}"

            query_params = {}
            if params.get('start_date'):
                query_params['start_date'] = params['start_date']
            if params.get('end_date'):
                query_params['end_date'] = params['end_date']
            if params.get('recent'):
                query_params['recent'] = params.get('recent', 1)

            response = requests.get(url, params=query_params, headers=self.headers)

            if response.status_code != 200:
                return {"error": f"API request failed with status {response.status_code}"}

            data = response.json()
            observations = data.get('observations', [])
            series_detail = data.get('seriesDetail', {})

            results = {}
            for series_name in series_list:
                if observations and series_name in observations[0]:
                    results[series_name] = {
                        'value': observations[0][series_name].get('v'),
                        'date': observations[0].get('d'),
                        'label': series_detail.get(series_name, {}).get('label')
                    }

            return results

        except Exception as e:
            return {"error": str(e)}

    # ==================== INTEREST RATES & MONETARY POLICY ====================

    def _get_policy_rate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Bank of Canada policy interest rate (target for overnight rate)"""
        return self._fetch_boc_series('V39079', params)

    def _get_overnight_rate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get overnight money market financing rate"""
        return self._fetch_boc_series('V39077', params)

    def _get_bank_rate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Bank of Canada bank rate"""
        return self._fetch_boc_series('V39078', params)

    def _get_prime_rate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get chartered bank prime business rate"""
        return self._fetch_boc_series('V122495', params)

    def _get_corra(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Canadian Overnight Repo Rate Average (CORRA)"""
        return self._fetch_boc_series('V1003023563', params)

    def _get_cdor(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Canadian Dollar Offered Rate (CDOR)"""
        term = params.get('term', '3M')

        series_map = {
            '1M': 'V39067',
            '2M': 'V39068',
            '3M': 'V39069',
            '6M': 'V39070',
            '12M': 'V39071'
        }

        series_name = series_map.get(term, 'V39069')
        return self._fetch_boc_series(series_name, params)

    def _get_ba_rates(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Bankers' Acceptances rates"""
        term = params.get('term', '3M')

        series_map = {
            '1M': 'V122504',
            '3M': 'V122506',
            '6M': 'V122508'
        }

        series_name = series_map.get(term, 'V122506')
        return self._fetch_boc_series(series_name, params)

    def _get_treasury_bills(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Treasury Bill rates"""
        term = params.get('term', '3M')

        series_map = {
            '1M': 'V39065',
            '3M': 'V39066',
            '6M': 'V39067',
            '12M': 'V39068'
        }

        series_name = series_map.get(term, 'V39066')
        return self._fetch_boc_series(series_name, params)

    def _get_monetary_conditions(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get monetary conditions index components"""
        # Fetch policy rate and exchange rate
        series_list = ['V39079', 'FXCADUSD']
        return self._fetch_multiple_series(series_list, {'recent': 1})

    def _get_lvts_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Large Value Transfer System data"""
        return self._fetch_boc_series('V36645', params)

    # ==================== ECONOMIC INDICATORS ====================

    def _get_gdp_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Canadian GDP data"""
        gdp_type = params.get('gdp_type', 'monthly')

        series_map = {
            'monthly': 'V65201210',
            'quarterly': 'V62305752',
            'real': 'V62305752',
            'nominal': 'V62305668'
        }

        series_name = series_map.get(gdp_type, 'V65201210')
        return self._fetch_boc_series(series_name, params)

    def _get_gdp_by_industry(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get GDP by industry"""
        industry = params.get('industry', 'all')

        if industry == 'all':
            # Get major industry categories
            series_list = [
                'V65201210',  # All industries
                'V65201228',  # Goods-producing
                'V65201751',  # Services-producing
            ]
            return self._fetch_multiple_series(series_list, {'recent': 1})
        else:
            series_map = {
                'manufacturing': 'V65201376',
                'construction': 'V65201335',
                'retail': 'V65201825',
                'finance': 'V65201912'
            }
            series_name = series_map.get(industry, 'V65201210')
            return self._fetch_boc_series(series_name, params)

    def _get_cpi_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Consumer Price Index data"""
        cpi_type = params.get('cpi_type', 'all_items')

        series_map = {
            'all_items': 'V41690973',
            'ex_food_energy': 'V41690930',
            'goods': 'V41690967',
            'services': 'V41690970'
        }

        series_name = series_map.get(cpi_type, 'V41690973')
        return self._fetch_boc_series(series_name, params)

    def _get_core_inflation(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Bank of Canada core inflation measures"""
        measure = params.get('measure', 'cpi_trim')

        series_map = {
            'cpi_trim': 'V1003004069',
            'cpi_median': 'V1003004070',
            'cpi_common': 'V1003004071'
        }

        series_name = series_map.get(measure, 'V1003004069')
        return self._fetch_boc_series(series_name, params)

    def _get_inflation_targets(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get inflation target information"""
        return {
            "target": "2%",
            "range": "1% to 3%",
            "description": "Bank of Canada inflation-control target",
            "renewal_date": "2026"
        }

    def _get_output_gap(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get output gap estimates"""
        # Note: This would require specific BoC estimates
        return {
            "message": "Output gap estimates available in Monetary Policy Report",
            "source": "Bank of Canada staff estimates"
        }

    def _get_potential_output(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get potential output estimates"""
        return {
            "message": "Potential output estimates available in Monetary Policy Report",
            "source": "Bank of Canada staff estimates"
        }

    # ==================== EXCHANGE RATES ====================

    def _get_exchange_rates(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get foreign exchange rates"""
        currency = params.get('currency', 'USD')

        series_map = {
            'USD': 'FXCADUSD',
            'EUR': 'FXCADEUR',
            'GBP': 'FXCADGBP',
            'JPY': 'FXCADJPY',
            'CNY': 'FXCADCNY',
            'MXN': 'FXCADMXN',
            'AUD': 'FXCADAUD',
            'INR': 'FXCADINR'
        }

        series_name = series_map.get(currency, 'FXCADUSD')
        return self._fetch_boc_series(series_name, params)

    def _get_cad_usd(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get CAD/USD exchange rate with additional details"""
        result = self._fetch_boc_series('FXCADUSD', params)

        # Also get USD/CAD for convenience
        usd_cad = self._fetch_boc_series('FXUSDCAD', {'recent': 1})

        if 'latest_value' in result and 'latest_value' in usd_cad:
            result['usd_per_cad'] = result['latest_value']
            result['cad_per_usd'] = usd_cad['latest_value']

        return result

    def _get_effective_exchange_rate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Canadian-dollar effective exchange rate index (CERI)"""
        return self._fetch_boc_series('V111666275', params)

    def _get_currency_cross_rates(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get cross rates between major currencies"""
        cross = params.get('cross', 'EUR_USD')

        series_map = {
            'EUR_USD': 'FXEURUSD',
            'GBP_USD': 'FXGBPUSD',
            'USD_JPY': 'FXUSDJPY'
        }

        series_name = series_map.get(cross, 'FXEURUSD')
        return self._fetch_boc_series(series_name, params)

    def _get_noon_rates(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get noon exchange rates (historical)"""
        # Note: Noon rates were discontinued in 2017
        return {
            "message": "Noon rates discontinued in April 2017",
            "alternative": "Use closing rates or daily average rates"
        }

    def _get_closing_rates(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get closing exchange rates"""
        currency = params.get('currency', 'USD')
        series_name = f'FXCAD{currency}'
        return self._fetch_boc_series(series_name, params)

    # ==================== CANADIAN BONDS & SECURITIES ====================

    def _get_government_bonds(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Government of Canada bond yields"""
        maturity = params.get('maturity', '10Y')

        series_map = {
            '3M': 'V39055',
            '6M': 'V39056',
            '1Y': 'V39057',
            '2Y': 'V39051',
            '3Y': 'V39052',
            '5Y': 'V39053',
            '7Y': 'V39054',
            '10Y': 'V39055',
            '30Y': 'V39056'
        }

        series_name = series_map.get(maturity, 'V39055')
        return self._fetch_boc_series(series_name, params)

    def _get_yield_curve(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get complete Canadian yield curve"""
        maturities = {
            '3M': 'V39065',
            '6M': 'V39066',
            '1Y': 'V39067',
            '2Y': 'V39051',
            '3Y': 'V39052',
            '5Y': 'V39053',
            '7Y': 'V39054',
            '10Y': 'V39055',
            '30Y': 'V39056'
        }

        curve_data = {}
        for maturity, series_name in maturities.items():
            result = self._fetch_boc_series(series_name, {'recent': 1})
            if 'latest_value' in result:
                curve_data[maturity] = float(result['latest_value'])

        # Calculate spreads
        spreads = {}
        if '10Y' in curve_data and '2Y' in curve_data:
            spreads['10Y2Y'] = round(curve_data['10Y'] - curve_data['2Y'], 2)
        if '10Y' in curve_data and '3M' in curve_data:
            spreads['10Y3M'] = round(curve_data['10Y'] - curve_data['3M'], 2)

        return {
            "date": datetime.now().strftime('%Y-%m-%d'),
            "yield_curve": curve_data,
            "spreads": spreads
        }

    def _get_real_return_bonds(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Real Return Bond yields"""
        return self._fetch_boc_series('V39062', params)

    def _get_provincial_bonds(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get provincial bond yields"""
        province = params.get('province', 'ON')

        series_map = {
            'ON': 'V39060',  # Ontario
            'QC': 'V39061',  # Quebec
            'BC': 'V39059',  # British Columbia
            'AB': 'V39058'  # Alberta
        }

        series_name = series_map.get(province, 'V39060')
        return self._fetch_boc_series(series_name, params)

    def _get_corporate_bonds(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get corporate bond yields"""
        return self._fetch_boc_series('V39063', params)

    def _get_bond_spreads(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get bond spreads"""
        spread_type = params.get('spread_type', 'corporate_government')

        # Fetch relevant series
        if spread_type == 'corporate_government':
            govt = self._fetch_boc_series('V39055', {'recent': 1})
            corp = self._fetch_boc_series('V39063', {'recent': 1})

            if 'latest_value' in govt and 'latest_value' in corp:
                spread = float(corp['latest_value']) - float(govt['latest_value'])
                return {
                    "spread_type": spread_type,
                    "spread": round(spread, 2),
                    "government_yield": govt['latest_value'],
                    "corporate_yield": corp['latest_value'],
                    "date": govt['latest_date']
                }

        return {"error": "Unable to calculate spread"}

    # ==================== LABOR MARKET ====================

    def _get_employment_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get employment data"""
        return self._fetch_boc_series('V2062815', params)

    def _get_unemployment_rate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get unemployment rate"""
        return self._fetch_boc_series('V2062815', params)

    def _get_job_vacancies(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get job vacancy data"""
        return self._fetch_boc_series('V1003237174', params)

    def _get_wage_growth(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get wage growth data"""
        measure = params.get('measure', 'average_hourly')

        series_map = {
            'average_hourly': 'V2132579',
            'seph': 'V1003267459',  # Survey of Employment, Payrolls and Hours
            'wage_common': 'V1003004073'  # Wage-Common measure
        }

        series_name = series_map.get(measure, 'V2132579')
        return self._fetch_boc_series(series_name, params)

    def _get_hours_worked(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get hours worked data"""
        return self._fetch_boc_series('V2057608', params)

    def _get_labour_force(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get labour force statistics"""
        return self._fetch_boc_series('V2062809', params)

    def _get_employment_by_province(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get employment by province"""
        province = params.get('province', 'ON')

        series_map = {
            'ON': 'V2057600',  # Ontario
            'QC': 'V2057582',  # Quebec
            'BC': 'V2057636',  # British Columbia
            'AB': 'V2057618',  # Alberta
            'MB': 'V2057546',  # Manitoba
            'SK': 'V2057564',  # Saskatchewan
            'NS': 'V2057492',  # Nova Scotia
            'NB': 'V2057474',  # New Brunswick
            'NL': 'V2057456',  # Newfoundland and Labrador
            'PE': 'V2057510'  # Prince Edward Island
        }

        series_name = series_map.get(province, 'V2057600')
        return self._fetch_boc_series(series_name, params)

    def _get_employment_by_industry(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get employment by industry"""
        industry = params.get('industry', 'total')

        series_map = {
            'total': 'V2062815',
            'goods': 'V2057672',
            'services': 'V2057798',
            'manufacturing': 'V2057714',
            'construction': 'V2057696',
            'retail': 'V2057843',
            'finance': 'V2057906'
        }

        series_name = series_map.get(industry, 'V2062815')
        return self._fetch_boc_series(series_name, params)

    # ==================== BANKING & FINANCIAL SYSTEM ====================

    def _get_chartered_bank_assets(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get chartered bank assets"""
        return self._fetch_boc_series('V36596', params)

    def _get_bank_deposits(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get bank deposits"""
        deposit_type = params.get('deposit_type', 'total')

        series_map = {
            'total': 'V36611',
            'personal': 'V36612',
            'non_personal': 'V36613',
            'demand': 'V36614',
            'notice': 'V36615',
            'fixed_term': 'V36616'
        }

        series_name = series_map.get(deposit_type, 'V36611')
        return self._fetch_boc_series(series_name, params)

    def _get_bank_loans(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get bank loans"""
        loan_type = params.get('loan_type', 'total')

        series_map = {
            'total': 'V36810',
            'business': 'V36811',
            'residential_mortgage': 'V36812',
            'consumer': 'V36813'
        }

        series_name = series_map.get(loan_type, 'V36810')
        return self._fetch_boc_series(series_name, params)

    def _get_mortgage_credit(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get mortgage credit data"""
        return self._fetch_boc_series('V122740', params)

    def _get_consumer_credit(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get consumer credit data"""
        return self._fetch_boc_series('V122741', params)

    def _get_business_credit(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get business credit data"""
        return self._fetch_boc_series('V122742', params)

    def _get_money_supply(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get money supply data"""
        aggregate = params.get('aggregate', 'M2')

        series_map = {
            'M1+': 'V37258',
            'M1++': 'V37260',
            'M2': 'V37261',
            'M2+': 'V37262',
            'M2++': 'V37263',
            'M3': 'V37264'
        }

        series_name = series_map.get(aggregate, 'V37261')
        return self._fetch_boc_series(series_name, params)

    def _get_financial_institutions_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get financial institutions data"""
        return self._fetch_boc_series('V36574', params)

    def _get_payment_systems(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get payment systems data"""
        system = params.get('system', 'lvts')

        series_map = {
            'lvts': 'V36645',
            'acss': 'V36646',
            'lynx': 'V1003027500'
        }

        series_name = series_map.get(system, 'V36645')
        return self._fetch_boc_series(series_name, params)

    # ==================== HOUSING MARKET ====================

    def _get_housing_starts(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get housing starts data"""
        return self._fetch_boc_series('V52298215', params)

    def _get_housing_prices(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get housing price indices"""
        index_type = params.get('index_type', 'new_house')

        series_map = {
            'new_house': 'V52939252',
            'crea_hpi': 'V1003003992',
            'teranet': 'V111973340'
        }

        series_name = series_map.get(index_type, 'V52939252')
        return self._fetch_boc_series(series_name, params)

    def _get_mls_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get MLS home sales data"""
        return self._fetch_boc_series('V723253', params)

    def _get_mortgage_rates(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get mortgage interest rates"""
        mortgage_type = params.get('mortgage_type', '5Y_fixed')

        series_map = {
            '1Y_fixed': 'V80691311',
            '3Y_fixed': 'V80691312',
            '5Y_fixed': 'V80691313',
            'variable': 'V80691314'
        }

        series_name = series_map.get(mortgage_type, 'V80691313')
        return self._fetch_boc_series(series_name, params)

    def _get_housing_affordability(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get housing affordability index"""
        # This would require calculation based on prices, income, and rates
        return {
            "message": "Housing affordability data available from RBC, National Bank reports",
            "components": "House prices, household income, mortgage rates"
        }

    def _get_rental_market(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get rental market data"""
        return self._fetch_boc_series('V52941896', params)

    def _get_construction_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get construction activity data"""
        return self._fetch_boc_series('V52991847', params)

    # ==================== TRADE & INTERNATIONAL ====================

    def _get_trade_balance(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get trade balance data"""
        return self._fetch_boc_series('V1001830033', params)

    def _get_exports(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get export data"""
        return self._fetch_boc_series('V1001826858', params)

    def _get_imports(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get import data"""
        return self._fetch_boc_series('V1001826945', params)

    def _get_current_account(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get current account data"""
        return self._fetch_boc_series('V51291287', params)

    def _get_international_investment(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get international investment position"""
        return self._fetch_boc_series('V51291309', params)

    def _get_commodity_prices(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Bank of Canada commodity price index"""
        commodity = params.get('commodity', 'total')

        series_map = {
            'total': 'V1003018802',
            'energy': 'V1003018803',
            'non_energy': 'V1003018808',
            'metals': 'V1003018813',
            'forestry': 'V1003018815',
            'agriculture': 'V1003018818'
        }

        series_name = series_map.get(commodity, 'V1003018802')
        return self._fetch_boc_series(series_name, params)

    def _get_energy_prices(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get energy price data"""
        energy_type = params.get('energy_type', 'oil')

        series_map = {
            'oil': 'V39768',
            'natural_gas': 'V39769',
            'electricity': 'V39770'
        }

        series_name = series_map.get(energy_type, 'V39768')
        return self._fetch_boc_series(series_name, params)

    # ==================== BUSINESS & INDUSTRY ====================

    def _get_business_outlook_survey(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Business Outlook Survey indicators"""
        indicator = params.get('indicator', 'future_sales')

        series_map = {
            'future_sales': 'V1003013847',
            'investment': 'V1003013848',
            'employment': 'V1003013849',
            'inflation': 'V1003013850'
        }

        series_name = series_map.get(indicator, 'V1003013847')
        return self._fetch_boc_series(series_name, params)

    def _get_senior_loan_officer_survey(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Senior Loan Officer Survey results"""
        return {
            "message": "Senior Loan Officer Survey available quarterly",
            "source": "Bank of Canada website"
        }

    def _get_capacity_utilization(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get capacity utilization rates"""
        return self._fetch_boc_series('V4331085', params)

    def _get_industrial_production(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get industrial production index"""
        return self._fetch_boc_series('V41707177', params)

    def _get_manufacturing_sales(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get manufacturing sales"""
        return self._fetch_boc_series('V800582', params)

    def _get_retail_sales(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get retail sales data"""
        return self._fetch_boc_series('V42575726', params)

    def _get_wholesale_trade(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get wholesale trade data"""
        return self._fetch_boc_series('V41707134', params)

    def _get_business_investment(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get business investment data"""
        return self._fetch_boc_series('V62305770', params)

    # ==================== Additional methods continue... ====================
    # The rest of the methods follow the same pattern

    def _get_consumer_confidence(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get consumer confidence index"""
        return self._fetch_boc_series('V54408912', params)

    def _get_household_debt(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get household debt data"""
        return self._fetch_boc_series('V52961760', params)

    def _get_household_wealth(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get household net worth data"""
        return self._fetch_boc_series('V52961782', params)

    def _get_savings_rate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get household savings rate"""
        return self._fetch_boc_series('V62305978', params)

    def _get_disposable_income(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get household disposable income"""
        return self._fetch_boc_series('V62305963', params)

    def _get_consumer_spending(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get consumer spending data"""
        return self._fetch_boc_series('V62305723', params)

    def _get_provincial_gdp(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get provincial GDP data"""
        province = params.get('province', 'ON')

        series_map = {
            'ON': 'V86718883',
            'QC': 'V86718669',
            'BC': 'V86719525',
            'AB': 'V86719311'
        }

        series_name = series_map.get(province, 'V86718883')
        return self._fetch_boc_series(series_name, params)

    def _get_provincial_employment(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get provincial employment data"""
        return self._get_employment_by_province(params)

    def _get_provincial_cpi(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get provincial CPI data"""
        province = params.get('province', 'ON')

        series_map = {
            'ON': 'V41692462',
            'QC': 'V41692228',
            'BC': 'V41692930',
            'AB': 'V41692696'
        }

        series_name = series_map.get(province, 'V41692462')
        return self._fetch_boc_series(series_name, params)

    def _get_provincial_retail(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get provincial retail sales"""
        province = params.get('province', 'ON')

        series_map = {
            'ON': 'V42575735',
            'QC': 'V42575732',
            'BC': 'V42575741',
            'AB': 'V42575738'
        }

        series_name = series_map.get(province, 'V42575735')
        return self._fetch_boc_series(series_name, params)

    def _get_major_cities_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get economic data for major cities"""
        city = params.get('city', 'toronto')
        data_type = params.get('data_type', 'cpi')

        if data_type == 'cpi':
            city_map = {
                'toronto': 'V41691796',
                'montreal': 'V41691102',
                'vancouver': 'V41693264',
                'calgary': 'V41693030'
            }
            series_name = city_map.get(city, 'V41691796')
            return self._fetch_boc_series(series_name, params)

        return {"message": f"Data for {city} - {data_type}"}

    def _get_tsx_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get TSX index data"""
        return self._fetch_boc_series('V122620', params)

    def _get_equity_indices(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Canadian equity indices"""
        index = params.get('index', 'tsx_composite')

        series_map = {
            'tsx_composite': 'V122620',
            'tsx_60': 'V122629',
            'tsx_venture': 'V44342010'
        }

        series_name = series_map.get(index, 'V122620')
        return self._fetch_boc_series(series_name, params)

    def _get_derivatives_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get derivatives market data"""
        return {
            "message": "Derivatives data available from Montreal Exchange",
            "source": "TMX Group"
        }

    def _get_foreign_exchange_volume(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get foreign exchange trading volume"""
        return self._fetch_boc_series('V36387', params)

    def _get_financial_system_review(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Financial System Review information"""
        return {
            "frequency": "Semi-annual (May and November)",
            "content": "Assessment of vulnerabilities and risks",
            "source": "Bank of Canada Financial System Review"
        }

    def _get_systemic_risk_indicators(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get systemic risk indicators"""
        return {
            "indicators": [
                "Household debt-to-income ratio",
                "House price growth",
                "Credit-to-GDP gap",
                "Banking sector leverage"
            ],
            "source": "Bank of Canada financial stability indicators"
        }

    def _get_credit_conditions(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get credit conditions assessment"""
        return {
            "source": "Senior Loan Officer Survey",
            "frequency": "Quarterly",
            "measures": ["Lending standards", "Demand for credit"]
        }

    def _get_financial_stress_index(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Canadian financial stress index"""
        # Note: Would require construction from multiple indicators
        return {
            "message": "Financial stress indicators available",
            "components": ["Credit spreads", "Volatility", "Liquidity measures"]
        }

    def _get_monetary_policy_report(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Monetary Policy Report information"""
        return {
            "frequency": "Quarterly (January, April, July, October)",
            "content": "Economic outlook and monetary policy assessment",
            "source": "Bank of Canada Monetary Policy Report"
        }

    def _get_consumer_expectations(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Canadian Survey of Consumer Expectations"""
        indicator = params.get('indicator', 'inflation_1y')

        series_map = {
            'inflation_1y': 'V1003022553',
            'inflation_2y': 'V1003022554',
            'inflation_5y': 'V1003022555'
        }

        series_name = series_map.get(indicator, 'V1003022553')
        return self._fetch_boc_series(series_name, params)

    def _get_market_expectations(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get market expectations for policy rate"""
        return {
            "source": "Overnight Index Swaps",
            "message": "Market-implied policy rate expectations"
        }

    def _get_staff_projections(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get Bank of Canada staff economic projections"""
        return {
            "source": "Monetary Policy Report",
            "frequency": "Quarterly",
            "variables": ["GDP growth", "Inflation", "Output gap"]
        }

    def _get_historical_statistics(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get historical statistics"""
        statistic = params.get('statistic', 'policy_rate')
        start_date = params.get('start_date', '1935-01-01')

        series_map = {
            'policy_rate': 'V39079',
            'inflation': 'V41690973',
            'gdp': 'V62305752'
        }

        series_name = series_map.get(statistic, 'V39079')
        params['start_date'] = start_date
        return self._fetch_boc_series(series_name, params)

    def _get_historical_exchange_rates(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get historical exchange rates"""
        params['start_date'] = params.get('start_date', '1950-01-01')
        return self._get_exchange_rates(params)

    def _get_historical_interest_rates(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get historical interest rates"""
        params['start_date'] = params.get('start_date', '1935-01-01')
        return self._get_policy_rate(params)

    def _search_series(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Search for Bank of Canada data series"""
        search_term = params.get('search_term', '')

        # This would require implementation of search functionality
        return {
            "message": "Search Bank of Canada Valet API",
            "search_term": search_term,
            "url": "https://www.bankofcanada.ca/valet/docs"
        }

    def _get_series_metadata(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get metadata for a specific series"""
        series_name = params.get('series_name', '')

        if not series_name:
            return {"error": "Series name required"}

        # Fetch series with minimal data to get metadata
        return self._fetch_boc_series(series_name, {'recent': 1})

    def _get_data_availability(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get information about data availability"""
        return {
            "valet_api": "https://www.bankofcanada.ca/valet",
            "update_frequency": "Various (daily to annual)",
            "historical_data": "Available from 1935 for some series",
            "real_time": "Exchange rates updated daily"
        }