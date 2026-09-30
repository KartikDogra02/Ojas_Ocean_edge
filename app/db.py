from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.config import settings

client: AsyncMongoClient | None = None


async def connect() -> None:
    global client
    client = AsyncMongoClient(settings.mongo_uri, tz_aware=True)
    await client.admin.command("ping")
    await ensure_indexes()


async def disconnect() -> None:
    if client is not None:
        await client.close()


def get_db() -> AsyncDatabase:
    assert client is not None, "Mongo client not initialised"
    return client[settings.mongo_db]


async def ensure_indexes() -> None:
    db = get_db()
    await db.roles.create_index("code", unique=True)
    await db.users.create_index("email", unique=True)
    await db.users.create_index("username", unique=True)
    await db.users.create_index("roles")
    await db.users.create_index(
        "service_engineer.engineer_id",
        unique=True,
        partialFilterExpression={"service_engineer.engineer_id": {"$exists": True}},
    )
    await db.users.create_index("service_engineer.territory")
    await db.reference_standards.create_index("serial_number", unique=True)
    await db.reference_standards.create_index("master_cert_number", unique=True)
    await db.reference_standards.create_index("due_date")
    # Logged-out tokens; Mongo deletes each entry once the token would have expired anyway.
    await db.revoked_tokens.create_index("expires_at", expireAfterSeconds=0)
