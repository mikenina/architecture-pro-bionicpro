import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Keycloak settings (internal for auth-service)
    KEYCLOAK_INTERNAL_URL: str = "http://keycloak:8080"
    KEYCLOAK_EXTERNAL_URL: str = "http://localhost:8080"
    KEYCLOAK_REALM: str = "reports-realm"
    KEYCLOAK_CLIENT_ID: str = "bionicpro-auth"
    KEYCLOAK_CLIENT_SECRET: str = "oNwoLQdvJAvRcL89SydqCWCe5ry1jMgq"

    # Auth service settings
    AUTH_HOST: str = "0.0.0.0"
    AUTH_PORT: int = 8000
    AUTH_CALLBACK_URL: str = "http://localhost:3000/callback"

    # Frontend settings
    FRONTEND_URL: str = "http://localhost:3000"

    # Redis settings
    REDIS_URL: str = "redis://redis:6379"

    # Session settings
    SESSION_TTL: int = 1800

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

# Computed URLs
KEYCLOAK_BASE_URL_INTERNAL = f"{settings.KEYCLOAK_INTERNAL_URL}/realms/{settings.KEYCLOAK_REALM}"
KEYCLOAK_BASE_URL_EXTERNAL = f"{settings.KEYCLOAK_EXTERNAL_URL}/realms/{settings.KEYCLOAK_REALM}"

# URLs for internal communication (auth-service → Keycloak)
KEYCLOAK_TOKEN_URL = f"{KEYCLOAK_BASE_URL_INTERNAL}/protocol/openid-connect/token"
KEYCLOAK_USERINFO_URL = f"{KEYCLOAK_BASE_URL_INTERNAL}/protocol/openid-connect/userinfo"
KEYCLOAK_LOGOUT_URL = f"{KEYCLOAK_BASE_URL_INTERNAL}/protocol/openid-connect/logout"

# URLs for browser redirects (user → Keycloak)
KEYCLOAK_AUTH_URL_EXTERNAL = f"{KEYCLOAK_BASE_URL_EXTERNAL}/protocol/openid-connect/auth"