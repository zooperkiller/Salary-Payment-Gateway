import csv
import json
import random
from pathlib import Path

FIRST_NAMES = [
    "Alex", "Sam", "Jordan", "Taylor", "Chris", "Pat", "Jamie", "Morgan",
    "Casey", "Riley", "Robin", "Lee", "Avery", "Drew", "Cameron",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis", "Garcia",
    "Rodriguez", "Wilson",
]


def random_weekly_values(base_weekly: float):
    weeks = []
    for i in range(4):
        noise = random.normalvariate(0, base_weekly * 0.05)
        if random.random() < 0.02:
            weeks.append(round(base_weekly * random.uniform(0.2, 2.5), 2))
        else:
            weeks.append(round(max(0, base_weekly + noise), 2))
    return weeks


def maybe_adjustments():
    if random.random() < 0.1:
        return {"bonus": round(random.uniform(50, 500), 2)}
    return {}


def maybe_deductions(base_weekly: float):
    tax = round(base_weekly * random.uniform(0.1, 0.2), 2)
    pension = round(base_weekly * random.uniform(0.02, 0.05), 2)
    return {"tax": tax, "pension": pension}


def generate(n=200, out_path="employees.csv"):
    path = Path(out_path)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "employee_id",
            "name",
            "department",
            "role",
            "weekly_values",
            "adjustments",
            "deductions",
        ])
        writer.writeheader()
        for i in range(n):
            emp_id = f"E{1000 + i}"
            name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
            dept = random.choice(["Finance", "Engineering", "HR", "Sales", "Support"])
            role = random.choice(["Engineer", "Manager", "Analyst", "Clerk", "Director"])
            base_weekly = round(random.uniform(400, 3000), 2)
            weeks = random_weekly_values(base_weekly)
            adjustments = maybe_adjustments()
            deductions = maybe_deductions(base_weekly)

            writer.writerow({
                "employee_id": emp_id,
                "name": name,
                "department": dept,
                "role": role,
                "weekly_values": json.dumps(weeks),
                "adjustments": json.dumps(adjustments),
                "deductions": json.dumps(deductions),
            })


if __name__ == "__main__":
    print("Generating 200 employee records to employees.csv")
    generate(200, out_path="employees.csv")
    print("Done: employees.csv")
