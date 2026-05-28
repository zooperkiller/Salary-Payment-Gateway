"""
Phase 0: Schema Migration for Tier 3 Strategic Features.

Adds:
  - company_id column to employees (with 'default' backfill)
  - companies table
  - budgets table
  - scenarios table
  - monthly_snapshots table

Safe to run multiple times — uses IF NOT EXISTS / try-except for column addition.
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("employees.db")

def migrate():
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found. Run import_employees.py first.")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()

    # ── 1. Add company_id to employees ──────────────────────────────
    try:
        cursor.execute("ALTER TABLE employees ADD COLUMN company_id TEXT DEFAULT 'default'")
        print("  ✓ Added company_id column to employees")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print("  • company_id column already exists — skipping")
        else:
            raise

    # Backfill any NULL values
    cursor.execute("UPDATE employees SET company_id = 'default' WHERE company_id IS NULL")
    if cursor.rowcount:
        print(f"  ✓ Backfilled {cursor.rowcount} employees with company_id='default'")

    # ── 2. Create companies table ──────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            fiscal_year_start TEXT DEFAULT '01-01',
            currency        TEXT DEFAULT 'USD',
            tax_country     TEXT DEFAULT 'US',
            is_active       INTEGER DEFAULT 1,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        )
    """)
    print("  ✓ companies table ready")

    # Seed default company
    cursor.execute("""
        INSERT OR IGNORE INTO companies (id, name, currency, tax_country)
        VALUES ('default', 'Default Company', 'USD', 'US')
    """)
    if cursor.rowcount:
        print("  ✓ Seeded 'Default Company'")

    # ── 3. Create budgets table ────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id      TEXT NOT NULL DEFAULT 'default',
            department      TEXT NOT NULL,
            fiscal_year     INTEGER NOT NULL,
            period          TEXT DEFAULT 'annual',
            quarter         INTEGER,
            budget_gross    REAL DEFAULT 0,
            budget_net      REAL DEFAULT 0,
            budget_tax      REAL DEFAULT 0,
            budget_headcount INTEGER DEFAULT 0,
            budget_basic    REAL DEFAULT 0,
            notes           TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now')),
            UNIQUE(company_id, department, fiscal_year, period, quarter)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_budgets_company_dept_year
        ON budgets(company_id, department, fiscal_year)
    """)
    print("  ✓ budgets table ready")

    # ── 4. Create scenarios table ──────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scenarios (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id       TEXT NOT NULL DEFAULT 'default',
            name             TEXT NOT NULL,
            adjustments_json TEXT NOT NULL,
            result_json      TEXT,
            created_at       TEXT DEFAULT (datetime('now'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_scenarios_company
        ON scenarios(company_id)
    """)
    print("  ✓ scenarios table ready")

    # ── 5. Create monthly_snapshots table ──────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS monthly_snapshots (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id          TEXT NOT NULL DEFAULT 'default',
            snapshot_date       TEXT NOT NULL,
            total_employees     INTEGER,
            active_count        INTEGER,
            total_net_payroll   REAL,
            total_gross_payroll REAL,
            total_tax           REAL,
            avg_net_salary      REAL,
            avg_gross_salary    REAL,
            departments_json    TEXT,
            created_at          TEXT DEFAULT (datetime('now')),
            UNIQUE(company_id, snapshot_date)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_snapshots_company_date
        ON monthly_snapshots(company_id, snapshot_date)
    """)
    print("  ✓ monthly_snapshots table ready")

    # ── 6. Add indexes for company_id on employees ─────────────────
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_employees_company
        ON employees(company_id)
    """)
    print("  ✓ idx_employees_company ready")

    conn.commit()
    conn.close()

    print("\n✅ Phase 0 schema migration complete.")

    # ── Verify ────────────────────────────────────────────────────
    conn = sqlite3.connect(str(DB_PATH))
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    print("\nTables in database:")
    for (name,) in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
        print(f"  {name:<30} {count:>6} rows")
    conn.close()


if __name__ == "__main__":
    migrate()