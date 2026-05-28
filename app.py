from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
import sqlite3
import io
import csv
import json
from pathlib import Path
from salary_gateway.analytics import *
from salary_gateway.calculator import compute_progressive_tax, compute_net_salary
from salary_gateway.scenarios import apply_scenario

app = FastAPI(title="Salary Payment Gateway — Payroll Intelligence Dashboard")
templates = Jinja2Templates(directory="templates")

DB_PATH = Path("employees.db")


# ── Startup migration ────────────────────────────────────────────

@app.on_event("startup")
def _run_startup_migrations():
    """Apply any pending schema migrations on startup (idempotent)."""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # 1. Add company_id to employees if missing
    try:
        cur.execute("ALTER TABLE employees ADD COLUMN company_id TEXT DEFAULT 'default'")
    except sqlite3.OperationalError:
        pass  # column already exists

    cur.execute("UPDATE employees SET company_id = 'default' WHERE company_id IS NULL")

    # 2. companies table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id TEXT PRIMARY KEY, name TEXT NOT NULL,
            fiscal_year_start TEXT DEFAULT '01-01', currency TEXT DEFAULT 'USD',
            tax_country TEXT DEFAULT 'US', is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    cur.execute("INSERT OR IGNORE INTO companies (id, name, currency, tax_country) VALUES ('default', 'Default Company', 'USD', 'US')")

    # 3. budgets table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id TEXT NOT NULL DEFAULT 'default',
            department TEXT NOT NULL, fiscal_year INTEGER NOT NULL,
            period TEXT DEFAULT 'annual', quarter INTEGER,
            budget_gross REAL DEFAULT 0, budget_net REAL DEFAULT 0,
            budget_tax REAL DEFAULT 0, budget_headcount INTEGER DEFAULT 0,
            budget_basic REAL DEFAULT 0, notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(company_id, department, fiscal_year, period, quarter)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_budgets_company_dept_year ON budgets(company_id, department, fiscal_year)")

    # 4. scenarios table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scenarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id TEXT NOT NULL DEFAULT 'default',
            name TEXT NOT NULL, adjustments_json TEXT NOT NULL,
            result_json TEXT, created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_scenarios_company ON scenarios(company_id)")

    # 5. monthly_snapshots table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS monthly_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id TEXT NOT NULL DEFAULT 'default',
            snapshot_date TEXT NOT NULL,
            total_employees INTEGER, active_count INTEGER,
            total_net_payroll REAL, total_gross_payroll REAL,
            total_tax REAL, avg_net_salary REAL,
            avg_gross_salary REAL, departments_json TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(company_id, snapshot_date)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_company_date ON monthly_snapshots(company_id, snapshot_date)")

    # 6. company_id index on employees
    cur.execute("CREATE INDEX IF NOT EXISTS idx_employees_company ON employees(company_id)")

    conn.commit()
    conn.close()
    print("✅ Startup migrations applied successfully")


# ── DB helpers ──────────────────────────────────────────────────


def _get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


COLUMNS = [
    "id", "emp_count", "employee_id", "company_id", "first_name", "last_name",
    "business_unit_code", "business_unit_name", "continuous_service_date",
    "country_name", "date_of_birth", "age", "age_range", "date_of_joining",
    "experience", "tenure", "date_of_termination", "effective_start_date",
    "effective_end_date", "employee_category", "employee_status", "employee_type",
    "ethnicity", "department", "gender", "grade", "designation",
    "last_working_date", "leave_status", "country", "marital_status", "continent",
    "frequency", "payroll_employee_status", "payroll_end_date", "payroll_start_date",
    "pay_period", "rehire_date", "resignation_date", "basic_salary", "allowance",
    "statutory_bonus", "gross_salary", "arrear_special_allowance", "total_deductions",
    "arrear_statutory_bonus", "net_salary", "tax_spend", "reimbursement_paid",
]


def _row_to_dict(row) -> Optional[Dict]:
    if not row:
        return None
    return dict(row)


def _build_where(search: str = None, department: str = None, status: str = None,
                 country: str = None, gender: str = None, designation: str = None,
                 grade: str = None, min_salary: float = None, max_salary: float = None,
                 company_id: str = None) -> tuple:
    clauses = []
    params = []

    if company_id:
        clauses.append("e.company_id = ?")
        params.append(company_id)

    if search:
        clauses.append("(e.employee_id LIKE ? OR e.first_name LIKE ? OR e.last_name LIKE ? OR e.department LIKE ? OR e.designation LIKE ?)")
        s = f"%{search}%"
        params.extend([s, s, s, s, s])

    if department:
        clauses.append("e.department = ?")
        params.append(department)
    if status:
        clauses.append("e.employee_status = ?")
        params.append(status)
    if country:
        clauses.append("e.country = ?")
        params.append(country)
    if gender:
        clauses.append("e.gender = ?")
        params.append(gender)
    if designation:
        clauses.append("e.designation = ?")
        params.append(designation)
    if grade:
        clauses.append("e.grade = ?")
        params.append(grade)
    if min_salary is not None:
        clauses.append("e.net_salary >= ?")
        params.append(min_salary)
    if max_salary is not None:
        clauses.append("e.net_salary <= ?")
        params.append(max_salary)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


