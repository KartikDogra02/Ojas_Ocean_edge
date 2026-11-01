"""Who can read and change what. One row per (endpoint, role) pair that matters."""

import pytest

from app.models.role import Role

ROLES = ["admin", "hr", "tech", "owner", "engineer"]
VIEW_ALL = {"admin", "hr", "tech", "owner"}


@pytest.fixture
async def users(admin, hr, tech, owner, engineer):
    return {"admin": admin, "hr": hr, "tech": tech, "owner": owner, "engineer": engineer}


READ_ENDPOINTS = [
    "/work-plans",
    "/work-orders",
    "/fsr",
    "/workflow",
    "/planner/daily",
    "/planner/monthly",
    "/expense-claims",
    "/check-ins",
    "/certificates",
    "/reference-standards",
    "/options",
    "/permissions",
]


@pytest.mark.parametrize("path", READ_ENDPOINTS)
@pytest.mark.parametrize("role", ROLES)
async def test_everyone_can_read(client, users, role, path):
    """Reads are allowed for every role; service engineers get only their own rows."""
    assert (await client.get(path, headers=users[role].headers)).status_code == 200


@pytest.mark.parametrize("role", ROLES)
async def test_admin_and_hr_only_endpoints(client, users, role):
    expected_users = 200 if role == "admin" else 403
    assert (await client.get("/users", headers=users[role].headers)).status_code == expected_users
    expected_roles = 200 if role in {"admin", "hr"} else 403
    assert (await client.get("/roles", headers=users[role].headers)).status_code == expected_roles
    expected_engineers = 200 if role in {"admin", "hr"} else 403
    assert (await client.get("/service-engineers", headers=users[role].headers)).status_code == expected_engineers


WRITE_RULES = {
    # (method, path, body) -> roles allowed (status != 403)
    ("POST", "/work-plans", '{"title":"T","customer":{"company":"C"}}'): {"admin", "tech"},
    ("POST", "/users", '{"email":"z@example.com","username":"zzz","password":"Password123"}'): {"admin"},
    ("POST", "/roles", '{"code":"sonar","name":"Sonar"}'): {"admin"},
    ("PUT", "/planner/monthly", '{"entries":[{"engineer_id":"ENG-2000-001","year":2999,"month":1,"status":"off"}]}'): {
        "hr",
        "tech",
    },
    ("PATCH", "/planner/engineers/ENG-2000-001", '{"current_country":"X"}'): {"hr", "tech"},
}


@pytest.mark.parametrize(("method", "path", "body"), list(WRITE_RULES))
@pytest.mark.parametrize("role", ROLES)
async def test_write_permissions(client, users, role, method, path, body):
    response = await client.request(
        method, path, headers=users[role].headers | {"content-type": "application/json"}, content=body
    )
    allowed = WRITE_RULES[(method, path, body)]
    if role in allowed:
        assert response.status_code != 403, response.text
    else:
        assert response.status_code == 403, response.text


async def test_owner_reads_everything_engineers_only_their_own(client, users, tech, engineer, engineer2):
    await client.post(
        "/work-plans",
        headers=tech.headers,
        json={"title": "Mine", "customer": {"company": "C"}, "assigned_engineer_ids": [engineer.engineer_id]},
    )
    await client.post(
        "/work-plans",
        headers=tech.headers,
        json={"title": "Theirs", "customer": {"company": "C"}, "assigned_engineer_ids": [engineer2.engineer_id]},
    )
    owner_view = (await client.get("/work-plans", headers=users["owner"].headers)).json()
    engineer_view = (await client.get("/work-plans", headers=engineer.headers)).json()
    assert {p["title"] for p in owner_view} == {"Mine", "Theirs"}
    assert [p["title"] for p in engineer_view] == ["Mine"]


async def test_custom_roles_do_not_grant_api_access(client, admin, make_user):
    await client.post("/roles", headers=admin.headers, json={"code": "sonar_specialist", "name": "Sonar"})
    sonar = await make_user("sonar_specialist")
    assert (await client.get("/users", headers=sonar.headers)).status_code == 403
    assert (await client.get("/work-plans", headers=sonar.headers)).status_code == 403


def test_view_all_roles_match_expectations():
    from app.auth import VIEW_ALL_ROLES

    assert VIEW_ALL_ROLES == {r.value for r in (Role.ADMIN, Role.HR_TEAM, Role.TECHNICAL_TEAM, Role.OWNER)}
