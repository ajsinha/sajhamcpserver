"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
OpenBB Platform MCP Tool Implementations

Uses the OpenBB Python SDK (pip install openbb).
Docs: https://docs.openbb.co/platform/
Routers: equity, economy, currency, crypto, etf, fixedincome, index, news, commodity

OpenBB aggregates 100+ data providers (Yahoo Finance, FMP, FRED, SEC, etc.)
under a single consistent API. No API key needed for Yahoo Finance provider.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sajha.tools.base_mcp_tool import BaseMCPTool

logger = logging.getLogger(__name__)

# Lazy import — openbb is heavy, only load when needed
_obb = None


def _get_obb():
    """Lazy-load the OpenBB SDK."""
    global _obb
    if _obb is None:
        try:
            from openbb import obb
            _obb = obb
            logger.info('OpenBB SDK loaded successfully')
        except ImportError:
            raise ImportError(
                'OpenBB SDK not installed. Run: pip install openbb\n'
                'For specific providers: pip install openbb[yfinance,fmp,fred]'
            )
    return _obb


def _to_records(result) -> List[Dict]:
    """Convert OpenBB OBBject result to list of dicts."""
    try:
        df = result.to_dataframe()
        # Convert timestamps to strings for JSON serialization
        for col in df.columns:
            if hasattr(df[col], 'dt'):
                df[col] = df[col].astype(str)
        return df.to_dict(orient='records')
    except Exception:
        try:
            return result.to_dict() if hasattr(result, 'to_dict') else [{"data": str(result)}]
        except Exception:
            return [{"data": str(result)}]


class OpenBBBaseTool(BaseMCPTool):
    """Base class for all OpenBB tools."""

    def __init__(self, config: Dict = None):
        super().__init__(config)
        self.default_provider = config.get('default_provider', 'yfinance') if config else 'yfinance'

    def get_input_schema(self) -> Dict:
        return self._input_schema

    def get_output_schema(self) -> Dict:
        return self._output_schema


# ═══════════════════════════════════════════════════════════════════════════
# 1. Equity Historical Prices
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBEquityPriceTool(OpenBBBaseTool):
    """Get historical equity prices — OHLCV data for any stock."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        symbol = arguments.get('symbol', '').upper()
        start_date = arguments.get('start_date', (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d'))
        end_date = arguments.get('end_date', datetime.now().strftime('%Y-%m-%d'))
        provider = arguments.get('provider', self.default_provider)
        if not symbol:
            return {"error": "Symbol is required"}
        result = obb.equity.price.historical(
            symbol=symbol, start_date=start_date, end_date=end_date, provider=provider
        )
        records = _to_records(result)
        return {"symbol": symbol, "provider": provider, "data_points": len(records),
                "start_date": start_date, "end_date": end_date, "prices": records}


# ═══════════════════════════════════════════════════════════════════════════
# 2. Equity Profile
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBEquityProfileTool(OpenBBBaseTool):
    """Get company profile — sector, industry, market cap, description, CEO."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        symbol = arguments.get('symbol', '').upper()
        provider = arguments.get('provider', self.default_provider)
        if not symbol:
            return {"error": "Symbol is required"}
        result = obb.equity.profile(symbol=symbol, provider=provider)
        records = _to_records(result)
        return {"symbol": symbol, "profile": records[0] if records else {}}


