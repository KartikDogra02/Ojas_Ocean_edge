from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "ojas_ocean_edge"

    # At least 32 characters (HS256 needs a key of 256 bits or more).
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Failed logins allowed per username + IP address before a temporary lockout.
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15

    # Serve the interactive API docs (/docs, /redoc, /openapi.json). Consider turning off in production.
    api_docs_enabled: bool = True

    # Comma-separated frontend origins allowed to call the API from a browser, e.g.
    # "https://app.ojasoceanedge.com,http://localhost:5173". Must be exact origins ("*" is not allowed).
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    # Expense claims: mileage reimbursement rate (USD per km) and maximum receipt upload size.
    mileage_rate_per_km: float = 0.42
    receipt_max_mb: int = 10
    # Maximum size of a service engineer's signature PNG.
    signature_max_kb: int = 1024

    # Where receipts and signatures are stored: "gridfs" (inside MongoDB) or "r2" (Cloudflare R2).
    storage_backend: Literal["gridfs", "r2"] = "gridfs"
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket: str | None = None
    # Overrides the endpoint built from the account ID, e.g. the local SeaweedFS S3 server for testing.
    r2_endpoint: str | None = None
    # How long a direct file link (presigned URL) stays valid.
    file_link_expiry_seconds: int = 300

    # The company's time zone, e.g. "Europe/London": decides "today" on the planner and the month in
    # document numbers (CAL-2026-10-0001). PLANNER_TIMEZONE is still accepted as the old name.
    app_timezone: str = Field(default="UTC", validation_alias=AliasChoices("APP_TIMEZONE", "PLANNER_TIMEZONE"))
    # How many days ahead the daily planner covers, starting today.
    planner_days: int = 14

    # Seeded on startup if the database has no admin user yet. Must change password on first login.
    initial_admin_email: str | None = None
    initial_admin_username: str | None = None
    initial_admin_password: str | None = None

    @field_validator("app_timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown time zone {value!r}; use a name like 'Europe/London' or 'UTC'") from None
        return value


settings = Settings()  # pyright: ignore[reportCallIssue] - required values come from the environment / .env
