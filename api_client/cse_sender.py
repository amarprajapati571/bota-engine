"""
Background sender for CSE manual verification.

Posts the exact full frame used for recognition together with the AI response
for that frame as multipart/form-data.
"""
import json
import os
import queue
import threading
import time
from pathlib import Path

import requests
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CSE_OUTBOX = PROJECT_ROOT / "logs" / "cse_outbox.jsonl"

_q: "queue.Queue[tuple[str, dict]]" = queue.Queue()
_stop = threading.Event()
_thread: "threading.Thread | None" = None


def cse_enabled() -> bool:
    return os.getenv("CSE_REVIEW_ENABLED", "false").strip().lower() in (
        "true",
        "1",
        "yes",
        "on",
    )


def cse_frame_dir() -> Path:
    return Path(os.getenv("CSE_FRAME_DIR", "./logs/cse_frames"))


def _endpoint() -> str | None:
    url = os.getenv("CSE_API_URL", "").strip()
    return url or None


def _auth_header() -> dict:
    token = os.getenv("CSE_API_TOKEN", "").strip()
    if token:
        header_name = os.getenv("CSE_API_TOKEN_HEADER", "Authorization").strip()
        if header_name.lower() == "authorization":
            return {"Authorization": f"Bearer {token}"}
        return {header_name: token}
    return {}


def _append_outbox(image_path: str, payload: dict) -> None:
    CSE_OUTBOX.parent.mkdir(parents=True, exist_ok=True)
    item = {"image_path": image_path, "payload": payload}
    with CSE_OUTBOX.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(item, ensure_ascii=False) + "\n")


def submit_cse_review(image_path: str, ai_response: dict) -> None:
    if not cse_enabled():
        return
    _q.put((image_path, _review_payload(ai_response)))


def _review_payload(ai_response: dict) -> dict:
    """Return the CSE-facing payload with cards in image visual order.

    The recognition core keeps deal order for baccarat scoring, but CSE users
    review cards by looking at the screenshot from left to right. Sending the
    visual order as the main card fields keeps manual feedback aligned with the
    image while still preserving deal-order fields for debugging/retraining.
    """
    payload = dict(ai_response)
    player_visual = ai_response.get("player_cards_visual_order")
    banker_visual = ai_response.get("banker_cards_visual_order")

    if player_visual:
        payload["player_cards"] = list(player_visual)
        payload["playerCards"] = list(player_visual)
    if banker_visual:
        payload["banker_cards"] = list(banker_visual)
        payload["bankerCards"] = list(banker_visual)

    payload["card_order_for_review"] = "visual_left_to_right"
    payload["cardOrderForReview"] = "visual_left_to_right"
    payload.setdefault("player_cards_deal_order", ai_response.get("player_cards_deal_order"))
    payload.setdefault("banker_cards_deal_order", ai_response.get("banker_cards_deal_order"))
    return payload


def send_cse_review(image_path: str, ai_response: dict) -> bool:
    url = _endpoint()
    if not url:
        logger.warning("CSE_REVIEW_ENABLED=true but CSE_API_URL is empty — skipping CSE send.")
        return False
    if not os.path.exists(image_path):
        logger.error(f"CSE image missing, cannot send | image={image_path}")
        return False

    timeout = int(os.getenv("CSE_TIMEOUT_SECONDS", 15))
    retries = int(os.getenv("CSE_MAX_RETRIES", 3))
    image_field = os.getenv("CSE_IMAGE_FIELD", "image")
    response_field = os.getenv("CSE_AI_RESPONSE_FIELD", "ai_response")
    source_field = os.getenv("CSE_SOURCE_FIELD", "source")
    round_id_field = os.getenv("CSE_ROUND_ID_FIELD", "round_id")

    headers = {"X-Source": "baccarat-ai-cse-review"}
    headers.update(_auth_header())
    data = {
        response_field: json.dumps(ai_response, ensure_ascii=False),
        source_field: "live",
        round_id_field: str(ai_response.get("round_id", "")),
        "image_name": os.path.basename(image_path),
    }

    for attempt in range(1, retries + 1):
        try:
            with open(image_path, "rb") as fh:
                files = {image_field: (os.path.basename(image_path), fh, "image/png")}
                resp = requests.post(url, data=data, files=files, headers=headers, timeout=timeout)
            if 200 <= resp.status_code < 300:
                logger.success(
                    f"CSE API ok | round={ai_response.get('round_id')} | {resp.status_code}"
                )
                return True
            logger.warning(
                f"CSE API {resp.status_code} | round={ai_response.get('round_id')} "
                f"| attempt {attempt}"
            )
        except requests.exceptions.RequestException as exc:
            logger.error(f"CSE API error: {exc} | attempt {attempt}")
        if attempt < retries:
            time.sleep(2 ** attempt)

    logger.error(
        f"CSE API failed after {retries} tries | round={ai_response.get('round_id')} -> outbox"
    )
    _append_outbox(image_path, ai_response)
    return False


def _loop() -> None:
    logger.info("CSE sender thread started")
    while not _stop.is_set() or not _q.empty():
        try:
            image_path, payload = _q.get(timeout=1)
        except queue.Empty:
            continue
        try:
            send_cse_review(image_path, payload)
        except Exception as exc:
            logger.error(f"CSE sender error: {exc}")
        finally:
            _q.task_done()
    logger.info("CSE sender thread stopped")


def start_cse_sender() -> "threading.Thread | None":
    global _thread
    if not cse_enabled():
        return None
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="CseSender", daemon=True)
    _thread.start()
    return _thread


def stop_cse_sender(drain: bool = True, timeout: float = 10.0) -> None:
    _stop.set()
    if _thread and drain:
        _thread.join(timeout=timeout)
