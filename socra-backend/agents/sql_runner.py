"""Small in-memory SQLite evaluator for generated SQL exercises.

Student SQL runs against a disposable database. Only read-only SELECT queries
and a short allow-list of scalar/aggregate functions are permitted.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from typing import Any


_SETUP_STATEMENT = re.compile(r"^\s*(CREATE\s+TABLE|INSERT\s+INTO)\b", re.IGNORECASE)
_READ_QUERY = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_SAFE_FUNCTIONS = {
    "abs", "avg", "coalesce", "count", "ifnull", "length", "lower",
    "max", "min", "round", "substr", "sum", "trim", "typeof", "upper",
}
_ALLOWED_SETUP_ACTIONS = {
    sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_INSERT, sqlite3.SQLITE_READ,
    sqlite3.SQLITE_SELECT, sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_UPDATE,
}
_ALLOWED_QUERY_ACTIONS = {
    sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, "SQLITE_RECURSIVE", -1),
}


def _authorizer(allowed_actions: set[int], *, deny_internal_tables: bool = True):
    def authorize(action: int, arg1: str | None, arg2: str | None, _db: str | None, _source: str | None) -> int:
        if action not in allowed_actions:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_UPDATE and str(arg1 or "").casefold() not in {"sqlite_master", "sqlite_schema"}:
            return sqlite3.SQLITE_DENY
        if deny_internal_tables and action == sqlite3.SQLITE_READ and str(arg1 or "").casefold().startswith("sqlite_"):
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            function = str(arg2 or arg1 or "").casefold()
            if function not in _SAFE_FUNCTIONS:
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    return authorize


def _open_database(setup_statements: list[str]) -> sqlite3.Connection:
    if not isinstance(setup_statements, list) or not 1 <= len(setup_statements) <= 20:
        raise ValueError("SQL exercises need between 1 and 20 schema/data statements")
    if sum(len(statement) for statement in setup_statements) > 12_000:
        raise ValueError("SQL exercise setup is too large")

    connection = sqlite3.connect(":memory:")
    connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 100_000)
    connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 10_000)
    connection.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 20)
    connection.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
    connection.set_progress_handler(lambda: 1, 100_000)
    connection.set_authorizer(_authorizer(_ALLOWED_SETUP_ACTIONS, deny_internal_tables=False))
    try:
        for statement in setup_statements:
            if not isinstance(statement, str) or len(statement) > 3_000 or not _SETUP_STATEMENT.match(statement):
                raise ValueError("SQL setup may only create tables and insert sample rows")
            connection.execute(statement)
        connection.commit()
        connection.set_authorizer(None)
        connection.execute("PRAGMA query_only = ON")
        connection.set_authorizer(_authorizer(_ALLOWED_QUERY_ACTIONS))
        return connection
    except sqlite3.Error as exc:
        connection.close()
        raise ValueError("SQL exercise schema or sample data could not be prepared safely") from exc
    except Exception:
        connection.close()
        raise


def run_readonly_sql(setup_statements: list[str], query: str) -> dict[str, Any]:
    """Run one bounded read-only query and return normalized column/row data."""
    if not isinstance(query, str) or len(query) > 10_000 or not _READ_QUERY.match(query):
        raise ValueError("Only a single SELECT or WITH query is supported")
    connection = _open_database(setup_statements)
    steps = 0

    def stop_after_budget() -> int:
        nonlocal steps
        steps += 1
        return 1 if steps > 500 else 0

    connection.set_progress_handler(stop_after_budget, 1_000)
    try:
        cursor = connection.execute(query)
        columns = [str(item[0]) for item in cursor.description or []]
        if not columns or len(columns) > 20:
            raise ValueError("SQL queries must return between 1 and 20 columns")
        rows = cursor.fetchmany(201)
        if len(rows) > 200:
            raise ValueError("SQL query returned too many rows")
        normalized_rows: list[list[Any]] = []
        for row in rows:
            values: list[Any] = []
            for value in row:
                if isinstance(value, float):
                    if not math.isfinite(value):
                        raise ValueError("SQL query returned a non-finite number")
                    value = round(value, 10)
                elif isinstance(value, bytes):
                    raise ValueError("Binary SQL values are not supported")
                elif value is not None and not isinstance(value, (str, int, float)):
                    raise ValueError("SQL query returned an unsupported value")
                if isinstance(value, str) and len(value) > 2_000:
                    raise ValueError("SQL query returned an oversized value")
                values.append(value)
            normalized_rows.append(values)
        return {"columns": columns, "rows": normalized_rows}
    except sqlite3.Error as exc:
        raise ValueError("SQL query could not be evaluated against the supplied tables") from exc
    finally:
        connection.close()


def sql_results_match(expected: dict[str, Any], actual: dict[str, Any], *, ordered: bool) -> bool:
    if [str(item).casefold() for item in expected.get("columns", [])] != [
        str(item).casefold() for item in actual.get("columns", [])
    ]:
        return False
    expected_rows = expected.get("rows", [])
    actual_rows = actual.get("rows", [])
    if ordered:
        return expected_rows == actual_rows
    key = lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sorted(expected_rows, key=key) == sorted(actual_rows, key=key)
