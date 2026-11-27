"""
Step 6: Execution Engine
Executes VALIDATED SQL only. Never call this directly on raw LLM output.

SQLite has no Postgres-style read-only roles, so the connection is opened in
read-only mode via URI (mode=ro). For Postgres in production, connect with a
dedicated read-only DB role.
"""
import os
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "sample.db")
QUERY_TIMEOUT_SECONDS = 5


class ExecutionResult:
    def __init__(self, success: bool, rows=None, columns=None, error: str = "",
                 execution_time_ms: float = 0, raw_error: str = ""):
        self.success = success
        self.rows = rows or []
        self.columns = columns or []
        self.error = error              # sanitized, safe to show the user
        self.raw_error = raw_error      # internal only — fed back to the LLM on retry
        self.execution_time_ms = execution_time_ms

    def __repr__(self):
        return f"ExecutionResult(success={self.success}, rows={len(self.rows)}, error='{self.error}')"


def execute_query(sql: str, db_path: str = DB_PATH, session_id: str = None) -> ExecutionResult:
    """
    If session_id is connected to a real PostgreSQL database, routes execution
    there. Otherwise runs against the demo SQLite file.
    """
    if session_id:
        from backend.db.connection_manager import get_session, POSTGRES_MODE
        session = get_session(session_id)
        if session.mode == POSTGRES_MODE:
            from backend.db.postgres_connector import execute_query_postgres
            return execute_query_postgres(session.engine, sql)

    start = time.time()
    conn = None
    try:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=QUERY_TIMEOUT_SECONDS)

        # enforce a real statement timeout (connect(timeout=) only covers lock waits)
        deadline = start + QUERY_TIMEOUT_SECONDS
        conn.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 10000)

        cur = conn.cursor()
        cur.execute(sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()

        elapsed = (time.time() - start) * 1000
        return ExecutionResult(True, rows=rows, columns=columns, execution_time_ms=round(elapsed, 2))

    except sqlite3.Error as e:
        elapsed = (time.time() - start) * 1000
        return ExecutionResult(
            False,
            error="Query execution failed",
            raw_error=str(e),
            execution_time_ms=round(elapsed, 2),
        )
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    result = execute_query("SELECT name, city FROM customers LIMIT 5")
    print(result, result.columns, result.rows)