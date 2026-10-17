"""Health check run by GitHub Actions (and locally): python scripts/check_db.py

Connects to the hosted database as the read-only quiz_reader role, using
QUIZ_READER_DATABASE_URL from the environment (a GitHub Secret in CI), then checks:
  1. the quiz tables are loaded
  2. every question's hint SQL still returns its stored expected result
  3. the quiz role really is read-only and can't see the audit log
  4. the audit log's hash chain is intact
Exits non-zero if anything fails.
"""

import sys

import psycopg2
from dotenv import load_dotenv

from quizdb import connect, results_match, run_query

load_dotenv()
failures = []


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")
    if not ok:
        failures.append(name)


def expect_error(conn, name, sql):
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        check(name, False, "statement was allowed")
    except psycopg2.Error as e:
        check(name, True, e.pgerror.strip().splitlines()[0] if e.pgerror else type(e).__name__)
    conn.rollback()


conn = connect()
cur = conn.cursor()

# 1. Data loaded
for table, minimum in [("pressure_zones", 5), ("mains", 200), ("crews", 4), ("breaks", 120), ("repairs", 100)]:
    cur.execute(f"SELECT count(*) FROM quiz.{table}")
    n = cur.fetchone()[0]
    check(f"quiz.{table} loaded", n >= minimum, f"{n} rows")

# 2. Answer key matches live data
cur.execute("SELECT id, points, hint_sql, hint_result, order_matters FROM public.questions ORDER BY id")
questions = cur.fetchall()
conn.rollback()
check("questions total 20 points", sum(q[1] for q in questions) == 20, f"{len(questions)} questions")
for qid, _, hint_sql, expected, order_matters in questions:
    got = run_query(conn, hint_sql)
    check(f"Q{qid} hint matches live result", results_match(got, expected, order_matters),
          f"{len(got['rows'])} rows")

# 3. Read-only and isolated
cur = conn.cursor()
cur.execute("""SELECT bool_or(has_table_privilege(current_user, 'quiz.' || tablename,
                                  'INSERT,UPDATE,DELETE,TRUNCATE'))
               FROM pg_tables WHERE schemaname = 'quiz'""")
check("quiz role has no write privileges", cur.fetchone()[0] is False)
cur.execute("SELECT has_schema_privilege(current_user, 'quiz', 'CREATE')")
check("quiz role cannot create tables", cur.fetchone()[0] is False)
conn.rollback()
expect_error(conn, "a write attempt is rejected", "DELETE FROM quiz.breaks WHERE break_id = 1")
expect_error(conn, "quiz role cannot read the audit log", "SELECT * FROM public.audit_log")
expect_error(conn, "quiz role cannot read saved answers", "SELECT * FROM public.answers")

# 4. Audit log integrity
cur = conn.cursor()
cur.execute("SELECT total_rows, broken_rows, first_broken_id FROM public.verify_audit_log()")
total, broken, first_bad = cur.fetchone()
check("audit log hash chain intact", broken == 0,
      f"{total} rows checked" + (f", first broken id {first_bad}" if broken else ""))
conn.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
