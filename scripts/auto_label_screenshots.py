"""
Auto-label baccarat screenshots using the current card model.

This is meant to speed up dataset creation, not replace human review. It:
  - copies screenshots into a YOLO image folder
  - detects player/banker cards inside configured ROIs
  - writes YOLO label .txt files using the current compact model class order
  - saves individual card crops into class-named folders
  - optionally labels the winner badge when --winner is provided

Examples:
  python scripts/auto_label_screenshots.py dataset/raw_frames/*.png --annotate
  python scripts/auto_label_screenshots.py screenshot.png --winner banker --to-labeled
  python scripts/auto_label_screenshots.py screenshot.png --player-cards 8S,3D,KC --banker-cards 2S,JH,QS
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import cv2  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from capture.roi_config import BANKER_CARDS_ROI, PLAYER_CARDS_ROI, WIN_BADGE_ROI  # noqa: E402
from recognition.card_recognizer import cards_in_deal_order, recognize_cards_in_roi  # noqa: E402

AUTO_ROOT = PROJECT_ROOT / "dataset" / "auto_labeled"
LABELED_ROOT = PROJECT_ROOT / "dataset" / "labeled"
CARD_CROP_DIR = PROJECT_ROOT / "dataset" / "card_crops"
ANNOTATED_DIR = PROJECT_ROOT / "dataset" / "auto_labeled_annotated"

SUITS = {
    "C": "clubs",
    "D": "diamonds",
    "H": "hearts",
    "S": "spades",
    "club": "clubs",
    "clubs": "clubs",
    "diamond": "diamonds",
    "diamonds": "diamonds",
    "heart": "hearts",
    "hearts": "hearts",
    "spade": "spades",
    "spades": "spades",
}
RANKS = {"A": "A", "J": "J", "Q": "Q", "K": "K"}
RANK_ORDER = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
COMPACT_CLASS_NAMES = [
    "10C", "10D", "10H", "10S",
    "2C", "2D", "2H", "2S",
    "3C", "3D", "3H", "3S",
    "4C", "4D", "4H", "4S",
    "5C", "5D", "5H", "5S",
    "6C", "6D", "6H", "6S",
    "7C", "7D", "7H", "7S",
    "8C", "8D", "8H", "8S",
    "9C", "9D", "9H", "9S",
    "AC", "AD", "AH", "AS",
    "JC", "JD", "JH", "JS",
    "KC", "KD", "KH", "KS",
    "QC", "QD", "QH", "QS",
]
WINNER_CLASS_ID = {
    "player": 52,
    "banker": 53,
    "tie": 54,
}
BASE_WIDTH = int(os.getenv("ROI_BASE_WIDTH", "1920"))
BASE_HEIGHT = int(os.getenv("ROI_BASE_HEIGHT", "1080"))


def _canonical_card(label: str) -> str:
    label = label.strip()
    if "_" in label:
        rank, suit = label.split("_", 1)
        rank = RANKS.get(rank.upper(), rank)
        suit = SUITS.get(suit.lower())
        if suit:
            return f"{rank}_{suit}"

    rank = label[:-1].upper()
    suit = SUITS.get(label[-1:].upper())
    rank = RANKS.get(rank, rank)
    if suit and rank in RANK_ORDER:
        return f"{rank}_{suit}"

    raise ValueError(f"Unsupported card label from model: {label}")


CARD_CLASS_ID = {_canonical_card(label): idx for idx, label in enumerate(COMPACT_CLASS_NAMES)}


def _parse_card_list(raw: str | None) -> list[str] | None:
    if raw is None:
        return None
    cards = [c.strip() for c in raw.split(",") if c.strip()]
    return [_canonical_card(card) for card in cards]


def _is_sideways(det: dict) -> bool:
    x1, y1, x2, y2 = det["bbox"]
    return (x2 - x1) > (y2 - y1) * 1.15


def _sort_deal_order(detections: list[dict]) -> list[dict]:
    vertical = sorted((d for d in detections if not _is_sideways(d)), key=lambda d: d["bbox"][0])
    sideways = sorted((d for d in detections if _is_sideways(d)), key=lambda d: d["bbox"][0])
    return vertical + sideways


def _yolo_line(class_id: int, bbox: list[float], width: int, height: int) -> str:
    x1, y1, x2, y2 = bbox
    cx = ((x1 + x2) / 2) / width
    cy = ((y1 + y2) / 2) / height
    bw = max(0.0, x2 - x1) / width
    bh = max(0.0, y2 - y1) / height
    return f"{class_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}"


def _global_bbox(local_bbox: list[float], roi: tuple[int, int, int, int]) -> list[float]:
    x1, y1, _, _ = roi
    lx1, ly1, lx2, ly2 = local_bbox
    return [lx1 + x1, ly1 + y1, lx2 + x1, ly2 + y1]


def _scale_roi(roi: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    if width == BASE_WIDTH and height == BASE_HEIGHT:
        return roi

    sx = width / BASE_WIDTH
    sy = height / BASE_HEIGHT
    x1, y1, x2, y2 = roi
    scaled = (
        int(round(x1 * sx)),
        int(round(y1 * sy)),
        int(round(x2 * sx)),
        int(round(y2 * sy)),
    )
    return (
        max(0, min(width, scaled[0])),
        max(0, min(height, scaled[1])),
        max(0, min(width, scaled[2])),
        max(0, min(height, scaled[3])),
    )


def _clip_bbox(bbox: list[float], width: int, height: int) -> list[int]:
    x1, y1, x2, y2 = bbox
    return [
        max(0, min(width, int(round(x1)))),
        max(0, min(height, int(round(y1)))),
        max(0, min(width, int(round(x2)))),
        max(0, min(height, int(round(y2)))),
    ]


def _draw_box(frame, bbox: list[float], label: str, color: tuple[int, int, int]) -> None:
    x1, y1, x2, y2 = _clip_bbox(bbox, frame.shape[1], frame.shape[0])
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    cv2.putText(frame, label, (x1, max(14, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)


def _save_card_crop(frame, bbox: list[float], class_name: str, image_stem: str, suffix: str) -> None:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = _clip_bbox(bbox, w, h)
    if x2 <= x1 or y2 <= y1:
        return
    out_dir = CARD_CROP_DIR / class_name
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / f"{image_stem}-{suffix}.png"), frame[y1:y2, x1:x2])


def _output_dirs(to_labeled: bool) -> tuple[Path, Path]:
    root = LABELED_ROOT if to_labeled else AUTO_ROOT
    image_dir = root / "images"
    label_dir = root / "labels"
    image_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)
    CARD_CROP_DIR.mkdir(parents=True, exist_ok=True)
    return image_dir, label_dir


def _label_image(
    image_path: Path,
    winner: str | None,
    to_labeled: bool,
    annotate: bool,
    player_cards: list[str] | None,
    banker_cards: list[str] | None,
) -> None:
    frame = cv2.imread(str(image_path))
    if frame is None:
        raise ValueError(f"Could not read image: {image_path}")

    h, w = frame.shape[:2]
    image_dir, label_dir = _output_dirs(to_labeled)
    out_image = image_dir / image_path.name
    if image_path.resolve() != out_image.resolve():
        shutil.copy2(image_path, out_image)

    lines: list[str] = []
    annotated = frame.copy()
    summary: dict[str, list[str]] = {}

    player_roi = _scale_roi(PLAYER_CARDS_ROI, w, h)
    banker_roi = _scale_roi(BANKER_CARDS_ROI, w, h)
    winner_roi = _scale_roi(WIN_BADGE_ROI, w, h)

    for zone, roi, color, manual_cards in (
        ("player", player_roi, (0, 210, 0), player_cards),
        ("banker", banker_roi, (255, 120, 0), banker_cards),
    ):
        detections = recognize_cards_in_roi(frame, roi, zone)
        summary[zone] = cards_in_deal_order(detections)
        detections_for_labels = _sort_deal_order(detections) if manual_cards else detections

        if manual_cards and len(manual_cards) != len(detections_for_labels):
            print(
                f"[warn] {image_path.name} {zone}: manual cards={len(manual_cards)} "
                f"but detected boxes={len(detections_for_labels)}. "
                "Only matching positions will be overridden."
            )

        for idx, det in enumerate(detections_for_labels, start=1):
            if manual_cards and idx <= len(manual_cards):
                class_name = manual_cards[idx - 1]
            else:
                class_name = _canonical_card(det["card"])
            class_id = CARD_CLASS_ID[class_name]
            bbox = _global_bbox(det["bbox"], roi)
            lines.append(_yolo_line(class_id, bbox, w, h))
            _save_card_crop(frame, bbox, class_name, image_path.stem, f"{zone}-{idx}")
            _draw_box(annotated, bbox, f"{zone}:{class_name}", color)

    if winner:
        winner = winner.lower()
        if winner not in WINNER_CLASS_ID:
            raise ValueError("--winner must be one of: player, banker, tie")
        x1, y1, x2, y2 = winner_roi
        bbox = [float(x1), float(y1), float(x2), float(y2)]
        lines.append(_yolo_line(WINNER_CLASS_ID[winner], bbox, w, h))
        _draw_box(annotated, bbox, f"winner_{winner}", (0, 215, 255))

    label_path = label_dir / f"{image_path.stem}.txt"
    label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    if annotate:
        ANNOTATED_DIR.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(ANNOTATED_DIR / f"annotated-{image_path.name}"), annotated)

    print(
        f"[ok] {image_path.name} | labels={len(lines)} | "
        f"player={summary.get('player', [])} banker={summary.get('banker', [])} "
        f"-> {label_path}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-label card screenshots with current YOLO model")
    parser.add_argument("images", nargs="+", help="screenshot paths")
    parser.add_argument("--winner", choices=["player", "banker", "tie"], help="also label the winner badge")
    parser.add_argument("--player-cards", help="manual player cards in deal order, e.g. 8S,3D,KC")
    parser.add_argument("--banker-cards", help="manual banker cards in deal order, e.g. 2S,JH,QS")
    parser.add_argument("--to-labeled", action="store_true", help="write into dataset/labeled instead of dataset/auto_labeled")
    parser.add_argument("--annotate", action="store_true", help="save annotated preview images")
    args = parser.parse_args()

    player_cards = _parse_card_list(args.player_cards)
    banker_cards = _parse_card_list(args.banker_cards)

    ok = 0
    for raw in args.images:
        try:
            _label_image(
                Path(raw).expanduser(),
                args.winner,
                args.to_labeled,
                args.annotate,
                player_cards,
                banker_cards,
            )
            ok += 1
        except Exception as exc:
            print(f"[error] {raw}: {exc}")

    print(f"Done - labeled {ok}/{len(args.images)} images")


if __name__ == "__main__":
    main()
