"""
A "version 5" of calc_percentage_change for Tutorial 23 (docs/tutorials/TUTORIAL_23_test_and_canary_your_tools.md):
rounds to two places and says which way the value moved. ``FlakyPercentChange`` fails every
call, to watch the canary roll back.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from sajha.tools.impl.calc_tools import CalcBaseTool


class PercentChangeV2(CalcBaseTool):
    def execute(self, a):
        old, new = a['old_value'], a['new_value']
        change = ((new - old) / abs(old)) * 100 if old != 0 else 0.0
        direction = 'up' if change > 0 else 'down' if change < 0 else 'flat'
        return {'old_value': old, 'new_value': new, 'percentage_change': round(change, 2), 'direction': direction}


class FlakyPercentChange(CalcBaseTool):
    def execute(self, a):
        raise RuntimeError('upstream unavailable (FlakyPercentChange always fails)')
