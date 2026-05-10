"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Financial Calculator MCP Tools — Pure Python, No API keys required

Compound interest, NPV, IRR, bond pricing, options (Black-Scholes),
WACC, loan amortization, Sharpe/Sortino ratios, Monte Carlo, DCF, etc.
"""

import math, logging
from typing import Dict, Any, List
from sajha.tools.base_mcp_tool import BaseMCPTool

logger = logging.getLogger(__name__)

class CalcBaseTool(BaseMCPTool):
    def __init__(self, config=None):
        super().__init__(config)
    def get_input_schema(self): return self._input_schema
    def get_output_schema(self): return self._output_schema

class CalcCompoundInterestTool(CalcBaseTool):
    def execute(self, a):
        P, r, n, t = a['principal'], a['rate']/100, a.get('compounds_per_year',12), a['years']
        fv = P * (1 + r/n)**(n*t)
        return {"principal": P, "rate": a['rate'], "years": t, "future_value": round(fv,2), "total_interest": round(fv-P,2)}

class CalcPresentValueTool(CalcBaseTool):
    def execute(self, a):
        fv, r, t = a['future_value'], a['rate']/100, a['years']
        pv = fv / (1 + r)**t
        return {"future_value": fv, "rate": a['rate'], "years": t, "present_value": round(pv,2)}

class CalcFutureValueTool(CalcBaseTool):
    def execute(self, a):
        pv, r, t = a['present_value'], a['rate']/100, a['years']
        fv = pv * (1 + r)**t
        return {"present_value": pv, "rate": a['rate'], "years": t, "future_value": round(fv,2)}

class CalcNPVTool(CalcBaseTool):
    def execute(self, a):
        rate = a['discount_rate']/100
        cfs = a['cash_flows']  # list: [initial_investment(negative), cf1, cf2, ...]
        npv = sum(cf / (1+rate)**i for i, cf in enumerate(cfs))
        return {"discount_rate": a['discount_rate'], "cash_flows": cfs, "npv": round(npv,2)}

class CalcIRRTool(CalcBaseTool):
    def execute(self, a):
        cfs = a['cash_flows']
        lo, hi = -0.5, 5.0
        for _ in range(200):
            mid = (lo+hi)/2
            npv = sum(cf/(1+mid)**i for i, cf in enumerate(cfs))
            if abs(npv) < 0.01: break
            if npv > 0: lo = mid
            else: hi = mid
        return {"cash_flows": cfs, "irr": round(mid*100, 4)}

class CalcLoanAmortizationTool(CalcBaseTool):
    def execute(self, a):
        P, r, n = a['principal'], a['annual_rate']/100/12, a['months']
        pmt = P * r * (1+r)**n / ((1+r)**n - 1) if r > 0 else P/n
        total = pmt * n
        return {"principal": P, "monthly_payment": round(pmt,2), "total_paid": round(total,2),
                "total_interest": round(total-P,2), "months": n}

class CalcBondPriceTool(CalcBaseTool):
    def execute(self, a):
        fv, c, y, n = a['face_value'], a['coupon_rate']/100, a['yield_rate']/100, a['years']
        coupon = fv * c / 2
        price = sum(coupon/(1+y/2)**i for i in range(1, n*2+1)) + fv/(1+y/2)**(n*2)
        return {"face_value": fv, "coupon_rate": a['coupon_rate'], "yield": a['yield_rate'], "price": round(price,2)}

class CalcBlackScholesTool(CalcBaseTool):
    def execute(self, a):
        S, K, T, r, sigma = a['stock_price'], a['strike'], a['time_years'], a['risk_free_rate']/100, a['volatility']/100
        d1 = (math.log(S/K) + (r + sigma**2/2)*T) / (sigma*math.sqrt(T))
        d2 = d1 - sigma*math.sqrt(T)
        def N(x):
            return (1 + math.erf(x/math.sqrt(2)))/2
        call = S*N(d1) - K*math.exp(-r*T)*N(d2)
        put = K*math.exp(-r*T)*N(-d2) - S*N(-d1)
        return {"call_price": round(call,4), "put_price": round(put,4), "d1": round(d1,4), "d2": round(d2,4)}

class CalcWACCTool(CalcBaseTool):
    def execute(self, a):
        E, D = a['equity_value'], a['debt_value']
        Re, Rd, tax = a['cost_of_equity']/100, a['cost_of_debt']/100, a['tax_rate']/100
        V = E + D
        wacc = (E/V)*Re + (D/V)*Rd*(1-tax)
        return {"wacc": round(wacc*100, 4), "equity_weight": round(E/V,4), "debt_weight": round(D/V,4)}

class CalcSharpeRatioTool(CalcBaseTool):
    def execute(self, a):
        ret, rf, vol = a['portfolio_return']/100, a['risk_free_rate']/100, a['volatility']/100
        sharpe = (ret - rf) / vol if vol > 0 else 0
        return {"sharpe_ratio": round(sharpe, 4)}

class CalcSortinoRatioTool(CalcBaseTool):
    def execute(self, a):
        ret, rf, dv = a['portfolio_return']/100, a['risk_free_rate']/100, a['downside_deviation']/100
        sortino = (ret - rf) / dv if dv > 0 else 0
        return {"sortino_ratio": round(sortino, 4)}

class CalcCAPMTool(CalcBaseTool):
    def execute(self, a):
        rf, beta, rm = a['risk_free_rate']/100, a['beta'], a['market_return']/100
        expected = rf + beta * (rm - rf)
        return {"expected_return": round(expected*100, 4), "risk_premium": round((rm-rf)*100, 4)}

class CalcDCFModelTool(CalcBaseTool):
    def execute(self, a):
        fcf, g, wacc, tg = a['free_cash_flow'], a['growth_rate']/100, a['wacc']/100, a.get('terminal_growth',2)/100
        years = a.get('projection_years', 5)
        pvs = []
        for i in range(1, years+1):
            projected = fcf * (1+g)**i
            pv = projected / (1+wacc)**i
            pvs.append(round(pv, 2))
        terminal = (fcf*(1+g)**years*(1+tg)) / (wacc - tg)
        terminal_pv = terminal / (1+wacc)**years
        ev = sum(pvs) + terminal_pv
        return {"enterprise_value": round(ev,2), "pv_cash_flows": sum(pvs), "terminal_value_pv": round(terminal_pv,2)}

class CalcRetirementTool(CalcBaseTool):
    def execute(self, a):
        current, annual, rate, years = a['current_savings'], a['annual_contribution'], a['return_rate']/100, a['years']
        balance = current
        for _ in range(years):
            balance = balance * (1+rate) + annual
        return {"final_balance": round(balance,2), "total_contributed": current + annual*years,
                "investment_growth": round(balance - current - annual*years, 2)}

class CalcMaxDrawdownTool(CalcBaseTool):
    def execute(self, a):
        values = a['portfolio_values']
        peak = values[0]
        max_dd = 0
        for v in values:
            peak = max(peak, v)
            dd = (peak - v) / peak
            max_dd = max(max_dd, dd)
        return {"max_drawdown": round(max_dd*100, 4)}

class CalcCorrelationTool(CalcBaseTool):
    def execute(self, a):
        x, y = a['series_x'], a['series_y']
        n = min(len(x), len(y))
        x, y = x[:n], y[:n]
        mx, my = sum(x)/n, sum(y)/n
        cov = sum((x[i]-mx)*(y[i]-my) for i in range(n)) / n
        sx = (sum((xi-mx)**2 for xi in x)/n)**0.5
        sy = (sum((yi-my)**2 for yi in y)/n)**0.5
        corr = cov / (sx*sy) if sx*sy > 0 else 0
        return {"correlation": round(corr, 6), "data_points": n}

class CalcBetaTool(CalcBaseTool):
    def execute(self, a):
        stock, market = a['stock_returns'], a['market_returns']
        n = min(len(stock), len(market))
        stock, market = stock[:n], market[:n]
        ms, mm = sum(stock)/n, sum(market)/n
        cov = sum((stock[i]-ms)*(market[i]-mm) for i in range(n)) / n
        var_m = sum((m-mm)**2 for m in market) / n
        beta = cov / var_m if var_m > 0 else 1
        return {"beta": round(beta, 4), "data_points": n}

class CalcCurrencyConverterTool(CalcBaseTool):
    def execute(self, a):
        import urllib.request, json
        fr, to, amt = a.get('from','USD'), a.get('to','EUR'), a.get('amount',1)
        try:
            url = f"https://open.er-api.com/v6/latest/{fr}"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
                rate = data['rates'].get(to, 1)
                return {"from": fr, "to": to, "amount": amt, "rate": rate, "converted": round(amt*rate, 4)}
        except Exception as e:
            return {"error": str(e)}

class CalcPercentageChangeTool(CalcBaseTool):
    def execute(self, a):
        old, new = a['old_value'], a['new_value']
        change = ((new - old) / abs(old)) * 100 if old != 0 else 0
        return {"old_value": old, "new_value": new, "percentage_change": round(change, 4)}
