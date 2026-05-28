"""
Multi-Company Employee Data Generator
======================================
Generates 3 realistic companies with 11,500+ employees directly into employees.db.
Each company has its own department structure, country mix, salary bands, and culture.

Companies:
  1. acme-tech    — Acme Technologies Inc. (SaaS/Cloud, US-based, ~4,500 employees)
  2. globex-mfg   — Globex Manufacturing Corp (Heavy Mfg, Germany-based, ~4,000 employees)
  3. apex-fin     — Apex Financial Services Ltd (Banking/FinTech, UK-based, ~3,000 employees)

Usage:
    python scripts/generate_multi_company.py

Idempotent: re-running skips already-inserted employee IDs.
Preserves the existing 'default' company and its employees untouched.
"""

import sqlite3
import random
import sys
import math
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

# ── Add parent to path so we can import salary_gateway ─────────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from salary_gateway.calculator import compute_net_salary

DB_PATH = Path(__file__).resolve().parent.parent / "employees.db"

random.seed(42)  # reproducible

# ═══════════════════════════════════════════════════════════════════
#  DATA POOLS
# ═══════════════════════════════════════════════════════════════════

MALE_FIRST = [
    "James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph",
    "Thomas", "Daniel", "Matthew", "Anthony", "Mark", "Donald", "Steven", "Paul",
    "Andrew", "Joshua", "Kenneth", "Kevin", "Brian", "George", "Timothy", "Ronald",
    "Edward", "Jason", "Jeffrey", "Ryan", "Jacob", "Nicholas", "Gary", "Eric",
    "Jonathan", "Stephen", "Larry", "Justin", "Scott", "Brandon", "Benjamin", "Samuel",
    "Raymond", "Gregory", "Frank", "Alexander", "Patrick", "Jack", "Dennis", "Jerry",
    "Tyler", "Aaron", "Jose", "Adam", "Nathan", "Henry", "Douglas", "Zachary",
    "Peter", "Kyle", "Walter", "Ethan", "Jeremy", "Harold", "Keith", "Christian",
    "Roger", "Noah", "Gerald", "Carl", "Terry", "Sean", "Austin", "Arthur",
    "Lawrence", "Jesse", "Dylan", "Bryan", "Joe", "Jordan", "Billy", "Bruce",
    "Albert", "Willie", "Gabriel", "Logan", "Alan", "Juan", "Wayne", "Roy",
    "Ralph", "Randy", "Eugene", "Vincent", "Russell", "Elijah", "Louis", "Bobby",
    "Philip", "Johnny", "Bradley", "Liam", "Oliver", "Lucas", "Mason", "Ethan", "Noah",
]

FEMALE_FIRST = [
    "Mary", "Patricia", "Jennifer", "Linda", "Barbara", "Elizabeth", "Susan", "Jessica",
    "Sarah", "Karen", "Lisa", "Nancy", "Betty", "Margaret", "Sandra", "Ashley",
    "Dorothy", "Kimberly", "Emily", "Donna", "Michelle", "Carol", "Amanda", "Melissa",
    "Deborah", "Stephanie", "Rebecca", "Sharon", "Laura", "Cynthia", "Kathleen", "Amy",
    "Angela", "Shirley", "Anna", "Brenda", "Pamela", "Emma", "Nicole", "Helen",
    "Samantha", "Katherine", "Christine", "Debra", "Rachel", "Carolyn", "Janet", "Catherine",
    "Maria", "Heather", "Diane", "Ruth", "Julie", "Olivia", "Joyce", "Virginia",
    "Victoria", "Kelly", "Lauren", "Christina", "Joan", "Madison", "Abigail", "Megan",
    "Alice", "Donna", "Dawn", "Teresa", "Gloria", "Charlotte", "Marie", "Judith",
    "Hannah", "Grace", "Sophia", "Isabella", "Mia", "Amelia", "Harper", "Evelyn",
    "Aria", "Scarlett", "Zoe", "Lily", "Layla", "Riley", "Nora", "Ellie",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
    "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill",
    "Flores", "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell",
    "Mitchell", "Carter", "Roberts", "Gomez", "Phillips", "Evans", "Turner", "Diaz",
    "Parker", "Cruz", "Edwards", "Collins", "Reyes", "Stewart", "Morris", "Morales",
    "Murphy", "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan", "Cooper", "Peterson",
    "Bailey", "Reed", "Kelly", "Howard", "Ramos", "Kim", "Cox", "Ward",
    "Richardson", "Watson", "Brooks", "Chavez", "Wood", "James", "Bennett", "Gray",
    "Mendoza", "Ruiz", "Hughes", "Price", "Alvarez", "Castillo", "Sanders", "Patel",
    "Myers", "Long", "Ross", "Foster", "Müller", "Schmidt", "Weber", "Fischer",
    "Singh", "Kumar", "Sharma", "Chen", "Wang", "Zhang", "Tanaka", "Sato",
    "Dubois", "Leroy", "Bernard", "Petit", "Rossi", "Bianchi", "Ferrari", "Esposito",
]

