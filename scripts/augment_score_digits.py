"""
Balance score digit classification crops with lightweight augmentation.

Input:
  dataset/score_digits/labeled/0/*.png ... labeled/9/*.png

Output:
  dataset/score_digits/augmented_labeled/0/*.png ... augmented_labeled/9/*.png

The originals are copied first, then low-count classes are augmented up to the
target count. This keeps manual labels untouched.
"""
from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = PROJECT_ROOT / "dataset" / "score_digits" / "labeled"
DEFAULT_OUT = PROJECT_ROOT / "dataset" / "score_digits" / "augmented_labeled"


def _image_paths(folder: Path) -> list[Path]:
    paths: list[Path] = []
    for pattern in ("*.png", "*.jpg", "*.jpeg"):
        paths.extend(folder.glob(pattern))
    return sorted(paths)


def _shift_canvas(image: Image.Image, rng: random.Random) -> Image.Image:
    width, height = image.size
    dx = rng.randint(-4, 4)
    dy = rng.randint(-4, 4)
    shifted = Image.new("RGB", image.size, tuple(int(v) for v in ImageStat_mean(image)))
    shifted.paste(image, (dx, dy))
    return shifted.crop((0, 0, width, height))


def ImageStat_mean(image: Image.Image) -> tuple[float, float, float]:
    arr = np.asarray(image.convert("RGB"), dtype=np.float32)
    return tuple(arr.reshape(-1, 3).mean(axis=0).tolist())


def _augment(image: Image.Image, rng: random.Random) -> Image.Image:
    out = image.convert("RGB")

    if rng.random() < 0.75:
        out = ImageEnhance.Brightness(out).enhance(rng.uniform(0.70, 1.35))
    if rng.random() < 0.75:
        out = ImageEnhance.Contrast(out).enhance(rng.uniform(0.75, 1.45))
    if rng.random() < 0.60:
        out = ImageEnhance.Color(out).enhance(rng.uniform(0.75, 1.25))
    if rng.random() < 0.55:
        out = ImageEnhance.Sharpness(out).enhance(rng.uniform(0.65, 1.55))
    if rng.random() < 0.45:
        out = _shift_canvas(out, rng)
    if rng.random() < 0.35:
        fill = tuple(int(v) for v in ImageStat_mean(out))
        out = out.rotate(rng.uniform(-4.0, 4.0), resample=Image.Resampling.BICUBIC, fillcolor=fill)
    if rng.random() < 0.30:
        out = out.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.15, 0.55)))

    arr = np.asarray(out).astype(np.int16)
    if rng.random() < 0.55:
        noise = np.random.default_rng(rng.randrange(1 << 30)).normal(0, rng.uniform(1.5, 6.0), arr.shape)
        arr += noise.astype(np.int16)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def _prepare_out(src: Path, out: Path) -> dict[str, int]:
    if out.exists():
        shutil.rmtree(out)
    counts: dict[str, int] = {}
    for digit in map(str, range(10)):
        src_dir = src / digit
        out_dir = out / digit
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = _image_paths(src_dir) if src_dir.exists() else []
        counts[digit] = len(paths)
        for path in paths:
            shutil.copy2(path, out_dir / path.name)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Augment and balance score digit crops")
    parser.add_argument("--src", default=str(DEFAULT_SRC), help="manual labeled digit root")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="augmented labeled output root")
    parser.add_argument("--target", type=int, default=50, help="minimum images per digit")
    parser.add_argument("--seed", type=int, default=20260614)
    args = parser.parse_args()

    src = Path(args.src).expanduser()
    out = Path(args.out).expanduser()
    rng = random.Random(args.seed)

    counts = _prepare_out(src, out)
    created = 0
    for digit in map(str, range(10)):
        source_paths = _image_paths(src / digit)
        if not source_paths:
            print(f"[warn] no source images for digit {digit}")
            continue

        out_dir = out / digit
        needed = max(0, args.target - counts[digit])
        for idx in range(needed):
            source = rng.choice(source_paths)
            image = Image.open(source)
            aug = _augment(image, rng)
            aug.save(out_dir / f"aug_{digit}_{idx:04d}_{source.stem}.png")
            created += 1

    final_counts = {
        digit: len(_image_paths(out / digit))
        for digit in map(str, range(10))
    }
    print(f"created_augmented: {created}")
    print("final_counts:", final_counts)
    print(f"output: {out}")
    print(f"Next: python scripts/build_score_classifier_dataset.py --src {out}")


if __name__ == "__main__":
    main()