# ═══════════════════════════════════════════════════════════════════════════
# 3. Equity Fundamental Metrics
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBEquityMetricsTool(OpenBBBaseTool):
    """Get key financial metrics — PE, PB, ROE, margins, growth rates."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        symbol = arguments.get('symbol', '').upper()
        period = arguments.get('period', 'annual')
        provider = arguments.get('provider', 'fmp')
        limit = arguments.get('limit', 5)
        if not symbol:
            return {"error": "Symbol is required"}
        result = obb.equity.fundamental.metrics(
            symbol=symbol, period=period, provider=provider, limit=limit
        )
        records = _to_records(result)
        return {"symbol": symbol, "period": period, "metrics": records}


# ═══════════════════════════════════════════════════════════════════════════
# 4. Economy GDP
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBEconomyGDPTool(OpenBBBaseTool):
    """Get GDP data — nominal and real GDP for countries worldwide."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        country = arguments.get('country', 'united_states')
        provider = arguments.get('provider', 'oecd')
        try:
            result = obb.economy.gdp.nominal(provider=provider, country=country)
            records = _to_records(result)
            return {"country": country, "data_points": len(records), "gdp_data": records}
        except Exception as e:
            return {"country": country, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# 5. Economy CPI (Consumer Price Index)
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBEconomyCPITool(OpenBBBaseTool):
    """Get CPI/inflation data — consumer price index trends by country."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        country = arguments.get('country', 'united_states')
        provider = arguments.get('provider', 'fred')
        try:
            result = obb.economy.cpi(provider=provider, country=country)
            records = _to_records(result)
            return {"country": country, "data_points": len(records), "cpi_data": records}
        except Exception as e:
            return {"country": country, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# 6. Forex Historical Rates
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBForexHistoricalTool(OpenBBBaseTool):
    """Get historical forex exchange rates — any currency pair."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        symbol = arguments.get('symbol', 'EURUSD').upper()
        start_date = arguments.get('start_date', (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d'))
        end_date = arguments.get('end_date', datetime.now().strftime('%Y-%m-%d'))
        provider = arguments.get('provider', self.default_provider)
        result = obb.currency.price.historical(
            symbol=symbol, start_date=start_date, end_date=end_date, provider=provider
        )
        records = _to_records(result)
        return {"symbol": symbol, "data_points": len(records),
                "start_date": start_date, "end_date": end_date, "rates": records}


# ═══════════════════════════════════════════════════════════════════════════
# 7. Cryptocurrency Prices
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBCryptoPriceTool(OpenBBBaseTool):
    """Get historical cryptocurrency prices — BTC, ETH, and more."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        symbol = arguments.get('symbol', 'BTCUSD').upper()
        start_date = arguments.get('start_date', (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d'))
        end_date = arguments.get('end_date', datetime.now().strftime('%Y-%m-%d'))
        provider = arguments.get('provider', self.default_provider)
        result = obb.crypto.price.historical(
            symbol=symbol, start_date=start_date, end_date=end_date, provider=provider
        )
        records = _to_records(result)
        return {"symbol": symbol, "data_points": len(records),
                "start_date": start_date, "end_date": end_date, "prices": records}


# ═══════════════════════════════════════════════════════════════════════════
# 8. ETF Holdings
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBETFHoldingsTool(OpenBBBaseTool):
    """Get ETF holdings breakdown — top holdings, weights, sectors."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        symbol = arguments.get('symbol', 'SPY').upper()
        provider = arguments.get('provider', 'fmp')
        result = obb.etf.holdings(symbol=symbol, provider=provider)
        records = _to_records(result)
        return {"symbol": symbol, "holdings_count": len(records), "holdings": records[:50]}


# ═══════════════════════════════════════════════════════════════════════════
# 9. Treasury / Interest Rates
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBTreasuryRatesTool(OpenBBBaseTool):
    """Get US Treasury rates — yield curve data across maturities."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        start_date = arguments.get('start_date', (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d'))
        end_date = arguments.get('end_date', datetime.now().strftime('%Y-%m-%d'))
        provider = arguments.get('provider', 'federal_reserve')
        try:
            result = obb.fixedincome.rate.dff(
                start_date=start_date, end_date=end_date, provider=provider
            )
            records = _to_records(result)
            return {"data_points": len(records), "start_date": start_date,
                    "end_date": end_date, "rates": records}
        except Exception as e:
            return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# 10. Market News
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBMarketNewsTool(OpenBBBaseTool):
    """Get latest market and world news from multiple sources."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        limit = arguments.get('limit', 10)
        provider = arguments.get('provider', 'benzinga')
        try:
            result = obb.news.world(provider=provider, limit=limit)
            records = _to_records(result)
            return {"articles_count": len(records), "articles": records}
        except Exception as e:
            return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# 11-13. Financial Statements
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBIncomeStatementTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        symbol = arguments.get('symbol', '').upper()
        if not symbol: return {"error": "Symbol is required"}
        result = obb.equity.fundamental.income(
            symbol=symbol, period=arguments.get('period', 'annual'),
            provider=arguments.get('provider', self.default_provider), limit=arguments.get('limit', 5)
        )
        return {"symbol": symbol, "statements": _to_records(result)}

class OpenBBBalanceSheetTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        symbol = arguments.get('symbol', '').upper()
        if not symbol: return {"error": "Symbol is required"}
        result = obb.equity.fundamental.balance(
            symbol=symbol, period=arguments.get('period', 'annual'),
            provider=arguments.get('provider', self.default_provider), limit=arguments.get('limit', 5)
        )
        return {"symbol": symbol, "statements": _to_records(result)}

class OpenBBCashFlowTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        symbol = arguments.get('symbol', '').upper()
        if not symbol: return {"error": "Symbol is required"}
        result = obb.equity.fundamental.cash(
            symbol=symbol, period=arguments.get('period', 'annual'),
            provider=arguments.get('provider', self.default_provider), limit=arguments.get('limit', 5)
        )
        return {"symbol": symbol, "statements": _to_records(result)}


# ═══════════════════════════════════════════════════════════════════════════
# 14-15. Dividends & Earnings
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBDividendsTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        symbol = arguments.get('symbol', '').upper()
        if not symbol: return {"error": "Symbol is required"}
        result = obb.equity.fundamental.dividends(
            symbol=symbol, provider=arguments.get('provider', self.default_provider)
        )
        return {"symbol": symbol, "dividends": _to_records(result)}

class OpenBBEarningsTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        symbol = arguments.get('symbol', '').upper()
        if not symbol: return {"error": "Symbol is required"}
        try:
            result = obb.equity.fundamental.earnings(
                symbol=symbol, provider=arguments.get('provider', self.default_provider)
            )
            return {"symbol": symbol, "earnings": _to_records(result)}
        except Exception as e:
            return {"symbol": symbol, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# 16. Company News
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBCompanyNewsTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        symbol = arguments.get('symbol', '').upper()
        if not symbol: return {"error": "Symbol is required"}
        result = obb.news.company(
            symbol=symbol, limit=arguments.get('limit', 10),
            provider=arguments.get('provider', 'benzinga')
        )
        return {"symbol": symbol, "articles": _to_records(result)}


# ═══════════════════════════════════════════════════════════════════════════
# 17. Options Chains
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBOptionsChainsTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        symbol = arguments.get('symbol', '').upper()
        if not symbol: return {"error": "Symbol is required"}
        try:
            result = obb.derivatives.options.chains(
                symbol=symbol, provider=arguments.get('provider', 'cboe')
            )
            records = _to_records(result)
            return {"symbol": symbol, "contracts": len(records), "chain": records[:100]}
        except Exception as e:
            return {"symbol": symbol, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# 18. Index Constituents
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBIndexConstituentsTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        index = arguments.get('index', 'sp500').lower()
        try:
            if index == 'sp500':
                result = obb.index.sp500(provider=arguments.get('provider', 'fmp'))
            elif index in ('nasdaq', 'nasdaq100'):
                result = obb.index.constituents(index='nasdaq', provider=arguments.get('provider', 'fmp'))
            elif index in ('dowjones', 'dow'):
                result = obb.index.constituents(index='dowjones', provider=arguments.get('provider', 'fmp'))
            else:
                result = obb.index.constituents(index=index, provider=arguments.get('provider', 'fmp'))
            return {"index": index, "constituents": _to_records(result)}
        except Exception as e:
            return {"index": index, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# 19. Commodity Price
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBCommodityPriceTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        symbol = arguments.get('symbol', 'GC=F')
        start = arguments.get('start_date', (datetime.now() - timedelta(days=180)).strftime('%Y-%m-%d'))
        result = obb.commodity.price.historical(
            symbol=symbol, start_date=start,
            provider=arguments.get('provider', self.default_provider)
        )
        records = _to_records(result)
        return {"symbol": symbol, "data_points": len(records), "prices": records}


# ═══════════════════════════════════════════════════════════════════════════
# 20-21. Economic Data
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBEconomicIndicatorsTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        try:
            symbol = arguments.get('symbol', 'UNRATE')
            result = obb.economy.indicators(
                symbol=symbol, provider=arguments.get('provider', 'fred'),
                country=arguments.get('country', 'united_states')
            )
            return {"indicator": symbol, "data": _to_records(result)}
        except Exception as e:
            return {"error": str(e)}

class OpenBBUnemploymentTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        try:
            result = obb.economy.unemployment(
                country=arguments.get('country', 'united_states'),
                provider=arguments.get('provider', 'oecd')
            )
            return {"country": arguments.get('country', 'united_states'), "data": _to_records(result)}
        except Exception as e:
            return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# 22. Yield Curve
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBYieldCurveTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        try:
            params = {'provider': arguments.get('provider', 'federal_reserve')}
            if arguments.get('date'):
                params['date'] = arguments['date']
            result = obb.fixedincome.government.us_yield_curve(**params)
            return {"yield_curve": _to_records(result)}
        except Exception as e:
            return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# 23. Equity Screener
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBEquityScreenerTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        try:
            params = {'provider': arguments.get('provider', 'fmp')}
            for k in ['market_cap_min', 'market_cap_max', 'sector', 'country', 'limit']:
                if arguments.get(k) is not None:
                    params[k] = arguments[k]
            result = obb.equity.screener(**params)
            records = _to_records(result)
            return {"results_count": len(records), "results": records}
        except Exception as e:
            return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# 24-25. Ownership
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBInstitutionalOwnershipTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        symbol = arguments.get('symbol', '').upper()
        if not symbol: return {"error": "Symbol is required"}
        try:
            result = obb.equity.ownership.institutional(
                symbol=symbol, provider=arguments.get('provider', 'fmp')
            )
            return {"symbol": symbol, "holders": _to_records(result)}
        except Exception as e:
            return {"symbol": symbol, "error": str(e)}

class OpenBBInsiderTradingTool(OpenBBBaseTool):
    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        symbol = arguments.get('symbol', '').upper()
        if not symbol: return {"error": "Symbol is required"}
        try:
            result = obb.equity.ownership.insider_trading(
                symbol=symbol, provider=arguments.get('provider', 'fmp'),
                limit=arguments.get('limit', 20)
            )
            return {"symbol": symbol, "transactions": _to_records(result)}
        except Exception as e:
            return {"symbol": symbol, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# Generic OpenBB Tool — auto-maps tool name to OpenBB SDK command
# ═══════════════════════════════════════════════════════════════════════════

class OpenBBGenericTool(OpenBBBaseTool):
    """Generic OpenBB tool — executes based on tool name mapping to obb.x.y.z()."""

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        obb = _get_obb()
        tool_name = self._name.replace('openbb_', '', 1)

        # Build params from arguments, filtering None values
        params = {k: v for k, v in arguments.items() if v is not None}
        provider = params.pop('provider', self.default_provider)

        try:
            # Map tool names to obb SDK paths
            cmd = self._resolve_command(obb, tool_name)
            if cmd is None:
                return {"tool": self._name, "error": f"No OpenBB command mapping for: {tool_name}"}

            result = cmd(provider=provider, **params)
            records = _to_records(result)
            return {"tool": self._name, "data_points": len(records), "data": records[:100]}
        except Exception as e:
            return {"tool": self._name, "error": str(e)}

    def _resolve_command(self, obb, tool_name):
        """Map tool name to obb.x.y.z function."""
        mappings = {
            'equity_calendar_earnings': lambda **kw: obb.equity.calendar.earnings(**kw),
            'equity_calendar_dividend': lambda **kw: obb.equity.calendar.dividend(**kw),
            'equity_compare_peers': lambda **kw: obb.equity.compare.peers(**kw),
            'equity_estimates_consensus': lambda **kw: obb.equity.estimates.consensus(**kw),
            'equity_share_statistics': lambda **kw: obb.equity.ownership.share_statistics(**kw),
            'equity_revenue_geographic': lambda **kw: obb.equity.fundamental.revenue_per_geography(**kw),
            'equity_revenue_segment': lambda **kw: obb.equity.fundamental.revenue_per_segment(**kw),
            'equity_management': lambda **kw: obb.equity.fundamental.management(**kw),
            'equity_search': lambda **kw: obb.equity.search(**kw),
            'equity_fundamental_overview': lambda **kw: obb.equity.fundamental.overview(**kw),
            'equity_fundamental_ratios': lambda **kw: obb.equity.fundamental.ratios(**kw),
            'equity_price_performance': lambda **kw: obb.equity.price.performance(**kw),
            'equity_discovery_gainers': lambda **kw: obb.equity.discovery.gainers(**kw),
            'equity_discovery_losers': lambda **kw: obb.equity.discovery.losers(**kw),
            'equity_discovery_active': lambda **kw: obb.equity.discovery.active(**kw),
            'currency_snapshots': lambda **kw: obb.currency.snapshots(**kw),
            'crypto_search': lambda **kw: obb.crypto.search(**kw),
            'etf_info': lambda **kw: obb.etf.info(**kw),
            'etf_sectors': lambda **kw: obb.etf.sectors(**kw),
            'etf_countries': lambda **kw: obb.etf.countries(**kw),
            'etf_search': lambda **kw: obb.etf.search(**kw),
            'etf_equity_exposure': lambda **kw: obb.etf.equity_exposure(**kw),
            'fixedincome_ice_bofa': lambda **kw: obb.fixedincome.corporate.ice_bofa(**kw),
            'fixedincome_moody': lambda **kw: obb.fixedincome.corporate.moody(**kw),
            'fixedincome_sofr': lambda **kw: obb.fixedincome.rate.sofr(**kw),
            'fixedincome_estr': lambda **kw: obb.fixedincome.rate.estr(**kw),
            'fixedincome_effr': lambda **kw: obb.fixedincome.rate.effr(**kw),
            'fixedincome_iorb': lambda **kw: obb.fixedincome.rate.iorb(**kw),
            'fixedincome_treasury_auctions': lambda **kw: obb.fixedincome.government.treasury_auctions(**kw),
            'regulators_sec_filings': lambda **kw: obb.regulators.sec.filings(**kw),
            'regulators_sec_search': lambda **kw: obb.regulators.sec.institutions_search(**kw),
            'economy_leading': lambda **kw: obb.economy.composite_leading_indicator(**kw),
            'economy_interest_rate': lambda **kw: obb.economy.short_term_interest_rate(**kw),
            'economy_risk_premium': lambda **kw: obb.economy.risk_premium(**kw),
            'economy_available_indicators': lambda **kw: obb.economy.available_indicators(**kw),
            'economy_calendar': lambda **kw: obb.economy.calendar(**kw),
            'commodity_search': lambda **kw: obb.commodity.search(**kw) if hasattr(obb.commodity, 'search') else {"error": "not available"},
            'commodity_lbma_gold': lambda **kw: obb.commodity.price.historical(symbol='GC=F', **kw),
            'commodity_lbma_silver': lambda **kw: obb.commodity.price.historical(symbol='SI=F', **kw),
            'index_search': lambda **kw: obb.index.search(**kw),
            'index_available': lambda **kw: obb.index.available(**kw),
            'index_price_historical': lambda **kw: obb.index.price.historical(**kw),
            'news_search': lambda **kw: obb.news.world(**kw),
            'derivatives_futures_curve': lambda **kw: obb.derivatives.futures.curve(**kw),
            'derivatives_futures_historical': lambda **kw: obb.derivatives.futures.historical(**kw),
        }
        return mappings.get(tool_name)