ETHNICITIES = [
    "White/Caucasian", "Asian", "Hispanic/Latino", "Black/African American",
    "Middle Eastern", "South Asian", "East Asian", "Southeast Asian",
    "Native American", "Pacific Islander", "Mixed/Other",
]

MARITAL_STATUSES = ["Single", "Married", "Divorced", "Widowed", "Civil Partnership"]

# ═══════════════════════════════════════════════════════════════════
#  COUNTRY DATA
# ═══════════════════════════════════════════════════════════════════

COUNTRY_CONTINENT = {
    "United States": "Americas",
    "Canada": "Americas",
    "Mexico": "Americas",
    "Brazil": "Americas",
    "United Kingdom": "Europe",
    "Germany": "Europe",
    "France": "Europe",
    "Italy": "Europe",
    "Spain": "Europe",
    "Netherlands": "Europe",
    "Poland": "Europe",
    "Czech Republic": "Europe",
    "Switzerland": "Europe",
    "Sweden": "Europe",
    "Ireland": "Europe",
    "India": "Asia",
    "China": "Asia",
    "Japan": "Asia",
    "Singapore": "Asia",
    "Hong Kong": "Asia",
    "South Korea": "Asia",
    "UAE": "Asia",
    "Australia": "Oceania",
    "South Africa": "Africa",
    "Kenya": "Africa",
    "Nigeria": "Africa",
}

def _country_info(country: str) -> Tuple[str, str]:
    """Return (country_name, continent)."""
    return country, COUNTRY_CONTINENT.get(country, "Europe")

# ═══════════════════════════════════════════════════════════════════
#  COMPANY PROFILES
# ═══════════════════════════════════════════════════════════════════

