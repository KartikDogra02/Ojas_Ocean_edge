import pytest


@pytest.fixture
async def plan(client, tech, engineer):
    response = await client.post(
        "/work-plans",
        headers=tech.headers,
        json={
            "title": "PLC Diagnostics",
            "priority": "high",
            "estimated_duration_days": 2.5,
            "customer": {"company": "Apex", "site_address": "742 Evergreen"},
            "assigned_engineer_ids": [engineer.engineer_id],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_plan_numbering_and_fields(plan):
    assert plan["plan_number"].startswith("WP-")
    assert plan["status"] == "assigned"
    assert plan["estimated_duration_days"] == 2.5


async def test_draft_without_engineers(client, tech):
    plan = (await client.post("/work-plans", headers=tech.headers, json={"title": "D", "customer": {"company": "C"}})).json()
    assert plan["status"] == "draft"


async def test_duration_bounds(client, tech):
    for bad in (0, -1, 400):
        body = {"title": "D", "customer": {"company": "C"}, "estimated_duration_days": bad}
        assert (await client.post("/work-plans", headers=tech.headers, json=body)).status_code == 422


async def test_unknown_engineer_rejected(client, tech):
    body = {"title": "D", "customer": {"company": "C"}, "assigned_engineer_ids": ["ENG-2026-999"]}
    assert (await client.post("/work-plans", headers=tech.headers, json=body)).status_code == 422


async def test_convert_copies_plan_and_locks_it(client, tech, plan, engineer):
    converted = await client.post(
        f"/work-plans/{plan['plan_number']}/convert",
        headers=tech.headers,
        json={"service_type": "calibration", "equipment": {"name": "Transmitter", "serial_number": "SN-1"}},
    )
    assert converted.status_code == 201, converted.text
    order = converted.json()
    assert order["work_order_number"].startswith("WO-")
    assert order["title"] == plan["title"] and order["priority"] == "high"
    assert order["estimated_duration_days"] == 2.5
    assert order["lead_engineer"]["engineer_id"] == engineer.engineer_id
    assert order["work_plan"]["plan_number"] == plan["plan_number"]

    locked = (await client.get(f"/work-plans/{plan['plan_number']}", headers=tech.headers)).json()
    assert locked["status"] == "converted" and locked["work_order"]["work_order_number"] == order["work_order_number"]
    assert (await client.patch(f"/work-plans/{plan['id']}", headers=tech.headers, json={"title": "X"})).status_code == 409
    assert (await client.delete(f"/work-plans/{plan['id']}", headers=tech.headers)).status_code == 409
    again = await client.post(f"/work-plans/{plan['id']}/convert", headers=tech.headers, json={"service_type": "inspection"})
    assert again.status_code == 409


async def test_only_technical_team_converts(client, admin, plan):
    response = await client.post(f"/work-plans/{plan['id']}/convert", headers=admin.headers, json={"service_type": "inspection"})
    assert response.status_code == 403


async def test_deleting_converted_order_unlocks_plan(client, tech, plan):
    order = (await client.post(f"/work-plans/{plan['id']}/convert", headers=tech.headers, json={"service_type": "inspection"})).json()
    assert (await client.delete(f"/work-orders/{order['id']}", headers=tech.headers)).status_code == 204
    assert (await client.get(f"/work-plans/{plan['id']}", headers=tech.headers)).json()["status"] == "assigned"


async def test_lead_engineer_rules(client, tech, engineer, engineer2):
    body = {
        "title": "W",
        "service_type": "breakdown_repair",
        "assigned_engineer_ids": [engineer.engineer_id, engineer2.engineer_id],
        "customer": {"company": "C"},
    }
    order = (await client.post("/work-orders", headers=tech.headers, json=body)).json()
    assert order["lead_engineer"]["engineer_id"] == engineer.engineer_id
    bad_lead = await client.post("/work-orders", headers=tech.headers, json=body | {"lead_engineer_id": "ENG-2026-999"})
    assert bad_lead.status_code == 422
    # Dropping the lead from the crew hands the lead to the first remaining engineer.
    updated = await client.patch(
        f"/work-orders/{order['id']}", headers=tech.headers, json={"assigned_engineer_ids": [engineer2.engineer_id]}
    )
    assert updated.json()["lead_engineer"]["engineer_id"] == engineer2.engineer_id
    empty = await client.patch(f"/work-orders/{order['id']}", headers=tech.headers, json={"assigned_engineer_ids": []})
    assert empty.status_code == 422


async def test_start_work_order(client, tech, engineer, engineer2, plan):
    order = (await client.post(f"/work-plans/{plan['id']}/convert", headers=tech.headers, json={"service_type": "inspection"})).json()
    path = f"/work-orders/{order['id']}/start"
    assert (await client.post(path, headers=engineer2.headers)).status_code == 403
    started = await client.post(path, headers=engineer.headers)
    assert started.json()["status"] == "in_progress"
    assert (await client.post(path, headers=engineer.headers)).status_code == 409


async def test_engineers_see_only_their_orders(client, tech, engineer, engineer2):
    body = {"title": "W", "service_type": "inspection", "customer": {"company": "C"}}
    await client.post("/work-orders", headers=tech.headers, json=body | {"assigned_engineer_ids": [engineer.engineer_id]})
    other = await client.post("/work-orders", headers=tech.headers, json=body | {"assigned_engineer_ids": [engineer2.engineer_id]})
    assert len((await client.get("/work-orders", headers=engineer.headers)).json()) == 1
    assert (await client.get(f"/work-orders/{other.json()['id']}", headers=engineer.headers)).status_code == 404
