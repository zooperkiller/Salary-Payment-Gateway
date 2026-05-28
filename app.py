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

app = FastAPI(title="Salary Payment Gateway — Payroll Intelligence Dashboard")
templates = Jinja2Templates(directory="templates")

DB_PATH = Path("employees.db")

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
def get_filter_values():
    """Return all distinct filter values for dropdowns."""
    conn = _get_conn()
    filters = {}
    for col in ["department", "country", "gender", "designation", "grade",
                "employee_status", "employee_type", "continent"]:
        rows = conn.execute(f"SELECT DISTINCT {col} FROM employees WHERE {col} IS NOT NULL AND {col} != '' ORDER BY {col}").fetchall()
        filters[col] = [r[0] for r in rows]
    conn.close()
    return filters


# ── Dashboard Analytics ────────────────────────────────────────


@app.get("/api/dashboard")
def dashboard():
    """Full dashboard analytics payload."""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM employees").fetchall()
    conn.close()
    employees = [_row_to_dict(r) for r in rows]
    return build_full_dashboard(employees)


@app.get("/api/dashboard/summary")
def dashboard_summary():
    """Quick summary stats."""
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM employees").fetchall()
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
def list_departments():
    conn = _get_conn()
    rows = conn.execute("SELECT DISTINCT department FROM employees WHERE department IS NOT NULL AND department != '' ORDER BY department").fetchall()
    conn.close()
    return [r[0] for r in rows]


@app.get("/api/departments/{dept_name}")
def department_detail(dept_name: str):
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM employees WHERE department = ?", (dept_name,)).fetchall()
    conn.close()
    emps = [_row_to_dict(r) for r in rows]
    if not emps:
        raise HTTPException(status_code=404, detail="Department not found")
    return department_kpis(emps)[0] if department_kpis(emps) else {}


# ── Home Page ──────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
def home(request: Request, employee_id: Optional[str] = None):
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM employees").fetchall()
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
