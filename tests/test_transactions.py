"""Multi-step writes run in one MongoDB transaction: a failure part way through leaves nothing half-saved."""

import pytest

from app import db
from app.routers import fsr, roles, work_orders
from tests.helpers import png_data_url


class Boom(Exception):
    pass


async def fail(*args, **kwargs):
    raise Boom


@pytest.fixture
async def plan(client, tech, engineer):
    response = await client.post(
        "/work-plans",
        headers=tech.headers,
        json={"title": "P", "customer": {"company": "C"}, "assigned_engineer_ids": [engineer.engineer_id]},
    )
    return response.json()


async def convert(client, tech, plan):
    return await client.post(
        f"/work-plans/{plan['id']}/convert", headers=tech.headers, json={"service_type": "inspection"}
    )


async def test_failed_conversion_leaves_the_plan_unconverted(client, tech, plan, monkeypatch):
    monkeypatch.setattr(work_orders, "record", fail)  # fails after the plan is locked and the order inserted
    with pytest.raises(Boom):
        await convert(client, tech, plan)
    assert await db.get_db().work_orders.count_documents({}) == 0
    assert (await client.get(f"/work-plans/{plan['id']}", headers=tech.headers)).json()["work_order"] is None

    monkeypatch.undo()
    assert (await convert(client, tech, plan)).status_code == 201


async def test_failed_work_order_delete_keeps_the_order_and_plan_lock(client, tech, plan, monkeypatch):
    order = (await convert(client, tech, plan)).json()
    monkeypatch.setattr(work_orders, "record", fail)
    with pytest.raises(Boom):
        await client.delete(f"/work-orders/{order['id']}", headers=tech.headers)
    assert (await client.get(f"/work-orders/{order['id']}", headers=tech.headers)).status_code == 200
    locked = (await client.get(f"/work-plans/{plan['id']}", headers=tech.headers)).json()
    assert locked["work_order"]["work_order_number"] == order["work_order_number"]


async def test_failed_fsr_submit_keeps_the_order_open_and_drops_the_file(client, tech, engineer, plan, monkeypatch):
    order = (await convert(client, tech, plan)).json()
    body = {
        "work_order": order["id"],
        "root_cause": "x",
        "corrective_action": "y",
        "customer_rep_name": "z",
        "client_signature": png_data_url(),
    }
    monkeypatch.setattr(fsr, "record", fail)
    with pytest.raises(Boom):
        await client.post("/fsr", headers=engineer.headers, json=body)
    after = (await client.get(f"/work-orders/{order['id']}", headers=tech.headers)).json()
    assert after["status"] == order["status"] and after["field_service_report"] is None
    assert await db.get_db().field_service_reports.count_documents({}) == 0
    assert await db.get_db()["fs.files"].count_documents({}) == 0  # the uploaded signature was deleted

    monkeypatch.undo()
    assert (await client.post("/fsr", headers=engineer.headers, json=body)).status_code == 201


async def test_failed_role_delete_keeps_the_role_on_inactive_users(client, admin, make_user, monkeypatch):
    await client.post("/roles", headers=admin.headers, json={"code": "sonar", "name": "Sonar"})
    user = await make_user("sonar")
    await client.patch(f"/users/{user.user_id}", headers=admin.headers, json={"is_active": False})
    monkeypatch.setattr(roles, "record", fail)
    with pytest.raises(Boom):
        await client.delete("/roles/sonar", headers=admin.headers)
    assert (await client.get("/roles/sonar", headers=admin.headers)).status_code == 200
    assert await db.get_db().users.count_documents({"username": user.username, "roles": "sonar"}) == 1
