from tests.conftest import login


async def test_create_user_is_temporary_and_unique(client, admin):
    body = {"email": "new@example.com", "username": "New.User", "password": "Password123", "roles": ["hr_team"]}
    created = await client.post("/users", headers=admin.headers, json=body)
    assert created.status_code == 201
    assert created.json()["username"] == "new.user"
    assert created.json()["must_change_password"] is True
    assert "hashed_password" not in created.text
    duplicate = await client.post("/users", headers=admin.headers, json=body | {"username": "other"})
    assert duplicate.status_code == 409


async def test_user_validation(client, admin):
    base = {"email": "a@example.com", "username": "abc", "password": "Password123"}
    assert (await client.post("/users", headers=admin.headers, json=base | {"password": "short"})).status_code == 422
    assert (await client.post("/users", headers=admin.headers, json=base | {"roles": ["ghost"]})).status_code == 422
    engineer_role = base | {"roles": ["service_engineer"]}
    assert (await client.post("/users", headers=admin.headers, json=engineer_role)).status_code == 422


async def test_system_roles_seeded_and_protected(client, admin):
    roles = (await client.get("/roles", headers=admin.headers)).json()
    assert {r["code"] for r in roles} >= {"admin", "hr_team", "technical_team", "service_engineer", "owner"}
    assert (await client.delete("/roles/admin", headers=admin.headers)).status_code == 403
    assert (await client.patch("/roles/admin", headers=admin.headers, json={"name": "Boss"})).status_code == 403


async def test_custom_role_lifecycle(client, admin, make_user):
    created = await client.post("/roles", headers=admin.headers, json={"code": "sonar_specialist", "name": "Sonar"})
    assert created.status_code == 201
    assert (await client.post("/roles", headers=admin.headers, json={"code": "sonar_specialist", "name": "X"})).status_code == 409
    user = await make_user("sonar_specialist")
    assert (await client.delete("/roles/sonar_specialist", headers=admin.headers)).status_code == 400
    await client.patch(f"/users/{user.user_id}", headers=admin.headers, json={"is_active": False})
    assert (await client.delete("/roles/sonar_specialist", headers=admin.headers)).status_code == 204


async def test_permission_matrix_bulk_update_is_all_or_nothing(client, admin):
    good = {"permissions": [{"menu_id": "menu-subsea", "permissions": {"hr_team": True}}]}
    assert (await client.put("/permissions", headers=admin.headers, json=good)).status_code == 200
    bad = {"permissions": [{"menu_id": "menu-users", "permissions": {"hr_team": False}}, {"menu_id": "menu-x", "permissions": {}}]}
    assert (await client.put("/permissions", headers=admin.headers, json=bad)).status_code == 422
    matrix = (await client.get("/permissions", headers=admin.headers)).json()
    users_menu = next(m for m in matrix["menu_items"] if m["menu_id"] == "menu-users")
    assert users_menu["permissions"]["hr_team"] is True
    admin_off = {"permissions": [{"menu_id": "menu-users", "permissions": {"admin": False}}]}
    assert (await client.put("/permissions", headers=admin.headers, json=admin_off)).status_code == 400


async def test_my_menus(client, hr, engineer):
    hr_menus = {m["menu_id"] for m in (await client.get("/permissions/me", headers=hr.headers)).json()["authorized_menus"]}
    engineer_menus = {
        m["menu_id"] for m in (await client.get("/permissions/me", headers=engineer.headers)).json()["authorized_menus"]
    }
    assert "menu-users" in hr_menus and "menu-users" not in engineer_menus


async def test_login_after_role_change_uses_new_roles(client, admin, hr):
    await client.patch(f"/users/{hr.user_id}", headers=admin.headers, json={"roles": ["technical_team"]})
    assert (await client.get("/roles", headers=hr.headers)).status_code == 403
    assert (await login(client, hr.username)).status_code == 200
