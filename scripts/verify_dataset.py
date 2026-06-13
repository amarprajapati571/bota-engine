"""
Verify raw frames and YOLO labeled dataset consistency.

Run:
  python scripts/verify_dataset.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "dataset" / "raw_frames"
LABELED_IMAGES = ROOT / "dataset" / "labeled" / "images"
LABELED_LABELS = ROOT / "dataset" / "labeled" / "labels"
YAML_PATH = ROOT / "model" / "cards_with_winner.yaml"


def _read_names() -> dict[int, str]:
    names: dict[int, str] = {}
    if not YAML_PATH.exists():
        return names
    in_names = False
    for raw in YAML_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line == "names:":
            in_names = True
            continue
        if in_names and ":" in line and line.split(":", 1)[0].strip().isdigit():
            key, value = line.split(":", 1)
            names[int(key)] = value.strip().strip("'\"")
    return names


def _stems(path: Path, suffix: str) -> set[str]:
    if not path.exists():
        return set()
    return {p.stem for p in path.glob(f"*{suffix}") if p.is_file()}


def main() -> None:
    names = _read_names()
    class_count = len(names) if names else None
    raw = _stems(RAW_DIR, ".png")
    images = _stems(LABELED_IMAGES, ".png")
    labels = _stems(LABELED_LABELS, ".txt")

    errors = []
    counts: dict[int, int] = {}
    boxes = 0
    for path in sorted(LABELED_LABELS.glob("*.txt")) if LABELED_LABELS.exists() else []:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            parts = line.split()
            if not parts:
                continue
            if len(parts) != 5:
                errors.append(f"{path.name}:{line_no} expected 5 columns")
                continue
            try:
                cls = int(float(parts[0]))
                coords = [float(v) for v in parts[1:]]
            except ValueError:
                errors.append(f"{path.name}:{line_no} non-numeric row")
                continue
            if class_count is not None and not 0 <= cls < class_count:
                errors.append(f"{path.name}:{line_no} invalid class {cls}")
            if any(v < 0 or v > 1 for v in coords):
                errors.append(f"{path.name}:{line_no} coordinate outside 0..1")
            counts[cls] = counts.get(cls, 0) + 1
            boxes += 1

    print("DATASET VERIFICATION")
    print("====================")
    print(f"raw frames          : {len(raw)}")
    print(f"labeled images      : {len(images)}")
    print(f"label files         : {len(labels)}")
    print(f"raw frames labeled  : {len(raw & labels)}")
    print(f"raw frames unlabeled: {len(raw - labels)}")
    print(f"total boxes         : {boxes}")
    print(f"classes in yaml     : {class_count if class_count is not None else 'unknown'}")
    print(f"classes with boxes  : {len(counts)}")
    print()
    print(f"images without labels: {len(images - labels)}")
    print(f"labels without images: {len(labels - images)}")
    print(f"errors: {len(errors)}")
    for err in errors[:50]:
        print(f"  {err}")

    if class_count is not None:
        missing = [cid for cid in range(class_count) if counts.get(cid, 0) == 0]
        print(f"missing classes: {len(missing)}")
        for cid in missing:
            print(f"  {cid}: {names.get(cid, cid)}")
    weak = [(cid, count) for cid, count in sorted(counts.items()) if count < 3]
    print(f"weak classes (<3 boxes): {len(weak)}")
    for cid, count in weak:
        print(f"  {cid}: {names.get(cid, cid)} = {count}")


if __name__ == "__main__":
    main()
