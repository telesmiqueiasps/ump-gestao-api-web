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

    # Cloudflare R2
    r2_access_key_id: str
    r2_secret_access_key: str
    r2_bucket_name: str
    r2_endpoint_url: str
    r2_public_domain: str

    @property
    def b2_bucket_name(self) -> str:
        return self.r2_bucket_name

    @property
    def b2_key_id(self) -> str:
        return self.r2_access_key_id

    @property
    def b2_application_key(self) -> str:
        return self.r2_secret_access_key

    @property
    def b2_endpoint_url(self) -> str:
        return self.r2_endpoint_url

    # App
    app_env: str = "development"
    frontend_url: str = "http://localhost:5173"

    # Admin
    admin_federation_id: str = ""

    # VAPID (Push Notifications)
    vapid_public_key:  str = ""
    vapid_private_key: str = ""
    vapid_email:       str = "admin@umpgestao.netlify.app"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()