COMPANY_PROFILES = {
    "acme-tech": {
        "name": "Acme Technologies Inc.",
        "currency": "USD",
        "tax_country": "US",
        "fiscal_year_start": "01-01",
        "total_employees": 4500,
        "headquarters_country": "United States",
        "countries": {
            "United States": 0.60,
            "India": 0.20,
            "Canada": 0.10,
            "United Kingdom": 0.05,
            "Ireland": 0.03,
            "Australia": 0.02,
        },
        "departments": {
            "Engineering": {
                "weight": 0.40,
                "salary_range": (80000, 180000),
                "designations": [
                    ("Junior Software Engineer", 0.20),
                    ("Software Engineer", 0.30),
                    ("Senior Software Engineer", 0.25),
                    ("Staff Engineer", 0.10),
                    ("Principal Engineer", 0.08),
                    ("Engineering Manager", 0.05),
                    ("Director of Engineering", 0.02),
                ],
                "grades": ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"],
                "business_unit": "Product & Technology",
            },
            "Product": {
                "weight": 0.10,
                "salary_range": (70000, 150000),
                "designations": [
                    ("Associate Product Manager", 0.20),
                    ("Product Manager", 0.35),
                    ("Senior Product Manager", 0.25),
                    ("Director of Product", 0.12),
                    ("VP of Product", 0.08),
                ],
                "grades": ["L3", "L4", "L5", "L6", "L7", "L8"],
                "business_unit": "Product & Technology",
            },
            "Sales": {
                "weight": 0.155,
                "salary_range": (50000, 160000),
                "designations": [
                    ("Sales Development Rep", 0.25),
                    ("Account Executive", 0.35),
                    ("Senior Account Executive", 0.20),
                    ("Sales Manager", 0.10),
                    ("Regional Sales Director", 0.07),
                    ("VP of Sales", 0.03),
                ],
                "grades": ["L2", "L3", "L4", "L5", "L6", "L7"],
                "business_unit": "Go-To-Market",
            },
            "Marketing": {
                "weight": 0.078,
                "salary_range": (45000, 130000),
                "designations": [
                    ("Marketing Specialist", 0.30),
                    ("Content Marketing Manager", 0.20),
                    ("Digital Marketing Manager", 0.20),
                    ("Brand Manager", 0.15),
                    ("Director of Marketing", 0.10),
                    ("VP of Marketing", 0.05),
                ],
                "grades": ["L2", "L3", "L4", "L5", "L6", "L7"],
                "business_unit": "Go-To-Market",
            },
            "Human Resources": {
                "weight": 0.067,
                "salary_range": (40000, 120000),
                "designations": [
                    ("HR Coordinator", 0.25),
                    ("HR Business Partner", 0.30),
                    ("Senior HRBP", 0.20),
                    ("Talent Acquisition Lead", 0.15),
                    ("Director of HR", 0.07),
                    ("VP of People", 0.03),
                ],
                "grades": ["L2", "L3", "L4", "L5", "L6", "L7"],
                "business_unit": "People & Culture",
            },
            "Finance": {
                "weight": 0.055,
                "salary_range": (50000, 140000),
                "designations": [
                    ("Financial Analyst", 0.30),
                    ("Senior Financial Analyst", 0.25),
                    ("Finance Manager", 0.20),
                    ("Controller", 0.15),
                    ("Director of Finance", 0.07),
                    ("CFO", 0.03),
                ],
                "grades": ["L2", "L3", "L4", "L5", "L6", "L7", "L8"],
                "business_unit": "Finance & Legal",
            },
            "Customer Success": {
                "weight": 0.089,
                "salary_range": (35000, 90000),
                "designations": [
                    ("Customer Support Agent", 0.35),
                    ("Customer Success Manager", 0.30),
                    ("Senior CSM", 0.20),
                    ("Team Lead CS", 0.10),
                    ("Director of Customer Success", 0.05),
                ],
                "grades": ["L1", "L2", "L3", "L4", "L5", "L6"],
                "business_unit": "Go-To-Market",
            },
            "IT & Security": {
                "weight": 0.056,
                "salary_range": (55000, 155000),
                "designations": [
                    ("IT Support Specialist", 0.25),
                    ("Systems Administrator", 0.20),
                    ("Security Engineer", 0.25),
                    ("DevOps Engineer", 0.20),
                    ("Director of IT", 0.10),
                ],
                "grades": ["L2", "L3", "L4", "L5", "L6", "L7"],
                "business_unit": "Product & Technology",
            },
        },
        "allowance_pct": (0.08, 0.18),       # 8-18% of basic
        "bonus_pct_range": (0.05, 0.30),      # 5-30% of basic (tech style)
        "deductions_pct": (0.10, 0.20),       # 10-20% of gross
        "reimbursement_chance": 0.08,
        "arrear_chance": 0.03,
        "inactive_pct": 0.05,
        "employee_types": {"Permanent": 0.85, "Temporary": 0.10, "External User": 0.05},
    },

    "globex-mfg": {
        "name": "Globex Manufacturing Corp",
        "currency": "EUR",
        "tax_country": "DE",
        "fiscal_year_start": "04-01",
        "total_employees": 4000,
        "headquarters_country": "Germany",
        "countries": {
            "Germany": 0.50,
            "Poland": 0.20,
            "Czech Republic": 0.15,
            "France": 0.08,
            "Italy": 0.04,
            "Netherlands": 0.03,
        },
        "departments": {
            "Production": {
                "weight": 0.30,
                "salary_range": (30000, 75000),
                "designations": [
                    ("Production Operator", 0.35),
                    ("Senior Operator", 0.25),
                    ("Shift Supervisor", 0.18),
                    ("Production Engineer", 0.12),
                    ("Production Manager", 0.07),
                    ("Plant Director", 0.03),
                ],
                "grades": ["G1", "G2", "G3", "G4", "G5", "G6", "G7"],
                "business_unit": "Operations",
            },
            "Engineering": {
                "weight": 0.15,
                "salary_range": (45000, 110000),
                "designations": [
                    ("Junior Engineer", 0.20),
                    ("Engineer", 0.30),
                    ("Senior Engineer", 0.25),
                    ("Lead Engineer", 0.12),
                    ("Engineering Manager", 0.08),
                    ("Chief Engineer", 0.05),
                ],
                "grades": ["G3", "G4", "G5", "G6", "G7", "G8"],
                "business_unit": "Technology",
            },
            "Quality Assurance": {
                "weight": 0.0875,
                "salary_range": (32000, 70000),
                "designations": [
                    ("QA Inspector", 0.30),
                    ("QA Technician", 0.25),
                    ("QA Engineer", 0.20),
                    ("Senior QA Engineer", 0.15),
                    ("QA Manager", 0.10),
                ],
                "grades": ["G2", "G3", "G4", "G5", "G6"],
                "business_unit": "Operations",
            },
            "Logistics": {
                "weight": 0.10,
                "salary_range": (28000, 65000),
                "designations": [
                    ("Warehouse Operator", 0.35),
                    ("Logistics Coordinator", 0.25),
                    ("Supply Chain Analyst", 0.18),
                    ("Logistics Supervisor", 0.12),
                    ("Logistics Manager", 0.07),
                    ("Head of Supply Chain", 0.03),
                ],
                "grades": ["G1", "G2", "G3", "G4", "G5", "G6", "G7"],
                "business_unit": "Operations",
            },
            "Sales": {
                "weight": 0.0875,
                "salary_range": (40000, 100000),
                "designations": [
                    ("Sales Representative", 0.30),
                    ("Key Account Manager", 0.25),
                    ("Regional Sales Manager", 0.20),
                    ("Business Development Manager", 0.15),
                    ("Director of Sales", 0.10),
                ],
                "grades": ["G3", "G4", "G5", "G6", "G7"],
                "business_unit": "Commercial",
            },
            "Human Resources": {
                "weight": 0.075,
                "salary_range": (35000, 90000),
                "designations": [
                    ("HR Administrator", 0.30),
                    ("HR Officer", 0.25),
                    ("HR Business Partner", 0.20),
                    ("Senior HR Manager", 0.15),
                    ("Director of HR", 0.10),
                ],
                "grades": ["G2", "G3", "G4", "G5", "G6", "G7"],
                "business_unit": "People",
            },
            "Finance": {
                "weight": 0.05,
                "salary_range": (38000, 95000),
                "designations": [
                    ("Finance Assistant", 0.25),
                    ("Accountant", 0.30),
                    ("Finance Controller", 0.20),
                    ("Senior Controller", 0.15),
                    ("Finance Director", 0.10),
                ],
                "grades": ["G3", "G4", "G5", "G6", "G7"],
                "business_unit": "Finance",
            },
            "Maintenance": {
                "weight": 0.075,
                "salary_range": (28000, 65000),
                "designations": [
                    ("Maintenance Technician", 0.40),
                    ("Electrical Technician", 0.25),
                    ("Maintenance Supervisor", 0.18),
                    ("Facilities Manager", 0.12),
                    ("Head of Maintenance", 0.05),
                ],
                "grades": ["G1", "G2", "G3", "G4", "G5", "G6"],
                "business_unit": "Operations",
            },
            "R&D": {
                "weight": 0.075,
                "salary_range": (50000, 115000),
                "designations": [
                    ("Research Associate", 0.25),
                    ("R&D Engineer", 0.30),
                    ("Senior R&D Engineer", 0.20),
                    ("R&D Project Lead", 0.15),
                    ("Head of R&D", 0.10),
                ],
                "grades": ["G3", "G4", "G5", "G6", "G7", "G8"],
                "business_unit": "Technology",
            },
        },
        "allowance_pct": (0.12, 0.25),       # generous allowances (union style)
        "bonus_pct_range": (0.03, 0.15),      # lower bonuses
        "deductions_pct": (0.18, 0.30),       # higher deductions (European)
        "reimbursement_chance": 0.05,
        "arrear_chance": 0.04,
        "inactive_pct": 0.04,
        "employee_types": {"Permanent": 0.88, "Temporary": 0.10, "External User": 0.02},
    },

    "apex-fin": {
        "name": "Apex Financial Services Ltd",
        "currency": "GBP",
        "tax_country": "UK",
        "fiscal_year_start": "04-06",
        "total_employees": 3000,
        "headquarters_country": "United Kingdom",
        "countries": {
            "United Kingdom": 0.55,
            "Singapore": 0.15,
            "Hong Kong": 0.10,
            "United Arab Emirates": 0.10,
            "United States": 0.05,
            "Switzerland": 0.05,
        },
        "departments": {
            "Investment Banking": {
                "weight": 0.133,
                "salary_range": (80000, 250000),
                "designations": [
                    ("Analyst", 0.25),
                    ("Associate", 0.30),
                    ("Vice President", 0.20),
                    ("Director", 0.15),
                    ("Managing Director", 0.10),
                ],
                "grades": ["Analyst", "Associate", "VP", "Director", "MD"],
                "business_unit": "Investment Banking Division",
            },
            "Risk & Compliance": {
                "weight": 0.167,
                "salary_range": (55000, 170000),
                "designations": [
                    ("Compliance Analyst", 0.25),
                    ("Risk Officer", 0.25),
                    ("Compliance Manager", 0.20),
                    ("Senior Risk Manager", 0.15),
                    ("Head of Compliance", 0.10),
                    ("Chief Risk Officer", 0.05),
                ],
                "grades": ["Associate", "VP", "Director", "MD"],
                "business_unit": "Risk & Compliance",
            },
            "Technology": {
                "weight": 0.20,
                "salary_range": (60000, 180000),
                "designations": [
                    ("Software Developer", 0.25),
                    ("Senior Developer", 0.25),
                    ("Tech Lead", 0.18),
                    ("Solutions Architect", 0.15),
                    ("Engineering Manager", 0.10),
                    ("Head of Technology", 0.07),
                ],
                "grades": ["Associate", "VP", "Director", "MD"],
                "business_unit": "Technology & Digital",
            },
            "Operations": {
                "weight": 0.167,
                "salary_range": (35000, 90000),
                "designations": [
                    ("Operations Analyst", 0.30),
                    ("Senior Operations Analyst", 0.25),
                    ("Operations Manager", 0.20),
                    ("Senior Ops Manager", 0.15),
                    ("Head of Operations", 0.10),
                ],
                "grades": ["Analyst", "Associate", "VP", "Director"],
                "business_unit": "Operations",
            },
            "Wealth Management": {
                "weight": 0.10,
                "salary_range": (65000, 200000),
                "designations": [
                    ("Wealth Management Associate", 0.25),
                    ("Relationship Manager", 0.30),
                    ("Senior RM", 0.20),
                    ("Director WM", 0.15),
                    ("Managing Director WM", 0.10),
                ],
                "grades": ["Associate", "VP", "Director", "MD"],
                "business_unit": "Wealth Management",
            },
            "Human Resources": {
                "weight": 0.067,
                "salary_range": (35000, 90000),
                "designations": [
                    ("HR Assistant", 0.25),
                    ("HR Advisor", 0.30),
                    ("HR Manager", 0.20),
                    ("Senior HR Manager", 0.15),
                    ("Head of HR", 0.10),
                ],
                "grades": ["Analyst", "Associate", "VP", "Director"],
                "business_unit": "Human Resources",
            },
            "Finance & Treasury": {
                "weight": 0.083,
                "salary_range": (50000, 150000),
                "designations": [
                    ("Finance Analyst", 0.25),
                    ("Treasury Analyst", 0.20),
                    ("Finance Manager", 0.20),
                    ("Treasury Manager", 0.15),
                    ("Head of Treasury", 0.10),
                    ("CFO", 0.10),
                ],
                "grades": ["Associate", "VP", "Director", "MD"],
                "business_unit": "Finance",
            },
            "Legal": {
                "weight": 0.05,
                "salary_range": (70000, 180000),
                "designations": [
                    ("Legal Counsel", 0.30),
                    ("Senior Legal Counsel", 0.30),
                    ("Head of Legal", 0.25),
                    ("General Counsel", 0.15),
                ],
                "grades": ["VP", "Director", "MD"],
                "business_unit": "Legal & Compliance",
            },
            "Marketing": {
                "weight": 0.033,
                "salary_range": (40000, 110000),
                "designations": [
                    ("Marketing Associate", 0.30),
                    ("Marketing Manager", 0.30),
                    ("Senior Marketing Manager", 0.25),
                    ("Head of Marketing", 0.15),
                ],
                "grades": ["Analyst", "Associate", "VP", "Director"],
                "business_unit": "Marketing & Communications",
            },
        },
        "allowance_pct": (0.05, 0.15),       # moderate allowances
        "bonus_pct_range": (0.15, 0.50),      # high bonuses (finance style)
        "deductions_pct": (0.15, 0.28),       # higher deductions
        "reimbursement_chance": 0.10,
        "arrear_chance": 0.05,
        "inactive_pct": 0.06,
        "employee_types": {"Permanent": 0.82, "Temporary": 0.08, "External User": 0.10},
    },
}

