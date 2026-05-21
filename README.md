# Salary-Payment-Gateway

Minimal starter for a salary/payment calculation gateway.

Run locally:

1. Create a virtualenv and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn app:app --reload
```

2. Example request:

POST /calculate with JSON body:

```json
{
	"employee_id": "E123",
	"weekly_values": [1000,1100,1200,1300],
	"adjustments": {"bonus": 50},
	"deductions": {"tax": 100}
}
```

Docker:

```bash
docker build -t salary-gateway .
docker run --rm -p 8000:8000 -v "${PWD}:/app" -w /app salary-gateway
```

Docker workflow (Docker-only):

```bash
docker build -t salary-gateway .
# Generate 200 employee records in employees.csv
docker run --rm -v "${PWD}:/app" -w /app python:3.11-slim python scripts/generate_employees.py
# Import into SQLite database employees.db
docker run --rm -v "${PWD}:/app" -w /app python:3.11-slim python scripts/import_employees.py employees.csv
# Start the FastAPI app in Docker
docker run --rm -p 8000:8000 -v "${PWD}:/app" -w /app salary-gateway
```

Open `http://localhost:8000/` in your browser to use the interactive Payroll Admin Dashboard.

If you want the raw API docs, open `http://localhost:8000/docs`.

Docker Compose:

```bash
docker compose up --build
```
