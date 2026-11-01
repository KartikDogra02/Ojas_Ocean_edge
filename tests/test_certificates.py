from datetime import UTC, datetime

import pytest

import app.services
from app import db


@pytest.fixture
async def standard(client, tech):
    response = await client.post(
        "/reference-standards",
        headers=tech.headers,
        json={
            "name": "Deadweight",
            "make": "Budenberg",
            "model": "580",
            "serial_number": "bdn-1",
            "master_cert_number": "UKAS-1",
            "calibration_date": "2026-01-15",
            "due_date": "2099-01-15",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def certificate(standard, **extra):
    return {
        "instrument_type": "temp_pressure",
        "customer": "Vessel 1",
        "serial_number": "SER1",
        "result": "pass",
        "reference_standard_ids": [standard["id"]],
    } | extra


async def test_reference_standard_rules(client, tech, engineer, admin, standard):
    assert standard["serial_number"] == "BDN-1"
    duplicate = await client.post(
        "/reference-standards",
        headers=engineer.headers,
        json={
            "name": "X",
            "make": "X",
            "model": "X",
            "serial_number": "BDN-1",
            "master_cert_number": "X-2",
            "calibration_date": "2026-01-01",
            "due_date": "2027-01-01",
        },
    )
    assert duplicate.status_code == 409
    backwards = {
        "name": "X",
        "make": "X",
        "model": "X",
        "serial_number": "Z",
        "master_cert_number": "Z",
        "calibration_date": "2026-01-01",
        "due_date": "2025-01-01",
    }
    assert (await client.post("/reference-standards", headers=tech.headers, json=backwards)).status_code == 422
    assert (await client.post("/reference-standards", headers=admin.headers, json=backwards)).status_code == 403


async def test_monthly_numbering_and_cap(client, tech, standard, monkeypatch):
    monkeypatch.setattr(app.services, "utcnow", lambda: datetime(2026, 10, 12, tzinfo=UTC))
    first = (await client.post("/certificates", headers=tech.headers, json=certificate(standard))).json()
    assert first["certificate_number"] == "CAL-2026-10-0001"
    await db.get_db().counters.update_one({"_id": "certificate:2026-10"}, {"$set": {"seq": 9998}})
    assert (await client.post("/certificates", headers=tech.headers, json=certificate(standard))).json()[
        "certificate_number"
    ] == "CAL-2026-10-9999"
    assert (await client.post("/certificates", headers=tech.headers, json=certificate(standard))).status_code == 409
    monkeypatch.setattr(app.services, "utcnow", lambda: datetime(2026, 11, 1, tzinfo=UTC))
    assert (await client.post("/certificates", headers=tech.headers, json=certificate(standard))).json()[
        "certificate_number"
    ] == "CAL-2026-11-0001"


async def test_test_points_and_verdict(client, tech, standard):
    points = [
        {"parameter": "100 bar", "nominal_value": 100, "observed_value": 100, "tolerance": 0.05},
        {"parameter": "25 bar", "nominal_value": 25, "observed_value": 25.01, "tolerance": 0.05},
        {"parameter": "edge", "nominal_value": 0.3, "observed_value": 0.35, "tolerance": 0.05},
    ]
    issued = (
        await client.post("/certificates", headers=tech.headers, json=certificate(standard, test_points=points))
    ).json()
    assert [(p["deviation"], p["status"]) for p in issued["test_points"]] == [
        (0.0, "pass"),
        (0.01, "pass"),
        (0.05, "pass"),
    ]
    failing = certificate(standard, test_points=[{"nominal_value": 25, "observed_value": 25.08, "tolerance": 0.05}])
    assert (await client.post("/certificates", headers=tech.headers, json=failing)).status_code == 422
    assert (
        await client.post("/certificates", headers=tech.headers, json=failing | {"result": "fail"})
    ).status_code == 201


async def test_expired_standard_and_snapshot(client, tech, standard):
    issued = (await client.post("/certificates", headers=tech.headers, json=certificate(standard))).json()
    await client.patch(
        f"/reference-standards/{standard['id']}",
        headers=tech.headers,
        json={"calibration_date": "2026-01-01", "due_date": "2026-02-01", "master_cert_number": "UKAS-2"},
    )
    again = (await client.get(f"/certificates/{issued['certificate_number']}", headers=tech.headers)).json()
    assert again["reference_standards"][0]["master_cert_number"] == "UKAS-1"
    expired = await client.post(
        "/certificates", headers=tech.headers, json=certificate(standard, calibration_date="2026-03-01")
    )
    assert expired.status_code == 422
    assert (await client.delete(f"/reference-standards/{standard['id']}", headers=tech.headers)).status_code == 409