# ═══════════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════

def _weighted_choice(items: List[Tuple[str, float]]) -> str:
    """Pick an item from (item, weight) list."""
    total = sum(w for _, w in items)
    r = random.uniform(0, total)
    cumulative = 0
    for item, w in items:
        cumulative += w
        if r <= cumulative:
            return item
    return items[-1][0]


def _pick_weighted_dict(d: Dict[str, float]) -> str:
    """Pick a key from a dict of {key: weight}."""
    items = list(d.items())
    return _weighted_choice(items)


def _random_date_of_birth(min_age: int = 22, max_age: int = 65) -> Tuple[str, int, str]:
    """Generate a realistic date of birth. Returns (date_str, age, age_range)."""
    today = datetime.now()
    age = int(random.gauss(36, 10))
    age = max(min_age, min(max_age, age))
    birth_year = today.year - age
    # randomise day within year
    start = datetime(birth_year, 1, 1)
    days_in_year = 365 if birth_year % 4 != 0 else 366
    dob = start + timedelta(days=random.randint(0, days_in_year - 1))

    # age range
    if age <= 20:
        a_range = "16–20"
    elif age <= 25:
        a_range = "21–25"
    elif age <= 30:
        a_range = "26–30"
    elif age <= 35:
        a_range = "31–35"
    elif age <= 40:
        a_range = "36–40"
    elif age <= 45:
        a_range = "41–45"
    elif age <= 50:
        a_range = "46–50"
    elif age <= 55:
        a_range = "51–55"
    elif age <= 60:
        a_range = "56–60"
    else:
        a_range = "60+"

    return dob.strftime("%d-%b-%Y"), age, a_range


