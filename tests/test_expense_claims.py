import pytest

from tests.helpers import JPEG, PDF


@pytest.fixture
async def claim(client, engineer):
    response = await client.post(
        "/expense-claims", headers=engineer.headers, json={"category": "field_meals", "amount": 40, "description": "Meal"}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_mileage_amount_is_calculated(client, engineer):
    response = await client.post(
        "/expense-claims", headers=engineer.headers, json={"category": "travel_fuel", "distance_km": 33.3, "description": "Fuel"}
    )
    assert response.json()["amount"] == 13.99  # 33.3 km x $0.42, rounded half up
    bad = {"category": "field_meals", "distance_km": 5, "description": "x"}
    assert (await client.post("/expense-claims", headers=engineer.headers, json=bad)).status_code == 422


async def test_full_approval_flow(client, claim, tech, owner, hr):
    number = claim["claim_number"]
    assert (await client.post(f"/expense-claims/{number}/approve", headers=owner.headers)).status_code == 403
    assert (await client.post(f"/expense-claims/{number}/reimburse", headers=hr.headers)).status_code == 409
    assert (await client.post(f"/expense-claims/{number}/approve", headers=tech.headers)).json()["status"] == "technical_approved"
    assert (await client.post(f"/expense-claims/{number}/approve", headers=owner.headers)).json()["status"] == "owner_approved"
    paid = await client.post(f"/expense-claims/{number}/reimburse", headers=hr.headers, json={"payment_reference": "TRX-1"})
    assert paid.json()["status"] == "reimbursed"
    assert [e["action"] for e in paid.json()["history"]] == ["approved", "approved", "reimbursed"]
    assert "user_id" not in paid.json()["history"][0]


async def test_rejection_needs_reason_and_is_final(client, claim, tech, owner):
    number = claim["claim_number"]
    assert (await client.post(f"/expense-claims/{number}/reject", headers=tech.headers, json={})).status_code == 422
    rejected = await client.post(f"/expense-claims/{number}/reject", headers=tech.headers, json={"reason": "Not work"})
    assert rejected.json()["status"] == "rejected"
    assert (await client.post(f"/expense-claims/{number}/approve", headers=owner.headers)).status_code == 409


async def test_nobody_acts_on_own_claim_or_twice(client, make_user, tech):
    both = await make_user("technical_team", "owner")
    own = (await client.post("/expense-claims", headers=tech.headers, json={"category": "other", "amount": 5, "description": "x"})).json()
    assert (await client.post(f"/expense-claims/{own['id']}/approve", headers=tech.headers)).status_code == 403
    engineer = await make_user("service_engineer")
    claim = (await client.post("/expense-claims", headers=engineer.headers, json={"category": "other", "amount": 5, "description": "x"})).json()
    await client.post(f"/expense-claims/{claim['id']}/approve", headers=both.headers)
    assert (await client.post(f"/expense-claims/{claim['id']}/approve", headers=both.headers)).status_code == 403


async def test_receipts(client, claim, engineer, engineer2, hr):
    path = f"/expense-claims/{claim['id']}/receipt"
    uploaded = await client.post(path, headers=engineer.headers, files={"file": ("r.pdf", PDF, "application/pdf")})
    assert uploaded.json()["receipt"]["content_type"] == "application/pdf"
    fake = await client.post(path, headers=engineer.headers, files={"file": ("r.pdf", b"not a pdf", "application/pdf")})
    assert fake.status_code == 415
    replaced = await client.post(path, headers=engineer.headers, files={"file": ("r.jpg", JPEG, "image/jpeg")})
    assert replaced.json()["receipt"]["content_type"] == "image/jpeg"
    assert (await client.get(path, headers=hr.headers)).content == JPEG
    assert (await client.get(path, headers=engineer2.headers)).status_code == 404


async def test_withdraw_only_while_pending(client, claim, engineer, tech):
    await client.post(f"/expense-claims/{claim['id']}/approve", headers=tech.headers)
    assert (await client.delete(f"/expense-claims/{claim['id']}", headers=engineer.headers)).status_code == 409


async def test_awaiting_my_action(client, claim, tech, owner, hr):
    def numbers(response):
        return [c["claim_number"] for c in response.json()]

    assert numbers(await client.get("/expense-claims", headers=tech.headers, params={"awaiting_my_action": True})) == [claim["claim_number"]]
    assert numbers(await client.get("/expense-claims", headers=owner.headers, params={"awaiting_my_action": True})) == []
