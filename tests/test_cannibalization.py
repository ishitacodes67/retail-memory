import random
from unittest.mock import MagicMock, patch

import duckdb
import pytest

from retail_memory.tools.cannibalization import (
    _get_depth_correlation,
    _get_pretrend_correlation,
    detect_cannibalization,
)

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def con():
    c = duckdb.connect()

    c.execute("""CREATE TABLE product_store_week (
        store_id BIGINT, week_no BIGINT, product_id BIGINT,
        total_quantity BIGINT, discount_depth DOUBLE,
        is_price_promo BOOLEAN, is_featured BOOLEAN)""")

    c.execute("""CREATE TABLE product_week (
        product_id BIGINT, week_no BIGINT, total_quantity BIGINT,
        net_revenue DOUBLE, list_revenue DOUBLE, n_transactions BIGINT,
        discount_depth DOUBLE, is_price_promo_any_store BOOLEAN,
        is_featured BOOLEAN)""")

    random.seed(42)

    # 25 stores where BOTH products sell.
    for s in range(25):
        for w in range(1, 6):
            a_d = 0.4 + (w * 0.05) + random.uniform(-0.01, 0.01)
            b_d = 0.1 + (w * 0.02) + random.uniform(-0.01, 0.01)
            c.execute(
                "INSERT INTO product_store_week VALUES (?, ?, 1127831, 10, ?, TRUE, FALSE)",
                [s, w, a_d],
            )
            c.execute(
                "INSERT INTO product_store_week VALUES (?, ?, 860299, 5, ?, TRUE, FALSE)",
                [s, w, b_d],
            )
            c.execute(
                "INSERT INTO product_store_week VALUES (?, ?, 1127831, 10, 0.0, FALSE, FALSE)",
                [s, w + 10],
            )
            c.execute(
                "INSERT INTO product_store_week VALUES (?, ?, 860299, 5, 0.0, FALSE, FALSE)",
                [s, w + 10],
            )

    for s in range(1, 10):
        c.execute(
            "INSERT INTO product_week VALUES (1127831, ?, 10, 10.0, 10.0, 1, 0.0, FALSE, FALSE)",
            [s],
        )
        c.execute(
            "INSERT INTO product_week VALUES (860299, ?, 5, 5.0, 5.0, 1, 0.0, FALSE, FALSE)",
            [s],
        )

    yield c
    c.close()


# ---------------------------------------------------------------------------
# Fake connection for isolated helper tests
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, value):
        self._value = value

    def fetchone(self):
        return (self._value,)


class _FakeCon:
    """Mimics enough of duckdb.connect() to exercise the helper functions.

    Records (query, parameters) for each execute() so parameterization can
    be asserted without a real database.
    """

    def __init__(self, value):
        self._value = value
        self.calls = []

    def execute(self, query, parameters=None):
        self.calls.append(
            (query, list(parameters) if parameters is not None else None)
        )
        return _FakeResult(self._value)


# ---------------------------------------------------------------------------
# Core behavior tests
# ---------------------------------------------------------------------------

def test_insufficient_stores_refuses(con):
    res = detect_cannibalization(con, 1127831, 999999)
    assert res.status == "insufficient_data"
    assert res.n_shared_stores == 0


@patch("retail_memory.tools.cannibalization._get_depth_correlation", return_value=0.98)
@patch("retail_memory.tools.cannibalization._get_pretrend_correlation", return_value=0.5)
def test_high_correlation_refuses(mock_trend, mock_depth, con):
    res = detect_cannibalization(con, 1127831, 860299)
    assert res.status == "refused_correlated"
    assert res.depth_correlation == 0.98


@patch("retail_memory.tools.cannibalization._get_depth_correlation", return_value=0.5)
@patch("retail_memory.tools.cannibalization._get_pretrend_correlation", return_value=0.1)
def test_divergent_pretrend_refuses(mock_trend, mock_depth, con):
    res = detect_cannibalization(con, 1127831, 860299)
    assert res.status == "refused_pretrend"
    assert any("pre-trend" in n for n in res.notes)


@patch("retail_memory.tools.cannibalization._get_depth_correlation", return_value=0.5)
@patch("retail_memory.tools.cannibalization._get_pretrend_correlation", return_value=None)
def test_pretrend_none_refuses(mock_trend, mock_depth, con):
    """A NULL from the pre-trend query must produce an explicit refusal."""
    res = detect_cannibalization(con, 1127831, 860299)
    assert res.status == "insufficient_data"
    assert any("Pre-trend check could not be computed" in n for n in res.notes)


def test_insufficient_observations_refuses(con, monkeypatch):
    import retail_memory.tools.cannibalization as mod
    
    # Force the threshold higher than any real fixture row count
    monkeypatch.setattr(mod, "MIN_OBSERVATIONS", 10_000)
    
    with patch.object(mod, "_get_depth_correlation", return_value=0.5), \
         patch.object(mod, "_get_pretrend_correlation", return_value=0.5):
        res = detect_cannibalization(con, 1127831, 860299)
        
    assert res.status == "insufficient_data"
    assert any("observations" in n.lower() for n in res.notes)
    # Explicitly assert we did NOT hit the singular matrix branch
    assert not any("Rank-deficient" in n for n in res.notes)


@patch("retail_memory.tools.cannibalization._get_depth_correlation", return_value=0.5)
@patch("retail_memory.tools.cannibalization._get_pretrend_correlation", return_value=0.5)
def test_clean_case_returns_estimate(mock_trend, mock_depth, con):
    res = detect_cannibalization(con, 1127831, 860299)
    assert res.status == "estimated"
    assert res.coefficient is not None
    assert res.confidence in ("high", "low")


