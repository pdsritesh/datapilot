import pytest
from backend.validator.sql_validator import validate_sql

SCHEMA = {
    "customers": {"columns": [
        ("customer_id", "INTEGER"), ("name", "TEXT"), ("email", "TEXT"),
        ("phone", "INTEGER"), ("city", "TEXT"), ("signup_date", "TEXT"),
    ]},
    "orders": {"columns": [
        ("order_id", "INTEGER"), ("customer_id", "INTEGER"), ("item_name", "TEXT"),
        ("category", "TEXT"), ("quantity", "INTEGER"), ("amount", "REAL"),
        ("payment_method", "TEXT"), ("order_date", "TEXT"),
    ]},
}


def check(sql):
    return validate_sql(sql, SCHEMA, dialect="sqlite")


# ---------- should pass ----------
def test_simple_select_passes_and_gets_limit():
    r = check("SELECT name FROM customers")
    assert r.is_valid
    assert "LIMIT 100" in r.sql.upper()


def test_join_with_aliases_passes():
    r = check(
        "SELECT c.name, SUM(o.amount) AS total FROM customers c "
        "JOIN orders o ON c.customer_id = o.customer_id "
        "GROUP BY c.name ORDER BY total DESC LIMIT 5"
    )
    assert r.is_valid, r.reason


def test_cte_names_are_not_unknown_tables():
    # the exact failure from the eval: customers_below_average_spend
    r = check(
        "WITH customer_totals AS (SELECT customer_id, SUM(amount) AS total FROM orders GROUP BY customer_id), "
        "avg_total AS (SELECT AVG(total) AS avg_spend FROM customer_totals) "
        "SELECT COUNT(*) FROM customer_totals WHERE total < (SELECT avg_spend FROM avg_total)"
    )
    assert r.is_valid, r.reason


def test_derived_table_passes():
    r = check("SELECT t.total FROM (SELECT SUM(amount) AS total FROM orders) AS t")
    assert r.is_valid, r.reason


def test_limit_is_capped():
    r = check("SELECT name FROM customers LIMIT 5000")
    assert r.is_valid
    assert "LIMIT 500" in r.sql.upper()
    assert "5000" not in r.sql


# ---------- should fail: schema mistakes (retryable) ----------
def test_unknown_table():
    r = check("SELECT * FROM fake_table")
    assert not r.is_valid and r.retryable


def test_unknown_column():
    r = check("SELECT salary FROM customers")
    assert not r.is_valid and r.retryable


def test_column_on_wrong_table():
    # city exists in the DB, but not on orders
    r = check("SELECT o.city FROM orders o")
    assert not r.is_valid and r.retryable


def test_unknown_alias():
    r = check("SELECT x.name FROM customers c")
    assert not r.is_valid and r.retryable


# ---------- should fail: safety violations (not retryable) ----------
@pytest.mark.parametrize("sql", [
    "DROP TABLE customers",
    "DELETE FROM customers",
    "UPDATE customers SET name = 'x'",
    "INSERT INTO customers (name) VALUES ('x')",
    "SELECT name FROM customers; DROP TABLE customers",
    "PRAGMA table_info(customers)",
])
def test_unsafe_statements_blocked(sql):
    r = check(sql)
    assert not r.is_valid and not r.retryable


def test_too_many_joins():
    joins = " ".join(f"JOIN orders o{i} ON o{i}.customer_id = c.customer_id" for i in range(6))
    r = check(f"SELECT c.name FROM customers c {joins}")
    assert not r.is_valid


def test_empty_sql():
    assert not check("").is_valid