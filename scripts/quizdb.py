"""Shared helpers: run a quiz query the same way the site does, and compare results.

Mirrors supabase/functions/run-sql/index.ts so the answer key, CI, and the
live site all agree on what a result looks like.
"""

import json
import os
import re

import psycopg2

MAX_ROWS = 500


def connect(url_env="QUIZ_READER_DATABASE_URL"):
    url = os.environ.get(url_env)
    if not url:
        raise SystemExit(f"{url_env} is not set (put it in .env locally, GitHub Secrets in CI)")
    conn = psycopg2.connect(url, sslmode=os.environ.get("PGSSLMODE", "require"))
    conn.set_session(readonly=True, autocommit=False)
    return conn


def clean_sql(sql):
    """One statement only: strip trailing semicolons, reject any remaining one."""
    s = re.sub(r"[;\s]+$", "", sql.strip())
    if not s:
        raise ValueError("Enter a query.")
    if ";" in s:
        raise ValueError("Run one statement at a time (remove the extra semicolon).")
    first = re.split(r"[\s(]", re.sub(r"^(\s*--[^\n]*\n)+", "", s).strip())[0].lower()
    if first not in ("select", "with", "values", "table", ""):
        raise ValueError("Only SELECT queries can run here. The quiz database is read-only.")
    return s


def run_query(conn, sql):
    """Return {"columns": [...], "rows": [[...], ...]} using Postgres's own JSON formatting."""
    s = clean_sql(sql)
    with conn.cursor() as cur:
        cur.execute("SET LOCAL search_path = quiz")
        cur.execute(f"SELECT * FROM ({s}\n) AS q LIMIT 0")
        columns = [d.name for d in cur.description]
        cur.execute(f"SELECT json_agg(t)::text FROM (SELECT * FROM ({s}\n) AS q LIMIT {MAX_ROWS + 1}) AS t")
        data = json.loads(cur.fetchone()[0] or "[]")
    conn.rollback()
    rows = [[obj.get(c) for c in columns] for obj in data]
    return {"columns": columns, "rows": rows}


def _norm(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    return str(v)


def results_match(got, expected, order_matters=True):
    """Same values, same column count; column names don't matter."""
    if len(got["columns"]) != len(expected["columns"]):
        return False
    a = [[_norm(v) for v in r] for r in got["rows"]]
    b = [[_norm(v) for v in r] for r in expected["rows"]]
    if not order_matters:
        a, b = sorted(a, key=json.dumps), sorted(b, key=json.dumps)
    return a == b
