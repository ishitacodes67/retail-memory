import duckdb
import pytest
from retail_memory.tools.cannibalization import detect_cannibalization

@pytest.fixture
def con():
    c = duckdb.connect()
    # Minimal tables for tool logic
    c.execute("""CREATE TABLE product_store_week (
        store_id BIGINT, week_no BIGINT, product_id BIGINT, 
        total_quantity BIGINT, discount_depth DOUBLE, 
        is_price_promo BOOLEAN, is_featured BOOLEAN)""")
    
    # Insert 25 stores where BOTH products sell (clears shared store guardrail)
    for s in range(25):
        for w in range(1, 6):
            # A is on promo (depth 0.5), B is on promo (depth 0.5)
            c.execute("INSERT INTO product_store_week VALUES (?, ?, 1127831, 10, 0.5, TRUE, FALSE)", [s, w])
            c.execute("INSERT INTO product_store_week VALUES (?, ?, 860299, 5, 0.5, TRUE, FALSE)", [s, w])
            
            # Add some non-promo weeks to establish baseline
            c.execute("INSERT INTO product_store_week VALUES (?, ?, 1127831, 10, 0.0, FALSE, FALSE)", [s, w+10])
            c.execute("INSERT INTO product_store_week VALUES (?, ?, 860299, 5, 0.0, FALSE, FALSE)", [s, w+10])
    yield c
    c.close()

def test_high_correlation_refuses(con):
    # Because depth_A and depth_B are perfectly correlated (both 0.5 in promo weeks)
    res = detect_cannibalization(con, 1127831, 860299)
    assert res.status == "refused_correlated"
    assert res.depth_correlation == pytest.approx(1.0)

def test_insufficient_stores_refuses(con):
    # Query a fake neighbor that doesn't share the 25 stores
    res = detect_cannibalization(con, 1127831, 999999)
    assert res.status == "insufficient_data"
    assert res.n_shared_stores == 0