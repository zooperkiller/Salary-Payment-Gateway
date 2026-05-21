from salary_gateway.calculator import compute_pay


def test_four_week_mean_simple():
    r = compute_pay("E1", [100, 200, 300, 400])
    assert r["four_week_mean"] == 250
    assert r["payable"] == 250


def test_with_adjustments_and_deductions():
    r = compute_pay("E2", [100, 200, 300, 400], adjustments={"bonus": 50}, deductions={"tax": 25})
    assert r["four_week_mean"] == 250
    assert r["adjustment_total"] == 50
    assert r["deduction_total"] == 25
    assert r["payable"] == 275
