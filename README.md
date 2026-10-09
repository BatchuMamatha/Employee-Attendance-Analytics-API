# Employee Attendance & Analytics API

FastAPI and MongoDB backend for employee attendance tracking, regularization audit trail, and analytics aggregation pipelines.

## Requirements
- Python 3.11+
- MongoDB 6.0+ (Tested against MongoDB 7.0)

## Quick Start
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment (optional, defaults to localhost:27017 and attendance_db)
export MONGO_URI="mongodb://localhost:27017"
export MONGO_DB="attendance_db"

# 3. Seed sample data (optional)
python sample_seed.py

# 4. Start the application
uvicorn app.main:app --port 8000
```

The application creates all required indexes idempotently on startup.
Readiness check is available at `GET /health` (returns 200 when MongoDB is connected, otherwise 503).

## Key Implementation Highlights
- **Single-File Structure**: All models, business logic (R1–R10), routes, and aggregation pipelines are self-contained in `app/main.py`.
- **Concurrency & Races**: Race conditions on punch-in (`409 Conflict`) are enforced via a unique compound index on `(emp_code, date)`. Punch-out is guarded by atomic `find_one_and_update` on open records. Regularizations employ optimistic concurrency locking on the audit history.
- **Pure MongoDB Aggregations**: All analytics endpoints (`employee_monthly`, `department_summary`, `late_leaderboard`, `department_trend`) are fully executed in MongoDB without Python in-memory loops.
- **Index-Backed Performance**: Verified index scan (`IXSCAN`) with zero collection scans (`COLLSCAN`) across all explained endpoints.
- **Audit History**: Full immutable audit trail on `PATCH /attendance/{emp_code}/{date}` capturing field-level transitions.

## Verification & Tests
Run automated tests with:
```bash
python test_suite.py
python test_edge_cases.py
```
