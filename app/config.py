from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Required credentials
    oauth_client_id: str
    oauth_client_secret: str

    # Server
    port: int = 8000

    # Endpoints
    token_url: str = "https://identity.genix.abilityplatform.abb/public/api/oauth2/token"
    routing_ws_url: str = "wss://api.voyageoptimization.abb.com/vessel-routing/v2/shortest-path"
    oauth_scope: str = "https://genb2cep01euwprod.onmicrosoft.com/rs.iam/region"

    # Timeouts (seconds)
    http_timeout: float = 10.0       # OAuth token request timeout
    ws_connect_timeout: float = 15.0  # WebSocket connection timeout
    ws_recv_timeout: float = 120.0    # Max wait per WebSocket message

    # Retry
    token_retry_attempts: int = 3
    token_retry_backoff: float = 1.0  # seconds between retries

    # Inbound JWT validation
    # URL to the JWKS endpoint of your identity provider, e.g.:
    # https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys
    jwt_jwks_uri: str = ""
    jwt_audience: str = ""   # expected `aud` claim in the inbound JWT
    jwt_issuer: str = ""     # expected `iss` claim in the inbound JWT
    jwt_algorithms: list[str] = ["RS256"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
