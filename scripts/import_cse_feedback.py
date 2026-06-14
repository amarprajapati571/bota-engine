#!/usr/bin/env python3
"""Import CSE review feedback and turn it into a YOLO ROI dataset.

The CSE API returns full screenshots plus corrected card/score/winner fields.
Card feedback is text, not drawn boxes, so this script:

1. Fetches paginated CSE feedback records.
2. Downloads each reviewed image.
3. Crops the configured player/banker card ROIs.
4. Uses current detections for physical card boxes when available.
5. Falls back to fixed baccarat slot templates when boxes are missing.
6. Writes YOLO labels with CSE-corrected card classes.

Output defaults to:
  dataset/cse_feedback_card_roi/images/
  dataset/cse_feedback_card_roi/labels/
  dataset/cse_feedback_card_roi/data.yaml
  dataset/cse_feedback_card_roi/reviews.jsonl

Train with:
  DATA_YAML=./dataset/cse_feedback_card_roi/data.yaml python model/train.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import cv2
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from capture.roi_config import (  # noqa: E402
    BANKER_CARDS_ROI,
    PLAYER_CARDS_ROI,
    scale_roi_for_frame,
)
from recognition.card_recognizer import recognize_cards_in_roi  # noqa: E402
from scripts.auto_label_screenshots import (  # noqa: E402
    CARD_CLASS_ID,
    COMPACT_CLASS_NAMES,
    _canonical_card,
    _yolo_line,
)

DEFAULT_API_URL = "http://154.19.187.190:3000/api/ai-feedback/cse-reviews"
DEFAULT_OUT = PROJECT_ROOT / "dataset" / "cse_feedback_card_roi"
DEFAULT_RAW = PROJECT_ROOT / "dataset" / "cse_feedback_raw_frames"


PLAYER_FALLBACK_BOXES = {
    2: [
        [0.462, 0.152, 0.026, 0.145],
        [0.690, 0.158, 0.026, 0.145],
    ],
    3: [
        [0.117, 0.788, 0.064, 0.055],
        [0.462, 0.152, 0.026, 0.145],
        [0.690, 0.158, 0.026, 0.145],
    ],
}

BANKER_FALLBACK_BOXES = {
    2: [
        [0.252, 0.756, 0.027, 0.158],
        [0.526, 0.748, 0.027, 0.151],
    ],
    3: [
        [0.252, 0.756, 0.027, 0.158],
        [0.526, 0.748, 0.027, 0.151],
        [0.881, 0.364, 0.070, 0.076],
    ],
}


def _token() -> str:
    token = os.getenv("AI_FEEDBACK_API_TOKEN", "").strip()
    return token or os.getenv("CSE_API_TOKEN", "").strip()


def _headers() -> dict[str, str]:
    token = _token()
    if not token:
        raise SystemExit(
            "Missing token. Set AI_FEEDBACK_API_TOKEN or CSE_API_TOKEN in .env"
        )
    return {
        "x-ai-feedback-token": token,
        "Authorization": f"Bearer {token}",
    }


def _base_origin(api_url: str) -> str:
    match = re.match(r"^(https?://[^/]+)", api_url)
    if not match:
        raise ValueError(f"Could not derive origin from API URL: {api_url}")
    return match.group(1)


def _get_json(url: str, params: dict) -> dict:
    resp = requests.get(url, params=params, headers=_headers(), timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("success"):
        raise RuntimeError(f"API response was not successful: {payload}")
    return payload


def _fetch_records(api_url: str, limit: int, since: str | None, is_correct: str | None) -> list[dict]:
    records: list[dict] = []
    cursor = None
    page_limit = min(max(limit, 1), 500)

    while True:
        params = {"limit": page_limit}
        if cursor:
            params["cursor"] = cursor
        if since:
            params["since"] = since
        if is_correct:
            params["is_correct"] = is_correct

        payload = _get_json(api_url, params)
        data = payload.get("data", {})
        page_records = data.get("records", [])
        records.extend(page_records)
        cursor = data.get("nextCursor")
        if not data.get("hasMore") or not cursor:
            break
    return records


def _download_image(record: dict, api_url: str, raw_dir: Path, overwrite: bool) -> Path | None:
    image = record.get("image") or {}
    name = image.get("name") or f"{record.get('roundId') or record.get('feedbackId')}.png"
    out_path = raw_dir / name
    if out_path.exists() and not overwrite:
        return out_path

    url = image.get("url")
    if not url:
        return None
    absolute_url = url if url.startswith("http") else urljoin(_base_origin(api_url), url)

    resp = requests.get(absolute_url, headers=_headers(), timeout=60)
    resp.raise_for_status()
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(resp.content)
    return out_path


def _normalize_cards(cards: object) -> list[str]:
    if cards is None:
        return []
    if isinstance(cards, str):
        raw_cards = [c.strip() for c in cards.split(",") if c.strip()]
    elif isinstance(cards, list):
        raw_cards = [str(c).strip() for c in cards if str(c).strip()]
    else:
        return []
    return [_canonical_card(card) for card in raw_cards]


def _training_cards(record: dict, zone: str) -> list[str]:
    key = "playerCards" if zone == "player" else "bankerCards"
    corrected_key = "correctedPlayerCards" if zone == "player" else "correctedBankerCards"

    feedback = record.get("cseFeedback") or {}
    training = record.get("trainingLabel") or {}
    prediction = record.get("aiPrediction") or {}

    for value in (
        feedback.get(corrected_key),
        training.get(key),
        prediction.get(key),
    ):
        cards = _normalize_cards(value)
        if cards:
            return cards[:3]
    return []


def _card_order_for_review(record: dict) -> str:
    for container in (
        record.get("trainingLabel") or {},
        record.get("aiResponse") or {},
        record.get("aiPrediction") or {},
    ):
        value = (
            container.get("cardOrderForReview")
            or container.get("card_order_for_review")
            or container.get("cardOrder")
            or container.get("card_order")
        )
        if value:
            return str(value).strip().lower()
    # New CSE UI payloads are visual. Older records may not include the marker,
    # but visual order is the safest default for manual feedback.
    return "visual_left_to_right"


def _deal_to_visual(cards: list[str], zone: str) -> list[str]:
    if zone == "player" and len(cards) == 3:
        return [cards[2], cards[0], cards[1]]
    return cards


def _fallback_lines(cards_visual: list[str], zone: str) -> list[str]:
    templates = PLAYER_FALLBACK_BOXES if zone == "player" else BANKER_FALLBACK_BOXES
    boxes = templates.get(len(cards_visual), [])
    lines: list[str] = []
    for card, box in zip(cards_visual, boxes):
        lines.append(f"{CARD_CLASS_ID[card]} {box[0]:.6f} {box[1]:.6f} {box[2]:.6f} {box[3]:.6f}")
    return lines


def _detected_lines(frame, roi: tuple[int, int, int, int], zone: str, cards_visual: list[str]) -> list[str]:
    if not cards_visual:
        return []
    x1, y1, x2, y2 = roi
    crop_h = max(1, y2 - y1)
    crop_w = max(1, x2 - x1)
    detections = recognize_cards_in_roi(frame, roi, zone)
    if len(detections) < len(cards_visual):
        return _fallback_lines(cards_visual, zone)

    lines: list[str] = []
    for card, det in zip(cards_visual, detections[: len(cards_visual)]):
        lines.append(_yolo_line(CARD_CLASS_ID[card], det["bbox"], crop_w, crop_h))
    return lines


def _write_data_yaml(out_root: Path) -> None:
    lines = [
        f"path: {out_root}",
        "train: images",
        "val: images",
        "",
        "names:",
    ]
    for idx, name in enumerate(COMPACT_CLASS_NAMES):
        lines.append(f"  {idx}: {name}")
    (out_root / "data.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_review_manifest(path: Path, record: dict, image_path: Path, player_cards: list[str], banker_cards: list[str]) -> None:
    item = {
        "feedbackId": record.get("feedbackId"),
        "reviewItemId": record.get("reviewItemId"),
        "roundId": record.get("roundId"),
        "source": record.get("source"),
        "image_path": str(image_path),
        "player_cards": player_cards,
        "banker_cards": banker_cards,
        "aiPrediction": record.get("aiPrediction"),
        "cseFeedback": record.get("cseFeedback"),
        "trainingLabel": record.get("trainingLabel"),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(item, ensure_ascii=False) + "\n")


def _process_record(record: dict, image_path: Path, out_root: Path) -> int:
    frame = cv2.imread(str(image_path))
    if frame is None:
        print(f"[skip] unreadable image: {image_path}")
        return 0

    height, width = frame.shape[:2]
    saved = 0
    image_dir = out_root / "images"
    label_dir = out_root / "labels"
    image_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)

    for zone, base_roi in (("player", PLAYER_CARDS_ROI), ("banker", BANKER_CARDS_ROI)):
        cards = _training_cards(record, zone)
        if not (2 <= len(cards) <= 3):
            continue
        if _card_order_for_review(record).startswith("visual"):
            cards_visual = cards
        else:
            cards_visual = _deal_to_visual(cards, zone)

        roi = scale_roi_for_frame(base_roi, width, height)
        x1, y1, x2, y2 = roi
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            print(f"[skip] empty {zone} crop: {image_path}")
            continue

        stem = f"cse_{record.get('feedbackId') or image_path.stem}_{zone}"
        out_image = image_dir / f"{stem}.png"
        out_label = label_dir / f"{stem}.txt"
        cv2.imwrite(str(out_image), crop)
        lines = _detected_lines(frame, roi, zone, cards_visual)
        if lines:
            out_label.write_text("\n".join(lines) + "\n", encoding="utf-8")
            saved += 1
    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description="Import CSE feedback into a YOLO ROI dataset")
    parser.add_argument("--api-url", default=os.getenv("AI_FEEDBACK_API_URL", DEFAULT_API_URL))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--since", default=None)
    parser.add_argument("--is-correct", choices=["true", "false"], default=None)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW))
    parser.add_argument("--overwrite-images", action="store_true")
    args = parser.parse_args()

    out_root = Path(args.out).expanduser()
    raw_dir = Path(args.raw_dir).expanduser()
    manifest = out_root / "reviews.jsonl"
    out_root.mkdir(parents=True, exist_ok=True)
    if manifest.exists():
        manifest.unlink()

    records = _fetch_records(args.api_url, args.limit, args.since, args.is_correct)
    _write_data_yaml(out_root)

    downloaded = 0
    saved_roi = 0
    for record in records:
        image_path = _download_image(record, args.api_url, raw_dir, args.overwrite_images)
        if image_path is None:
            print(f"[skip] no image url for feedback={record.get('feedbackId')}")
            continue
        downloaded += 1
        player_cards = _training_cards(record, "player")
        banker_cards = _training_cards(record, "banker")
        _write_review_manifest(manifest, record, image_path, player_cards, banker_cards)
        saved_roi += _process_record(record, image_path, out_root)

    print("CSE feedback import complete")
    print(f"records: {len(records)}")
    print(f"images: {downloaded}")
    print(f"roi_images_with_labels: {saved_roi}")
    print(f"dataset: {out_root}")
    print(f"manifest: {manifest}")
    print(f"Train: DATA_YAML={out_root / 'data.yaml'} python model/train.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
