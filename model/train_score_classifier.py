"""
Train the score digit classifier used by recognition/score_classifier.py.

Dataset format is YOLO classification format:
  dataset/score_digits/classify/train/0/*.png
  dataset/score_digits/classify/train/1/*.png
  ...
  dataset/score_digits/classify/val/9/*.png

Run:
  SCORE_DATA_DIR=./dataset/score_digits/classify python model/train_score_classifier.py
"""
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from recognition.device import resolve_device  # noqa: E402


def main() -> None:
    try:
        from ultralytics import YOLO
    except ImportError:
        print("ERROR: ultralytics not installed. Run: pip install -r requirements.txt")
        sys.exit(1)

    data_dir = Path(os.getenv("SCORE_DATA_DIR", "./dataset/score_digits/classify"))
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    if not (data_dir / "train").exists():
        print(f"ERROR: score classifier dataset not found: {data_dir}")
        print("Run scripts/build_score_classifier_dataset.py first.")
        sys.exit(1)

    dest = Path(os.getenv("SCORE_MODEL_WEIGHTS_PATH", "./models/weights/score_digits.pt"))
    if not dest.is_absolute():
        dest = PROJECT_ROOT / dest

    device = resolve_device()
    model_name = os.getenv("SCORE_BASE_MODEL", "yolov8n-cls.pt")
    print(f"Training score classifier on {data_dir} | device={device}")

    model = YOLO(model_name)
    train_args = {
        "data": str(data_dir),
        "epochs": int(os.getenv("SCORE_TRAIN_EPOCHS", "40")),
        "imgsz": int(os.getenv("SCORE_TRAIN_IMGSZ", "96")),
        "batch": int(os.getenv("SCORE_TRAIN_BATCH", "64")),
        "device": device,
        "project": str(PROJECT_ROOT / "runs"),
        "name": os.getenv("SCORE_TRAIN_RUN_NAME", "score_digits"),
        "exist_ok": True,
        "workers": int(os.getenv("SCORE_TRAIN_WORKERS", "4")),
        "cache": os.getenv("SCORE_TRAIN_CACHE", "true").strip().lower() in ("1", "true", "yes", "on"),
        "patience": int(os.getenv("SCORE_TRAIN_PATIENCE", "8")),
        "plots": os.getenv("SCORE_TRAIN_PLOTS", "false").strip().lower() in ("1", "true", "yes", "on"),
        "verbose": os.getenv("SCORE_TRAIN_VERBOSE", "true").strip().lower() in ("1", "true", "yes", "on"),
    }
    model.train(**train_args)

    best = getattr(model.trainer, "best", None)
    if not best or not os.path.exists(best):
        print(f"Training finished but best.pt not found at {best}.")
        sys.exit(1)

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(best, dest)
    print(f"\nBest weights: {best}")
    print(f"Copied to   : {dest}")
    print("Test: python main.py --image dataset/raw_frames/your_frame.png")


if __name__ == "__main__":
    main()
