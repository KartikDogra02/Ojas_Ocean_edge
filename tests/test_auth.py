from pydantic import SecretStr

from app.models.role import Role
from app.models.user import UserCreate
from app.services import insert_user
from tests.conftest import PASSWORD, login


async def test_health(client):
    assert (await client.get("/health")).json() == {"status": "ok"}


async def test_login_by_username_or_email(client, admin):
    assert (await login(client, admin.username)).status_code == 200
    assert (await login(client, f"{admin.username}@example.com")).status_code == 200


async def test_wrong_password_and_unknown_user_give_same_error(client, admin):
    wrong = await login(client, admin.username, "WrongPass999")
    unknown = await login(client, "nobody", "WrongPass999")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_requests_need_a_valid_token(client):
    assert (await client.get("/users/me")).status_code == 401
    bad = {"Authorization": "Bearer not-a-token"}
    assert (await client.get("/users/me", headers=bad)).status_code == 401


async def test_temporary_password_must_be_changed_first(client):
    await insert_user(
        UserCreate(email="t@example.com", username="temp.user", password=SecretStr(PASSWORD), roles=[Role.HR_TEAM])
    )
    token = (await login(client, "temp.user")).json()
    assert token["must_change_password"] is True
    headers = {"Authorization": f"Bearer {token['access_token']}"}
    assert (await client.get("/work-plans", headers=headers)).json()["detail"] == "Password change required"
    assert (await client.get("/users/me", headers=headers)).status_code == 200

    changed = await client.post(
        "/auth/change-password",
        headers=headers,
        json={"current_password": PASSWORD, "new_password": "BrandNew123"},
    )
    assert changed.status_code == 200
    new_headers = {"Authorization": f"Bearer {changed.json()['access_token']}"}
    assert (await client.get("/work-plans", headers=new_headers)).status_code == 200
    # The old token stops working once the password changes.
    assert (await client.get("/users/me", headers=headers)).status_code == 401


async def test_change_password_checks_current_password(client, hr):
    response = await client.post(
        "/auth/change-password", headers=hr.headers, json={"current_password": "nope", "new_password": "BrandNew123"}
    )
    assert response.status_code == 400


async def test_logout_revokes_only_that_token(client, admin):
    other = (await login(client, admin.username)).json()["access_token"]
    assert (await client.post("/auth/logout", headers=admin.headers)).status_code == 204
    assert (await client.get("/users/me", headers=admin.headers)).status_code == 401
    assert (await client.get("/users/me", headers={"Authorization": f"Bearer {other}"})).status_code == 200


async def test_deactivated_user_is_locked_out(client, admin, hr):
    await client.patch(f"/users/{hr.user_id}", headers=admin.headers, json={"is_active": False})
    assert (await client.get("/users/me", headers=hr.headers)).status_code == 401
    assert (await login(client, hr.username)).status_code == 401


async def test_admin_set_password_is_temporary(client, admin, hr):
    await client.patch(f"/users/{hr.user_id}", headers=admin.headers, json={"password": "ResetPass123"})
    assert (await login(client, hr.username, "ResetPass123")).json()["must_change_password"] is True
