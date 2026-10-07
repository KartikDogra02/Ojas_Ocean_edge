from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.auth import get_principal
from app.config import settings
from app.routers import (
    auth,
    certificates,
    expense_claims,
    options,
    permissions,
    reference_standards,
    roles,
    service_engineers,
    users,
    work_plans,
)
from app.services import seed_initial_admin, seed_system_roles


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    await seed_system_roles()
    await seed_initial_admin()
    yield
    await db.disconnect()


app = FastAPI(title="Ojas Ocean Edge API", lifespan=lifespan)

if "*" in settings.cors_origin_list:
    raise RuntimeError("CORS_ORIGINS must list exact origins; '*' is not allowed with credentials")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,  # needed if the frontend later uses cookie-based auth
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)
authenticated = [Depends(get_principal)]
app.include_router(options.router, dependencies=authenticated)
app.include_router(roles.router, dependencies=authenticated)
app.include_router(permissions.router, dependencies=authenticated)
app.include_router(users.router)  # routes declare their own auth (/users/me allows a pending password change)
app.include_router(service_engineers.router, dependencies=authenticated)
app.include_router(reference_standards.router, dependencies=authenticated)
app.include_router(certificates.router, dependencies=authenticated)
app.include_router(work_plans.router, dependencies=authenticated)
app.include_router(expense_claims.router, dependencies=authenticated)
app.include_router(auth.router)


@app.get("/health")
async def health():
    await db.get_db().command("ping")
    return {"status": "ok"}
