import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.auth import get_principal
from app.config import settings
from app.legacy_paths import API_PREFIX, LegacyPathMiddleware
from app.request_context import RequestLoggingMiddleware
from app.routers import (
    audit_log,
    auth,
    certificates,
    check_ins,
    expense_claims,
    fsr,
    options,
    permissions,
    planner,
    reference_standards,
    roles,
    service_engineers,
    signatures,
    users,
    work_orders,
    work_plans,
    workflow,
)
from app.services import seed_initial_admin, seed_system_roles
from app.storage import get_storage

logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_storage().check()
    await db.connect()
    await seed_system_roles()
    await seed_initial_admin()
    yield
    await db.disconnect()


docs = settings.api_docs_enabled
app = FastAPI(
    title="Ojas Ocean Edge API",
    lifespan=lifespan,
    docs_url="/docs" if docs else None,
    redoc_url="/redoc" if docs else None,
    openapi_url="/openapi.json" if docs else None,
)

if "*" in settings.cors_origin_list:
    raise RuntimeError("CORS_ORIGINS must list exact origins; '*' is not allowed with credentials")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,  # needed if the frontend later uses cookie-based auth
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=[
        "X-Total-Count",
        "Retry-After",
        "X-Request-ID",
        "Deprecation",
        "Link",
    ],  # readable by the frontend (paging totals, login lockout, old-path warnings)
    max_age=600,
)
app.add_middleware(LegacyPathMiddleware)
app.add_middleware(RequestLoggingMiddleware)
authenticated = [Depends(get_principal)]
api = APIRouter()
api.include_router(options.router, dependencies=authenticated)
api.include_router(roles.router, dependencies=authenticated)
api.include_router(permissions.router, dependencies=authenticated)
api.include_router(users.router)  # routes declare their own auth (/users/me allows a pending password change)
api.include_router(service_engineers.router, dependencies=authenticated)
api.include_router(signatures.router, dependencies=authenticated)
api.include_router(reference_standards.router, dependencies=authenticated)
api.include_router(certificates.router, dependencies=authenticated)
api.include_router(work_plans.router, dependencies=authenticated)
api.include_router(work_orders.router, dependencies=authenticated)
api.include_router(fsr.router, dependencies=authenticated)
api.include_router(check_ins.router, dependencies=authenticated)
api.include_router(workflow.router, dependencies=authenticated)
api.include_router(planner.router, dependencies=authenticated)
api.include_router(expense_claims.router, dependencies=authenticated)
api.include_router(auth.router)
api.include_router(audit_log.router, dependencies=authenticated)

app.include_router(api, prefix=API_PREFIX)
# The same endpoints at their old unversioned paths, hidden from the docs and marked deprecated, until the
# frontend has moved to /api/v1.
app.include_router(api, include_in_schema=False)


@app.get("/health")
async def health():
    await db.get_db().command("ping")
    return {"status": "ok"}