@patch("retail_memory.tools.cannibalization._get_depth_correlation", return_value=0.5)
@patch("retail_memory.tools.cannibalization._get_pretrend_correlation", return_value=0.5)
def test_singular_matrix_refuses(mock_trend, mock_depth, con):
    import warnings

    from statsmodels.tools.sm_exceptions import SingularMatrixWarning

    with patch("retail_memory.tools.cannibalization.smf.ols") as mock_ols:
        def mock_fit(*args, **kwargs):
            warnings.warn("mock singular", SingularMatrixWarning)
            return MagicMock()

        mock_ols.return_value.fit.side_effect = mock_fit

        res = detect_cannibalization(con, 1127831, 860299)
        assert res.status == "insufficient_data"
        assert any("Rank-deficient" in n for n in res.notes)


@patch("retail_memory.tools.cannibalization._get_depth_correlation", return_value=0.5)
@patch("retail_memory.tools.cannibalization._get_pretrend_correlation", return_value=0.5)
def test_regression_error_refuses(mock_trend, mock_depth, con):
    with patch("retail_memory.tools.cannibalization.smf.ols") as mock_ols:
        mock_ols.return_value.fit.side_effect = Exception("Mocked regression crash")
        res = detect_cannibalization(con, 1127831, 860299)
        assert res.status == "insufficient_data"
        assert any("Regression failed to converge" in n for n in res.notes)


# ---------------------------------------------------------------------------
# NaN / NULL handling in helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value", [None, float("nan")])
@pytest.mark.parametrize(
    "fn",
    [_get_pretrend_correlation, _get_depth_correlation],
    ids=["pretrend", "depth"],
)
def test_undefined_correlation_returns_none(fn, value):
    """NaN or NULL from SQL must be returned as None, never a numeric fallback."""
    con = _FakeCon(value)
    assert fn(con, 123, 456) is None


# ---------------------------------------------------------------------------
# NaN must reach the refusal path in detect_cannibalization
# ---------------------------------------------------------------------------

@patch("retail_memory.tools.cannibalization._get_depth_correlation", return_value=0.5)
@patch(
    "retail_memory.tools.cannibalization._get_pretrend_correlation",
    return_value=float("nan"),
)
def test_pretrend_nan_refuses(mock_trend, mock_depth, con):
    """If the pre-trend check returns NaN (not None), still refuse."""
    res = detect_cannibalization(con, 1127831, 860299)
    assert res.status == "insufficient_data"
    assert any("pre-trend" in n.lower() for n in res.notes)
    assert res.coefficient is None
    assert res.ci_low is None
    assert res.ci_high is None


@patch("retail_memory.tools.cannibalization._get_depth_correlation", return_value=None)
@patch("retail_memory.tools.cannibalization._get_pretrend_correlation", return_value=0.5)
def test_depth_none_refuses_with_variance_note(mock_trend, mock_depth, con):
    """Depth NULL must refuse with a variance/measurement note, not lockstep."""
    res = detect_cannibalization(con, 1127831, 860299)
    assert res.status == "insufficient_data"
    assert res.coefficient is None
    assert any(
        ("variance" in n.lower())
        or ("could not be computed" in n.lower())
        or ("no price" in n.lower())
        for n in res.notes
    )
    assert not any("lockstep" in n.lower() for n in res.notes)


@patch(
    "retail_memory.tools.cannibalization._get_depth_correlation",
    return_value=float("nan"),
)
@patch("retail_memory.tools.cannibalization._get_pretrend_correlation", return_value=0.5)
def test_depth_nan_refuses(mock_trend, mock_depth, con):
    """NaN depth correlation must not slip through as a passing check."""
    res = detect_cannibalization(con, 1127831, 860299)
    assert res.status == "insufficient_data"
    assert res.coefficient is None


# ---------------------------------------------------------------------------
# Parameterization and SQL strictness
# ---------------------------------------------------------------------------

def test_pretrend_query_is_parameterized():
    con = _FakeCon(0.5)
    _get_pretrend_correlation(con, 123, 456)

    assert len(con.calls) == 1
    query, params = con.calls[0]
    assert "?" in query
    assert "123" not in query
    assert "456" not in query
    assert params is not None
    assert 123 in params
    assert 456 in params
    assert "NOT isnan(corr)" in query, "SQL must filter NaN before MEDIAN"


def test_depth_query_is_parameterized():
    con = _FakeCon(0.5)
    _get_depth_correlation(con, 123, 456)

    assert len(con.calls) == 1
    query, params = con.calls[0]
    assert "?" in query
    assert "123" not in query
    assert "456" not in query
    assert params is not None
    assert 123 in params
    assert 456 in params


def test_duckdb_median_isnan_behavior():
    """Proves that DuckDB MEDIAN() skews when NaNs are included, and that
    filtering with NOT isnan() corrects it."""
    c = duckdb.connect()
    c.execute("CREATE TABLE test_vals (v DOUBLE)")
    
    # 5 valid values (true median 0.3) + 2 NaNs
    c.executemany(
        "INSERT INTO test_vals VALUES (?)",
        [[0.1], [0.2], [0.3], [0.4], [0.5], [float("nan")], [float("nan")]]
    )
    
    # The old, broken behavior: includes NaNs, shifting the median
    res_with_nan = c.execute("SELECT MEDIAN(v) FROM test_vals").fetchone()[0]
    
    # The fixed behavior: filters NaNs
    res_without_nan = c.execute(
        "SELECT MEDIAN(v) FROM test_vals WHERE NOT isnan(v)"
    ).fetchone()[0]
    
    assert res_without_nan == 0.3
    assert res_with_nan != 0.3, "DuckDB MEDIAN() unexpectedly ignored NaN"
    assert res_with_nan > 0.3, "Median skewed upward by NaN"
    
    c.close()