import pathlib
from bson import json_util
from starlette.testclient import TestClient
from app.main import app, db, init_indexes

client = TestClient(app)

def seed_database():
    here = pathlib.Path(__file__).parent / "sample_data"
    opts = json_util.JSONOptions(tz_aware=True)
    for name in ("employees", "attendance_logs"):
        docs = json_util.loads((here / f"{name}.json").read_text(), json_options=opts)
        db[name].delete_many({})
        db[name].insert_many(docs)

def run_all_tests():
    print("Initializing indexes and seeding DB...")
    init_indexes()
    seed_database()

    print("Testing GET /health...")
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    print("PASSED")

    print("Testing /employees...")
    # Validation failures
    r_bad = client.post("/employees", json={
        "emp_code": "INVALID",
        "name": "Test",
        "email": "test@example.com",
        "department": "Engineering",
        "shift_start": "09:30",
        "shift_end": "09:30", # equal shifts
        "joined_on": "2026-01-01"
    })
    assert r_bad.status_code == 422

    # Success create
    r_good = client.post("/employees", json={
        "emp_code": "EMP0099",
        "name": "Test User",
        "email": "test@example.com",
        "department": "QA",
        "shift_start": "10:00",
        "shift_end": "19:00",
        "joined_on": "2026-07-01"
    })
    assert r_good.status_code == 201
    data = r_good.json()
    assert data["emp_code"] == "EMP0099"
    assert isinstance(data["created_at"], int)
    assert "_id" not in data

    # Duplicate create -> 409
    r_dup = client.post("/employees", json={
        "emp_code": "EMP0099",
        "name": "Test User",
        "email": "test@example.com",
        "department": "QA",
        "shift_start": "10:00",
        "shift_end": "19:00",
        "joined_on": "2026-07-01"
    })
    assert r_dup.status_code == 409

    # List employees
    r_list = client.get("/employees?department=QA&page=1&page_size=20")
    assert r_list.status_code == 200
    res = r_list.json()
    assert res["total"] == 1
    assert len(res["items"]) == 1
    assert res["items"][0]["emp_code"] == "EMP0099"
    print("PASSED")

    print("Testing /attendance/punch-in and punch-out...")
    ts_in = 1783658100000 # 2026-07-10 04:35:00 UTC (10:05 IST)
    r_in = client.post("/attendance/punch-in", json={
        "emp_code": "EMP0099",
        "punched_at": ts_in,
        "status": "PRESENT"
    })
    assert r_in.status_code == 201
    rec = r_in.json()
    assert rec["emp_code"] == "EMP0099"
    assert rec["date"] == "2026-07-10"
    assert rec["late_minutes"] == 0
    assert rec["punch_out"] is None

    # Duplicate punch in for same day -> 409
    r_in_dup = client.post("/attendance/punch-in", json={
        "emp_code": "EMP0099",
        "punched_at": ts_in,
        "status": "PRESENT"
    })
    assert r_in_dup.status_code == 409

    # Punch out 9 hours 35 min later
    ts_out = ts_in + 9 * 3600 * 1000 + 35 * 60 * 1000
    r_out = client.post("/attendance/punch-out", json={
        "emp_code": "EMP0099",
        "punched_at": ts_out
    })
    assert r_out.status_code == 200
    out_rec = r_out.json()
    assert out_rec["work_hours"] == 9.58
    assert out_rec["overtime_minutes"] == 40
    assert out_rec["half_day"] is False

    # Second punch out -> 409
    r_out_dup = client.post("/attendance/punch-out", json={
        "emp_code": "EMP0099",
        "punched_at": ts_out
    })
    assert r_out_dup.status_code == 409
    print("PASSED")

    print("Testing /attendance regularization...")
    r_patch = client.patch("/attendance/EMP0099/2026-07-10", json={
        "status": "WFH",
        "reason": "WFH approved by manager",
        "regularized_by": "manager.qa"
    })
    assert r_patch.status_code == 200
    patched = r_patch.json()
    assert patched["status"] == "WFH"
    assert len(patched["history"]) == 1
    assert patched["history"][0]["by"] == "manager.qa"
    assert patched["history"][0]["reason"] == "WFH approved by manager"
    assert "status" in patched["history"][0]["changes"]
    assert patched["history"][0]["changes"]["status"] == {"from": "PRESENT", "to": "WFH"}

    # No changes -> 422
    r_no_change = client.patch("/attendance/EMP0099/2026-07-10", json={
        "status": "WFH",
        "reason": "Redundant update",
        "regularized_by": "manager.qa"
    })
    assert r_no_change.status_code == 422
    print("PASSED")

    print("Testing GET /attendance list...")
    resp = client.get("/attendance?date_from=2026-07-06&date_to=2026-07-10")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data

    resp_bad = client.get("/attendance?date_from=2026-07-10&date_to=2026-07-06")
    assert resp_bad.status_code == 422
    print("PASSED")

    print("Testing /analytics/employees/{emp_code}/monthly...")
    resp = client.get("/analytics/employees/EMP0001/monthly?month=2026-07")
    assert resp.status_code == 200
    data = resp.json()
    assert data["emp_code"] == "EMP0001"
    assert data["month"] == "2026-07"
    assert data["working_days"] == 23
    assert data["present_days"] == 2.0
    assert data["attendance_pct"] is not None
    print("PASSED")

    print("Testing /analytics/departments/summary...")
    resp = client.get("/analytics/departments/summary?month=2026-07")
    assert resp.status_code == 200
    data = resp.json()
    assert data["month"] == "2026-07"
    assert len(data["items"]) >= 3
    eng = next((d for d in data["items"] if d["department"] == "Engineering"), None)
    assert eng is not None
    assert eng["headcount"] == 2
    print("PASSED")

    print("Testing /analytics/leaderboard/late...")
    resp = client.get("/analytics/leaderboard/late?month=2026-07&limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert len(data["items"]) >= 1
    assert data["items"][0]["rank"] == 1
    print("PASSED")

    print("Testing /analytics/departments/{department}/trend...")
    resp = client.get("/analytics/departments/Engineering/trend?from=2026-07-06&to=2026-07-15")
    assert resp.status_code == 200
    data = resp.json()
    assert data["department"] == "Engineering"
    assert len(data["items"]) == 10
    assert data["items"][0]["date"] == "2026-07-06"
    assert data["items"][-1]["date"] == "2026-07-15"
    print("PASSED")

    print("Testing /admin/explain/{endpoint}...")
    endpoints = [
        "/admin/explain/attendance_list?date_from=2026-07-01&date_to=2026-07-31",
        "/admin/explain/employee_monthly?emp_code=EMP0001&month=2026-07",
        "/admin/explain/department_summary?month=2026-07",
        "/admin/explain/late_leaderboard?month=2026-07",
        "/admin/explain/department_trend?department=Engineering&from=2026-07-01&to=2026-07-15",
    ]
    for url in endpoints:
        r = client.get(url)
        assert r.status_code == 200, f"Failed for {url}: {r.text}"
        data = r.json()
        assert "endpoint" in data
        assert "collection" in data
        assert "explain" in data
    print("PASSED")

    print("\nALL AUTOMATED TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_all_tests()