# ── Endpoints ───────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Employee CRUD ──────────────────────────────────────────────


@app.get("/api/employees")
def list_employees(
    page: int = Query(1, ge=1),
    page_size: int = Query(15, ge=5, le=200),
    search: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    gender: Optional[str] = Query(None),
    designation: Optional[str] = Query(None),
    grade: Optional[str] = Query(None),
    min_salary: Optional[float] = Query(None),
    max_salary: Optional[float] = Query(None),
    sort_by: Optional[str] = Query("employee_id"),
    sort_dir: Optional[str] = Query("asc"),
    company_id: Optional[str] = Query(None),
):
    """Paginated, filterable employee list."""
    conn = _get_conn()
    where, params = _build_where(search, department, status, country, gender, designation, grade, min_salary, max_salary, company_id=company_id)

    count_sql = f"SELECT COUNT(*) FROM employees e {where}"
    total = conn.execute(count_sql, params).fetchone()[0]

    allowed_sort = {"employee_id", "first_name", "last_name", "department", "designation",
                    "country", "gender", "employee_status", "net_salary", "basic_salary",
                    "gross_salary", "age", "grade"}
    col = sort_by if sort_by in allowed_sort else "employee_id"
    direction = "DESC" if sort_dir and sort_dir.lower() == "desc" else "ASC"

    offset = (page - 1) * page_size
    data_sql = f"SELECT * FROM employees e {where} ORDER BY e.{col} {direction} LIMIT ? OFFSET ?"
    rows = conn.execute(data_sql, params + [page_size, offset]).fetchall()
    conn.close()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total else 1,
        "data": [_row_to_dict(r) for r in rows],
    }


@app.get("/api/employees/{employee_id}")
def read_employee(employee_id: str):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM employees WHERE employee_id=?", (employee_id,)).fetchone()
    conn.close()
    emp = _row_to_dict(row)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    return emp


@app.get("/api/employees/{employee_id}/analyze")
def analyze_employee(employee_id: str):
    emp = read_employee(employee_id)
    salary_vals = [emp.get("net_salary", 0) or 0, emp.get("basic_salary", 0) or 0,
                   emp.get("gross_salary", 0) or 0]
    anomalies = detect_anomalies(salary_vals, threshold=0.5)
    recommendations = recommend_rules(emp)
    return {"employee_id": employee_id, "anomalies": anomalies, "recommendations": recommendations}


# ── Create / Update / Delete ────────────────────────────────────


class EmployeeCreate(BaseModel):
    employee_id: str
    company_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    employee_status: Optional[str] = "Active"
    employee_type: Optional[str] = "Permanent"
    gender: Optional[str] = None
    grade: Optional[str] = None
    country: Optional[str] = None
    country_name: Optional[str] = None
    continent: Optional[str] = None
    date_of_birth: Optional[str] = None
    age: Optional[int] = None
    age_range: Optional[str] = None
    date_of_joining: Optional[str] = None
    experience: Optional[str] = None
    tenure: Optional[str] = None
    basic_salary: Optional[float] = None
    allowance: Optional[float] = 0.0
    statutory_bonus: Optional[float] = None
    gross_salary: Optional[float] = None
    arrear_special_allowance: Optional[float] = None
    total_deductions: Optional[float] = None
    arrear_statutory_bonus: Optional[float] = None
    net_salary: Optional[float] = None
    tax_spend: Optional[float] = None
    reimbursement_paid: Optional[float] = None
    business_unit_code: Optional[str] = None
    business_unit_name: Optional[str] = None
    continuous_service_date: Optional[str] = None
    employee_category: Optional[str] = None
    ethnicity: Optional[str] = None
    last_working_date: Optional[str] = None
    leave_status: Optional[str] = None
    marital_status: Optional[str] = None
    frequency: Optional[str] = None
    payroll_employee_status: Optional[str] = None
    payroll_start_date: Optional[str] = None
    payroll_end_date: Optional[str] = None
    pay_period: Optional[str] = None
    rehire_date: Optional[str] = None
    resignation_date: Optional[str] = None
    date_of_termination: Optional[str] = None
    effective_start_date: Optional[str] = None
    effective_end_date: Optional[str] = None


def _auto_compute_tax(data: dict) -> dict:
    """Auto-compute tax_spend and net_salary from gross_salary using US progressive tax brackets."""
    gross = data.get("gross_salary")
    if gross is None or gross <= 0:
        # Try to derive gross from basic_salary + allowance + statutory_bonus
        basic = data.get("basic_salary") or 0
        allowance = data.get("allowance") or 0
        bonus = data.get("statutory_bonus") or 0
        gross = basic + allowance + bonus
        if gross <= 0:
            return data  # insufficient data to compute tax

    deductions = data.get("total_deductions") or 0.0
    arrear_sa = data.get("arrear_special_allowance") or 0.0
    arrear_sb = data.get("arrear_statutory_bonus") or 0.0
    reimburse = data.get("reimbursement_paid") or 0.0

    result = compute_net_salary(
        gross_salary=gross,
        total_deductions=deductions,
        arrear_special_allowance=arrear_sa,
        arrear_statutory_bonus=arrear_sb,
        reimbursement_paid=reimburse,
    )
    data["gross_salary"] = gross
    data["tax_spend"] = result["tax_spend"]
    data["net_salary"] = result["net_salary"]
    return data


