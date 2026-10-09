import pytest
from starlette.testclient import TestClient
from app.main import (
    app, db, init_indexes,
    compute_late_minutes, compute_overtime_minutes,
    compute_work_hours_and_half_day, get_attendance_date,
    count_working_days, IST, dt_to_epoch_ms, epoch_ms_to_utc_dt
)
from datetime import datetime, timezone, timedelta
import pathlib
from bson import json_util

client = TestClient(app)

def setup_module():
    init_indexes()
    here = pathlib.Path(__file__).parent / "sample_data"
    opts = json_util.JSONOptions(tz_aware=True)
    for name in ("employees", "attendance_logs"):
        docs = json_util.loads((here / f"{name}.json").read_text(), json_options=opts)
        db[name].delete_many({})
        db[name].insert_many(docs)

def test_rule_r1_overnight_shift_date():
    # Overnight shift: 22:00 - 06:00
    # Punch in 2026-07-07 01:15 IST (strictly before 06:00) -> belongs to 2026-07-06
    dt_1 = datetime(2026, 7, 7, 1, 15, 0, tzinfo=IST).astimezone(timezone.utc)
    date_1 = get_attendance_date(dt_1, "22:00", "06:00")
    assert date_1 == "2026-07-06"

    # Punch in 2026-07-06 21:55 IST (not before 06:00) -> belongs to 2026-07-06
    dt_2 = datetime(2026, 7, 6, 21, 55, 0, tzinfo=IST).astimezone(timezone.utc)
    date_2 = get_attendance_date(dt_2, "22:00", "06:00")
    assert date_2 == "2026-07-06"

    # Normal shift: 09:30 - 18:30 on 2026-07-07 09:20 IST -> 2026-07-07
    dt_3 = datetime(2026, 7, 7, 9, 20, 0, tzinfo=IST).astimezone(timezone.utc)
    date_3 = get_attendance_date(dt_3, "09:30", "18:30")
    assert date_3 == "2026-07-07"

def test_rule_r2_late_minutes_examples():
    # Shift 09:30:
    # 09:40:00 -> 0
    t1 = datetime(2026, 7, 6, 9, 40, 0, tzinfo=IST).astimezone(timezone.utc)
    assert compute_late_minutes(t1, "09:30", "2026-07-06") == 0

    # 09:40:01 -> 10
    t2 = datetime(2026, 7, 6, 9, 40, 1, tzinfo=IST).astimezone(timezone.utc)
    assert compute_late_minutes(t2, "09:30", "2026-07-06") == 10

    # 10:15:59 -> 45
    t3 = datetime(2026, 7, 6, 10, 15, 59, tzinfo=IST).astimezone(timezone.utc)
    assert compute_late_minutes(t3, "09:30", "2026-07-06") == 45

def test_rule_r3_overtime_threshold():
    # Normal shift 09:30 - 18:30 on 2026-07-06
    # Punch out 18:59 (29 min OT) -> 0
    t1 = datetime(2026, 7, 6, 18, 59, 0, tzinfo=IST).astimezone(timezone.utc)
    assert compute_overtime_minutes(t1, "09:30", "18:30", "2026-07-06") == 0

    # Punch out 19:00 (30 min OT) -> 30
    t2 = datetime(2026, 7, 6, 19, 0, 0, tzinfo=IST).astimezone(timezone.utc)
    assert compute_overtime_minutes(t2, "09:30", "18:30", "2026-07-06") == 30

    # Overnight shift 22:00 - 06:00 on 2026-07-06
    # Punch out 2026-07-07 06:40 (40 min OT) -> 40
    t3 = datetime(2026, 7, 7, 6, 40, 0, tzinfo=IST).astimezone(timezone.utc)
    assert compute_overtime_minutes(t3, "22:00", "06:00", "2026-07-06") == 40

def test_rule_r4_and_r5_work_hours_half_day():
    # 2.125 hours = 7650 seconds -> half up to 2 decimals = 2.13 (Banker's would do 2.12)
    t_in = datetime(2026, 7, 6, 9, 0, 0, tzinfo=timezone.utc)
    t_out = t_in + timedelta(seconds=7650)
    hours, half_day = compute_work_hours_and_half_day(t_in, t_out)
    assert hours == 2.13
    assert half_day is True # < 4.50

    # Exactly 4.50 hours = 16200 seconds -> half_day is False
    t_out_45 = t_in + timedelta(seconds=16200)
    hours_45, half_day_45 = compute_work_hours_and_half_day(t_in, t_out_45)
    assert hours_45 == 4.50
    assert half_day_45 is False

def test_rule_r7_working_days_mid_month_joiner():
    # EMP0002 joined on 2026-07-13 (Monday).
    # Month is July 2026 (31 days).
    # From 2026-07-13 to 2026-07-31:
    # Weeks: July 13-17 (5), July 20-24 (5), July 27-31 (5) = 15 working days.
    assert count_working_days("2026-07-13", "2026-07") == 15
    # Full month joiner (joined 2026-01-05): 23 working days in July 2026.
    assert count_working_days("2026-01-05", "2026-07") == 23
    # Future joiner (joined 2026-08-01): 0 working days in July 2026.
    assert count_working_days("2026-08-01", "2026-07") == 0

def test_regularize_absent_clearing_punches():
    # Regularize EMP0001 on 2026-07-06 to ABSENT
    r = client.patch("/attendance/EMP0001/2026-07-06", json={
        "status": "ABSENT",
        "reason": "Marked absent by HR correction",
        "regularized_by": "hr.lead"
    })
    assert r.status_code == 200
    doc = r.json()
    assert doc["status"] == "ABSENT"
    assert doc["punch_in"] is None
    assert doc["punch_out"] is None
    assert doc["work_hours"] is None
    assert doc["late_minutes"] == 0
    assert doc["overtime_minutes"] == 0
    assert doc["half_day"] is False
    assert len(doc["history"]) == 1

if __name__ == "__main__":
    setup_module()
    test_rule_r1_overnight_shift_date()
    test_rule_r2_late_minutes_examples()
    test_rule_r3_overtime_threshold()
    test_rule_r4_and_r5_work_hours_half_day()
    test_rule_r7_working_days_mid_month_joiner()
    test_regularize_absent_clearing_punches()
    print("ALL EDGE CASE TESTS PASSED!")
