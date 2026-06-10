"""
Capture frames from the live game to build a training dataset.

Two modes:
  # one frame per finished hand (fires on the gold WIN badge — the useful frames):
  python scripts/extract_frames.py --on-badge --max 300

  # a frame every N seconds (good for grabbing lots of variety):
  python scripts/extract_frames.py --interval 2 --max 300

Frames are saved to dataset/raw_frames/. With --crop it also saves the
PLAYER/BANKER card-zone crops to dataset/crops/ (handy for inspecting detection
or cutting out card templates for the synthetic generator).

Next: upload dataset/raw_frames/ to Roboflow (or label with LabelImg/CVAT),
export YOLOv8, and train with model/train.py.
"""
import argparse
import os
import sys
import time
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import cv2  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from capture.roi_config import BANKER_CARDS_ROI, CAPTURE_FPS, PLAYER_CARDS_ROI  # noqa: E402
from capture.screen_agent import capture_frame, is_win_badge_visible, should_trigger  # noqa: E402

RAW_DIR = os.path.join(PROJECT_ROOT, "dataset", "raw_frames")
CROP_DIR = os.path.join(PROJECT_ROOT, "dataset", "crops")


def _save(frame, crop: bool) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    path = os.path.join(RAW_DIR, f"frame-{ts}.png")
    cv2.imwrite(path, frame)
    if crop:
        for zone, roi in (("player", PLAYER_CARDS_ROI), ("banker", BANKER_CARDS_ROI)):
            x1, y1, x2, y2 = roi
            sub = frame[y1:y2, x1:x2]
            if sub.size:
                cv2.imwrite(os.path.join(CROP_DIR, zone, f"{zone}-{ts}.png"), sub)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="Capture game frames for a dataset")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--on-badge", action="store_true", help="save one frame per WIN badge")
    mode.add_argument("--interval", type=float, metavar="SECS", help="save a frame every N seconds")
    ap.add_argument("--max", type=int, default=300, help="stop after this many frames")
    ap.add_argument("--crop", action="store_true", help="also save player/banker card-zone crops")
    args = ap.parse_args()

    os.makedirs(RAW_DIR, exist_ok=True)
    if args.crop:
        os.makedirs(os.path.join(CROP_DIR, "player"), exist_ok=True)
        os.makedirs(os.path.join(CROP_DIR, "banker"), exist_ok=True)

    print(f"Saving to {RAW_DIR} | mode={'on-badge' if args.on_badge else f'every {args.interval}s'} "
          f"| max={args.max} | Ctrl-C to stop early")

    count = 0
    poll = 1.0 / max(CAPTURE_FPS, 1)
    try:
        while count < args.max:
            frame = capture_frame()
            if args.on_badge:
                visible, _ = is_win_badge_visible(frame)
                if should_trigger(visible):
                    path = _save(frame, args.crop)
                    count += 1
                    print(f"[{count}/{args.max}] {path}")
                time.sleep(poll)
            else:
                path = _save(frame, args.crop)
                count += 1
                print(f"[{count}/{args.max}] {path}")
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    print(f"Done — {count} frames in {RAW_DIR}")


if __name__ == "__main__":
    main()
