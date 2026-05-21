import sqlite3
import csv
import json
from pathlib import Path

DB_PATH = Path("employees.db")


def init_db(db_path=DB_PATH):
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
    CREATE TABLE IF NOT EXISTS employees (
        employee_id TEXT PRIMARY KEY,
        name TEXT,
        department TEXT,
        role TEXT,
        weekly_values TEXT,
        adjustments TEXT,
        deductions TEXT
    )
    """
    )
    conn.commit()
    return conn


def import_csv(path, db_path=DB_PATH):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    conn = init_db(db_path)
    with p.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            conn.execute(
                "INSERT OR REPLACE INTO employees (employee_id,name,department,role,weekly_values,adjustments,deductions) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    r.get("employee_id"),
                    r.get("name"),
                    r.get("department"),
                    r.get("role"),
                    r.get("weekly_values") or json.dumps([]),
                    r.get("adjustments") or json.dumps({}),
                    r.get("deductions") or json.dumps({}),
                ),
            )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "employees.csv"
    print(f"Importing {path} into {DB_PATH}")
    import_csv(path)
    print("Done")
