"""Advanced payroll analytics: salary bands, gender pay gap, department KPIs, age distributions, etc."""
from typing import List, Dict, Optional, Any
import statistics
import math


def detect_anomalies(values: List[float], threshold: float = 0.5) -> Dict:
    """Flag values deviating > threshold * mean. Returns mean, stdev, anomaly list."""
    if not values:
        return {"mean": 0.0, "stdev": 0.0, "anomalies": []}
    mean = statistics.mean(values)
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
    anomalies = []
    for idx, v in enumerate(values):
        if mean == 0:
            continue
        deviation = abs(v - mean) / mean
        if deviation > threshold:
            anomalies.append({
                "index": idx,
                "value": round(v, 2),
                "deviation_pct": round((v - mean) / mean * 100, 1),
            })
    return {
        "mean": round(mean, 2),
        "stdev": round(stdev, 2),
        "anomalies": anomalies,
    }


def salary_bands(rows: List[Dict], field: str = "net_salary") -> Dict:
    """Bucket salaries into predefined bands for distribution charts."""
    values = [r.get(field, 0) or 0 for r in rows if r.get(field)]
    if not values:
        return {"bands": [], "counts": [], "avg_per_band": []}

    band_defs = [
        (0, 25000, "$0–$25K"),
        (25001, 50000, "$25K–$50K"),
        (50001, 75000, "$50K–$75K"),
        (75001, 100000, "$75K–$100K"),
        (100001, 150000, "$100K–$150K"),
        (150001, 250000, "$150K–$250K"),
        (250001, 500000, "$250K–$500K"),
        (500001, 1000000, "$500K–$1M"),
        (1000001, float("inf"), "$1M+"),
    ]

    bands = []
    counts = []
    avgs = []
    for lo, hi, label in band_defs:
        band_vals = [v for v in values if lo <= v <= hi]
        bands.append(label)
        counts.append(len(band_vals))
        avgs.append(round(statistics.mean(band_vals), 2) if band_vals else 0)

    return {"bands": bands, "counts": counts, "avg_per_band": avgs}


def gender_pay_gap(rows: List[Dict]) -> Dict:
    """Compute gender-based salary statistics."""
    by_gender: Dict[str, list] = {}
    for r in rows:
        g = (r.get("gender") or "Unknown").strip()
        ns = r.get("net_salary") or 0
        bs = r.get("basic_salary") or 0
        gs = r.get("gross_salary") or 0
        if g not in by_gender:
            by_gender[g] = []
        by_gender[g].append({"net": ns, "basic": bs, "gross": gs, "designation": r.get("designation", "")})

    result = {"genders": [], "avg_net": [], "avg_basic": [], "avg_gross": [], "counts": [], "gap_pct": None}
    avgs = {}
    for g, items in by_gender.items():
        result["genders"].append(g)
        result["counts"].append(len(items))
        result["avg_net"].append(round(statistics.mean([i["net"] for i in items]), 2))
        result["avg_basic"].append(round(statistics.mean([i["basic"] for i in items]), 2))
        result["avg_gross"].append(round(statistics.mean([i["gross"] for i in items]), 2))
        avgs[g] = statistics.mean([i["net"] for i in items])

    # Pay gap: highest avg vs lowest avg
    if len(avgs) >= 2:
        max_avg = max(avgs.values())
        min_avg = min(avgs.values())
        if max_avg > 0:
            result["gap_pct"] = round((max_avg - min_avg) / max_avg * 100, 1)
            result["highest_gender"] = max(avgs, key=avgs.get)
            result["lowest_gender"] = min(avgs, key=avgs.get)

    return result


