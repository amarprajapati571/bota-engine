"""
Extract player/banker score-circle crops from saved screenshots.

Usage:
  python scripts/extract_score_digit_crops.py dataset/raw_frames/*.png

Outputs unlabeled crops to:
  dataset/score_digits/unlabeled/

Then manually move each crop into:
  dataset/score_digits/labeled/0/
  dataset/score_digits/labeled/1/
  ...
  dataset/score_digits/labeled/9/
"""
import argparse
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import cv2  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from capture.roi_config import BANKER_SCORE_ROI, PLAYER_SCORE_ROI, scale_roi_for_frame  # noqa: E402

OUT_DIR = PROJECT_ROOT / "dataset" / "score_digits" / "unlabeled"
MANIFEST = PROJECT_ROOT / "dataset" / "score_digits" / "unlabeled_manifest.csv"


def _safe_stem(path: Path) -> str:
    return path.stem.replace(" ", "_")


def _extract_one(image_path: Path) -> list[dict]:
    frame = cv2.imread(str(image_path))
    if frame is None:
        print(f"[skip] cannot read {image_path}")
        return []

    height, width = frame.shape[:2]
    rows: list[dict] = []
    for zone, roi in (("player", PLAYER_SCORE_ROI), ("banker", BANKER_SCORE_ROI)):
        x1, y1, x2, y2 = scale_roi_for_frame(roi, width, height)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            print(f"[skip] empty {zone} score crop: {image_path}")
            continue

        # Normalize crop size for easier manual review and classifier training.
        crop = cv2.resize(crop, (96, 96), interpolation=cv2.INTER_CUBIC)
        out = OUT_DIR / f"{_safe_stem(image_path)}__{zone}.png"
        cv2.imwrite(str(out), crop)
        rows.append({
            "crop_path": str(out.relative_to(PROJECT_ROOT)),
            "source_image": str(image_path),
            "zone": zone,
            "roi": f"{x1},{y1},{x2},{y2}",
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract score digit crops from raw frames")
    parser.add_argument("images", nargs="+", help="raw frame paths/globs expanded by shell")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for raw in args.images:
        rows.extend(_extract_one(Path(raw).expanduser()))

    with MANIFEST.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["crop_path", "source_image", "zone", "roi"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved {len(rows)} score crops to {OUT_DIR}")
    print(f"Manifest: {MANIFEST}")
    print("Next: move crops into dataset/score_digits/labeled/<digit>/ folders.")


if __name__ == "__main__":
    main()
