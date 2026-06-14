#!/usr/bin/env python3
"""Create photometric augmentations for selected YOLO ROI images.

This is useful when a few card classes have very few real examples. It keeps
YOLO boxes unchanged and only changes color/contrast/sharpness/noise.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


def _augment_image(image: Image.Image, rng: random.Random) -> Image.Image:
    out = image.convert("RGB")

    out = ImageEnhance.Brightness(out).enhance(rng.uniform(0.72, 1.25))
    out = ImageEnhance.Contrast(out).enhance(rng.uniform(0.75, 1.35))
    out = ImageEnhance.Color(out).enhance(rng.uniform(0.75, 1.25))
    out = ImageEnhance.Sharpness(out).enhance(rng.uniform(0.65, 1.45))

    if rng.random() < 0.35:
        out = out.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.15, 0.65)))

    arr = np.asarray(out).astype(np.int16)
    if rng.random() < 0.65:
        noise = rng.normalvariate(0, 1)
        sigma = rng.uniform(2.0, 7.0) + abs(noise)
        noise_arr = np.random.default_rng(rng.randrange(1 << 30)).normal(
            0, sigma, arr.shape
        )
        arr += noise_arr.astype(np.int16)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path, help="YOLO dataset root with images/labels")
    parser.add_argument("--sources", nargs="+", required=True, help="Base image stems to augment")
    parser.add_argument("--count", type=int, default=48, help="Augmentations per source")
    parser.add_argument("--seed", type=int, default=20260614)
    parser.add_argument("--prefix", default="rare")
    args = parser.parse_args()

    image_dir = args.dataset / "images"
    label_dir = args.dataset / "labels"
    rng = random.Random(args.seed)
    created = 0

    for stem in args.sources:
        image_path = image_dir / f"{stem}.png"
        label_path = label_dir / f"{stem}.txt"
        if not image_path.exists():
            raise FileNotFoundError(image_path)
        if not label_path.exists():
            raise FileNotFoundError(label_path)

        image = Image.open(image_path)
        labels = label_path.read_text()
        for idx in range(args.count):
            out_stem = f"{args.prefix}_{stem}_{idx:03d}"
            out_image = image_dir / f"{out_stem}.png"
            out_label = label_dir / f"{out_stem}.txt"
            _augment_image(image, rng).save(out_image)
            out_label.write_text(labels)
            created += 1

    print(f"created_images: {created}")
    print(f"created_labels: {created}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
