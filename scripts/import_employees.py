"""Import Payroll Data.xlsx into SQLite with full 47-column schema."""
import sqlite3
from pathlib import Path
import sys

DB_PATH = Path("employees.db")
XLSX_PATH = Path("Payroll Data.xlsx")


def init_db(db_path=DB_PATH):
    conn = sqlite3.connect(str(db_path))
    conn.execute("DROP TABLE IF EXISTS employees")
    conn.execute("""
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_count INTEGER,
            employee_id TEXT UNIQUE,
            first_name TEXT,
            last_name TEXT,
            business_unit_code TEXT,
            business_unit_name TEXT,
            continuous_service_date TEXT,
            country_name TEXT,
            date_of_birth TEXT,
            age INTEGER,
            age_range TEXT,
            date_of_joining TEXT,
            experience TEXT,
            tenure TEXT,
            date_of_termination TEXT,
            effective_start_date TEXT,
            effective_end_date TEXT,
            employee_category TEXT,
            employee_status TEXT,
            employee_type TEXT,
            ethnicity TEXT,
            department TEXT,
            gender TEXT,
            grade TEXT,
            designation TEXT,
            last_working_date TEXT,
            leave_status TEXT,
            country TEXT,
            marital_status TEXT,
            continent TEXT,
            frequency TEXT,
            payroll_employee_status TEXT,
            payroll_end_date TEXT,
            payroll_start_date TEXT,
            pay_period TEXT,
            rehire_date TEXT,
            resignation_date TEXT,
            basic_salary REAL,
            allowance REAL,
            statutory_bonus REAL,
            gross_salary REAL,
            arrear_special_allowance REAL,
            total_deductions REAL,
            arrear_statutory_bonus REAL,
            net_salary REAL,
            tax_spend REAL,
            reimbursement_paid REAL
        )
    """)
    # Performance indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dept ON employees(department)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON employees(employee_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_gender ON employees(gender)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_country ON employees(country)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_designation ON employees(designation)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_grade ON employees(grade)")
    conn.commit()
    return conn


def safe_float(val):
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def safe_int(val):
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def safe_str(val):
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def import_xlsx(xlsx_path=XLSX_PATH, db_path=DB_PATH):
    import subprocess as _sp, sys as _sys
    try:
        import openpyxl
    except ImportError:
        _sp.check_call([_sys.executable, "-m", "pip", "install", "openpyxl", "-q"])
        import openpyxl

    print(f"Loading {xlsx_path} ...")
    wb = openpyxl.load_workbook(str(xlsx_path), read_only=True)
    ws = wb.active

    conn = init_db(db_path)
    total = 0
    valid = 0
    batch = []
    batch_size = 500

    # Column mapping: XLSX col index (0-based) -> DB column name
    col_map = {
        0: "emp_count", 1: "employee_id", 2: "first_name", 3: "last_name",
        4: "business_unit_code", 5: "business_unit_name", 6: "continuous_service_date",
        7: "country_name", 8: "date_of_birth", 9: "age", 10: "age_range",
        11: "date_of_joining", 12: "experience", 13: "tenure", 14: "date_of_termination",
        15: "effective_start_date", 16: "effective_end_date", 17: "employee_category",
        18: "employee_status", 19: "employee_type", 20: "ethnicity", 21: "department",
        22: "gender", 23: "grade", 24: "designation", 25: "last_working_date",
        26: "leave_status", 27: "country", 28: "marital_status", 29: "continent",
        30: "frequency", 31: "payroll_employee_status", 32: "payroll_end_date",
        33: "payroll_start_date", 34: "pay_period", 35: "rehire_date",
        36: "resignation_date", 37: "basic_salary", 38: "allowance",
        39: "statutory_bonus", 40: "gross_salary", 41: "arrear_special_allowance",
        42: "total_deductions", 43: "arrear_statutory_bonus", 44: "net_salary",
        45: "tax_spend", 46: "reimbursement_paid",
    }

    num_cols = 47
    insert_sql = f"""INSERT OR REPLACE INTO employees (
        emp_count, employee_id, first_name, last_name, business_unit_code, business_unit_name,
        continuous_service_date, country_name, date_of_birth, age, age_range, date_of_joining,
        experience, tenure, date_of_termination, effective_start_date, effective_end_date,
        employee_category, employee_status, employee_type, ethnicity, department, gender,
        grade, designation, last_working_date, leave_status, country, marital_status,
        continent, frequency, payroll_employee_status, payroll_end_date, payroll_start_date,
        pay_period, rehire_date, resignation_date, basic_salary, allowance, statutory_bonus,
        gross_salary, arrear_special_allowance, total_deductions, arrear_statutory_bonus,
        net_salary, tax_spend, reimbursement_paid
    ) VALUES ({','.join(['?']*num_cols)})"""

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        total += 1
        emp_id = row[1]
        if emp_id is None:
            continue
        try:
            emp_id = str(int(emp_id))
        except (ValueError, TypeError):
            continue
        if not emp_id.strip():
            continue

        valid += 1
        values = tuple(
            safe_str(row[i]) if i in (0, 6, 8, 11, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 2, 3, 4, 5, 10, 12, 13)
            else safe_float(row[i]) if i in (37, 38, 39, 40, 41, 42, 43, 44, 45, 46)
            else safe_int(row[i]) if i == 9
            else safe_str(row[i])
            for i in range(num_cols)
        )
        batch.append(values)

        if len(batch) >= batch_size:
            conn.executemany(insert_sql, batch)
            conn.commit()
            batch.clear()
            if valid % 500 == 0:
                print(f"  Imported {valid} employees ...")

    if batch:
        conn.executemany(insert_sql, batch)
        conn.commit()

    conn.close()
    print(f"\nDone! Total rows in XLSX: {total}, Valid employees imported: {valid}")
    return valid


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else str(XLSX_PATH)
    if not Path(path).exists():
        print(f"ERROR: File not found: {path}")
        sys.exit(1)
    import_xlsx(Path(path))
