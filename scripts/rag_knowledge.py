"""Searchable schema, domain rules, and examples for the SQL quiz."""

from questions import QUESTIONS


TABLES = [
    {
        "name": "pressure_zones",
        "tables": ["pressure_zones"],
        "text": (
            "quiz.pressure_zones has one row per water-system pressure area. "
            "Columns: zone_id (integer primary key), zone_name (unique text)."
        ),
    },
    {
        "name": "mains",
        "tables": ["mains", "pressure_zones"],
        "text": (
            "quiz.mains has one row per pipe segment. Columns: main_id (integer primary key), "
            "zone_id (foreign key to pressure_zones.zone_id), material (Cast Iron, Ductile Iron, "
            "PVC, or Asbestos Cement), diameter_in (inches), length_ft (feet), and install_year. "
            "A pressure zone can contain many mains."
        ),
    },
    {
        "name": "crews",
        "tables": ["crews"],
        "text": (
            "quiz.crews has one row per repair crew. Columns: crew_id (integer primary key), "
            "crew_name (unique text), and shift (Day or Night)."
        ),
    },
    {
        "name": "breaks",
        "tables": ["breaks", "mains"],
        "text": (
            "quiz.breaks has one row per reported pipe break. Columns: break_id (integer primary key), "
            "main_id (foreign key to mains.main_id), reported_at (local timestamp without time zone), "
            "break_type, cause, and est_loss_gal. A main can have many breaks."
        ),
    },
    {
        "name": "repairs",
        "tables": ["repairs", "breaks", "crews"],
        "text": (
            "quiz.repairs has zero or one row per break: break_id is a unique foreign key to "
            "breaks.break_id. crew_id references crews. Other columns include started_at, "
            "completed_at, repair_method, and cost_usd. A crew can perform many repairs."
        ),
    },
]


RULES = [
    {
        "name": "open-break-status",
        "tables": ["breaks", "repairs"],
        "text": (
            "An open break has either no matching repairs row (unassigned) or a repairs row "
            "whose completed_at is NULL (in progress). Use a LEFT JOIN from breaks to repairs; "
            "testing completed_at IS NULL includes both cases."
        ),
    },
    {
        "name": "pipe-length-units",
        "tables": ["mains"],
        "text": (
            "main.length_ft is measured in feet. Convert total feet to miles by dividing by "
            "5280.0, not integer 5280, so PostgreSQL keeps fractional miles before rounding."
        ),
    },
    {
        "name": "break-rate-denominator",
        "tables": ["breaks", "mains"],
        "text": (
            "For breaks per 100 miles by material, count breaks separately from total main length. "
            "Include every main in the length denominator, including mains with no breaks; do not "
            "sum main lengths after joining to breaks because repeated breaks duplicate pipe length."
        ),
    },
    {
        "name": "repair-duration",
        "tables": ["repairs", "crews"],
        "text": (
            "Repair duration uses only completed repairs: filter completed_at IS NOT NULL, then "
            "subtract started_at from completed_at. PostgreSQL can convert the interval to hours "
            "with EXTRACT(EPOCH FROM completed_at - started_at) / 3600."
        ),
    },
    {
        "name": "timestamp-boundaries",
        "tables": ["breaks"],
        "text": (
            "reported_at is a local timestamp without a time zone. For all timestamps in a month, "
            "use an inclusive start and exclusive next-month boundary, such as >= '2025-01-01' "
            "and < '2025-02-01'."
        ),
    },
]


def knowledge_documents():
    """Return deterministic documents with IDs and metadata for vector indexing."""
    documents = []
    for table in TABLES:
        documents.append(
            {
                "id": f"schema-{table['name']}",
                "title": f"Schema: {table['name']}",
                "kind": "schema",
                "tables": table["tables"],
                "text": table["text"],
            }
        )

    for rule in RULES:
        documents.append(
            {
                "id": f"rule-{rule['name']}",
                "title": f"Business rule: {rule['name']}",
                "kind": "business_rule",
                "tables": rule["tables"],
                "text": rule["text"],
            }
        )

    for question in QUESTIONS:
        documents.append(
            {
                "id": f"example-question-{question['id']}",
                "title": f"Example: {question['title']}",
                "kind": "few_shot_example",
                "tables": [],
                "text": (
                    f"Question: {question['prompt']}\n"
                    f"Expected columns and order: {question['output_columns']}\n"
                    f"SQL example:\n{question['hint_sql']}"
                ),
            }
        )

    return documents