@app.post("/api/employees", status_code=201)
def create_employee(emp: EmployeeCreate):
    """Manually add a new employee. Auto-computes US progressive tax if gross_salary is provided."""
    conn = _get_conn()
    existing = conn.execute("SELECT 1 FROM employees WHERE employee_id = ?", (emp.employee_id,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=409, detail=f"Employee {emp.employee_id} already exists")

    fields = [k for k in COLUMNS if k not in ("id", "emp_count")]
    data = {k: getattr(emp, k, None) for k in fields}
    data["employee_status"] = data.get("employee_status") or "Active"
    data["employee_type"] = data.get("employee_type") or "Permanent"
    data["company_id"] = data.get("company_id") or "default"

    # Auto-compute US progressive tax
    data = _auto_compute_tax(data)

    placeholders = ",".join(["?"] * len(fields))
    columns_str = ",".join(fields)
    values = [data.get(f) for f in fields]

    conn.execute(f"INSERT INTO employees ({columns_str}) VALUES ({placeholders})", values)
    conn.commit()
    row = conn.execute("SELECT * FROM employees WHERE employee_id = ?", (emp.employee_id,)).fetchone()
    conn.close()
    return _row_to_dict(row)


@app.post("/api/employees/upload")
async def upload_employees(file: UploadFile = File(...)):
    """Upload CSV or XLSX file to bulk-import employees."""
    filename = (file.filename or "").lower()
    content = await file.read()

    if filename.endswith(".csv"):
        return _process_csv_upload(content)
    elif filename.endswith(".xlsx"):
        return _process_xlsx_upload(content)
    else:
        raise HTTPException(status_code=400, detail="Only .csv and .xlsx files are supported")


@app.put("/api/employees/{employee_id}")
def update_employee(employee_id: str, emp: EmployeeCreate):
    """Update an existing employee. Auto-computes US progressive tax if salary fields changed.
    
    Only fields explicitly sent (non-None) are updated — existing values are preserved.
    """
    conn = _get_conn()
    row = conn.execute("SELECT * FROM employees WHERE employee_id = ?", (employee_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Employee not found")

    existing = _row_to_dict(row)
    fields = [k for k in COLUMNS if k not in ("id", "emp_count")]
    incoming = {k: getattr(emp, k, None) for k in fields}

    # Merge: only overwrite fields the client actually sent (non-None);
    # retain existing values for everything else
    data = {}
    for k in fields:
        if incoming.get(k) is not None:
            data[k] = incoming[k]
        else:
            data[k] = existing.get(k)

    # Detect if any salary-relevant field changed — if so, recompute tax
    salary_fields = ["basic_salary", "allowance", "statutory_bonus", "gross_salary",
                     "total_deductions", "arrear_special_allowance", "arrear_statutory_bonus",
                     "reimbursement_paid"]
    salary_changed = any(incoming.get(f) is not None and incoming.get(f) != existing.get(f) for f in salary_fields)

    if salary_changed:
        data = _auto_compute_tax(data)

    sets = [f"{f} = ?" for f in fields]
    values = [data.get(f) for f in fields]

    conn.execute(f"UPDATE employees SET {', '.join(sets)} WHERE employee_id = ?", values + [employee_id])
    conn.commit()
    updated = conn.execute("SELECT * FROM employees WHERE employee_id = ?", (employee_id,)).fetchone()
    conn.close()
    return _row_to_dict(updated)


@app.delete("/api/employees/{employee_id}")
def delete_employee(employee_id: str):
    """Delete an employee."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM employees WHERE employee_id = ?", (employee_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Employee not found")
    conn.execute("DELETE FROM employees WHERE employee_id = ?", (employee_id,))
    conn.commit()
    conn.close()
    return {"deleted": employee_id}


# ── Upload helpers ──────────────────────────────────────────────


def _process_csv_upload(content: bytes) -> Dict:
    """Parse CSV content and bulk-insert employees."""
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return {"imported": 0, "skipped": 0, "errors": ["Empty file"]}

    db_cols = [k for k in COLUMNS if k not in ("id", "emp_count", "company_id")]
    csv_cols = list(rows[0].keys())
    # Map CSV columns to DB columns (case-insensitive)
    col_map = {}
    for dc in db_cols:
        for cc in csv_cols:
            if cc.strip().lower().replace(" ", "_") == dc.lower():
                col_map[dc] = cc
                break

    conn = _get_conn()
    imported = 0
    skipped = 0
    errors = []
    placeholders = ",".join(["?"] * len(db_cols))
    columns_str = ",".join(db_cols)

    for i, row in enumerate(rows):
        eid = (row.get(col_map.get("employee_id", "")) or row.get("employee_id") or row.get("Employee ID") or "").strip()
        if not eid:
            skipped += 1
            continue
        if conn.execute("SELECT 1 FROM employees WHERE employee_id = ?", (eid,)).fetchone():
            skipped += 1
            continue
        try:
            vals = []
            for dc in db_cols:
                raw = row.get(col_map.get(dc), None)
                if raw is not None:
                    raw = str(raw).strip()
                if dc in ("basic_salary", "allowance", "statutory_bonus", "gross_salary",
                          "arrear_special_allowance", "total_deductions", "arrear_statutory_bonus",
                          "net_salary", "tax_spend", "reimbursement_paid"):
                    try:
                        vals.append(float(raw) if raw else None)
                    except (ValueError, TypeError):
                        vals.append(None)
                elif dc == "age":
                    try:
                        vals.append(int(float(raw)) if raw else None)
                    except (ValueError, TypeError):
                        vals.append(None)
                else:
                    vals.append(raw if raw else None)
            conn.execute(f"INSERT INTO employees ({columns_str}) VALUES ({placeholders})", vals)
            imported += 1
        except Exception as e:
            errors.append(f"Row {i+1}: {str(e)}")
            skipped += 1

    conn.commit()
    conn.close()
    return {"imported": imported, "skipped": skipped, "errors": errors[:10]}


def _process_xlsx_upload(content: bytes) -> Dict:
    """Parse XLSX content and bulk-insert employees."""
    import subprocess as _sp, sys as _sys
    try:
        import openpyxl
    except ImportError:
        _sp.check_call([_sys.executable, "-m", "pip", "install", "openpyxl", "-q"])
        import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
    ws = wb.active

    # Read header row
    headers = [str(c.value).strip() if c.value else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]
    db_cols = [k for k in COLUMNS if k not in ("id", "emp_count", "company_id")]

    # Map headers to DB columns
    col_map = {}
    for dc in db_cols:
        for idx, h in enumerate(headers):
            if h.lower().replace(" ", "_") == dc.lower():
                col_map[dc] = idx
                break

    conn = _get_conn()
    imported = 0
    skipped = 0
    errors = []
    placeholders = ",".join(["?"] * len(db_cols))
    columns_str = ",".join(db_cols)

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        eid = None
        if "employee_id" in col_map and col_map["employee_id"] < len(row):
            eid = str(row[col_map["employee_id"]]).strip() if row[col_map["employee_id"]] else ""
        if not eid:
            skipped += 1
            continue
        if conn.execute("SELECT 1 FROM employees WHERE employee_id = ?", (eid,)).fetchone():
            skipped += 1
            continue
        try:
            vals = []
            for dc in db_cols:
                idx = col_map.get(dc)
                raw = str(row[idx]).strip() if idx is not None and idx < len(row) and row[idx] is not None else None
                if dc in ("basic_salary", "allowance", "statutory_bonus", "gross_salary",
                          "arrear_special_allowance", "total_deductions", "arrear_statutory_bonus",
                          "net_salary", "tax_spend", "reimbursement_paid"):
                    try:
                        vals.append(float(raw) if raw else None)
                    except (ValueError, TypeError):
                        vals.append(None)
                elif dc == "age":
                    try:
                        vals.append(int(float(raw)) if raw else None)
                    except (ValueError, TypeError):
                        vals.append(None)
                else:
                    vals.append(raw if raw else None)
            conn.execute(f"INSERT INTO employees ({columns_str}) VALUES ({placeholders})", vals)
            imported += 1
        except Exception as e:
            errors.append(f"Row {row_idx}: {str(e)}")
            skipped += 1

    conn.commit()
    conn.close()
    wb.close()
    return {"imported": imported, "skipped": skipped, "errors": errors[:10]}


# ── FAQ ──────────────────────────────────────────────────────────


@app.get("/api/faq")
def get_faq():
    """Return FAQ data."""
    return {
        "faqs": [
            {
                "q": "How is net salary calculated?",
                "a": "Net Salary = Gross Salary − Total Deductions + Arrear Special Allowance + Arrear Statutory Bonus. It represents the actual take-home pay after all deductions and additions."
            },
            {
                "q": "What do the different employee statuses mean?",
                "a": "<strong>Active</strong> employees are currently employed. <strong>Inactive</strong> employees have left the organization. <strong>On Leave</strong> means the employee is temporarily away."
            },
            {
                "q": "How do I add a new employee?",
                "a": "Click the <strong>'＋ Add Employee'</strong> button in the navigation bar to manually enter employee details. Alternatively, use the <strong>'📤 Upload'</strong> button to bulk-import via CSV or Excel file."
            },
            {
                "q": "What file formats are accepted for bulk upload?",
                "a": "We accept <strong>.csv</strong> (comma-separated values) and <strong>.xlsx</strong> (Microsoft Excel) files. The file should have a header row with column names matching our schema."
            },
            {
                "q": "Can I edit or delete an employee?",
                "a": "Yes! In the employee detail modal (click the 📋 button next to any employee), you'll find <strong>Edit</strong> and <strong>Delete</strong> options. Edit reuses the same form as Add Employee. Delete requires confirmation."
            },
            {
                "q": "What is the gender pay gap metric?",
                "a": "The gender pay gap shows the percentage difference between the <strong>highest</strong> and <strong>lowest</strong> average net salary across genders. A lower gap indicates more equitable pay distribution."
            },
            {
                "q": "How often is the dashboard data updated?",
                "a": "All dashboard metrics and charts are computed <strong>in real-time</strong> from the database. Changes made via Add, Edit, Delete, or Upload are reflected immediately upon page refresh."
            },
            {
                "q": "What does the anomaly detection do?",
                "a": "The recommendation engine checks for: net-to-gross ratio anomalies, unusually low basic salary, excessive tax rates, and inactive employees still receiving salary."
            },
        ]
    }

# ── Tax Calculator ──────────────────────────────────────────────


@app.get("/api/calculate-tax")
def calculate_tax_preview(
    gross_salary: float = Query(..., ge=0, description="Annual gross salary"),
    total_deductions: float = Query(0.0, description="Total deductions"),
    arrear_special_allowance: float = Query(0.0),
    arrear_statutory_bonus: float = Query(0.0),
    reimbursement_paid: float = Query(0.0),
):
    """Preview US progressive tax calculation for a given gross salary.

    Returns complete breakdown: tax_spend, net_salary, effective rate, marginal bracket.
    Useful for real-time UI preview before saving an employee.
    """
    result = compute_net_salary(
        gross_salary=gross_salary,
        total_deductions=total_deductions,
        arrear_special_allowance=arrear_special_allowance,
        arrear_statutory_bonus=arrear_statutory_bonus,
        reimbursement_paid=reimbursement_paid,
    )
    return {
        "gross_salary": gross_salary,
        "tax_spend": result["tax_spend"],
        "net_salary": result["net_salary"],
        "tax_bracket": result["tax_bracket"],
        "effective_tax_rate": round(result["tax_spend"] / gross_salary * 100, 2) if gross_salary > 0 else 0,
    }


@app.post("/api/employees/recalculate-tax")
def recalculate_all_taxes(
    employee_status: Optional[str] = Query("Active", description="Filter by employee status (Active/Inactive/All)"),
    dry_run: bool = Query(False, description="If true, preview changes without committing"),
):
    """Recalculate US progressive tax for all matching employees.

    Applies 2026 tax brackets to every matching employee based on their gross_salary.
    Use dry_run=true to preview the changes first.
    """
    conn = _get_conn()
    where = "" if employee_status.lower() == "all" else "WHERE employee_status = ?"
    params = () if employee_status.lower() == "all" else (employee_status,)

    rows = conn.execute(f"SELECT employee_id, first_name, last_name, gross_salary, tax_spend, net_salary, "
                        f"total_deductions, arrear_special_allowance, arrear_statutory_bonus, "
                        f"reimbursement_paid FROM employees {where}", params).fetchall()

    results = []
    updated = 0
    skipped = 0

    for row in rows:
        eid = row["employee_id"]
        gross = row["gross_salary"]
        if gross is None or gross <= 0:
            skipped += 1
            results.append({"employee_id": eid, "status": "skipped", "reason": "No gross_salary"})
            continue

        old_tax = row["tax_spend"] or 0
        old_net = row["net_salary"] or 0

        new_data = _auto_compute_tax(dict(row))
        new_tax = new_data["tax_spend"]
        new_net = new_data["net_salary"]

        if new_tax == old_tax and new_net == old_net:
            skipped += 1
            results.append({"employee_id": eid, "status": "unchanged", "tax_spend": new_tax})
            continue

        if not dry_run:
            conn.execute(
                "UPDATE employees SET tax_spend = ?, net_salary = ?, gross_salary = ? WHERE employee_id = ?",
                (new_tax, new_net, new_data["gross_salary"], eid),
            )
        updated += 1
        results.append({
            "employee_id": eid,
            "name": f"{row['first_name'] or ''} {row['last_name'] or ''}".strip(),
            "status": "updated",
            "gross_salary": gross,
            "old_tax": old_tax,
            "new_tax": new_tax,
            "old_net": old_net,
            "new_net": new_net,
        })

    if not dry_run:
        conn.commit()

    conn.close()
    return {
        "dry_run": dry_run,
        "total_matched": len(rows),
        "updated": updated,
        "skipped": skipped,
        "details": results[:50],  # return first 50 for the response
        "total_details_count": len(results),
    }


# ── Filter values ──────────────────────────────────────────────



@app.get("/api/filters")
def get_filter_values(company_id: Optional[str] = Query("default")):
    """Return all distinct filter values for dropdowns, scoped to company."""
    conn = _get_conn()
    filters = {}
    where = "AND company_id = ?" if company_id else ""
    params = [company_id] if company_id else []
    for col in ["department", "country", "gender", "designation", "grade",
                "employee_status", "employee_type", "continent"]:
        rows = conn.execute(f"SELECT DISTINCT {col} FROM employees WHERE {col} IS NOT NULL AND {col} != '' {where} ORDER BY {col}", params).fetchall()
        filters[col] = [r[0] for r in rows]
    conn.close()
    return filters


# ── Dashboard Analytics ────────────────────────────────────────


@app.get("/api/dashboard")
def dashboard(company_id: Optional[str] = Query("default")):
    """Full dashboard analytics payload, scoped to company."""
    conn = _get_conn()
    where, params = ("WHERE company_id = ?", [company_id]) if company_id else ("", [])
    rows = conn.execute(f"SELECT * FROM employees {where}", params).fetchall()
    conn.close()
    employees = [_row_to_dict(r) for r in rows]
    return build_full_dashboard(employees)


@app.get("/api/dashboard/summary")
def dashboard_summary(company_id: Optional[str] = Query("default")):
    """Quick summary stats, scoped to company."""
    conn = _get_conn()
    where, params = ("WHERE company_id = ?", [company_id]) if company_id else ("", [])
    rows = conn.execute(f"SELECT * FROM employees {where}", params).fetchall()
    conn.close()
    emps = [_row_to_dict(r) for r in rows]
    total = len(emps)
    if not total:
        return {"total_employees": 0}
    active = sum(1 for e in emps if (e.get("employee_status") or "").lower() == "active")
    total_net = sum(e.get("net_salary", 0) or 0 for e in emps)
    total_gross = sum(e.get("gross_salary", 0) or 0 for e in emps)
    total_tax = sum(e.get("tax_spend", 0) or 0 for e in emps)
    dept_count = len(set(e.get("department") for e in emps if e.get("department")))
    country_count = len(set(e.get("country") for e in emps if e.get("country")))
    net_vals = [e.get("net_salary", 0) or 0 for e in emps if e.get("net_salary")]
    return {
        "total_employees": total,
        "active_count": active,
        "inactive_count": total - active,
        "total_net_payroll": total_net,
        "total_gross_payroll": total_gross,
        "total_tax": total_tax,
        "avg_net_salary": round(sum(net_vals) / len(net_vals), 2) if net_vals else 0,
        "departments": dept_count,
        "countries": country_count,
    }


# ── Department drill-down ──────────────────────────────────────


@app.get("/api/departments")
def list_departments(company_id: Optional[str] = Query("default")):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT department FROM employees WHERE department IS NOT NULL AND department != '' AND company_id = ? ORDER BY department",
        (company_id,)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


@app.get("/api/departments/{dept_name}")
def department_detail(dept_name: str, company_id: Optional[str] = Query("default")):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM employees WHERE department = ? AND company_id = ?",
        (dept_name, company_id)
    ).fetchall()
    conn.close()
    emps = [_row_to_dict(r) for r in rows]
    if not emps:
        raise HTTPException(status_code=404, detail="Department not found")
    return department_kpis(emps)[0] if department_kpis(emps) else {}


# ── Companies CRUD ─────────────────────────────────────────────


class CompanyCreate(BaseModel):
    id: str
    name: str
    fiscal_year_start: Optional[str] = "01-01"
    currency: Optional[str] = "USD"
    tax_country: Optional[str] = "US"
    is_active: Optional[int] = 1


# ── Budget models ──────────────────────────────────────────────

class BudgetCreate(BaseModel):
    company_id: Optional[str] = "default"
    department: str
    fiscal_year: int
    period: Optional[str] = "annual"  # "annual" or "quarterly"
    quarter: Optional[int] = None
    budget_gross: Optional[float] = 0.0
    budget_net: Optional[float] = 0.0
    budget_tax: Optional[float] = 0.0
    budget_headcount: Optional[int] = 0
    budget_basic: Optional[float] = 0.0
    notes: Optional[str] = None


# ── Scenario models ────────────────────────────────────────────

class AdjustmentItem(BaseModel):
    target_type: str  # department | employee | grade | designation | company
    target_value: Optional[str] = ""
    field: str  # gross_salary | basic_salary | statutory_bonus | allowance
    adjustment_type: str  # percentage | absolute | set
    adjustment_value: float


class ScenarioRunRequest(BaseModel):
    company_id: Optional[str] = "default"
    name: Optional[str] = None
    adjustments: List[AdjustmentItem]
    save: Optional[bool] = False


@app.get("/api/companies")
def list_companies():
    """Return all companies ordered by name."""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM companies ORDER BY name").fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


@app.post("/api/companies", status_code=201)
def create_company(company: CompanyCreate):
    """Create a new company."""
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO companies (id, name, fiscal_year_start, currency, tax_country, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (company.id, company.name, company.fiscal_year_start,
             company.currency, company.tax_country, company.is_active),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM companies WHERE id = ?", (company.id,)).fetchone()
        conn.close()
        return _row_to_dict(row)
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=409, detail=f"Company '{company.id}' already exists")


@app.put("/api/companies/{company_id}")
def update_company(company_id: str, company: CompanyCreate):
    """Update an existing company's name, currency, tax country, or active status."""
    conn = _get_conn()
    existing = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Company not found")
    conn.execute(
        "UPDATE companies SET name = ?, fiscal_year_start = ?, currency = ?, "
        "tax_country = ?, is_active = ?, updated_at = datetime('now') WHERE id = ?",
        (company.name, company.fiscal_year_start, company.currency,
         company.tax_country, company.is_active, company_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    conn.close()
    return _row_to_dict(row)


@app.delete("/api/companies/{company_id}")
def delete_company(company_id: str):
    """Delete a company (cannot delete 'default')."""
    if company_id == "default":
        raise HTTPException(status_code=400, detail="Cannot delete the default company")
    conn = _get_conn()
    existing = conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Company not found")
    conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))
    conn.commit()
    conn.close()
    return {"deleted": company_id}


# ── Budgets CRUD ──────────────────────────────────────────────


@app.post("/api/budgets", status_code=201)
def create_budget(budget: BudgetCreate):
    """Create or upsert a budget (INSERT OR REPLACE on unique constraint)."""
    period = (budget.period or "annual").strip().lower()
    if period not in ("annual", "quarterly"):
        raise HTTPException(status_code=422, detail="period must be 'annual' or 'quarterly'")
    if period == "quarterly" and (budget.quarter is None or budget.quarter < 1 or budget.quarter > 4):
        raise HTTPException(status_code=422, detail="quarter must be 1-4 for quarterly budgets")
    if period == "annual":
        budget.quarter = None

    conn = _get_conn()
    conn.execute(
        """
        INSERT OR REPLACE INTO budgets
            (company_id, department, fiscal_year, period, quarter,
             budget_gross, budget_net, budget_tax, budget_headcount, budget_basic, notes,
             created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (
            budget.company_id, budget.department, budget.fiscal_year, period, budget.quarter,
            budget.budget_gross, budget.budget_net, budget.budget_tax, budget.budget_headcount,
            budget.budget_basic, budget.notes,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM budgets WHERE company_id=? AND department=? AND fiscal_year=? AND period=?",
        (budget.company_id, budget.department, budget.fiscal_year, period),
    ).fetchone()
    conn.close()
    return _row_to_dict(row)


@app.get("/api/budgets")
def list_budgets(
    company_id: Optional[str] = Query("default"),
    fiscal_year: Optional[int] = None,
    department: Optional[str] = None,
    period: Optional[str] = None,
):
    """List budgets with optional filters."""
    conn = _get_conn()
    query = "SELECT * FROM budgets WHERE company_id = ?"
    params: list = [company_id]

    if fiscal_year is not None:
        query += " AND fiscal_year = ?"
        params.append(fiscal_year)
    if department:
        query += " AND department LIKE ?"
        params.append(f"%{department}%")
    if period:
        query += " AND period = ?"
        params.append(period)

    query += " ORDER BY department, fiscal_year"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


@app.delete("/api/budgets/{budget_id}")
def delete_budget(budget_id: int):
    """Delete a budget by its integer id."""
    conn = _get_conn()
    existing = conn.execute("SELECT * FROM budgets WHERE id = ?", (budget_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Budget not found")
    conn.execute("DELETE FROM budgets WHERE id = ?", (budget_id,))
    conn.commit()
    conn.close()
    return {"deleted": budget_id}


@app.get("/api/budgets/analysis")
def budget_analysis(
    company_id: Optional[str] = Query("default"),
    fiscal_year: Optional[int] = None,
):
    """Full budget-vs-actual analysis: per-department rows + summary roll-up."""
    conn = _get_conn()

    b_query = "SELECT * FROM budgets WHERE company_id = ?"
    b_params: list = [company_id]
    if fiscal_year is not None:
        b_query += " AND fiscal_year = ?"
        b_params.append(fiscal_year)
    b_query += " ORDER BY department"
    budget_rows = conn.execute(b_query, b_params).fetchall()
    budgets = [_row_to_dict(r) for r in budget_rows]

    emp_rows = conn.execute("SELECT * FROM employees WHERE company_id = ?", (company_id,)).fetchall()
    employees = [_row_to_dict(r) for r in emp_rows]
    conn.close()

    if not budgets:
        return {
            "rows": [],
            "summary": None,
            "fiscal_year": fiscal_year,
            "hint": "No budgets configured. POST to /api/budgets to create one.",
        }

    rows = budget_vs_actual(employees, budgets)
    summary = budget_summary(rows)

    return {
        "rows": rows,
        "summary": summary,
        "fiscal_year": fiscal_year,
    }


# ── Scenarios ─────────────────────────────────────────────────


@app.post("/api/scenarios/run")
def run_scenario(req: ScenarioRunRequest):
    """Execute a what-if scenario with the given adjustments."""
    if not req.adjustments:
        raise HTTPException(status_code=422, detail="At least one adjustment is required")

    VALID_TARGETS = {"department", "employee", "grade", "designation", "company"}
    VALID_FIELDS = {"gross_salary", "basic_salary", "statutory_bonus", "allowance"}
    VALID_ADJ_TYPES = {"percentage", "absolute", "set"}

    for i, adj in enumerate(req.adjustments):
        if adj.target_type not in VALID_TARGETS:
            raise HTTPException(status_code=422, detail=f"Adjustment {i}: invalid target_type '{adj.target_type}'")
        if adj.field not in VALID_FIELDS:
            raise HTTPException(status_code=422, detail=f"Adjustment {i}: invalid field '{adj.field}'")
        if adj.adjustment_type not in VALID_ADJ_TYPES:
            raise HTTPException(status_code=422, detail=f"Adjustment {i}: invalid adjustment_type '{adj.adjustment_type}'")

    conn = _get_conn()
    emp_rows = conn.execute("SELECT * FROM employees WHERE company_id = ?", (req.company_id,)).fetchall()
    employees = [_row_to_dict(r) for r in emp_rows]

    adjustments_dicts = [adj.dict() for adj in req.adjustments]
    result = apply_scenario(employees, adjustments_dicts)

    saved_id = None
    if req.save:
        name = req.name or f"Scenario {len(adjustments_dicts)} adjustment(s)"
        conn.execute(
            """
            INSERT INTO scenarios (company_id, name, adjustments_json, result_json, created_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (req.company_id, name, json.dumps(adjustments_dicts), json.dumps(result)),
        )
        conn.commit()
        saved_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    conn.close()

    response = {"result": result}
    if saved_id is not None:
        response["saved_id"] = saved_id
    return response


@app.get("/api/scenarios")
def list_scenarios(company_id: Optional[str] = Query("default")):
    """List saved scenarios for a company."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM scenarios WHERE company_id = ? ORDER BY created_at DESC",
        (company_id,),
    ).fetchall()
    conn.close()
    scenarios = []
    for r in rows:
        d = _row_to_dict(r)
        try:
            d["adjustments_json"] = json.loads(d.get("adjustments_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["adjustments_json"] = []
        try:
            d["result_json"] = json.loads(d.get("result_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["result_json"] = {}
        scenarios.append(d)
    return scenarios


@app.get("/api/scenarios/{scenario_id}")
def get_scenario(scenario_id: int):
    """Get a single saved scenario with parsed JSON."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM scenarios WHERE id = ?", (scenario_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Scenario not found")
    d = _row_to_dict(row)
    try:
        d["adjustments_json"] = json.loads(d.get("adjustments_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["adjustments_json"] = []
    try:
        d["result_json"] = json.loads(d.get("result_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        d["result_json"] = {}
    return d


@app.delete("/api/scenarios/{scenario_id}")
def delete_scenario(scenario_id: int):
    """Delete a saved scenario."""
    conn = _get_conn()
    existing = conn.execute("SELECT * FROM scenarios WHERE id = ?", (scenario_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Scenario not found")
    conn.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))
    conn.commit()
    conn.close()
    return {"deleted": scenario_id}


@app.post("/api/scenarios/{scenario_id}/rerun")
def rerun_scenario(scenario_id: int, save: Optional[bool] = Query(False)):
    """Re-run a saved scenario's adjustments against current employee data."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM scenarios WHERE id = ?", (scenario_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Scenario not found")

    d = _row_to_dict(row)
    try:
        adjustments_dicts = json.loads(d.get("adjustments_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        conn.close()
        raise HTTPException(status_code=400, detail="Scenario has invalid adjustments JSON")

    company_id = d.get("company_id", "default")

    emp_rows = conn.execute("SELECT * FROM employees WHERE company_id = ?", (company_id,)).fetchall()
    employees = [_row_to_dict(r) for r in emp_rows]

    result = apply_scenario(employees, adjustments_dicts)

    if save:
        conn.execute(
            "UPDATE scenarios SET result_json = ?, updated_at = datetime('now') WHERE id = ?",
            (json.dumps(result), scenario_id),
        )
        conn.commit()

    conn.close()
    return {"result": result, "rerun": True}


# ── Home Page ──────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
def home(request: Request, employee_id: Optional[str] = None, company_id: Optional[str] = Query("default")):
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM employees WHERE company_id = ?", (company_id,)).fetchall()
    conn.close()
    employees = [_row_to_dict(r) for r in rows]

    total = len(employees)
    total_net = sum(e.get("net_salary", 0) or 0 for e in employees)
    avg_net = round(total_net / total, 2) if total else 0

    dept_set = sorted(set(e.get("department", "") for e in employees if e.get("department")))
    country_set = sorted(set(e.get("country", "") for e in employees if e.get("country")))
    status_set = sorted(set(e.get("employee_status", "") for e in employees if e.get("employee_status")))

    selected_employee = None
    selected_analysis = None
    not_found = False

    if employee_id:
        try:
            selected_employee = read_employee(employee_id)
            selected_analysis = analyze_employee(employee_id)
        except HTTPException:
            not_found = True

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "total_employees": total,
            "total_net_payroll": total_net,
            "avg_net_salary": avg_net,
            "departments_list": dept_set,
            "countries_list": country_set,
            "statuses_list": status_set,
            "selected_employee": selected_employee,
            "selected_analysis": selected_analysis,
            "not_found": not_found,
            "search_id": employee_id or "",
        },
    )
