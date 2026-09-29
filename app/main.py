from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from app import db
from app.auth import get_principal
from app.services import seed_initial_admin
from app.routers import auth, items, roles, service_engineers, territories, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await seed_initial_admin()
    yield
    await db.disconnect()


app = FastAPI(title="Ojas Ocean Edge API", lifespan=lifespan)
authenticated = [Depends(get_principal)]
app.include_router(items.router, dependencies=authenticated)
app.include_router(roles.router, dependencies=authenticated)
app.include_router(territories.router, dependencies=authenticated)
app.include_router(users.router)  # routes declare their own auth (/users/me allows a pending password change)
app.include_router(service_engineers.router, dependencies=authenticated)
app.include_router(auth.router)


@app.get("/health")
async def health():
    await db.get_db().command("ping")
    return {"status": "ok"}