def _date_of_joining(age: int, tenure_years: float) -> str:
    """Derive date_of_joining from current date minus tenure."""
    today = datetime.now()
    join_date = today - timedelta(days=int(tenure_years * 365.25))
    return join_date.strftime("%d-%b-%Y")


def _tenure_from_age(age: int) -> float:
    """Tenure correlates with age. Returns years of service."""
    base_working_years = max(0, age - 22)
    tenure = random.gauss(base_working_years * 0.45, base_working_years * 0.12)
    return round(max(0.5, min(base_working_years, tenure)), 1)


def _tenure_label(years: float) -> str:
    if years < 1:
        return "<1 year"
    elif years < 3:
        return "1–3 years"
    elif years < 5:
        return "3–5 years"
    elif years < 10:
        return "5–10 years"
    elif years < 15:
        return "10–15 years"
    elif years < 20:
        return "15–20 years"
    else:
        return "20+ years"


def _experience_label(years: float) -> str:
    """Total career experience (tenure + some prior)."""
    prior = random.uniform(0, max(0, years * 0.3))
    total_exp = years + prior
    if total_exp < 2:
        return "Entry Level"
    elif total_exp < 5:
        return "Junior"
    elif total_exp < 10:
        return "Mid-Level"
    elif total_exp < 15:
        return "Senior"
    elif total_exp < 20:
        return "Lead"
    elif total_exp < 25:
        return "Principal"
    else:
        return "Executive"