def department_kpis(rows: List[Dict]) -> List[Dict]:
    """Per-department KPIs: headcount, total payroll, avg salary, gender ratio, active ratio."""
    depts: Dict[str, dict] = {}
    for r in rows:
        d = (r.get("department") or "Unknown").strip()
        if d not in depts:
            depts[d] = {
                "count": 0, "active": 0, "male": 0, "female": 0,
                "net_salaries": [], "basic_salaries": [], "gross_salaries": [],
                "ages": [], "taxes": [],
            }
        depts[d]["count"] += 1
        if (r.get("employee_status") or "").strip().lower() == "active":
            depts[d]["active"] += 1
        g = (r.get("gender") or "").strip().lower()
        if g == "male":
            depts[d]["male"] += 1
        elif g == "female":
            depts[d]["female"] += 1
        ns = r.get("net_salary")
        if ns: depts[d]["net_salaries"].append(ns)
        bs = r.get("basic_salary")
        if bs: depts[d]["basic_salaries"].append(bs)
        gs = r.get("gross_salary")
        if gs: depts[d]["gross_salaries"].append(gs)
        age = r.get("age")
        if age: depts[d]["ages"].append(age)
        tx = r.get("tax_spend")
        if tx: depts[d]["taxes"].append(tx)

    result = []
    for name, data in sorted(depts.items()):
        result.append({
            "name": name,
            "headcount": data["count"],
            "active_count": data["active"],
            "active_pct": round(data["active"] / data["count"] * 100, 1) if data["count"] else 0,
            "male_pct": round(data["male"] / data["count"] * 100, 1) if data["count"] else 0,
            "female_pct": round(data["female"] / data["count"] * 100, 1) if data["count"] else 0,
            "avg_net_salary": round(statistics.mean(data["net_salaries"]), 2) if data["net_salaries"] else 0,
            "avg_basic_salary": round(statistics.mean(data["basic_salaries"]), 2) if data["basic_salaries"] else 0,
            "avg_gross_salary": round(statistics.mean(data["gross_salaries"]), 2) if data["gross_salaries"] else 0,
            "total_net_payroll": round(sum(data["net_salaries"]), 2),
            "avg_age": round(statistics.mean(data["ages"]), 1) if data["ages"] else 0,
            "avg_tax": round(statistics.mean(data["taxes"]), 2) if data["taxes"] else 0,
        })
    return result


def age_distribution(rows: List[Dict]) -> Dict:
    """Age distribution across brackets."""
    ages = [r.get("age") for r in rows if r.get("age") and r.get("age") > 0]
    if not ages:
        return {"brackets": [], "counts": []}

    brackets = [
        (16, 20, "16–20"), (21, 25, "21–25"), (26, 30, "26–30"),
        (31, 35, "31–35"), (36, 40, "36–40"), (41, 45, "41–45"),
        (46, 50, "46–50"), (51, 55, "51–55"), (56, 60, "56–60"),
        (61, 100, "60+"),
    ]
    labels = []
    counts = []
    for lo, hi, label in brackets:
        labels.append(label)
        counts.append(sum(1 for a in ages if lo <= a <= hi))

    return {
        "brackets": labels,
        "counts": counts,
        "avg_age_overall": round(statistics.mean(ages), 1),
        "median_age": round(statistics.median(ages), 1),
        "min_age": min(ages),
        "max_age": max(ages),
    }


def tenure_distribution(rows: List[Dict]) -> Dict:
    """Tenure bracket distribution."""
    tenures: Dict[str, int] = {}
    for r in rows:
        t = (r.get("tenure") or "Unknown").strip()
        tenures[t] = tenures.get(t, 0) + 1
    return {"labels": list(tenures.keys()), "counts": list(tenures.values())}


def country_distribution(rows: List[Dict]) -> Dict:
    """Employee distribution by country."""
    countries: Dict[str, int] = {}
    for r in rows:
        c = (r.get("country") or "Unknown").strip()
        countries[c] = countries.get(c, 0) + 1
    sorted_items = sorted(countries.items(), key=lambda x: x[1], reverse=True)
    return {"labels": [k for k, v in sorted_items], "counts": [v for k, v in sorted_items]}


def designation_distribution(rows: List[Dict]) -> Dict:
    """Top designations by headcount."""
    desigs: Dict[str, int] = {}
    for r in rows:
        d = (r.get("designation") or "Unknown").strip()
        desigs[d] = desigs.get(d, 0) + 1
    sorted_items = sorted(desigs.items(), key=lambda x: x[1], reverse=True)[:15]
    return {"labels": [k for k, v in sorted_items], "counts": [v for k, v in sorted_items]}


