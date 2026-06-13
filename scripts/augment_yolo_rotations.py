"""
Create rotated YOLO training samples and transform labels with the image.

This is useful for baccarat layouts where the third card is shown sideways.
The script rotates each image and its YOLO bounding boxes by 90/180/270 degrees.

Usage:
  python scripts/augment_yolo_rotations.py dataset/card_roi --angles 90 180 270
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2


def _read_labels(label_path: Path) -> list[tuple[int, float, float, float, float]]:
    labels: list[tuple[int, float, float, float, float]] = []
    if not label_path.exists():
        return labels

    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        cls, xc, yc, bw, bh = parts
        labels.append((int(cls), float(xc), float(yc), float(bw), float(bh)))
    return labels


def _corners_from_yolo(
    xc: float,
    yc: float,
    bw: float,
    bh: float,
    width: int,
    height: int,
) -> list[tuple[float, float]]:
    cx = xc * width
    cy = yc * height
    box_w = bw * width
    box_h = bh * height
    x1 = cx - box_w / 2
    y1 = cy - box_h / 2
    x2 = cx + box_w / 2
    y2 = cy + box_h / 2
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


def _rotate_point(x: float, y: float, width: int, height: int, angle: int) -> tuple[float, float]:
    if angle == 90:
        return height - y, x
    if angle == 180:
        return width - x, height - y
    if angle == 270:
        return y, width - x
    raise ValueError(f"Unsupported angle: {angle}")


def _rotate_label(
    label: tuple[int, float, float, float, float],
    width: int,
    height: int,
    angle: int,
) -> tuple[int, float, float, float, float]:
    cls, xc, yc, bw, bh = label
    corners = _corners_from_yolo(xc, yc, bw, bh, width, height)
    rotated = [_rotate_point(x, y, width, height, angle) for x, y in corners]
    xs = [p[0] for p in rotated]
    ys = [p[1] for p in rotated]

    out_w, out_h = (height, width) if angle in (90, 270) else (width, height)
    x1 = max(0.0, min(xs))
    y1 = max(0.0, min(ys))
    x2 = min(float(out_w), max(xs))
    y2 = min(float(out_h), max(ys))

    out_xc = ((x1 + x2) / 2) / out_w
    out_yc = ((y1 + y2) / 2) / out_h
    out_bw = (x2 - x1) / out_w
    out_bh = (y2 - y1) / out_h
    return cls, out_xc, out_yc, out_bw, out_bh


def _rotate_image(image, angle: int):
    if angle == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if angle == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if angle == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    raise ValueError(f"Unsupported angle: {angle}")


def _format_label(label: tuple[int, float, float, float, float]) -> str:
    cls, xc, yc, bw, bh = label
    return f"{cls} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}"


def augment_dataset(root: Path, angles: list[int], overwrite: bool = False) -> tuple[int, int]:
    image_dir = root / "images"
    label_dir = root / "labels"
    if not image_dir.exists() or not label_dir.exists():
        raise FileNotFoundError(f"Expected images/ and labels/ under {root}")

    created_images = 0
    created_boxes = 0
    source_images = sorted(
        p for p in image_dir.glob("*.png") if "_rot90" not in p.stem and "_rot180" not in p.stem and "_rot270" not in p.stem
    )

    for image_path in source_images:
        label_path = label_dir / f"{image_path.stem}.txt"
        labels = _read_labels(label_path)
        if not labels:
            continue

        image = cv2.imread(str(image_path))
        if image is None:
            print(f"[skip] unreadable: {image_path}")
            continue

        height, width = image.shape[:2]
        for angle in angles:
            out_stem = f"{image_path.stem}_rot{angle}"
            out_image = image_dir / f"{out_stem}.png"
            out_label = label_dir / f"{out_stem}.txt"
            if not overwrite and out_image.exists() and out_label.exists():
                continue

            rotated_image = _rotate_image(image, angle)
            rotated_labels = [_rotate_label(label, width, height, angle) for label in labels]

            cv2.imwrite(str(out_image), rotated_image)
            out_label.write_text("\n".join(_format_label(label) for label in rotated_labels) + "\n", encoding="utf-8")
            created_images += 1
            created_boxes += len(rotated_labels)

    cache_path = label_dir.with_suffix(".cache")
    if cache_path.exists():
        cache_path.unlink()

    return created_images, created_boxes


def main() -> None:
    parser = argparse.ArgumentParser(description="Add rotated YOLO image/label samples")
    parser.add_argument("dataset_root", nargs="?", default="dataset/card_roi", help="YOLO dataset root")
    parser.add_argument("--angles", nargs="+", type=int, default=[90, 180, 270], choices=[90, 180, 270])
    parser.add_argument("--overwrite", action="store_true", help="rewrite existing rotated samples")
    args = parser.parse_args()

    created_images, created_boxes = augment_dataset(Path(args.dataset_root), args.angles, args.overwrite)
    print(f"created_images: {created_images}")
    print(f"created_boxes : {created_boxes}")


if __name__ == "__main__":
    main()
