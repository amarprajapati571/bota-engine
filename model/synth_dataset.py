"""
Synthetic dataset generator.

Composites individual card images onto backgrounds at random positions, scales,
and small rotations, writing YOLO labels automatically — so ~52 card images
become thousands of labeled training images with zero manual labeling. This works
especially well when the game's cards are clean, consistent graphics (yours are).

Inputs:
  dataset/cards/<rank>_<suit>.png     one image per card; transparent corners
                                      ideal (e.g. K_diamonds.png, 9_clubs.png).
  dataset/backgrounds/*.{png,jpg}     optional; falls back to dark UI-like canvases.

Output:
  dataset/synth/{train,val}/{images,labels}/
  dataset/synth/data.yaml             <- point training at this

Run:
  python model/synth_dataset.py --count 2000
  DATA_YAML=./dataset/synth/data.yaml python model/train.py

Get the card images either by cropping them from your own game frames (most
accurate — use scripts/extract_frames.py --crop) or by rendering a standard SVG
deck to PNG. Filenames must match the <rank>_<suit> classes below.
"""
import argparse
import glob
import os
import random

import cv2
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARDS_DIR = os.path.join(PROJECT_ROOT, "dataset", "cards")
BG_DIR = os.path.join(PROJECT_ROOT, "dataset", "backgrounds")
OUT_DIR = os.path.join(PROJECT_ROOT, "dataset", "synth")

SUITS = ["clubs", "diamonds", "hearts", "spades"]
RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
CLASSES = [f"{r}_{s}" for s in SUITS for r in RANKS]   # 52, same order as cards.yaml


def _load_cards() -> dict:
    """class_name -> RGBA image. Adds a full-opaque alpha channel if missing."""
    cards = {}
    for name in CLASSES:
        path = os.path.join(CARDS_DIR, name + ".png")
        if not os.path.exists(path):
            continue
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            continue
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
        elif img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        cards[name] = img
    return cards


def _rotate_rgba(img: np.ndarray, angle: float) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(img, m, (nw, nh), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))


def _paste(bg: np.ndarray, fg: np.ndarray, x: int, y: int):
    """Alpha-composite fg (RGBA) onto bg (BGR) at top-left (x, y). Returns bbox or None."""
    fh, fw = fg.shape[:2]
    bh, bw = bg.shape[:2]
    x1, y1, x2, y2 = max(0, x), max(0, y), min(bw, x + fw), min(bh, y + fh)
    if x2 <= x1 or y2 <= y1:
        return None
    crop = fg[y1 - y:y2 - y, x1 - x:x2 - x]
    alpha = crop[:, :, 3:4].astype(float) / 255.0
    bg[y1:y2, x1:x2] = (alpha * crop[:, :, :3] + (1 - alpha) * bg[y1:y2, x1:x2]).astype(np.uint8)
    ys, xs = np.where(crop[:, :, 3] > 16)
    if len(xs) == 0:
        return None
    return x1 + int(xs.min()), y1 + int(ys.min()), x1 + int(xs.max()), y1 + int(ys.max())


def _background(size: int, bg_paths: list) -> np.ndarray:
    if bg_paths:
        img = cv2.imread(random.choice(bg_paths))
        if img is not None:
            return cv2.resize(img, (size, size))
    # Dark UI-like canvas with mild noise (mimics the game's bottom strip).
    base = random.randint(10, 45)
    canvas = np.full((size, size, 3), base, np.uint8)
    noise = np.random.randint(0, 18, (size, size, 3), np.uint8)
    return cv2.add(canvas, noise)


def _compose(cards: dict, bg_paths: list, size: int, max_cards: int):
    bg = _background(size, bg_paths)
    labels = []
    for _ in range(random.randint(1, max_cards)):
        name = random.choice(list(cards.keys()))
        card = cards[name]
        target_h = random.randint(int(size * 0.28), int(size * 0.55))
        scale = target_h / card.shape[0]
        resized = cv2.resize(card, (max(1, int(card.shape[1] * scale)), target_h))
        rotated = _rotate_rgba(resized, random.uniform(-12, 12))
        x = random.randint(-rotated.shape[1] // 5, size - rotated.shape[1] * 4 // 5)
        y = random.randint(-rotated.shape[0] // 5, size - rotated.shape[0] * 4 // 5)
        box = _paste(bg, rotated, x, y)
        if box is None:
            continue
        bx1, by1, bx2, by2 = box
        cx, cy = (bx1 + bx2) / 2 / size, (by1 + by2) / 2 / size
        bw, bh = (bx2 - bx1) / size, (by2 - by1) / size
        if bw > 0.02 and bh > 0.02:
            labels.append((CLASSES.index(name), cx, cy, bw, bh))
    return bg, labels


def _write_data_yaml() -> str:
    path = os.path.join(OUT_DIR, "data.yaml")
    with open(path, "w") as fh:
        fh.write(f"path: {OUT_DIR}\ntrain: train/images\nval: val/images\nnames:\n")
        for i, name in enumerate(CLASSES):
            fh.write(f"  {i}: {name}\n")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a synthetic YOLO card dataset")
    ap.add_argument("--count", type=int, default=2000, help="total images to generate")
    ap.add_argument("--imgsz", type=int, default=640, help="output image size")
    ap.add_argument("--max-cards", type=int, default=4, help="max cards per image")
    ap.add_argument("--val-split", type=float, default=0.15, help="fraction held out for val")
    args = ap.parse_args()

    cards = _load_cards()
    if not cards:
        print(f"No card images found in {CARDS_DIR}. Put <rank>_<suit>.png files there "
              "(crop them from your game with scripts/extract_frames.py --crop, or render an SVG deck).")
        raise SystemExit(1)
    print(f"Loaded {len(cards)}/52 card images")

    bg_paths = []
    for ext in ("*.png", "*.jpg", "*.jpeg"):
        bg_paths += glob.glob(os.path.join(BG_DIR, ext))
    print(f"Backgrounds: {len(bg_paths) or 'none (using dark canvases)'}")

    for split in ("train", "val"):
        os.makedirs(os.path.join(OUT_DIR, split, "images"), exist_ok=True)
        os.makedirs(os.path.join(OUT_DIR, split, "labels"), exist_ok=True)

    n_val = int(args.count * args.val_split)
    for i in range(args.count):
        split = "val" if i < n_val else "train"
        img, labels = _compose(cards, bg_paths, args.imgsz, args.max_cards)
        stem = f"synth_{i:06d}"
        cv2.imwrite(os.path.join(OUT_DIR, split, "images", stem + ".jpg"), img)
        with open(os.path.join(OUT_DIR, split, "labels", stem + ".txt"), "w") as fh:
            for cls, cx, cy, bw, bh in labels:
                fh.write(f"{cls} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{args.count}")

    data_yaml = _write_data_yaml()
    print(f"\nDone — {args.count} images in {OUT_DIR}")
    print(f"data.yaml: {data_yaml}")
    print(f"Train:  DATA_YAML={data_yaml} python model/train.py")


if __name__ == "__main__":
    main()
