"""
Create a balanced augmented YOLO ROI dataset for card recognition.

Input:
  dataset/card_roi/images/*.png
  dataset/card_roi/labels/*.txt
  dataset/card_roi/data.yaml

Output:
  dataset/card_roi_balanced/images/*.png
  dataset/card_roi_balanced/labels/*.txt
  dataset/card_roi_balanced/data.yaml

The original dataset is copied first. Then classes below --target-boxes are
boosted by photometric augmentation of images that contain those classes. Boxes
do not move, so labels can be copied exactly.
"""
from __future__ import annotations

import argparse
import random
import re
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = PROJECT_ROOT / "dataset" / "card_roi"
DEFAULT_OUT = PROJECT_ROOT / "dataset" / "card_roi_balanced"


def _read_names(data_yaml: Path) -> dict[int, str]:
    names: dict[int, str] = {}
    for line in data_yaml.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*(\d+):\s*(\S+)", line)
        if match:
            names[int(match.group(1))] = match.group(2)
    if not names:
        raise ValueError(f"No class names found in {data_yaml}")
    return names


def _read_label_classes(label_path: Path) -> list[int]:
    classes: list[int] = []
    if not label_path.exists():
        return classes
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 5:
            classes.append(int(parts[0]))
    return classes


def _image_path_for_stem(image_dir: Path, stem: str) -> Path | None:
    for ext in (".png", ".jpg", ".jpeg"):
        path = image_dir / f"{stem}{ext}"
        if path.exists():
            return path
    return None


def _copy_dataset(src: Path, out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "labels").mkdir(parents=True, exist_ok=True)
    for path in (src / "images").iterdir():
        if path.is_file():
            shutil.copy2(path, out / "images" / path.name)
    for path in (src / "labels").glob("*.txt"):
        shutil.copy2(path, out / "labels" / path.name)

    data_yaml = src / "data.yaml"
    out_data = out / "data.yaml"
    text = data_yaml.read_text(encoding="utf-8")
    text = re.sub(r"^path:\s*.*$", f"path: {out}", text, flags=re.MULTILINE)
    out_data.write_text(text, encoding="utf-8")


def _augment_image(image: Image.Image, rng: random.Random) -> Image.Image:
    out = image.convert("RGB")
    out = ImageEnhance.Brightness(out).enhance(rng.uniform(0.70, 1.35))
    out = ImageEnhance.Contrast(out).enhance(rng.uniform(0.75, 1.40))
    out = ImageEnhance.Color(out).enhance(rng.uniform(0.75, 1.25))
    out = ImageEnhance.Sharpness(out).enhance(rng.uniform(0.65, 1.50))
    if rng.random() < 0.35:
        out = out.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.12, 0.55)))

    arr = np.asarray(out).astype(np.int16)
    if rng.random() < 0.60:
        noise = np.random.default_rng(rng.randrange(1 << 30)).normal(
            0, rng.uniform(2.0, 7.0), arr.shape
        )
        arr += noise.astype(np.int16)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def _index_dataset(root: Path, class_count: int) -> tuple[dict[int, int], dict[int, list[Path]]]:
    counts = {idx: 0 for idx in range(class_count)}
    images_by_class = {idx: [] for idx in range(class_count)}
    image_dir = root / "images"
    label_dir = root / "labels"

    for label_path in sorted(label_dir.glob("*.txt")):
        classes = _read_label_classes(label_path)
        image_path = _image_path_for_stem(image_dir, label_path.stem)
        if image_path is None or not classes:
            continue
        for class_id in classes:
            counts[class_id] = counts.get(class_id, 0) + 1
            images_by_class.setdefault(class_id, []).append(image_path)
    return counts, images_by_class


def main() -> None:
    parser = argparse.ArgumentParser(description="Balance card ROI YOLO dataset with augmentations")
    parser.add_argument("--src", default=str(DEFAULT_SRC), help="source YOLO ROI dataset")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output balanced dataset")
    parser.add_argument("--target-boxes", type=int, default=100, help="minimum boxes per class")
    parser.add_argument("--max-new-images", type=int, default=1200, help="safety cap for generated images")
    parser.add_argument("--seed", type=int, default=20260614)
    args = parser.parse_args()

    src = Path(args.src).expanduser()
    out = Path(args.out).expanduser()
    names = _read_names(src / "data.yaml")
    rng = random.Random(args.seed)

    _copy_dataset(src, out)
    counts, images_by_class = _index_dataset(out, len(names))
    created = 0

    for class_id, class_name in sorted(names.items(), key=lambda item: counts.get(item[0], 0)):
        while counts.get(class_id, 0) < args.target_boxes and created < args.max_new_images:
            candidates = images_by_class.get(class_id) or []
            if not candidates:
                print(f"[warn] no source images for class {class_id}:{class_name}")
                break

            source_image = rng.choice(candidates)
            source_label = out / "labels" / f"{source_image.stem}.txt"
            label_classes = _read_label_classes(source_label)
            out_stem = f"bal_{class_name}_{created:05d}_{source_image.stem}"
            out_image = out / "images" / f"{out_stem}{source_image.suffix}"
            out_label = out / "labels" / f"{out_stem}.txt"

            _augment_image(Image.open(source_image), rng).save(out_image)
            shutil.copy2(source_label, out_label)
            created += 1

            for label_class in label_classes:
                counts[label_class] = counts.get(label_class, 0) + 1
                images_by_class.setdefault(label_class, []).append(out_image)

    low = {
        names[idx]: count
        for idx, count in sorted(counts.items(), key=lambda item: item[1])
        if count < args.target_boxes
    }
    print(f"created_images: {created}")
    print(f"output: {out}")
    print("lowest_counts:")
    for idx, count in sorted(counts.items(), key=lambda item: item[1])[:15]:
        print(f"  {names[idx]}: {count}")
    if low:
        print(f"WARNING: still below target: {low}")
    print(f"Train: DATA_YAML={out / 'data.yaml'} python model/train.py")


if __name__ == "__main__":
    main()
