"""Shared test setup.

Tests run the real app (startup included) against a throwaway database in the Docker MongoDB, using the
connection settings from .env. The database is reset before every test and dropped at the end of the session.
"""

import os
import uuid

# Must be set before the app is imported: settings are read at import time.
os.environ["MONGO_DB"] = f"ojas_test_{uuid.uuid4().hex[:8]}"
os.environ["STORAGE_BACKEND"] = "gridfs"
os.environ["INITIAL_ADMIN_EMAIL"] = ""  # tests create their own users
os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)

from dataclasses import dataclass  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402
from pwdlib import PasswordHash  # noqa: E402
from pwdlib.hashers.argon2 import Argon2Hasher  # noqa: E402
from pydantic import SecretStr  # noqa: E402

import app.security  # noqa: E402
from app import db  # noqa: E402

# Same algorithm, minimal cost: argon2's real settings are deliberately slow and dominate test time.
app.security._hasher = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=1024, parallelism=1),))
from app.main import app  # noqa: E402
from app.models.role import Role  # noqa: E402
from app.models.service_engineer import ServiceEngineerProfile  # noqa: E402
from app.models.user import UserCreate  # noqa: E402
from app.services import insert_user, seed_system_roles  # noqa: E402

PASSWORD = "TestPass123"


@dataclass
class TestUser:
    username: str
    user_id: str
    headers: dict[str, str]
    engineer_id: str | None = None


@pytest.fixture(scope="session")
async def client():
    async with LifespanManager(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c
        assert db.client is not None
        await db.client.drop_database(db.get_db().name)


@pytest.fixture(autouse=True)
async def clean_db(client):
    """An empty database for every test (indexes are kept), with the system roles re-seeded."""
    database = db.get_db()
    for name in await database.list_collection_names():
        if not name.startswith("system."):
            await database[name].delete_many({})
    await seed_system_roles()


async def login(client: httpx.AsyncClient, username: str, password: str = PASSWORD) -> httpx.Response:
    return await client.post("/auth/login", data={"username": username, "password": password})


@pytest.fixture
def make_user(client):
    """Create a user with the given roles (permanent password) and return it logged in."""
    counter = iter(range(1, 10_000))

    async def _make(*roles: Role | str, username: str | None = None, full_name: str | None = None) -> TestUser:
        codes = [r.value if isinstance(r, Role) else r for r in roles]
        username = username or f"user{next(counter)}.{'-'.join(codes) or 'none'}".replace("_", "-")
        user = UserCreate(
            email=f"{username}@example.com",
            username=username,
            full_name=full_name,
            password=SecretStr(PASSWORD),
            roles=codes,
        )
        profile = ServiceEngineerProfile() if Role.SERVICE_ENGINEER.value in codes else None
        doc = await insert_user(user, service_engineer=profile, temporary_password=False)
        response = await login(client, username)
        assert response.status_code == 200, response.text
        token = response.json()["access_token"]
        return TestUser(
            username=username,
            user_id=str(doc["_id"]),
            headers={"Authorization": f"Bearer {token}"},
            engineer_id=doc.get("service_engineer", {}).get("engineer_id"),
        )

    return _make


@pytest.fixture
async def admin(make_user):
    return await make_user(Role.ADMIN)


@pytest.fixture
async def hr(make_user):
    return await make_user(Role.HR_TEAM)


@pytest.fixture
async def tech(make_user):
    return await make_user(Role.TECHNICAL_TEAM)


@pytest.fixture
async def owner(make_user):
    return await make_user(Role.OWNER)


@pytest.fixture
async def engineer(make_user):
    return await make_user(Role.SERVICE_ENGINEER, full_name="Amit")


@pytest.fixture
async def engineer2(make_user):
    return await make_user(Role.SERVICE_ENGINEER, full_name="Priya")
