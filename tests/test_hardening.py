from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

import app.services
from app import db
from app.config import Settings, settings
from tests.conftest import login


async def test_login_lockout_after_too_many_failures(client, hr, admin):
    for _ in range(settings.login_max_attempts):
        assert (await login(client, hr.username, "WrongPass999")).status_code == 401
    locked = await login(client, hr.username)  # even the right password is refused while locked
    assert locked.status_code == 429
    assert 0 < int(locked.headers["Retry-After"]) <= settings.login_lockout_minutes * 60
    assert (await login(client, admin.username)).status_code == 200  # other accounts unaffected

    # Once the lockout window has passed, logging in works again.
    await db.get_db().login_attempts.update_many({}, {"$set": {"expire_at": datetime.now(UTC) - timedelta(seconds=1)}})
    assert (await login(client, hr.username)).status_code == 200


async def test_successful_login_resets_the_count(client, hr):
    for _ in range(settings.login_max_attempts - 1):
        await login(client, hr.username, "WrongPass999")
    assert (await login(client, hr.username)).status_code == 200
    assert await db.get_db().login_attempts.count_documents({}) == 0


@pytest.mark.parametrize("params", [{"limit": 1000}, {"limit": 0}, {"skip": -1}])
async def test_list_paging_is_bounded(client, admin, params):
    assert (await client.get("/users", headers=admin.headers, params=params)).status_code == 422


async def test_total_count_header(client, admin, tech, make_user):
    for _ in range(3):
        await make_user("hr_team")
    response = await client.get("/users", headers=admin.headers, params={"limit": 2})
    assert len(response.json()) == 2
    assert response.headers["X-Total-Count"] == "5"  # admin, tech and three HR users
    for i in range(3):
        await client.post("/work-plans", headers=tech.headers, json={"title": f"P{i}", "customer": {"company": "C"}})
    workflow = await client.get("/workflow", headers=tech.headers, params={"limit": 1})
    assert len(workflow.json()["chains"]) == 1 and workflow.headers["X-Total-Count"] == "3"


def test_settings_are_validated_at_startup(monkeypatch):
    with pytest.raises(ValidationError, match="at least 32"):
        Settings(jwt_secret="short")
    with pytest.raises(ValidationError, match="unknown time zone"):
        Settings(jwt_secret="x" * 40, app_timezone="Mars/Base")
    monkeypatch.setenv("PLANNER_TIMEZONE", "Asia/Singapore")
    monkeypatch.delenv("APP_TIMEZONE", raising=False)
    assert Settings(jwt_secret="x" * 40).app_timezone == "Asia/Singapore"


async def test_document_numbers_use_the_company_time_zone(client, tech, monkeypatch):
    # 20:00 UTC on 31 October is already 1 November in Singapore.
    monkeypatch.setattr(app.services, "utcnow", lambda: datetime(2026, 10, 31, 20, 0, tzinfo=UTC))
    monkeypatch.setattr(settings, "app_timezone", "Asia/Singapore")
    standard = (
        await client.post(
            "/reference-standards",
            headers=tech.headers,
            json={
                "name": "S",
                "make": "M",
                "model": "X",
                "serial_number": "S-1",
                "master_cert_number": "C-1",
                "calibration_date": "2026-01-01",
                "due_date": "2099-01-01",
            },
        )
    ).json()
    certificate = await client.post(
        "/certificates",
        headers=tech.headers,
        json={
            "instrument_type": "fixed_gas",
            "customer": "C",
            "serial_number": "X",
            "result": "pass",
            "reference_standard_ids": [standard["id"]],
            "calibration_date": "2026-10-31",
        },
    )
    assert certificate.json()["certificate_number"] == "CAL-2026-11-0001"
