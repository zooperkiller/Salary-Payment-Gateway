from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List, Dict, Optional
from salary_gateway.calculator import compute_pay
import sqlite3
import json
from pathlib import Path
from salary_gateway.analytics import detect_anomalies, recommend_rules

app = FastAPI(title="Salary Payment Gateway - Payroll Admin Dashboard")
templates = Jinja2Templates(directory="templates")


class CalcRequest(BaseModel):
    employee_id: str
    weekly_values: List[float]
    adjustments: Optional[Dict[str, float]] = None
    deductions: Optional[Dict[str, float]] = None


DB_PATH = Path("employees.db")


def _get_conn():
    return sqlite3.connect(str(DB_PATH))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/calculate")
def calculate(req: CalcRequest):
    return compute_pay(req.employee_id, req.weekly_values, req.adjustments, req.deductions)


def _row_to_employee(row):
    if not row:
        return None
    return {
        "employee_id": row[0],
        "name": row[1],
        "department": row[2],
        "role": row[3],
        "weekly_values": json.loads(row[4] or "[]"),
        "adjustments": json.loads(row[5] or "{}"),
        "deductions": json.loads(row[6] or "{}"),
    }


@app.get("/employees")
def list_employees(limit: int = Query(50, ge=1, le=500), offset: int = 0):
    conn = _get_conn()
    cur = conn.execute("SELECT employee_id,name,department,role,weekly_values,adjustments,deductions FROM employees LIMIT ? OFFSET ?", (limit, offset))
    rows = cur.fetchall()
    conn.close()
    return [ _row_to_employee(r) for r in rows ]


@app.get("/employees/{employee_id}")
def read_employee(employee_id: str):
    conn = _get_conn()
    cur = conn.execute("SELECT employee_id,name,department,role,weekly_values,adjustments,deductions FROM employees WHERE employee_id=?", (employee_id,))
    row = cur.fetchone()
    conn.close()
    emp = _row_to_employee(row)
    if not emp:
        raise HTTPException(status_code=404, detail="employee not found")
    return emp


@app.post("/employees/{employee_id}/calculate")
def calc_employee(employee_id: str):
    emp = read_employee(employee_id)
    return compute_pay(emp["employee_id"], emp["weekly_values"], emp.get("adjustments"), emp.get("deductions"))


@app.get("/employees/{employee_id}/analyze")
def analyze_employee(employee_id: str):
    emp = read_employee(employee_id)
    return detect_anomalies(emp.get("weekly_values", []))


@app.get("/employees/{employee_id}/recommend")
def recommend_employee(employee_id: str):
    emp = read_employee(employee_id)
    return recommend_rules(emp.get("weekly_values", []), emp.get("adjustments"), emp.get("deductions"))


def _get_all_employees():
    conn = _get_conn()
    cur = conn.execute("SELECT employee_id,name,department,role,weekly_values,adjustments,deductions FROM employees")
    rows = cur.fetchall()
    conn.close()
    return [ _row_to_employee(r) for r in rows ]


@app.get("/api/dashboard")
def dashboard():
    """Aggregate analytics endpoint for dashboard charts and insights."""
    employees = _get_all_employees()

    if not employees:
        return {"total_employees": 0, "total_monthly_payroll": 0, "departments": [], "roles": [], "top_earners": [], "salary_distribution": {"ranges": [], "counts": []}}

    total = len(employees)
    payroll_data = []
    for e in employees:
        pay = compute_pay(e["employee_id"], e.get("weekly_values", []), e.get("adjustments"), e.get("deductions"))
        payroll_data.append({
            "employee_id": e["employee_id"],
            "name": e["name"],
            "department": e["department"],
            "role": e["role"],
            "payable": round(pay["payable"], 2),
            "four_week_mean": round(pay["four_week_mean"], 2),
            "adjustment_total": round(pay["adjustment_total"], 2),
            "deduction_total": round(pay["deduction_total"], 2),
        })

    total_payroll = sum(p["payable"] for p in payroll_data)
    avg_salary = round(total_payroll / total, 2) if total else 0

    # Department aggregation
    dept_map: Dict[str, dict] = {}
    for p in payroll_data:
        d = p["department"]
        if d not in dept_map:
            dept_map[d] = {"name": d, "count": 0, "total_payroll": 0, "payables": []}
        dept_map[d]["count"] += 1
        dept_map[d]["total_payroll"] += p["payable"]
        dept_map[d]["payables"].append(p["payable"])
    departments = []
    for d in dept_map.values():
        departments.append({
            "name": d["name"],
            "count": d["count"],
            "total_payroll": round(d["total_payroll"], 2),
            "avg_salary": round(d["total_payroll"] / d["count"], 2) if d["count"] else 0,
        })

    # Role aggregation
    role_map: Dict[str, dict] = {}
    for p in payroll_data:
        r = p["role"]
        if r not in role_map:
            role_map[r] = {"name": r, "count": 0, "total_payroll": 0, "payables": []}
        role_map[r]["count"] += 1
        role_map[r]["total_payroll"] += p["payable"]
        role_map[r]["payables"].append(p["payable"])
    roles = []
    for r in role_map.values():
        roles.append({
            "name": r["name"],
            "count": r["count"],
            "total_payroll": round(r["total_payroll"], 2),
            "avg_salary": round(r["total_payroll"] / r["count"], 2) if r["count"] else 0,
        })

    # Top 10 earners
    sorted_earners = sorted(payroll_data, key=lambda x: x["payable"], reverse=True)
    top_earners = sorted_earners[:10]

    # Salary distribution buckets
    buckets = [0, 500, 1000, 1500, 2000, 2500, 3000, float("inf")]
    bucket_labels = ["$0-$500", "$500-$1K", "$1K-$1.5K", "$1.5K-$2K", "$2K-$2.5K", "$2.5K-$3K", "$3K+"]
    bucket_counts = [0] * len(bucket_labels)
    for p in payroll_data:
        payable = p["payable"]
        for i, upper in enumerate(buckets[1:], 1):
            if payable <= upper:
                bucket_counts[i-1] += 1
                break

    # Overall averages for deductions
    avg_tax = round(sum(
        sum((json.loads(e.get("deductions", "{}") or "{}") if isinstance(e.get("deductions"), str) else e.get("deductions", {})).get("tax", 0)
            for e in employees)
    ) / total, 2) if total else 0
    avg_pension = round(sum(
        sum((json.loads(e.get("deductions", "{}") or "{}") if isinstance(e.get("deductions"), str) else e.get("deductions", {})).get("pension", 0)
            for e in employees)
    ) / total, 2) if total else 0

    return {
        "total_employees": total,
        "total_monthly_payroll": round(total_payroll, 2),
        "avg_salary": avg_salary,
        "avg_tax": avg_tax,
        "avg_pension": avg_pension,
        "departments": departments,
        "roles": roles,
        "top_earners": top_earners,
        "salary_distribution": {
            "ranges": bucket_labels,
            "counts": bucket_counts,
        },
    }


