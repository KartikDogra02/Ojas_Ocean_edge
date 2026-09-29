from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "ojas_ocean_edge"

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Seeded on startup if the database has no admin user yet. Must change password on first login.
    initial_admin_email: str | None = None
    initial_admin_username: str | None = None
    initial_admin_password: str | None = None


settings = Settings()
