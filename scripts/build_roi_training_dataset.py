"""
Build a YOLO training dataset from player/banker ROI crops.

The runtime recognizer runs YOLO on cropped card zones, not on full screenshots.
Training on matching ROI crops avoids making card boxes tiny and usually gives a
better fine-tune dataset than full-frame labels.

Usage:
  python scripts/build_roi_training_dataset.py dataset/raw_frames/*.png

Outputs:
  dataset/card_roi/images/
  dataset/card_roi/labels/
  dataset/card_roi/data.yaml
"""
import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import cv2  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from capture.roi_config import BANKER_CARDS_ROI, PLAYER_CARDS_ROI  # noqa: E402
from scripts.auto_label_screenshots import (  # noqa: E402
    CARD_CLASS_ID,
    COMPACT_CLASS_NAMES,
    _canonical_card,
    _scale_roi,
    _yolo_line,
)
from recognition.card_recognizer import recognize_cards_in_roi  # noqa: E402

OUT_ROOT = PROJECT_ROOT / "dataset" / "card_roi"
IMAGE_DIR = OUT_ROOT / "images"
LABEL_DIR = OUT_ROOT / "labels"
DATA_YAML = OUT_ROOT / "data.yaml"


def _write_data_yaml() -> None:
    lines = [
        f"path: {OUT_ROOT}",
        "train: images",
        "val: images",
        "",
        "names:",
    ]
    for idx, name in enumerate(COMPACT_CLASS_NAMES):
        lines.append(f"  {idx}: {name}")
    DATA_YAML.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_one(image_path: Path, skip_existing: bool = False) -> int:
    frame = cv2.imread(str(image_path))
    if frame is None:
        print(f"[skip] unreadable: {image_path}")
        return 0

    h, w = frame.shape[:2]
    saved = 0
    for zone, base_roi in (("player", PLAYER_CARDS_ROI), ("banker", BANKER_CARDS_ROI)):
        roi = _scale_roi(base_roi, w, h)
        x1, y1, x2, y2 = roi
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            print(f"[skip] {image_path.name} {zone}: empty crop")
            continue

        out_stem = f"{image_path.stem}_{zone}"
        out_image = IMAGE_DIR / f"{out_stem}.png"
        out_label = LABEL_DIR / f"{out_stem}.txt"
        if skip_existing and out_image.exists() and out_label.exists():
            continue

        detections = recognize_cards_in_roi(frame, roi, zone)
        if not detections:
            print(f"[skip] {image_path.name} {zone}: no detections")
            continue

        crop_h, crop_w = crop.shape[:2]
        label_lines: list[str] = []
        for det in detections:
            class_name = _canonical_card(det["card"])
            class_id = CARD_CLASS_ID[class_name]
            label_lines.append(_yolo_line(class_id, det["bbox"], crop_w, crop_h))

        cv2.imwrite(str(out_image), crop)
        out_label.write_text("\n".join(label_lines) + "\n", encoding="utf-8")
        saved += 1

    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ROI-crop YOLO dataset from screenshots")
    parser.add_argument("images", nargs="+", help="raw screenshot paths")
    parser.add_argument("--skip-existing", action="store_true", help="do not overwrite existing ROI images/labels")
    args = parser.parse_args()

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    _write_data_yaml()

    total = 0
    for raw in args.images:
        total += _build_one(Path(raw).expanduser(), args.skip_existing)

    print(f"Done - saved {total} ROI training images")
    print(f"Data YAML: {DATA_YAML}")


if __name__ == "__main__":
    main()
