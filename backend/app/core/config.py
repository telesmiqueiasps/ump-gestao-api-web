from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Banco
    database_url: str

    # JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Backblaze B2
    b2_key_id: str
    b2_application_key: str
    b2_bucket_name: str
    b2_endpoint_url: str

    # App
    app_env: str = "development"
    frontend_url: str = "http://localhost:5173"

    # Admin
    admin_federation_id: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()