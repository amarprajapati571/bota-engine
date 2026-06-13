"""
Train a YOLOv8 card detector.

Reads settings from .env (see the TRAINING block in .env.example). Picks the
data config in this order:
  1. $DATA_YAML if set
  2. ./dataset/data.yaml         (what Roboflow's download produces)
  3. ./model/cards.yaml          (the self-labeling template)

After training, the best weights are copied to ./models/weights/best.pt, which
is exactly where the recognition pipeline expects them.
"""
import os
import shutil
import sys

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from recognition.device import resolve_device  # noqa: E402

WEIGHTS_DEST = os.path.join(PROJECT_ROOT, "models", "weights", "best.pt")


def find_data_yaml() -> str:
    candidates = [
        os.getenv("DATA_YAML"),
        os.path.join(PROJECT_ROOT, "dataset", "data.yaml"),
        os.path.join(PROJECT_ROOT, "model", "cards.yaml"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    print("ERROR: no dataset config found. Run model/download_dataset.py first, "
          "or set DATA_YAML in .env.")
    sys.exit(1)


def main() -> None:
    try:
        from ultralytics import YOLO
    except ImportError:
        print("ERROR: ultralytics not installed. Run: pip install -r requirements.txt")
        sys.exit(1)

    data = find_data_yaml()
    device = resolve_device()
    print(f"Training on {data} | device={device}")

    model = YOLO(os.getenv("BASE_MODEL", "yolov8n.pt"))
    train_args = {
        "data": data,
        "epochs": int(os.getenv("TRAIN_EPOCHS", 100)),
        "imgsz": int(os.getenv("TRAIN_IMGSZ", 640)),
        "batch": int(os.getenv("TRAIN_BATCH", 16)),
        "device": device,
        "project": os.path.join(PROJECT_ROOT, "runs"),
        "name": os.getenv("TRAIN_RUN_NAME", "cards"),
        "exist_ok": True,
        "workers": int(os.getenv("TRAIN_WORKERS", 8)),
        "cache": os.getenv("TRAIN_CACHE", "false").strip().lower() in ("1", "true", "yes", "on"),
        "patience": int(os.getenv("TRAIN_PATIENCE", 20)),
        "plots": os.getenv("TRAIN_PLOTS", "false").strip().lower() in ("1", "true", "yes", "on"),
        "verbose": os.getenv("TRAIN_VERBOSE", "true").strip().lower() in ("1", "true", "yes", "on"),
    }
    freeze = os.getenv("TRAIN_FREEZE")
    if freeze:
        train_args["freeze"] = int(freeze)

    model.train(**train_args)

    best = getattr(model.trainer, "best", None)
    if not best or not os.path.exists(best):
        print(f"Training finished but best.pt not found at {best}.")
        sys.exit(1)

    os.makedirs(os.path.dirname(WEIGHTS_DEST), exist_ok=True)
    shutil.copy(best, WEIGHTS_DEST)
    print(f"\nBest weights: {best}")
    print(f"Copied to   : {WEIGHTS_DEST}")
    print("Test it:  python main.py --image path/to/frame.png")


if __name__ == "__main__":
    main()
