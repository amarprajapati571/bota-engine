"""
Offline dataset augmentation with Albumentations (optional).

YOLO already augments online during training, so this is only worth running when
you have a *small* hand-labeled set and want more variety baked in. It reads
YOLO-format pairs from dataset/labeled/{images,labels} and writes `--per-image`
augmented copies (bounding boxes transformed too) to dataset/augmented/.

    pip install -r requirements-train.txt
    python model/augment.py --per-image 5
"""
import argparse
import glob
import os

import cv2

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_IMG = os.path.join(PROJECT_ROOT, "dataset", "labeled", "images")
SRC_LBL = os.path.join(PROJECT_ROOT, "dataset", "labeled", "labels")
OUT_IMG = os.path.join(PROJECT_ROOT, "dataset", "augmented", "images")
OUT_LBL = os.path.join(PROJECT_ROOT, "dataset", "augmented", "labels")


def _read_label(path: str):
    """Return (bboxes [[cx,cy,w,h], ...], class_ids [int, ...]) in YOLO format."""
    bboxes, classes = [], []
    if not os.path.exists(path):
        return bboxes, classes
    with open(path) as fh:
        for line in fh:
            parts = line.split()
            if len(parts) == 5:
                classes.append(int(parts[0]))
                bboxes.append([float(p) for p in parts[1:]])
    return bboxes, classes


def _write_label(path: str, bboxes, classes) -> None:
    with open(path, "w") as fh:
        for cls, (cx, cy, w, h) in zip(classes, bboxes):
            fh.write(f"{cls} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n")


def build_transform():
    import albumentations as A

    return A.Compose(
        [
            A.RandomBrightnessContrast(p=0.6),
            A.HueSaturationValue(p=0.4),
            A.MotionBlur(blur_limit=5, p=0.3),
            A.ImageCompression(quality_lower=55, quality_upper=95, p=0.4),
            A.Rotate(limit=10, border_mode=cv2.BORDER_CONSTANT, p=0.5),
            A.RandomScale(scale_limit=0.1, p=0.4),
        ],
        bbox_params=A.BboxParams(format="yolo", label_fields=["class_ids"],
                                 min_visibility=0.3),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline YOLO dataset augmentation")
    parser.add_argument("--per-image", type=int, default=5,
                        help="augmented copies to generate per source image")
    args = parser.parse_args()

    try:
        transform = build_transform()
    except ImportError:
        print("ERROR: albumentations not installed. Run: pip install -r requirements-train.txt")
        raise SystemExit(1)

    os.makedirs(OUT_IMG, exist_ok=True)
    os.makedirs(OUT_LBL, exist_ok=True)

    images = sorted(glob.glob(os.path.join(SRC_IMG, "*")))
    if not images:
        print(f"No images in {SRC_IMG}. Put labeled frames there first.")
        return

    written = 0
    for img_path in images:
        stem = os.path.splitext(os.path.basename(img_path))[0]
        image = cv2.imread(img_path)
        if image is None:
            continue
        bboxes, classes = _read_label(os.path.join(SRC_LBL, stem + ".txt"))

        for i in range(args.per_image):
            out = transform(image=image, bboxes=bboxes, class_ids=classes)
            if not out["bboxes"]:
                continue  # transform pushed every box out of frame; skip
            name = f"{stem}_aug{i}"
            cv2.imwrite(os.path.join(OUT_IMG, name + ".jpg"), out["image"])
            _write_label(os.path.join(OUT_LBL, name + ".txt"), out["bboxes"], out["class_ids"])
            written += 1

    print(f"Wrote {written} augmented images to {OUT_IMG}")


if __name__ == "__main__":
    main()
