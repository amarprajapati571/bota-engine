"""
Download a YOLOv8 playing-card dataset from Roboflow.

You need a free Roboflow account + API key (https://app.roboflow.com →
Settings → API). Then pick a dataset on https://universe.roboflow.com
(search "playing cards", choose one with a YOLOv8 export) and copy its
workspace / project / version from the "Download Dataset → YOLOv8" code snippet.

Put these in .env (see .env.example):

    ROBOFLOW_API_KEY=...
    ROBOFLOW_WORKSPACE=...
    ROBOFLOW_PROJECT=...
    ROBOFLOW_VERSION=1

Then run:  python model/download_dataset.py

The dataset (with its own data.yaml) lands in ./dataset/, which is what
model/train.py looks for by default.
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(PROJECT_ROOT, "dataset")


def main() -> None:
    api_key = os.getenv("ROBOFLOW_API_KEY")
    workspace = os.getenv("ROBOFLOW_WORKSPACE")
    project = os.getenv("ROBOFLOW_PROJECT")
    version = os.getenv("ROBOFLOW_VERSION")

    missing = [
        n for n, v in {
            "ROBOFLOW_API_KEY": api_key,
            "ROBOFLOW_WORKSPACE": workspace,
            "ROBOFLOW_PROJECT": project,
            "ROBOFLOW_VERSION": version,
        }.items() if not v
    ]
    if missing:
        print("ERROR: missing in .env -> " + ", ".join(missing))
        print("Copy workspace/project/version from the dataset's "
              "'Download Dataset -> YOLOv8' snippet on roboflow.com.")
        sys.exit(1)

    try:
        from roboflow import Roboflow
    except ImportError:
        print("ERROR: roboflow not installed. Run: pip install -r requirements-train.txt")
        sys.exit(1)

    os.makedirs(DEST, exist_ok=True)
    rf = Roboflow(api_key=api_key)
    proj = rf.workspace(workspace).project(project)
    dataset = proj.version(int(version)).download("yolov8", location=DEST)

    data_yaml = os.path.join(dataset.location, "data.yaml")
    print(f"\nDataset downloaded to : {dataset.location}")
    print(f"data.yaml             : {data_yaml}")
    print("\nNote: the model's class names come from this data.yaml. The baccarat "
          "engine's rank parser handles 'AS' / '10C' / 'A_spades' styles, so most "
          "card datasets work as-is.")
    print("Next: python model/train.py")


if __name__ == "__main__":
    main()
