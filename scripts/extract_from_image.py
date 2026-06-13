"""
Extract marked training crops from one or more saved screenshots.

Usage:
  python scripts/extract_from_image.py path/to/screenshot.png
  python scripts/extract_from_image.py dataset/raw_frames/*.png --annotate

Outputs:
  dataset/imported_frames/                 copy of the full screenshot
  dataset/crops/player_cards/
  dataset/crops/banker_cards/
  dataset/crops/winner_badge/
  dataset/crops/player_score/
  dataset/crops/banker_score/
  dataset/annotated_frames/                optional ROI overlay
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

from capture.calibrate import draw_rois  # noqa: E402
from capture.roi_config import MARKED_CROP_ROIS  # noqa: E402

RAW_DIR = PROJECT_ROOT / "dataset" / "imported_frames"
CROP_DIR = PROJECT_ROOT / "dataset" / "crops"
ANNOTATED_DIR = PROJECT_ROOT / "dataset" / "annotated_frames"


def _safe_stem(path: Path) -> str:
    return path.stem.replace(" ", "_")


def _save_crops(image_path: Path, annotate: bool) -> list[Path]:
    frame = cv2.imread(str(image_path))
    if frame is None:
        raise ValueError(f"Could not read image: {image_path}")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    copied = RAW_DIR / image_path.name
    if image_path.resolve() != copied.resolve():
        shutil.copy2(image_path, copied)

    stem = _safe_stem(image_path)
    saved: list[Path] = []
    for zone, roi in MARKED_CROP_ROIS.items():
        x1, y1, x2, y2 = roi
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            print(f"[skip] {image_path.name} {zone}: empty crop for ROI={roi}")
            continue

        zone_dir = CROP_DIR / zone
        zone_dir.mkdir(parents=True, exist_ok=True)
        out = zone_dir / f"{zone}-{stem}.png"
        cv2.imwrite(str(out), crop)
        saved.append(out)

    if annotate:
        ANNOTATED_DIR.mkdir(parents=True, exist_ok=True)
        annotated = ANNOTATED_DIR / f"annotated-{image_path.name}"
        cv2.imwrite(str(annotated), draw_rois(frame))
        saved.append(annotated)

    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract marked crops from saved screenshots")
    parser.add_argument("images", nargs="+", help="screenshot/image paths")
    parser.add_argument("--annotate", action="store_true", help="also save an ROI overlay image")
    args = parser.parse_args()

    total = 0
    for raw in args.images:
        image_path = Path(raw).expanduser()
        try:
            saved = _save_crops(image_path, args.annotate)
        except Exception as exc:
            print(f"[error] {image_path}: {exc}")
            continue

        total += 1
        print(f"[ok] {image_path} -> {len(saved)} files")
        for path in saved:
            print(f"     {path}")

    print(f"Done - processed {total}/{len(args.images)} images")


if __name__ == "__main__":
    main()
