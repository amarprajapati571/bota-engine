"""
Auth header for the API client.

Priority:
  1. API_JWT_SECRET set -> sign a short-lived HS256 JWT per request (Bearer)
  2. API_TOKEN set      -> send it as a static Bearer token
  3. neither            -> no auth header (fine for a local/open backend)
"""
import os
import time


def _jwt_header(secret: str) -> dict:
    import jwt  # PyJWT

    now = int(time.time())
    token = jwt.encode(
        {
            "sub": "baccarat-ai-agent",
            "role": "agent",
            "iat": now,
            "exp": now + int(os.getenv("API_JWT_TTL_SECONDS", 3600)),
        },
        secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def build_auth_header() -> dict:
    secret = os.getenv("API_JWT_SECRET")
    if secret:
        return _jwt_header(secret)
    token = os.getenv("API_TOKEN")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}
