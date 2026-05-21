from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import List, Dict, Optional
from salary_gateway.calculator import compute_pay
import sqlite3
import json
from pathlib import Path
from salary_gateway.analytics import detect_anomalies, recommend_rules

app = FastAPI(title="Salary Payment Gateway - Minimal API")


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
