"""
Step 5: SQL Validator / Guardrails
Non-negotiable safety layer. Runs AFTER generation, BEFORE execution.
Parses the query into an AST with sqlglot instead of trusting regex.

Checks:
  1. exactly one statement, and it is a SELECT (or UNION of SELECTs)
  2. no write/DDL/command nodes anywhere in the tree (incl. inside CTEs)
  3. every table exists (CTE names and derived tables are understood)
  4. every column exists on the table it is qualified with, or on at least
     one table actually referenced in the query (not any table in the DB)
  5. LIMIT injected / capped
  6. join-count complexity guard

ValidationResult.retryable tells the pipeline whether feeding the error back
to the LLM is worthwhile (schema/parse mistakes) or pointless (safety violations).
"""
import sqlglot
from sqlglot import exp

MAX_ROW_LIMIT = 500
DEFAULT_LIMIT = 100
MAX_JOINS = 5

_BLOCKED_NAMES = (
    "Insert", "Update", "Delete", "Drop", "Alter", "Create",
    "Merge", "Command", "TruncateTable", "Pragma",
)
# hasattr filter keeps this working across sqlglot versions
BLOCKED_STATEMENT_TYPES = tuple(
    getattr(exp, name) for name in _BLOCKED_NAMES if hasattr(exp, name)
)


class ValidationResult:
    def __init__(self, is_valid: bool, sql: str = "", reason: str = "", retryable: bool = False):
        self.is_valid = is_valid
        self.sql = sql            # possibly modified (e.g. LIMIT injected)
        self.reason = reason
        self.retryable = retryable

    def __repr__(self):
        return (f"ValidationResult(is_valid={self.is_valid}, "
                f"reason='{self.reason}', retryable={self.retryable})")


def _fail(reason: str, retryable: bool = False) -> ValidationResult:
    return ValidationResult(False, reason=reason, retryable=retryable)


def _output_columns(node) -> set:
    """Column names a CTE / derived table exposes. {'*'} means 'unknown'."""
    try:
        return {name.lower() for name in node.named_selects}
    except Exception:
        return {"*"}


def validate_sql(sql: str, allowed_schema: dict, dialect: str = "sqlite") -> ValidationResult:
    if not sql or not sql.strip():
        return _fail("Empty SQL generated", retryable=True)

    # --- parse: exactly one statement ---
    try:
        statements = [s for s in sqlglot.parse(sql, dialect=dialect) if s is not None]
    except Exception as e:
        return _fail(f"SQL failed to parse: {e}", retryable=True)

    if len(statements) != 1:
        return _fail("Exactly one SQL statement is allowed")
    parsed = statements[0]

    # --- 1. SELECT only ---
    if not isinstance(parsed, (exp.Select, exp.Union)):
        return _fail("Only SELECT statements are allowed")

    for blocked in BLOCKED_STATEMENT_TYPES:
        if parsed.find(blocked):
            return _fail(f"Blocked statement type: {blocked.__name__}")

    # --- schema lookup: table -> set of lowercase column names ---
    table_cols = {
        table.lower(): {c[0].lower() for c in info["columns"]}
        for table, info in allowed_schema.items()
    }

    # --- CTEs and derived tables ---
    cte_cols = {}
    for cte in parsed.find_all(exp.CTE):
        cte_cols[cte.alias_or_name.lower()] = _output_columns(cte.this)

    derived_cols = dict(cte_cols)  # alias -> output columns (CTEs, subquery aliases)
    for sub in parsed.find_all(exp.Subquery):
        if sub.alias:
            derived_cols[sub.alias.lower()] = _output_columns(sub.this)

    # --- 2. table existence + alias map ---
    alias_to_tables = {}   # alias or real name -> {real table names}
    referenced = set()     # real tables used anywhere in the query
    unknown = set()

    for t in parsed.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):
            return _fail("Table-valued functions are not allowed")
        name = t.name.lower()

        if name in cte_cols:                       # reference to a CTE, not a real table
            if t.alias:
                derived_cols[t.alias.lower()] = cte_cols[name]
            continue

        if name not in table_cols:
            unknown.add(name)
            continue

        referenced.add(name)
        alias_to_tables.setdefault(name, set()).add(name)
        if t.alias:
            alias_to_tables.setdefault(t.alias.lower(), set()).add(name)

    if unknown:
        return _fail(f"Unknown table(s) referenced: {sorted(unknown)}", retryable=True)

    # --- 3. column existence (per-table, best effort) ---
    allowed_unqualified = set()
    for t in referenced:
        allowed_unqualified |= table_cols[t]
    allowed_unqualified |= {a.alias_or_name.lower() for a in parsed.find_all(exp.Alias)}
    for cols in derived_cols.values():
        allowed_unqualified |= cols
    if any("*" in cols for cols in derived_cols.values()):
        # SELECT * inside a CTE/derived table: its columns are unknown, so
        # fall back to "any column in the schema" for unqualified names
        for cols in table_cols.values():
            allowed_unqualified |= cols

    for col in parsed.find_all(exp.Column):
        name = col.name.lower()
        qualifier = col.table.lower() if col.table else ""

        if qualifier:
            if qualifier in alias_to_tables:
                if name == "*":
                    continue
                valid_cols = set()
                for t in alias_to_tables[qualifier]:
                    valid_cols |= table_cols[t]
                if name not in valid_cols:
                    return _fail(
                        f"Unknown column '{name}' on table/alias '{qualifier}'", retryable=True
                    )
            elif qualifier in derived_cols:
                continue  # CTE / subquery output — can't verify further
            else:
                return _fail(f"Unknown table or alias '{qualifier}'", retryable=True)
        else:
            if name == "*" or name in allowed_unqualified:
                continue
            return _fail(f"Unknown column referenced: '{name}'", retryable=True)

    # --- 4. row limit: inject if missing, cap if excessive (top-level only) ---
    limit_node = parsed.args.get("limit")
    if limit_node is None:
        parsed = parsed.limit(DEFAULT_LIMIT)
    else:
        try:
            if int(limit_node.expression.name) > MAX_ROW_LIMIT:
                parsed.set("limit", exp.Limit(expression=exp.Literal.number(MAX_ROW_LIMIT)))
        except (ValueError, AttributeError):
            pass  # non-numeric limit: leave it, the DB will complain

    # --- 5. complexity guard ---
    join_count = len(list(parsed.find_all(exp.Join)))
    if join_count > MAX_JOINS:
        return _fail(f"Query too complex: {join_count} joins exceeds limit of {MAX_JOINS}")

    return ValidationResult(True, sql=parsed.sql(dialect=dialect), reason="Passed all checks")


if __name__ == "__main__":
    from backend.schema.schema_rag import get_full_schema

    schema = get_full_schema()
    for t in [
        "SELECT name FROM customers LIMIT 10",
        "DROP TABLE customers",
        "SELECT * FROM fake_table",
        "SELECT o.city FROM orders o",
        "WITH t AS (SELECT customer_id, SUM(amount) AS total FROM orders GROUP BY customer_id) "
        "SELECT COUNT(*) FROM t",
    ]:
        print(t, "->", validate_sql(t, schema))