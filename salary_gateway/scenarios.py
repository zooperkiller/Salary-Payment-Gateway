"""
What-If Scenario Modeling — apply salary adjustments and recompute taxes.

Usage:
    from salary_gateway.scenarios import apply_scenario

    result = apply_scenario(employees, [
        {
            "target_type": "department",
            "target_value": "Engineering",
            "field": "gross_salary",
            "adjustment_type": "percentage",
            "adjustment_value": 10.0,
        }
    ])
"""

from typing import Dict, List, Optional
import copy
import statistics

from salary_gateway.calculator import compute_net_salary, _get_tax_bracket

VALID_TARGET_TYPES = {"department", "employee", "grade", "designation", "company"}
VALID_FIELDS = {"gross_salary", "basic_salary", "statutory_bonus", "allowance"}
VALID_ADJUSTMENT_TYPES = {"percentage", "absolute", "set"}


def _apply_adjustment(old_value: float, adjustment_type: str, adjustment_value: float) -> float:
    """Return a new field value after applying the adjustment rule."""
    if adjustment_type == "percentage":
        return old_value * (1 + adjustment_value / 100.0)
    elif adjustment_type == "absolute":
        return old_value + adjustment_value
    elif adjustment_type == "set":
        return adjustment_value
    return old_value


def _employee_matches_adjustment(emp: Dict, adj: Dict) -> bool:
    """Return True if *all* conditions in the adjustment dict match this employee."""
    target_type = adj.get("target_type", "")
    target_value = adj.get("target_value", "")

    if target_type == "company":
        return True
    if target_type == "department":
        return (emp.get("department") or "").strip().lower() == (target_value or "").strip().lower()
    if target_type == "employee":
        return (emp.get("employee_id") or "").strip().lower() == (target_value or "").strip().lower()
    if target_type == "grade":
        return (emp.get("grade") or "").strip().lower() == (target_value or "").strip().lower()
    if target_type == "designation":
        return (emp.get("designation") or "").strip().lower() == (target_value or "").strip().lower()
    return False


