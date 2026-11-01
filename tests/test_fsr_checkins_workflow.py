import pytest

from tests.helpers import png_data_url


@pytest.fixture
async def order(client, tech, engineer):
    response = await client.post(
        "/work-orders",
        headers=tech.headers,
        json={
            "title": "Pump repair",
            "service_type": "breakdown_repair",
            "assigned_engineer_ids": [engineer.engineer_id],
            "customer": {"company": "Apex"},
            "scope_of_work": "Pressure loss on line 2",
        },
    )
    return response.json()


FSR = {
    "root_cause": "Worn seal",
    "corrective_action": "Replaced seal",
    "spare_parts": [{"name": "Seal kit", "quantity": 2, "unit_cost": 12.25}],
    "customer_rep_name": "Jo Smith",
    "customer_satisfaction": 4,
}


async def test_fsr_completes_work_order(client, tech, engineer, order):
    response = await client.post(
        "/fsr",
        headers=engineer.headers,
        json=FSR | {"work_order": order["work_order_number"], "client_signature": png_data_url()},
    )
    assert response.status_code == 201, response.text
    fsr = response.json()
    assert fsr["fsr_number"].startswith("FSR-")
    assert fsr["initial_condition"] == "Pressure loss on line 2"
    assert fsr["parts_total"] == 24.5
    assert fsr["client_signature"]["width"] == 40
    done = (await client.get(f"/work-orders/{order['id']}", headers=tech.headers)).json()
    assert done["status"] == "completed" and done["field_service_report"]["fsr_number"] == fsr["fsr_number"]
    signature = await client.get(f"/fsr/{fsr['id']}/signature", headers=tech.headers)
    assert signature.headers["content-type"] == "image/png"
    second = await client.post("/fsr", headers=engineer.headers, json=FSR | {"work_order": order["id"]})
    assert second.status_code == 409


async def test_fsr_only_by_crew_and_valid_signature(client, tech, engineer, engineer2, order):
    body = FSR | {"work_order": order["id"]}
    assert (await client.post("/fsr", headers=engineer2.headers, json=body)).status_code == 403
    assert (await client.post("/fsr", headers=tech.headers, json=body)).status_code == 403
    bad = body | {"client_signature": "data:image/png;base64,/9j/4AAQSkZJRg=="}
    assert (await client.post("/fsr", headers=engineer.headers, json=bad)).status_code == 422
    assert (
        await client.post("/fsr", headers=engineer.headers, json=body | {"customer_satisfaction": 6})
    ).status_code == 422


async def test_check_ins(client, tech, engineer, engineer2):
    hotel = await client.post(
        "/check-ins", headers=engineer.headers, json={"place_type": "hotel", "place_name": "Hilton"}
    )
    assert hotel.status_code == 201
    await client.post("/check-ins", headers=engineer.headers, json={"place_type": "vessel", "place_name": "MV Star"})
    await client.post("/check-ins", headers=engineer2.headers, json={"place_type": "airport", "place_name": "SIN T3"})
    latest = (await client.get("/check-ins/latest", headers=tech.headers)).json()
    assert {(c["engineer_id"], c["place_name"]) for c in latest} == {
        (engineer.engineer_id, "MV Star"),
        (engineer2.engineer_id, "SIN T3"),
    }
    assert {c["engineer_id"] for c in (await client.get("/check-ins", headers=engineer.headers)).json()} == {
        engineer.engineer_id
    }
    assert (
        await client.post("/check-ins", headers=tech.headers, json={"place_type": "hotel", "place_name": "X"})
    ).status_code == 403
    gps = {"place_type": "hotel", "place_name": "X", "lat": 1.2}
    assert (await client.post("/check-ins", headers=engineer.headers, json=gps)).status_code == 422


async def test_workflow_chain_and_summary(client, tech, engineer):
    plan = (
        await client.post(
            "/work-plans",
            headers=tech.headers,
            json={
                "title": "Turbine",
                "priority": "critical",
                "customer": {"company": "Apex"},
                "assigned_engineer_ids": [engineer.engineer_id],
            },
        )
    ).json()
    await client.post("/work-plans", headers=tech.headers, json={"title": "Staged", "customer": {"company": "Jude"}})
    order = (
        await client.post(
            f"/work-plans/{plan['id']}/convert", headers=tech.headers, json={"service_type": "calibration"}
        )
    ).json()
    await client.post("/fsr", headers=engineer.headers, json=FSR | {"work_order": order["id"]})
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
    await client.post(
        "/certificates",
        headers=tech.headers,
        json={
            "instrument_type": "temp_pressure",
            "customer": "Apex",
            "serial_number": "SN",
            "result": "pass",
            "reference_standard_ids": [standard["id"]],
            "work_order": order["id"],
        },
    )
    workflow = (await client.get("/workflow", headers=tech.headers)).json()
    assert workflow["summary"]["total_chains"] == 2
    assert workflow["summary"]["staged_plans"] == 1 and workflow["summary"]["iso_certified"] == 1
    full = next(c for c in workflow["chains"] if c["title"] == "Turbine")
    staged = next(c for c in workflow["chains"] if c["title"] == "Staged")
    assert full["completion"] == 100 and full["stage"] == "certified"
    assert staged["completion"] == 20 and staged["stage"] == "staged"
    found = (await client.get("/workflow", headers=tech.headers, params={"search": "jude"})).json()["chains"]
    assert [c["title"] for c in found] == ["Staged"]
