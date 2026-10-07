from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "ojas_ocean_edge"

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

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

    # Seeded on startup if the database has no admin user yet. Must change password on first login.
    initial_admin_email: str | None = None
    initial_admin_username: str | None = None
    initial_admin_password: str | None = None


settings = Settings()
