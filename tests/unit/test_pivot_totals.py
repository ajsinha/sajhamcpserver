"""The pivot grand-total row re-aggregates each measure over the underlying rows: SUM and COUNT
add up, AVG is the weighted average (not the average of group averages), MIN/MAX are extremes."""

from types import SimpleNamespace

import pytest

duckdb = pytest.importorskip("duckdb")

from sajha.olap.pivot_engine import PivotEngine, PivotSpec


class StubSemantic:
    """Just enough of SemanticLayer: one dataset over table ``sales``, no named measures."""

    def __init__(self, measures=None):
        self.dataset = SimpleNamespace(source_table="sales", joins=[])
        self.measures = measures or {}

    def get_dataset(self, name):
        return self.dataset if name == "sales" else None

    def get_measure(self, name):
        return self.measures.get(name)

    def resolve_dimension(self, dim, dataset):
        return dim


@pytest.fixture
def conn():
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE sales (region VARCHAR, quarter VARCHAR, amount DOUBLE)")
    # East: 3 rows averaging 20; West: 1 row of 100. Weighted avg = 160/4 = 40, avg of avgs = 60.
    c.execute("INSERT INTO sales VALUES ('East','Q1',10), ('East','Q1',20), ('East','Q2',30), "
              "('West','Q1',100)")
    yield c
    c.close()


def _total(result, row_dim="region"):
    assert result["success"], result
    total = result["data"][-1]
    assert total[row_dim] == "TOTAL"
    return total


@pytest.mark.parametrize("agg,expected", [
    ("SUM", 160), ("AVG", 40), ("COUNT", 4), ("MIN", 10), ("MAX", 100),
])
def test_total_row_uses_each_measures_aggregation(conn, agg, expected):
    spec = PivotSpec(dataset="sales", rows=["region"],
                     values=[{"measure": "amount", "aggregation": agg}])
    result = PivotEngine(StubSemantic(), conn).execute_pivot(spec)
    assert _total(result)["amount"] == pytest.approx(expected)


def test_avg_total_is_weighted_with_pivot_columns(conn):
    spec = PivotSpec(dataset="sales", rows=["region"], columns=["quarter"],
                     values=[{"measure": "amount", "aggregation": "AVG"}])
    result = PivotEngine(StubSemantic(), conn).execute_pivot(spec)
    assert _total(result)["amount"] == pytest.approx(40)


def test_named_non_additive_measure_is_evaluated_over_all_rows(conn):
    sem = StubSemantic({"regions": SimpleNamespace(expression="COUNT(DISTINCT region)")})
    spec = PivotSpec(dataset="sales", rows=["quarter"], values=[{"measure": "regions"}])
    # Q1 has 2 regions, Q2 has 1: summing the groups would say 3, the truth is 2.
    assert _total(PivotEngine(sem, conn).execute_pivot(spec), "quarter")["regions"] == 2


def test_total_respects_filters(conn):
    spec = PivotSpec(dataset="sales", rows=["region"],
                     values=[{"measure": "amount", "aggregation": "AVG"}],
                     filters=[{"dimension": "region", "operator": "=", "value": "East"}])
    assert _total(PivotEngine(StubSemantic(), conn).execute_pivot(spec))["amount"] == pytest.approx(20)


def test_python_fallback_weights_avg_by_row_count():
    engine = PivotEngine(StubSemantic(), connection=None)
    spec = PivotSpec(dataset="sales", rows=["region"],
                     values=[{"measure": "amount", "aggregation": "AVG"},
                             {"measure": "n", "aggregation": "COUNT"}])
    data = [{"region": "East", "amount": 20.0, "n": 3, "_row_count": 3},
            {"region": "West", "amount": 100.0, "n": 1, "_row_count": 1}]
    totals = engine._calculate_totals(data, spec)
    assert totals["amount"] == pytest.approx(40) and totals["n"] == 4