def _salary_noise(base: float, pct: float = 0.08) -> float:
    """Add Gaussian noise to a salary value."""
    noise = random.gauss(0, base * pct)
    return max(1000, round(base + noise, 2))


def _compute_salary_components(profile: dict, dept_name: str, basic_salary: float) -> dict:
    """Compute all salary fields for an employee given basic_salary."""
    min_allow, max_allow = profile["allowance_pct"]
    min_bonus, max_bonus = profile["bonus_pct_range"]
    min_ded, max_ded = profile["deductions_pct"]

    allowance = round(basic_salary * random.uniform(min_allow, max_allow), 2)
    statutory_bonus = round(basic_salary * random.uniform(min_bonus, max_bonus), 2)
    gross_salary = round(basic_salary + allowance + statutory_bonus, 2)

    total_deductions = round(gross_salary * random.uniform(min_ded, max_ded), 2)
    arrear_special_allowance = round(basic_salary * random.uniform(0.01, 0.04), 2) \
        if random.random() < profile["arrear_chance"] else 0.0
    arrear_statutory_bonus = round(statutory_bonus * random.uniform(0.1, 0.3), 2) \
        if random.random() < profile["arrear_chance"] else 0.0
    reimbursement_paid = round(random.uniform(100, 2000), 2) \
        if random.random() < profile["reimbursement_chance"] else 0.0

    result = compute_net_salary(
        gross_salary=gross_salary,
        total_deductions=total_deductions,
        arrear_special_allowance=arrear_special_allowance,
        arrear_statutory_bonus=arrear_statutory_bonus,
        reimbursement_paid=reimbursement_paid,
    )

    return {
        "basic_salary": basic_salary,
        "allowance": allowance,
        "statutory_bonus": statutory_bonus,
        "gross_salary": gross_salary,
        "total_deductions": total_deductions,
        "arrear_special_allowance": arrear_special_allowance,
        "arrear_statutory_bonus": arrear_statutory_bonus,
        "reimbursement_paid": reimbursement_paid,
        "tax_spend": result["tax_spend"],
        "net_salary": result["net_salary"],
    }


# ═══════════════════════════════════════════════════════════════════
#  EMPLOYEE GENERATOR
# ═══════════════════════════════════════════════════════════════════

