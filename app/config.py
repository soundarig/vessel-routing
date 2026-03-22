from pathlib import Path
from pydantic_settings import BaseSettings

# Resolve .env relative to this config file — always finds the right .env
# regardless of working directory
_ENV_FILE = Path(__file__).resolve().parent.parent / "vessel-routing" / ".env"
# Fallback: if running directly from the vessel-routing/ directory
if not _ENV_FILE.exists():
    _ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    # Required — outbound OAuth2 credentials
    oauth_client_id: str
    oauth_client_secret: str

    # Server
    port: int = 8300

    # Outbound endpoints
    token_url: str = "https://identity.genix.abilityplatform.abb/public/api/oauth2/token"
    routing_ws_url: str = "wss://api.voyageoptimization.abb.com/vessel-routing/v2/shortest-path"
    oauth_scope: str = "https://genb2cep01euwprod.onmicrosoft.com/rs.iam/region"

    # Timeouts (seconds)
    http_timeout: float = 10.0
    ws_connect_timeout: float = 15.0
    ws_recv_timeout: float = 120.0

    # Retry
    token_retry_attempts: int = 3
    token_retry_backoff: float = 1.0

    # Inbound authentication — username/password → JWT
    # API_USERNAME / API_PASSWORD_HASH are the credentials callers use to obtain a token.
    # Generate a bcrypt hash with: python -c "from passlib.hash import bcrypt; print(bcrypt.hash('yourpassword'))"
    api_username: str = "REPLACE_ME"
    api_password_hash: str = "REPLACE_ME"   # bcrypt hash of the password

    # SQL Server — ports database
    db_connection_string: str = ""  # full ODBC connection string, e.g. "Driver={ODBC Driver 18 for SQL Server};Server=...;Database=...;Uid=...;Pwd=..."

    # Secret used to sign issued JWTs — must be a long random string in production
    jwt_secret_key: str = "REPLACE_ME"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    model_config = {"env_file": str(_ENV_FILE), "env_file_encoding": "utf-8"}
