from typing import List, Optional, Dict


def four_week_mean(weeks: List[float]) -> float:
    """Compute 4-week rolling mean. If fewer than 4 weeks provided, average available weeks."""
    if not weeks:
        return 0.0
    return sum(weeks) / len(weeks)


def compute_pay(employee_id: str, weekly_values: List[float], adjustments: Optional[Dict[str, float]] = None, deductions: Optional[Dict[str, float]] = None) -> Dict:
    """Deterministic salary calculation using 4-week mean plus adjustments and deductions.

    Returns a dict with breakdown for auditability.
    """
    adjustments = adjustments or {}
    deductions = deductions or {}

    mean_4w = four_week_mean(weekly_values[-4:]) if weekly_values else 0.0

    adjustment_total = sum(adjustments.values()) if adjustments else 0.0
    deduction_total = sum(deductions.values()) if deductions else 0.0

    payable = mean_4w + adjustment_total - deduction_total

    return {
        "employee_id": employee_id,
        "weeks_considered": min(4, len(weekly_values)),
        "four_week_mean": mean_4w,
        "adjustment_total": adjustment_total,
        "deduction_total": deduction_total,
        "payable": payable,
    }


if __name__ == "__main__":
    # simple demo
    sample = compute_pay("E123", [1000, 1100, 1200, 1300], adjustments={"bonus": 50}, deductions={"tax": 100})
    print(sample)