def top_earners(rows: List[Dict], field: str = "net_salary", limit: int = 10) -> List[Dict]:
    """Return top N earners by a given salary field."""
    valid = [r for r in rows if r.get(field)]
    sorted_rows = sorted(valid, key=lambda r: r[field], reverse=True)
    return [
        {
            "employee_id": r.get("employee_id"),
            "name": f"{r.get('first_name','')} {r.get('last_name','')}".strip(),
            "department": r.get("department"),
            "designation": r.get("designation"),
            "country": r.get("country"),
            "gender": r.get("gender"),
            "net_salary": r.get("net_salary"),
            "basic_salary": r.get("basic_salary"),
            "gross_salary": r.get("gross_salary"),
            "tax_spend": r.get("tax_spend"),
        }
        for r in sorted_rows[:limit]
    ]


def recommend_rules(row: Dict) -> Dict:
    """Recommendation engine for a single employee row."""
    recs = []
    net = row.get("net_salary") or 0
    gross = row.get("gross_salary") or 0
    tax = row.get("tax_spend") or 0
    basic = row.get("basic_salary") or 0

    if gross and net:
        ratio = net / gross if gross else 0
        if ratio < 0.5:
            recs.append(f"Net salary is only {ratio*100:.0f}% of gross — verify deductions and tax calculations.")
        elif ratio > 0.95:
            recs.append("Net salary is very close to gross — minimal deductions applied; verify tax compliance.")

    if gross and basic:
        basic_ratio = basic / gross
        if basic_ratio < 0.1:
            recs.append("Basic salary is unusually low relative to gross — review pay structure.")

    if tax and gross:
        tax_rate = tax / gross if gross else 0
        if tax_rate > 0.5:
            recs.append(f"Tax spend is {tax_rate*100:.0f}% of gross salary — unusually high, verify tax codes.")

    status = (row.get("employee_status") or "").strip().lower()
    if status == "inactive" and row.get("net_salary", 0) > 0:
        recs.append("Inactive employee still receiving salary — verify termination status.")

    if not recs:
        recs.append("No rule violations detected — payroll data appears consistent.")

    return {"recommendations": recs}


def build_full_dashboard(rows: List[Dict]) -> Dict:
    """Build complete dashboard analytics payload."""
    total = len(rows)
    if not total:
        return {"total_employees": 0}

    active_count = sum(1 for r in rows if (r.get("employee_status") or "").strip().lower() == "active")
    inactive_count = total - active_count
    perm_count = sum(1 for r in rows if (r.get("employee_type") or "").strip().lower() == "permanent")
    temp_count = sum(1 for r in rows if (r.get("employee_type") or "").strip().lower() == "temporary")
    external_count = sum(1 for r in rows if (r.get("employee_type") or "").strip().lower() == "external user")

    total_net = sum(r.get("net_salary", 0) or 0 for r in rows)
    total_gross = sum(r.get("gross_salary", 0) or 0 for r in rows)
    total_basic = sum(r.get("basic_salary", 0) or 0 for r in rows)
    total_tax = sum(r.get("tax_spend", 0) or 0 for r in rows)
    total_reimburse = sum(r.get("reimbursement_paid", 0) or 0 for r in rows)

    net_vals = [r.get("net_salary", 0) or 0 for r in rows if r.get("net_salary")]
    gross_vals = [r.get("gross_salary", 0) or 0 for r in rows if r.get("gross_salary")]

    return {
        "total_employees": total,
        "active_count": active_count,
        "inactive_count": inactive_count,
        "active_pct": round(active_count / total * 100, 1) if total else 0,
        "permanent_count": perm_count,
        "temporary_count": temp_count,
        "external_count": external_count,
        "total_net_payroll": total_net,
        "total_gross_payroll": total_gross,
        "total_basic_payroll": total_basic,
        "total_tax": total_tax,
        "total_reimbursement": total_reimburse,
        "avg_net_salary": round(statistics.mean(net_vals), 2) if net_vals else 0,
        "median_net_salary": round(statistics.median(net_vals), 2) if net_vals else 0,
        "avg_gross_salary": round(statistics.mean(gross_vals), 2) if gross_vals else 0,
        "min_net_salary": min(net_vals) if net_vals else 0,
        "max_net_salary": max(net_vals) if net_vals else 0,
        "salary_bands": salary_bands(rows),
        "department_kpis": department_kpis(rows),
        "gender_pay_gap": gender_pay_gap(rows),
        "age_distribution": age_distribution(rows),
        "tenure_distribution": tenure_distribution(rows),
        "country_distribution": country_distribution(rows),
        "designation_distribution": designation_distribution(rows),
        "top_earners": top_earners(rows),
    }
