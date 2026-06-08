"""
HTTP client that POSTs a recognized round to the backend.

Configurable via .env. Retries with exponential backoff; if every attempt fails,
the payload is appended to logs/outbox.jsonl so nothing is lost while the API is
down (you can replay that file later).
"""
import json
import os
import time

import requests
from loguru import logger

from api_client.auth import build_auth_header

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTBOX = os.path.join(PROJECT_ROOT, "logs", "outbox.jsonl")


def _endpoint() -> str | None:
    base = os.getenv("API_BASE_URL")
    if not base:
        return None
    path = os.getenv("API_RESULT_PATH", "/baccarat/result")
    return base.rstrip("/") + "/" + path.lstrip("/")


def _append_outbox(payload: dict) -> None:
    os.makedirs(os.path.dirname(OUTBOX), exist_ok=True)
    with open(OUTBOX, "a") as fh:
        fh.write(json.dumps(payload) + "\n")


def send_round(payload: dict) -> bool:
    """POST one round. Returns True on 2xx, else False (after retries + outbox)."""
    url = _endpoint()
    if not url:
        logger.warning("API_BASE_URL not set — skipping send (recognition still works).")
        return False

    timeout = int(os.getenv("API_TIMEOUT_SECONDS", 10))
    retries = int(os.getenv("API_MAX_RETRIES", 3))
    headers = {"Content-Type": "application/json", "X-Source": "baccarat-ai-agent"}
    headers.update(build_auth_header())  # fresh token each call (avoids expiry)

    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            if resp.status_code in (200, 201):
                logger.success(f"API ok | round={payload.get('round_id')} | {resp.status_code}")
                return True
            logger.warning(
                f"API {resp.status_code} | round={payload.get('round_id')} | attempt {attempt}"
            )
        except requests.exceptions.RequestException as exc:
            logger.error(f"API error: {exc} | attempt {attempt}")

        if attempt < retries:
            time.sleep(2 ** attempt)

    logger.error(f"API failed after {retries} tries | round={payload.get('round_id')} -> outbox")
    _append_outbox(payload)
    return False