def generate_employee(company_id: str, profile: dict, seq: int) -> dict:
    """Generate one complete employee row for a given company."""
    today = datetime.now()

    # ── Demographic basics ─────────────────────────────────────────
    gender = _weighted_choice([("Male", 0.55), ("Female", 0.44), ("Other", 0.01)])
    if gender == "Male":
        first_name = random.choice(MALE_FIRST)
    elif gender == "Female":
        first_name = random.choice(FEMALE_FIRST)
    else:
        first_name = random.choice(MALE_FIRST + FEMALE_FIRST)
    last_name = random.choice(LAST_NAMES)

    country = _pick_weighted_dict(profile["countries"])
    country_name, continent = _country_info(country)

    dob_str, age, age_range = _random_date_of_birth(22, 65)
    ethnicity = _weighted_choice([
        ("White/Caucasian", 0.38), ("South Asian", 0.18), ("East Asian", 0.14),
        ("Hispanic/Latino", 0.10), ("Black/African American", 0.08),
        ("Middle Eastern", 0.05), ("Southeast Asian", 0.04),
        ("Mixed/Other", 0.02), ("Native American", 0.01),
    ])
    marital_status = _weighted_choice([
        ("Married", 0.45), ("Single", 0.35), ("Divorced", 0.10),
        ("Civil Partnership", 0.06), ("Widowed", 0.04),
    ])

    # ── Employment ─────────────────────────────────────────────────
    tenure_years = _tenure_from_age(age)
    doj = _date_of_joining(age, tenure_years)
    tenure_label = _tenure_label(tenure_years)
    experience_label = _experience_label(tenure_years)

    is_inactive = random.random() < profile["inactive_pct"]
    employee_status = "Inactive" if is_inactive else "Active"
    employee_type = _pick_weighted_dict(profile["employee_types"])
    employee_category = employee_type  # same for simplicity

    continuous_service_date = doj
    effective_start_date = doj
    effective_end_date = None

    last_working_date = None
    date_of_termination = None
    resignation_date = None
    rehire_date = None
    leave_status = "None"
    payroll_employee_status = employee_status

    if is_inactive:
        # terminated 30-365 days ago
        days_ago = random.randint(30, 365)
        term_date = today - timedelta(days=days_ago)
        date_of_termination = term_date.strftime("%d-%b-%Y")
        last_working_date = date_of_termination
        resignation_date = date_of_termination if random.random() < 0.4 else None
        effective_end_date = date_of_termination
        leave_status = "Resigned" if resignation_date else "Terminated"
        payroll_employee_status = "Inactive"

    # ── Department & Designation ───────────────────────────────────
    dept_name = _pick_weighted_dict(
        {k: v["weight"] for k, v in profile["departments"].items()}
    )
    dept_config = profile["departments"][dept_name]

    designation = _weighted_choice(dept_config["designations"])
    grade = random.choice(dept_config["grades"])
    business_unit_name = dept_config["business_unit"]
    # business_unit_code: first 4 chars of BU name, upper, e.g. "PROD"
    business_unit_code = "".join([w[0] for w in business_unit_name.split()]).upper()[:6]

    # ── Salary ─────────────────────────────────────────────────────
    sal_min, sal_max = dept_config["salary_range"]
    # base salary from range with Gaussian centered at 60% of range
    range_mid = sal_min + (sal_max - sal_min) * 0.55
    basic_salary = _salary_noise(range_mid, 0.15)
    basic_salary = round(max(sal_min * 0.8, min(sal_max * 1.2, basic_salary)), 2)

    salary = _compute_salary_components(profile, dept_name, basic_salary)

    # ── Payroll metadata ───────────────────────────────────────────
    frequency = "Monthly"

    return {
        "company_id": company_id,
        "employee_id": f"{_company_prefix(company_id)}-{seq:06d}",
        "first_name": first_name,
        "last_name": last_name,
        "department": dept_name,
        "designation": designation,
        "grade": grade,
        "business_unit_code": business_unit_code,
        "business_unit_name": business_unit_name,
        "gender": gender,
        "date_of_birth": dob_str,
        "age": age,
        "age_range": age_range,
        "country": country,
        "country_name": country_name,
        "continent": continent,
        "ethnicity": ethnicity,
        "marital_status": marital_status,
        "employee_status": employee_status,
        "employee_type": employee_type,
        "employee_category": employee_category,
        "continuous_service_date": continuous_service_date,
        "date_of_joining": doj,
        "tenure": tenure_label,
        "experience": experience_label,
        "effective_start_date": effective_start_date,
        "effective_end_date": effective_end_date,
        "date_of_termination": date_of_termination,
        "last_working_date": last_working_date,
        "resignation_date": resignation_date,
        "rehire_date": rehire_date,
        "leave_status": leave_status,
        "frequency": frequency,
        "payroll_employee_status": payroll_employee_status,
        "payroll_start_date": effective_start_date,
        "payroll_end_date": effective_end_date,
        "pay_period": "Calendar Month",
        "basic_salary": salary["basic_salary"],
        "allowance": salary["allowance"],
        "statutory_bonus": salary["statutory_bonus"],
        "gross_salary": salary["gross_salary"],
        "total_deductions": salary["total_deductions"],
        "arrear_special_allowance": salary["arrear_special_allowance"],
        "arrear_statutory_bonus": salary["arrear_statutory_bonus"],
        "net_salary": salary["net_salary"],
        "tax_spend": salary["tax_spend"],
        "reimbursement_paid": salary["reimbursement_paid"],
    }


def _company_prefix(company_id: str) -> str:
    """Map company_id to employee ID prefix."""
    return {"acme-tech": "ACM", "globex-mfg": "GLB", "apex-fin": "APX"}.get(company_id, company_id[:3].upper())


# ═══════════════════════════════════════════════════════════════════
#  DATABASE OPERATIONS
# ═══════════════════════════════════════════════════════════════════

INSERT_COLUMNS = [
    "employee_id", "company_id", "first_name", "last_name",
    "business_unit_code", "business_unit_name", "continuous_service_date",
    "country_name", "date_of_birth", "age", "age_range", "date_of_joining",
    "experience", "tenure", "date_of_termination", "effective_start_date",
    "effective_end_date", "employee_category", "employee_status", "employee_type",
    "ethnicity", "department", "gender", "grade", "designation",
    "last_working_date", "leave_status", "country", "marital_status",
    "continent", "frequency", "payroll_employee_status", "payroll_end_date",
    "payroll_start_date", "pay_period", "rehire_date", "resignation_date",
    "basic_salary", "allowance", "statutory_bonus", "gross_salary",
    "arrear_special_allowance", "total_deductions", "arrear_statutory_bonus",
    "net_salary", "tax_spend", "reimbursement_paid",
]


def ensure_companies(db_path: Path):
    """Register all 3 companies in the companies table."""
    conn = sqlite3.connect(str(db_path))
    for cid, profile in COMPANY_PROFILES.items():
        conn.execute("""
            INSERT OR IGNORE INTO companies (id, name, fiscal_year_start, currency, tax_country, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
        """, (cid, profile["name"], profile["fiscal_year_start"], profile["currency"], profile["tax_country"]))
    conn.commit()
    conn.close()


