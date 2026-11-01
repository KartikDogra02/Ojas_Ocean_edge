from tests.helpers import JPEG, png


async def provision(client, admin, **extra):
    body = {"full_name": "Jordan Miller", "email": "jordan@example.com", "username": "Jordan.Eng"} | extra
    return await client.post("/service-engineers", headers=admin.headers, json=body)


async def test_provision_allocates_id_and_temporary_password(client, admin):
    response = await provision(client, admin, skills="Calibration, Diagnostics, Calibration", territory="india")
    assert response.status_code == 201
    data = response.json()
    assert data["service_engineer"]["engineer_id"].startswith("ENG-")
    assert data["service_engineer"]["skills"] == ["Calibration", "Diagnostics"]
    assert data["temporary_password"] and data["must_change_password"] is True


async def test_failed_provisioning_does_not_burn_ids(client, admin):
    first = (await provision(client, admin)).json()["service_engineer"]["engineer_id"]
    assert (await provision(client, admin)).status_code == 409
    second = await provision(client, admin, email="b@example.com", username="b.eng")
    assert int(second.json()["service_engineer"]["engineer_id"][-3:]) == int(first[-3:]) + 1


async def test_only_admin_provisions(client, hr):
    assert (await provision(client, hr)).status_code == 403


async def test_territory_must_be_known(client, admin):
    assert (await provision(client, admin, territory="mars")).status_code == 422


async def test_signature_png_only(client, admin, engineer):
    path = f"/service-engineers/{engineer.engineer_id}/signature"
    ok = await client.put(path, headers=admin.headers, files={"file": ("s.png", png(400, 120), "image/png")})
    assert ok.status_code == 200 and ok.json()["width"] == 400
    jpg = await client.put(path, headers=admin.headers, files={"file": ("s.png", JPEG, "image/png")})
    assert jpg.status_code == 415
    own = await client.get("/users/me/signature", headers=engineer.headers)
    assert own.status_code == 200 and own.headers["content-type"] == "image/png"
    assert (await client.get(path, headers=engineer.headers)).status_code == 403


async def test_signature_replace_and_delete(client, engineer):
    await client.put(
        "/users/me/signature", headers=engineer.headers, files={"file": ("a.png", png(10, 5), "image/png")}
    )
    await client.put(
        "/users/me/signature", headers=engineer.headers, files={"file": ("b.png", png(20, 5), "image/png")}
    )
    me = (await client.get("/users/me", headers=engineer.headers)).json()
    assert me["service_engineer"]["signature"]["width"] == 20
    assert (await client.delete("/users/me/signature", headers=engineer.headers)).status_code == 204
    assert (await client.get("/users/me/signature", headers=engineer.headers)).status_code == 404