@app.get("/api/employees/paginated")
def employees_paginated(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=5, le=100),
    search: Optional[str] = Query(None),
    department: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("employee_id"),
    sort_dir: Optional[str] = Query("asc"),
):
    """Paginated employee list with search and filters."""
    conn = _get_conn()

    # Build query
    where_clauses = []
    params = []

    if search:
        where_clauses.append("(e.employee_id LIKE ? OR e.name LIKE ? OR e.department LIKE ? OR e.role LIKE ?)")
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param, search_param])

    if department:
        where_clauses.append("e.department = ?")
        params.append(department)

    if role:
        where_clauses.append("e.role = ?")
        params.append(role)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # Count
    count_sql = f"SELECT COUNT(*) FROM employees e {where_sql}"
    total = conn.execute(count_sql, params).fetchone()[0]

    # Sort
    allowed_sort_cols = {"employee_id", "name", "department", "role"}
    sort_col = sort_by if sort_by in allowed_sort_cols else "employee_id"
    sort_direction = "DESC" if sort_dir and sort_dir.lower() == "desc" else "ASC"

    # Fetch page
    offset = (page - 1) * page_size
    data_sql = f"SELECT e.employee_id, e.name, e.department, e.role, e.weekly_values, e.adjustments, e.deductions FROM employees e {where_sql} ORDER BY {sort_col} {sort_direction} LIMIT ? OFFSET ?"
    rows = conn.execute(data_sql, params + [page_size, offset]).fetchall()
    conn.close()

    employees_data = [_row_to_employee(r) for r in rows]

    # Enrich with computed pay
    enriched = []
    for e in employees_data:
        pay = compute_pay(e["employee_id"], e.get("weekly_values", []), e.get("adjustments"), e.get("deductions"))
        enriched.append({
            **e,
            "payable": round(pay["payable"], 2),
            "four_week_mean": round(pay["four_week_mean"], 2),
            "adjustment_total": round(pay["adjustment_total"], 2),
            "deduction_total": round(pay["deduction_total"], 2),
        })

    total_pages = (total + page_size - 1) // page_size

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "data": enriched,
    }


@app.get("/api/employees/departments")
def list_departments():
    conn = _get_conn()
    cur = conn.execute("SELECT DISTINCT department FROM employees ORDER BY department")
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]


@app.get("/api/employees/roles")
def list_roles():
    conn = _get_conn()
    cur = conn.execute("SELECT DISTINCT role FROM employees ORDER BY role")
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]


@app.get("/", response_class=HTMLResponse)
def home(request: Request, employee_id: Optional[str] = None):
    employees = _get_all_employees()
    selected_employee = None
    selected_summary = None
    selected_anomalies = None
    selected_recommendations = None
    not_found = False

    # Precompute dashboard summary for initial server render
    total = len(employees)
    payroll_total = 0.0
    for e in employees:
        pay = compute_pay(e["employee_id"], e.get("weekly_values", []), e.get("adjustments"), e.get("deductions"))
        payroll_total += pay["payable"]

    avg_salary = round(payroll_total / total, 2) if total else 0

    # Department list for filter dropdowns
    dept_set = sorted(set(e["department"] for e in employees))
    role_set = sorted(set(e["role"] for e in employees))

    if employee_id:
        try:
            selected_employee = read_employee(employee_id)
            selected_summary = compute_pay(
                selected_employee["employee_id"],
                selected_employee["weekly_values"],
                selected_employee.get("adjustments"),
                selected_employee.get("deductions"),
            )
            selected_anomalies = detect_anomalies(selected_employee.get("weekly_values", []))
            selected_recommendations = recommend_rules(
                selected_employee.get("weekly_values", []),
                selected_employee.get("adjustments"),
                selected_employee.get("deductions"),
            )
        except HTTPException:
            not_found = True
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "employees": employees,
            "total_employees": total,
            "total_payroll": round(payroll_total, 2),
            "avg_salary": avg_salary,
            "departments_list": dept_set,
            "roles_list": role_set,
            "selected_employee": selected_employee,
            "selected_summary": selected_summary,
            "selected_anomalies": selected_anomalies,
            "selected_recommendations": selected_recommendations,
            "not_found": not_found,
            "search_id": employee_id or "",
        },
    )
