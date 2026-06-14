"""
Build a YOLO classification dataset from labeled score crops.

Expected input:
  dataset/score_digits/labeled/0/*.png
  dataset/score_digits/labeled/1/*.png
  ...
  dataset/score_digits/labeled/9/*.png

Output:
  dataset/score_digits/classify/train/<digit>/*.png
  dataset/score_digits/classify/val/<digit>/*.png
"""
import argparse
import random
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = PROJECT_ROOT / "dataset" / "score_digits" / "labeled"
DEFAULT_OUT = PROJECT_ROOT / "dataset" / "score_digits" / "classify"


def _images_for_digit(src: Path, digit: str) -> list[Path]:
    digit_dir = src / digit
    if not digit_dir.exists():
        return []
    paths: list[Path] = []
    for pattern in ("*.png", "*.jpg", "*.jpeg"):
        paths.extend(digit_dir.glob(pattern))
    return sorted(paths)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build score digit classification dataset")
    parser.add_argument("--src", default=str(DEFAULT_SRC), help="labeled score crop root")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="classification dataset root")
    parser.add_argument("--val-ratio", type=float, default=0.2, help="validation split ratio")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    src = Path(args.src).expanduser()
    out = Path(args.out).expanduser()
    rng = random.Random(args.seed)

    if not src.exists():
        raise SystemExit(f"Missing labeled score folder: {src}")

    if out.exists():
        shutil.rmtree(out)

    totals = {"train": 0, "val": 0}
    per_digit: dict[str, int] = {}
    for digit in map(str, range(10)):
        paths = _images_for_digit(src, digit)
        rng.shuffle(paths)
        if not paths:
            print(f"[warn] no samples for digit {digit}")
            continue

        n_val = max(1, int(round(len(paths) * args.val_ratio))) if len(paths) > 1 else 0
        val_paths = set(paths[:n_val])
        per_digit[digit] = len(paths)
        for path in paths:
            split = "val" if path in val_paths else "train"
            dest_dir = out / split / digit
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest_dir / path.name)
            totals[split] += 1

    print(f"Built score classifier dataset at {out}")
    print(f"Train: {totals['train']} | Val: {totals['val']}")
    print("Per digit:", per_digit)
    missing = [d for d in map(str, range(10)) if per_digit.get(d, 0) == 0]
    if missing:
        print(f"WARNING: missing digits: {', '.join(missing)}")
    print("Train: SCORE_DATA_DIR=./dataset/score_digits/classify python model/train_score_classifier.py")


if __name__ == "__main__":
    main()
