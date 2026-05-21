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
docker run -p 8000:8000 salary-gateway
```
