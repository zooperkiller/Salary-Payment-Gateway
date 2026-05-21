"""
Payroll calculator with US progressive tax computation (2026 brackets).

Tax brackets (annual taxable income):
  10%     $0 – $11,925
  12%     $11,926 – $48,475
  22%     $48,476 – $103,350
  24%     $103,351 – $197,300
  32%     $197,301 – $250,525
  35%     $250,526 – $626,350
  37%     $626,351+
"""

from typing import List, Optional, Dict, Tuple


# ── 2026 US Federal Progressive Tax Brackets ──────────────────────
TAX_BRACKETS: List[Tuple[float, float, float]] = [
    # (floor, ceiling, rate)  — ceiling of None means "unbounded"
    (0.0,      11_925.0,  0.10),
    (11_925.0, 48_475.0,  0.12),
    (48_475.0, 103_350.0, 0.22),
    (103_350.0, 197_300.0, 0.24),
    (197_300.0, 250_525.0, 0.32),
    (250_525.0, 626_350.0, 0.35),
    (626_350.0, float("inf"), 0.37),
]


def compute_progressive_tax(annual_taxable_income: float) -> float:
    """Calculate US federal progressive tax on annual taxable income.

    Args:
        annual_taxable_income: Gross annual salary (before deductions).

    Returns:
        Total annual tax owed (float, rounded to 2 decimal places).
    """
    if annual_taxable_income <= 0:
        return 0.0

    tax = 0.0
    remaining = annual_taxable_income

    for floor, ceiling, rate in TAX_BRACKETS:
        if remaining <= 0:
            break
        bracket_width = ceiling - floor
        taxable_in_bracket = min(remaining, bracket_width)
        tax += taxable_in_bracket * rate
        remaining -= taxable_in_bracket

    return round(tax, 2)


def compute_net_salary(
    gross_salary: float,
    total_deductions: float = 0.0,
    arrear_special_allowance: float = 0.0,
    arrear_statutory_bonus: float = 0.0,
    reimbursement_paid: float = 0.0,
    tax_spend: Optional[float] = None,
) -> Dict:
    """Compute net salary from gross and deductions; auto-calculate tax if not provided.

    Returns a dict with the full breakdown.
    """
    if tax_spend is None:
        tax_spend = compute_progressive_tax(gross_salary)

    net_salary = (
        gross_salary
        - total_deductions
        + arrear_special_allowance
        + arrear_statutory_bonus
        - tax_spend
        + reimbursement_paid
    )

    return {
        "gross_salary": gross_salary,
        "total_deductions": total_deductions,
        "arrear_special_allowance": arrear_special_allowance,
        "arrear_statutory_bonus": arrear_statutory_bonus,
        "reimbursement_paid": reimbursement_paid,
        "tax_spend": tax_spend,
        "net_salary": round(net_salary, 2),
        "tax_bracket": _get_tax_bracket(gross_salary),
    }


def _get_tax_bracket(income: float) -> str:
    """Return a human-readable bracket label for the given income."""
    for floor, ceiling, rate in TAX_BRACKETS:
        if income <= ceiling or ceiling == float("inf"):
            pct = int(rate * 100)
            if ceiling == float("inf"):
                return f"{pct}% (≥ ${floor:,.0f})"
            return f"{pct}% (${floor:,.0f} – ${ceiling:,.0f})"
    return "N/A"


def four_week_mean(weeks: List[float]) -> float:
    """Compute 4-week rolling mean. If fewer than 4 weeks provided, average available weeks."""
    if not weeks:
        return 0.0
    return sum(weeks) / len(weeks)


def compute_pay(
    employee_id: str,
    weekly_values: List[float],
    adjustments: Optional[Dict[str, float]] = None,
    deductions: Optional[Dict[str, float]] = None,
) -> Dict:
    """Deterministic salary calculation using 4-week mean plus adjustments and deductions.

    Returns a dict with breakdown for auditability.
    """
    adjustments = adjustments or {}
    deductions = deductions or {}

    mean_4w = four_week_mean(weekly_values[-4:]) if weekly_values else 0.0

    adjustment_total = sum(adjustments.values()) if adjustments else 0.0
    deduction_total = sum(deductions.values()) if deductions else 0.0

    payable = mean_4w + adjustment_total - deduction_total
    annual_estimate = payable * 52  # extrapolate to annual
    estimated_tax = compute_progressive_tax(annual_estimate)

    return {
        "employee_id": employee_id,
        "weeks_considered": min(4, len(weekly_values)),
        "four_week_mean": mean_4w,
        "adjustment_total": adjustment_total,
        "deduction_total": deduction_total,
        "payable": payable,
        "annual_estimate": round(annual_estimate, 2),
        "estimated_tax": estimated_tax,
        "tax_bracket": _get_tax_bracket(annual_estimate),
    }


if __name__ == "__main__":
    # simple demo
    sample = compute_pay("E123", [1000, 1100, 1200, 1300], adjustments={"bonus": 50}, deductions={"tax": 100})
    print(sample)

    # test tax brackets
    print("\nTax examples:")
    for inc in [10000, 30000, 50000, 90000, 150000, 225000, 300000, 700000]:
        t = compute_progressive_tax(inc)
        print(f"  Income ${inc:>10,.0f} → Tax ${t:>10,.2f}  ({t/inc*100:.1f}% effective)  [{_get_tax_bracket(inc)}]")
