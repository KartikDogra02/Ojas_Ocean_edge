from datetime import date, timedelta

import pytest

import app.routers.planner as planner

TODAY = date(2026, 11, 2)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(planner, "_today", lambda: TODAY)


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


async def test_daily_window_and_bulk_validation(client, hr, engineer):
    view = (await client.get("/planner/daily", headers=hr.headers)).json()
    assert view["start"] == day(0) and view["end"] == day(13) and len(view["dates"]) == 14
    bad = {
        "entries": [
            {"engineer_id": engineer.engineer_id, "date": day(1), "status": "workshop"},
            {"engineer_id": engineer.engineer_id, "date": day(-1), "status": "ship"},
            {"engineer_id": engineer.engineer_id, "date": day(14), "status": "ship"},
        ]
    }
    response = await client.put("/planner/daily", headers=hr.headers, json=bad)
    assert response.status_code == 422
    view = (await client.get("/planner/daily", headers=hr.headers)).json()
    assert view["engineers"][0]["days"][day(1)]["status"] is None


async def test_entries_totals_and_expiry(client, tech, engineer):
    saved = await client.put(
        "/planner/daily",
        headers=tech.headers,
        json={"entries": [{"engineer_id": engineer.engineer_id, "date": day(0), "status": "ship", "note": "Rig"}]},
    )
    assert saved.json() == {"saved": 1, "cleared": 0}
    view = (await client.get("/planner/daily", headers=tech.headers)).json()
    assert view["totals"][day(0)]["ship"] == 1
    from app import db

    entry = await db.get_db().planner_days.find_one({"engineer_id": engineer.engineer_id})
    assert entry["expire_at"].date() == TODAY + timedelta(days=1)


async def test_work_order_must_include_engineer(client, tech, engineer, engineer2):
    order = (
        await client.post(
            "/work-orders",
            headers=tech.headers,
            json={
                "title": "W",
                "service_type": "inspection",
                "assigned_engineer_ids": [engineer.engineer_id],
                "customer": {"company": "C"},
            },
        )
    ).json()
    ok = {
        "engineer_id": engineer.engineer_id,
        "date": day(0),
        "status": "ship",
        "work_order": order["work_order_number"],
    }
    assert (await client.put("/planner/daily", headers=tech.headers, json={"entries": [ok]})).status_code == 200
    wrong = ok | {"engineer_id": engineer2.engineer_id}
    assert (await client.put("/planner/daily", headers=tech.headers, json={"entries": [wrong]})).status_code == 422
    weekly = (await client.get("/planner/weekly", headers=tech.headers, params={"start": day(0)})).json()
    first = next(e for e in weekly["engineers"] if e["engineer_id"] == engineer.engineer_id)
    assert [w["work_order_number"] for w in first["work_orders"]] == [order["work_order_number"]]


async def test_month_off_makes_days_unavailable(client, hr, engineer):
    await client.put(
        "/planner/monthly",
        headers=hr.headers,
        json={"entries": [{"engineer_id": engineer.engineer_id, "year": 2026, "month": 11, "status": "off"}]},
    )
    availability = (await client.get("/planner/availability", headers=hr.headers)).json()
    free = next(a for a in availability if a["engineer_id"] == engineer.engineer_id)["available_dates"]
    assert free == [d for d in (day(i) for i in range(14)) if d >= "2026-12-01"]
    past = {"entries": [{"engineer_id": engineer.engineer_id, "year": 2025, "month": 1, "status": "off"}]}
    assert (await client.put("/planner/monthly", headers=hr.headers, json=past)).status_code == 422


async def test_engineer_sees_only_own_row_and_cannot_edit(client, engineer, engineer2):
    rows = (await client.get("/planner/daily", headers=engineer.headers)).json()["engineers"]
    assert [r["engineer_id"] for r in rows] == [engineer.engineer_id]
    edit = {"entries": [{"engineer_id": engineer.engineer_id, "date": day(0), "status": "leave"}]}
    assert (await client.put("/planner/daily", headers=engineer.headers, json=edit)).status_code == 403