def apply_scenario(employees: List[Dict], adjustments: List[Dict]) -> Dict:
    """Apply adjustments to matching employees, recompute taxes, and return before/after analysis.

    Args:
        employees: List of employee dicts (as returned from the DB).
        adjustments: List of adjustment specs, each with:
            - target_type: "department" | "employee" | "grade" | "designation" | "company"
            - target_value: string (ignored for "company")
            - field: "gross_salary" | "basic_salary" | "statutory_bonus" | "allowance"
            - adjustment_type: "percentage" | "absolute" | "set"
            - adjustment_value: float

    Returns:
        Dict with before/after aggregates, department breakdown, and tax bracket shifts.
    """
    # ── 1. Deep-copy ──────────────────────────────────────────────
    scenario_employees = copy.deepcopy(employees)

    # ── 2. Identify & modify affected employees ────────────────────
    affected_ids: set = set()
    employee_by_id: Dict[str, Dict] = {}

    for emp in scenario_employees:
        eid = (emp.get("employee_id") or "").strip()
        if eid:
            employee_by_id[eid] = emp

    for adj in adjustments:
        for emp in scenario_employees:
            if _employee_matches_adjustment(emp, adj):
                field = adj.get("field", "")
                old_val = float(emp.get(field) or 0)
                new_val = max(0.0, _apply_adjustment(old_val, adj.get("adjustment_type", ""), float(adj.get("adjustment_value") or 0)))
                emp[field] = round(new_val, 2)
                eid = (emp.get("employee_id") or "").strip()
                if eid:
                    affected_ids.add(eid)

    # ── 3. Recompute tax for affected employees ────────────────────
    # Track bracket shifts
    bracket_shifts: Dict[str, Dict[str, int]] = {}  # "from_bracket" -> {"to_bracket": count}

    for eid in affected_ids:
        emp = employee_by_id.get(eid)
        if emp is None:
            continue

        gross = float(emp.get("gross_salary") or 0)
        deductions = float(emp.get("total_deductions") or 0)
        allowance = float(emp.get("arrear_special_allowance") or 0)
        bonus = float(emp.get("arrear_statutory_bonus") or 0)
        reimburse = float(emp.get("reimbursement_paid") or 0)

        before_bracket = emp.get("tax_bracket") or _get_tax_bracket(float(emp.get("_original_gross_salary", gross)))

        # If gross_salary was not modified, use the stored original to compare
        original_gross = float(emp.get("_original_gross_salary", 0)) if "_original_gross_salary" in emp else gross

        result = compute_net_salary(
            gross_salary=gross,
            total_deductions=deductions,
            arrear_special_allowance=allowance,
            arrear_statutory_bonus=bonus,
            reimbursement_paid=reimburse,
        )

        after_bracket = result["tax_bracket"]
        emp["tax_spend"] = result["tax_spend"]
        emp["net_salary"] = result["net_salary"]
        emp["tax_bracket"] = after_bracket

        # Track bracket shift
        if before_bracket and after_bracket and before_bracket != after_bracket:
            if before_bracket not in bracket_shifts:
                bracket_shifts[before_bracket] = {}
            bracket_shifts[before_bracket][after_bracket] = bracket_shifts[before_bracket].get(after_bracket, 0) + 1

    # ── 4. Before aggregates (stored on originals reference) ───────
    def _aggregate(emps: List[Dict]) -> Dict:
        total_emp = 0
        total_gross = 0.0
        total_net = 0.0
        total_tax = 0.0
        net_vals = []
        gross_vals = []
        for e in emps:
            total_emp += 1
            gs = float(e.get("gross_salary") or 0)
            ns = float(e.get("net_salary") or 0)
            ts = float(e.get("tax_spend") or 0)
            total_gross += gs
            total_net += ns
            total_tax += ts
            net_vals.append(ns)
            gross_vals.append(gs)
        return {
            "total_employees": total_emp,
            "total_gross_payroll": round(total_gross, 2),
            "total_net_payroll": round(total_net, 2),
            "total_tax": round(total_tax, 2),
            "avg_net_salary": round(statistics.mean(net_vals), 2) if net_vals else 0,
            "avg_gross_salary": round(statistics.mean(gross_vals), 2) if gross_vals else 0,
        }

    before = _aggregate(employees)
    after = _aggregate(scenario_employees)

    after["affected_employees"] = len(affected_ids)
    after["delta_gross"] = round(after["total_gross_payroll"] - before["total_gross_payroll"], 2)
    after["delta_net"] = round(after["total_net_payroll"] - before["total_net_payroll"], 2)
    after["delta_tax"] = round(after["total_tax"] - before["total_tax"], 2)
    after["delta_pct"] = (
        round((after["total_net_payroll"] - before["total_net_payroll"]) / before["total_net_payroll"] * 100, 2)
        if before["total_net_payroll"] > 0
        else 0
    )

    # ── 5. Per-department breakdown ───────────────────────────────
    def _dept_aggregate(emps: List[Dict]) -> Dict[str, Dict]:
        depts: Dict[str, Dict] = {}
        for e in emps:
            d = (e.get("department") or "Unknown").strip()
            if d not in depts:
                depts[d] = {"net": 0.0, "count": 0}
            depts[d]["net"] += float(e.get("net_salary") or 0)
            depts[d]["count"] += 1
        return depts

    before_dept = _dept_aggregate(employees)
    after_dept = _dept_aggregate(scenario_employees)

    affected_departments: List[Dict] = []
    all_dept_names = set(list(before_dept.keys()) + list(after_dept.keys()))
    for dname in sorted(all_dept_names):
        b_net = before_dept.get(dname, {}).get("net", 0.0)
        a_net = after_dept.get(dname, {}).get("net", 0.0)
        delta = a_net - b_net
        if abs(delta) > 0.01:
            affected_departments.append({
                "name": dname,
                "before_net": round(b_net, 2),
                "after_net": round(a_net, 2),
                "delta": round(delta, 2),
                "delta_pct": round((delta / b_net) * 100, 2) if b_net > 0 else 0,
            })

    # ── 6. Tax bracket shifts ──────────────────────────────────────
    bracket_shift_list: List[Dict] = []
    for from_bracket, to_map in bracket_shifts.items():
        for to_bracket, count in to_map.items():
            bracket_shift_list.append({
                "from_bracket": from_bracket,
                "to_bracket": to_bracket,
                "employees_moved": count,
            })

    return {
        "before": before,
        "after": after,
        "affected_departments": affected_departments,
        "tax_bracket_shifts": bracket_shift_list,
        "adjustments_applied": len(adjustments),
    }