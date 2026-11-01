import json

import pytest

from app import db
from app.config import settings


async def entries(client, headers, **params):
    return (await client.get("/audit-log", headers=headers, params=params)).json()


async def test_user_changes_are_recorded_without_secrets(client, admin, hr):
    await client.patch(
        f"/users/{hr.user_id}",
        headers=admin.headers,
        json={"roles": ["technical_team"], "full_name": "Sam", "password": "ResetPass123"},
    )
    [entry] = await entries(client, admin.headers, entity_type="user", action="update")
    assert entry["actor"]["username"] == admin.username
    assert entry["entity"] == {"type": "user", "id": hr.user_id, "number": hr.username}
    assert entry["changes"]["roles"] == [["hr_team"], ["technical_team"]]
    assert entry["changes"]["full_name"] == [None, "Sam"]
    assert entry["details"] == {"password_reset": True}
    everything = json.dumps([d async for d in db.get_db().audit_log.find({}, {"_id": 0, "at": 0, "actor.user_id": 0})])
    assert "hashed_password" not in everything and "ResetPass123" not in everything


async def test_job_lifecycle_is_recorded(client, admin, tech, engineer, owner, hr):
    plan = (
        await client.post(
            "/work-plans",
            headers=tech.headers,
            json={"title": "P", "customer": {"company": "C"}, "assigned_engineer_ids": [engineer.engineer_id]},
        )
    ).json()
    order = (
        await client.post(
            f"/work-plans/{plan['id']}/convert", headers=tech.headers, json={"service_type": "inspection"}
        )
    ).json()
    await client.post(f"/work-orders/{order['id']}/start", headers=engineer.headers)
    fsr = (
        await client.post(
            "/fsr",
            headers=engineer.headers,
            json={"work_order": order["id"], "root_cause": "x", "corrective_action": "y", "customer_rep_name": "z"},
        )
    ).json()
    claim = (
        await client.post(
            "/expense-claims", headers=engineer.headers, json={"category": "other", "amount": 5, "description": "x"}
        )
    ).json()
    await client.post(f"/expense-claims/{claim['id']}/approve", headers=tech.headers)

    log = await entries(client, admin.headers, limit=50)
    actions = [(e["action"], e["entity"]["type"], e["entity"]["number"]) for e in reversed(log)]
    assert actions == [
        ("create", "work_plan", plan["plan_number"]),
        ("convert", "work_order", order["work_order_number"]),
        ("start", "work_order", order["work_order_number"]),
        ("submit", "fsr", fsr["fsr_number"]),
        ("create", "expense_claim", claim["claim_number"]),
        ("approved", "expense_claim", claim["claim_number"]),
    ]
    approved = log[0]
    assert approved["changes"] == {"status": ["pending", "technical_approved"]}
    by_number = await entries(client, owner.headers, entity=order["work_order_number"].lower())
    assert [e["action"] for e in by_number] == ["start", "convert"]


@pytest.fixture
async def users(admin, owner, hr, tech, engineer):
    return {"admin": admin, "owner": owner, "hr": hr, "tech": tech, "engineer": engineer}


@pytest.mark.parametrize(
    ("who", "status"), [("admin", 200), ("owner", 200), ("hr", 403), ("tech", 403), ("engineer", 403)]
)
async def test_only_admin_and_owner_read_the_audit_log(client, users, who, status):
    assert (await client.get("/audit-log", headers=users[who].headers)).status_code == status


async def test_request_ids_link_responses_to_audit_entries(client, admin):
    response = await client.post(
        "/roles", headers=admin.headers | {"X-Request-ID": "req-abc-123"}, json={"code": "sonar", "name": "Sonar"}
    )
    assert response.headers["X-Request-ID"] == "req-abc-123"
    [entry] = await entries(client, admin.headers, entity_type="role")
    assert entry["request_id"] == "req-abc-123"
    assert len((await client.get("/health")).headers["X-Request-ID"]) == 32  # generated when not sent


async def test_audit_entries_expire_after_the_retention_period():
    indexes = {i["name"]: i async for i in await db.get_db().audit_log.list_indexes()}
    assert indexes["at_1"]["expireAfterSeconds"] == settings.audit_retention_days * 86400
