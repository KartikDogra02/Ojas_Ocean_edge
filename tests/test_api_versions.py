"""Endpoints live under /api/v1; the old unversioned paths still work but are marked deprecated."""

import logging

ROOT = "http://test"


async def test_versioned_paths_are_not_deprecated(client, admin):
    response = await client.get("/users", headers=admin.headers)  # the client's base URL is /api/v1
    assert str(response.request.url) == f"{ROOT}/api/v1/users"
    assert response.status_code == 200 and "Deprecation" not in response.headers


async def test_old_paths_still_work_but_point_to_the_new_ones(client, admin, caplog):
    with caplog.at_level(logging.INFO, logger="app.deprecated"):
        response = await client.get(f"{ROOT}/users", headers=admin.headers)
    assert response.status_code == 200
    assert response.headers["Deprecation"] == "true"
    assert response.headers["Link"] == '</api/v1/users>; rel="successor-version"'
    assert f"Old path used: GET /users (use /api/v1/users) user={admin.username}" in caplog.text


async def test_old_login_path_still_issues_tokens(client, admin):
    response = await client.post(f"{ROOT}/auth/login", data={"username": admin.username, "password": "x"})
    assert response.status_code == 401 and response.headers["Deprecation"] == "true"


async def test_health_and_unknown_paths_are_not_marked(client):
    assert "Deprecation" not in (await client.get(f"{ROOT}/health")).headers
    assert "Deprecation" not in (await client.get(f"{ROOT}/no-such-thing")).headers


async def test_docs_list_only_the_versioned_paths(client):
    schema = (await client.get(f"{ROOT}/openapi.json")).json()
    paths = set(schema["paths"]) - {"/health"}
    assert paths and all(p.startswith("/api/v1/") for p in paths)
    assert schema["components"]["securitySchemes"]["OAuth2PasswordBearer"]["flows"]["password"]["tokenUrl"] == (
        "/api/v1/auth/login"
    )
