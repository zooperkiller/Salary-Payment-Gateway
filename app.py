from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Dict, Optional
from salary_gateway.calculator import compute_pay

app = FastAPI(title="Salary Payment Gateway - Minimal API")


class CalcRequest(BaseModel):
    employee_id: str
    weekly_values: List[float]
    adjustments: Optional[Dict[str, float]] = None
    deductions: Optional[Dict[str, float]] = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/calculate")
def calculate(req: CalcRequest):
    return compute_pay(req.employee_id, req.weekly_values, req.adjustments, req.deductions)
