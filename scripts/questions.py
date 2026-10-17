"""The five quiz questions (4 points each, 20 total). Single source of truth.

build_questions.py runs each hint_sql against the database and writes
supabase/04_questions.sql. check_db.py (run in GitHub Actions) re-runs them
and fails if the live database no longer matches the stored answer key.
"""

QUESTIONS = [
    {
        "id": 1,
        "title": "Miles of pipe by material",
        "prompt": (
            "How many miles of water main does Haw Valley Water own of each pipe material? "
            "One mile is 5,280 feet. Round miles to 2 decimal places."
        ),
        "output_columns": "material, miles — most miles first",
        "order_matters": True,
        "points": 4,
        "hint_sql": """SELECT material,
       ROUND(SUM(length_ft) / 5280.0, 2) AS miles
FROM mains
GROUP BY material
ORDER BY miles DESC;""",
    },
    {
        "id": 2,
        "title": "January 2025 breaks",
        "prompt": (
            "List every break reported in January 2025, with the material of the main that broke."
        ),
        "output_columns": "break_id, reported_at, material — earliest report first",
        "order_matters": True,
        "points": 4,
        "hint_sql": """SELECT b.break_id, b.reported_at, m.material
FROM breaks AS b
JOIN mains AS m ON m.main_id = b.main_id
WHERE b.reported_at >= '2025-01-01'
  AND b.reported_at <  '2025-02-01'
ORDER BY b.reported_at;""",
    },
    {
        "id": 3,
        "title": "Break rate per 100 miles",
        "prompt": (
            "Utilities compare materials by breaks per 100 miles of pipe. For each material, count all "
            "breaks in the table and divide by that material's total miles of main (count every main, "
            "including ones that never broke), times 100. Round the rate to 1 decimal place."
        ),
        "output_columns": "material, breaks, breaks_per_100_miles — highest rate first",
        "order_matters": True,
        "points": 4,
        "hint_sql": """WITH break_counts AS (
    SELECT m.material, COUNT(*) AS breaks
    FROM breaks AS b
    JOIN mains AS m ON m.main_id = b.main_id
    GROUP BY m.material
),
pipe_miles AS (
    SELECT material, SUM(length_ft) / 5280.0 AS miles
    FROM mains
    GROUP BY material
)
SELECT p.material,
       COALESCE(c.breaks, 0) AS breaks,
       ROUND(COALESCE(c.breaks, 0) / p.miles * 100, 1) AS breaks_per_100_miles
FROM pipe_miles AS p
LEFT JOIN break_counts AS c ON c.material = p.material
ORDER BY breaks_per_100_miles DESC;""",
    },
    {
        "id": 4,
        "title": "Breaks still open",
        "prompt": (
            "A break is still open if no crew has been assigned (it has no row in repairs) or the "
            "repair has started but completed_at is empty. List every open break and label it "
            "'unassigned' or 'in progress'."
        ),
        "output_columns": "break_id, main_id, reported_at, status — oldest report first",
        "order_matters": True,
        "points": 4,
        "hint_sql": """SELECT b.break_id, b.main_id, b.reported_at,
       CASE WHEN r.repair_id IS NULL THEN 'unassigned'
            ELSE 'in progress' END AS status
FROM breaks AS b
LEFT JOIN repairs AS r ON r.break_id = b.break_id
WHERE r.completed_at IS NULL
ORDER BY b.reported_at;""",
    },
    {
        "id": 5,
        "title": "Fastest crews",
        "prompt": (
            "For each crew, find the average hours from started_at to completed_at across its "
            "completed repairs. Only include crews with at least 20 completed repairs. "
            "Round hours to 1 decimal place."
        ),
        "output_columns": "crew_name, repairs, avg_hours — fastest first",
        "order_matters": True,
        "points": 4,
        "hint_sql": """SELECT c.crew_name,
       COUNT(*) AS repairs,
       ROUND(AVG(EXTRACT(EPOCH FROM r.completed_at - r.started_at) / 3600)::numeric, 1) AS avg_hours
FROM repairs AS r
JOIN crews AS c ON c.crew_id = r.crew_id
WHERE r.completed_at IS NOT NULL
GROUP BY c.crew_name
HAVING COUNT(*) >= 20
ORDER BY avg_hours;""",
    },
]

assert sum(q["points"] for q in QUESTIONS) == 20