def insert_employees(db_path: Path, company_id: str, rows: List[dict], batch_size: int = 500):
    """Batch-insert employee rows into the database."""
    conn = sqlite3.connect(str(db_path))

    placeholders = ",".join(["?"] * len(INSERT_COLUMNS))
    cols = ",".join(INSERT_COLUMNS)
    sql = f"INSERT OR IGNORE INTO employees ({cols}) VALUES ({placeholders})"

    total_inserted = 0
    total_skipped = 0
    batch = []

    existing_ids = set()
    cur = conn.execute(f"SELECT employee_id FROM employees WHERE company_id = ?", (company_id,))
    for (eid,) in cur.fetchall():
        existing_ids.add(eid)

    for row in rows:
        if row["employee_id"] in existing_ids:
            total_skipped += 1
            continue
        batch.append(tuple(row[c] for c in INSERT_COLUMNS))
        if len(batch) >= batch_size:
            conn.executemany(sql, batch)
            conn.commit()
            total_inserted += len(batch)
            print(f"    Batch inserted {len(batch)} → running total: {total_inserted}")
            batch.clear()

    if batch:
        conn.executemany(sql, batch)
        conn.commit()
        total_inserted += len(batch)
        print(f"    Final batch: {len(batch)} → running total: {total_inserted}")

    conn.close()
    return total_inserted, total_skipped


# ═══════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  MULTI-COMPANY EMPLOYEE DATA GENERATOR")
    print("=" * 70)
    print(f"\n  Database: {DB_PATH.resolve()}")
    print(f"  Existing DB exists: {DB_PATH.exists()}\n")

    if not DB_PATH.exists():
        print("  ERROR: employees.db not found. Run import_employees.py first.")
        sys.exit(1)

    # ── Register companies ──────────────────────────────────────────
    print("[1/4] Registering companies in companies table ...")
    ensure_companies(DB_PATH)
    print("  ✓ Companies registered (acme-tech, globex-mfg, apex-fin)\n")

    # ── Generate & insert per company ───────────────────────────────
    grand_total_inserted = 0
    grand_total_skipped = 0

    for company_id, profile in COMPANY_PROFILES.items():
        n = profile["total_employees"]
        print(f"[2/4] Generating {n:,} employees for [{company_id}] {profile['name']} ...")

        generated = [generate_employee(company_id, profile, i + 1) for i in range(n)]
        print(f"  Generated {len(generated):,} employee records.")

        print(f"[3/4] Inserting {company_id} into database ...")
        inserted, skipped = insert_employees(DB_PATH, company_id, generated)
        grand_total_inserted += inserted
        grand_total_skipped += skipped
        print(f"  ✓ Inserted {inserted:,}, skipped {skipped:,} (already exist)\n")

    # ── Verify ──────────────────────────────────────────────────────
    print("[4/4] Verifying ...")
    conn = sqlite3.connect(str(DB_PATH))
    print()
    print(f"  {'Company':<20} {'Employees':>10}  {'Avg Net Salary':>16}  {'Total Payroll':>18}")
    print(f"  {'─'*20} {'─'*10}  {'─'*16}  {'─'*18}")
    grand_emps = 0
    grand_payroll = 0.0

    for company_id in ["default"] + list(COMPANY_PROFILES.keys()):
        count = conn.execute("SELECT COUNT(*) FROM employees WHERE company_id = ?", (company_id,)).fetchone()[0]
        avg_net = conn.execute(
            "SELECT ROUND(AVG(net_salary), 2) FROM employees WHERE company_id = ? AND net_salary IS NOT NULL",
            (company_id,)
        ).fetchone()[0] or 0
        total_pay = conn.execute(
            "SELECT ROUND(SUM(net_salary), 2) FROM employees WHERE company_id = ? AND net_salary IS NOT NULL",
            (company_id,)
        ).fetchone()[0] or 0
        name = COMPANY_PROFILES.get(company_id, {}).get("name", "Default Company") if company_id != "default" else "Default Company"
        print(f"  {company_id:<20} {count:>10,}  ${avg_net:>15,.2f}  ${total_pay:>17,.2f}")
        if company_id != "default":
            grand_emps += count
            grand_payroll += total_pay

    print(f"  {'─'*20} {'─'*10}  {'─'*16}  {'─'*18}")
    print(f"  {'TOTAL (new companies)':<20} {grand_emps:>10,}  {'':>16}  ${grand_payroll:>17,.2f}")
    print()

    # Dept breakdown per company
    for company_id in list(COMPANY_PROFILES.keys()):
        name = COMPANY_PROFILES[company_id]["name"]
        rows = conn.execute("""
            SELECT department, COUNT(*) as cnt,
                   ROUND(AVG(net_salary), 2) as avg_sal,
                   ROUND(SUM(net_salary), 2) as total_pay
            FROM employees WHERE company_id = ?
            GROUP BY department ORDER BY cnt DESC
        """, (company_id,)).fetchall()
        print(f"  {name} — Dept Breakdown:")
        for r in rows:
            print(f"    {r[0]:<25} {r[1]:>6,} emp  |  avg ${r[2]:>12,.2f}  |  total ${r[3]:>14,.2f}")
        print()

    conn.close()

    print("=" * 70)
    print(f"  ✅ DONE! Inserted {grand_total_inserted:,} new employees across 3 companies.")
    print(f"     Skipped {grand_total_skipped:,} (already existed).")
    print(f"     Total DB now has employees across 4 companies (default + 3 new).")
    print("=" * 70)


if __name__ == "__main__":
    main()