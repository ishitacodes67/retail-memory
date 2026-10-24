import duckdb
import pytest
import random
from unittest.mock import patch, MagicMock
from retail_memory.tools.cannibalization import detect_cannibalization

@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("""CREATE TABLE product_store_week (
        store_id BIGINT, week_no BIGINT, product_id BIGINT, 
        total_quantity BIGINT, discount_depth DOUBLE, 
        is_price_promo BOOLEAN, is_featured BOOLEAN)""")
    
    random.seed(42)
    
    # 25 stores where BOTH products sell. 
    # We add random noise to A and B's depths so they aren't perfectly collinear with week_no.
    for s in range(25):
        for w in range(1, 6):
            a_d = 0.4 + (w * 0.05) + random.uniform(-0.01, 0.01)
            b_d = 0.1 + (w * 0.02) + random.uniform(-0.01, 0.01)
            c.execute("INSERT INTO product_store_week VALUES (?, ?, 1127831, 10, ?, TRUE, FALSE)", [s, w, a_d])
            c.execute("INSERT INTO product_store_week VALUES (?, ?, 860299, 5, ?, TRUE, FALSE)", [s, w, b_d])
            
            # Add non-promo weeks to establish baseline for the regression
            c.execute("INSERT INTO product_store_week VALUES (?, ?, 1127831, 10, 0.0, FALSE, FALSE)", [s, w+10])
            c.execute("INSERT INTO product_store_week VALUES (?, ?, 860299, 5, 0.0, FALSE, FALSE)", [s, w+10])
    yield c
    c.close()

def test_insufficient_stores_refuses(con):
    # Query a neighbor with 0 shared stores
    res = detect_cannibalization(con, 1127831, 999999)
    assert res.status == "insufficient_data"
    assert res.n_shared_stores == 0

@patch("retail_memory.tools.cannibalization._get_depth_correlation", return_value=0.98)
def test_high_correlation_refuses(mock_corr, con):
    res = detect_cannibalization(con, 1127831, 860299)
    assert res.status == "refused_correlated"
    assert res.depth_correlation == 0.98

@patch("retail_memory.tools.cannibalization._get_depth_correlation", return_value=0.5)
def test_insufficient_observations_refuses(mock_corr, con):
    # Add a product that shares stores but has no variance in depth
    for s in range(25):
        con.execute("INSERT INTO product_store_week VALUES (?, 1, 777777, 5, 0.1, TRUE, FALSE)", [s])
    res = detect_cannibalization(con, 1127831, 777777)
    assert res.status == "insufficient_data"

@patch("retail_memory.tools.cannibalization._get_depth_correlation", return_value=0.5)
def test_clean_case_returns_estimate(mock_corr, con):
    res = detect_cannibalization(con, 1127831, 860299)
    assert res.status == "estimated"
    assert res.coefficient is not None
    assert res.confidence in ("high", "low")

@patch("retail_memory.tools.cannibalization._get_depth_correlation", return_value=0.5)
def test_singular_matrix_refuses(mock_corr, con):
    from statsmodels.tools.sm_exceptions import SingularMatrixWarning
    import warnings
    
    with patch("retail_memory.tools.cannibalization.smf.ols") as mock_ols:
        def mock_fit(*args, **kwargs):
            warnings.warn("mock singular", SingularMatrixWarning)
            return MagicMock()
        mock_ols.return_value.fit.side_effect = mock_fit
        
        res = detect_cannibalization(con, 1127831, 860299)
        assert res.status == "insufficient_data"
        assert any("Rank-deficient" in n for n in res.notes)

@patch("retail_memory.tools.cannibalization._get_depth_correlation", return_value=0.5)
def test_regression_error_refuses(mock_corr, con):
    with patch("retail_memory.tools.cannibalization.smf.ols") as mock_ols:
        mock_ols.return_value.fit.side_effect = Exception("Mocked regression crash")
        
        res = detect_cannibalization(con, 1127831, 860299)
        assert res.status == "insufficient_data"
        assert any("Regression failed to converge" in n for n in res.notes)