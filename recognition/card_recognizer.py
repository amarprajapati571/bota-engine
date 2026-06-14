"""
YOLOv8 card recognition.

Input : a full game frame (BGR) and a zone ("player" / "banker").
Output: detections sorted in visual order. Use cards_in_deal_order() when
baccarat rule order is needed, because the third card is often sideways.
"""
import os

import numpy as np
from loguru import logger
from ultralytics import YOLO

from capture.roi_config import BANKER_CARDS_ROI, PLAYER_CARDS_ROI, scale_roi_for_frame
from recognition.device import resolve_device

_model: YOLO | None = None


def _iou(a: list[float], b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union else 0.0


def _center_x(det: dict) -> float:
    x1, _, x2, _ = det["bbox"]
    return (x1 + x2) / 2


def _is_sideways(det: dict) -> bool:
    x1, y1, x2, y2 = det["bbox"]
    width = max(0, x2 - x1)
    height = max(0, y2 - y1)
    return width > height * 1.15


def _sort_deal_order(detections: list[dict]) -> list[dict]:
    vertical = sorted((d for d in detections if not _is_sideways(d)), key=lambda d: d["bbox"][0])
    sideways = sorted((d for d in detections if _is_sideways(d)), key=lambda d: d["bbox"][0])
    return vertical + sideways


def _sort_visual_order(detections: list[dict]) -> list[dict]:
    return sorted(detections, key=lambda d: d["bbox"][0])


def cards_in_deal_order(detections: list[dict]) -> list[str]:
    """Return card labels in baccarat rule order, putting sideways third cards last."""
    return [det["card"] for det in _sort_deal_order(detections)]


def _enabled(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("true", "1", "yes", "on")


def _format_detections(detections: list[dict]) -> list[dict]:
    return [
        {
            "card": det["card"],
            "conf": det["confidence"],
            "cx": round(_center_x(det), 1),
            "sideways": _is_sideways(det),
            "corrected_from": det.get("corrected_from"),
            "bbox": [round(v, 1) for v in det["bbox"]],
        }
        for det in detections
    ]


def _debug_stage(zone: str, stage: str, detections: list[dict]) -> None:
    if _enabled("CARD_DEBUG_DETECTIONS"):
        logger.info(f"Card debug [{zone}] {stage}: {_format_detections(detections)}")


def _dedup_by_center(detections: list[dict], center_threshold: float) -> list[dict]:
    detections = sorted(detections, key=lambda d: d["confidence"], reverse=True)
    kept = []
    for det in detections:
        if all(abs(_center_x(det) - _center_x(k)) >= center_threshold for k in kept):
            kept.append(det)
    return kept


def _pick_best_by_slot(detections: list[dict], roi_width: int, slot_count: int = 3) -> list[dict]:
    slot_width = roi_width / slot_count
    best_by_slot: dict[int, dict] = {}
    for det in detections:
        slot = int(_center_x(det) / slot_width)
        slot = max(0, min(slot_count - 1, slot))
        current = best_by_slot.get(slot)
        if current is None or det["confidence"] > current["confidence"]:
            best_by_slot[slot] = det
    return [best_by_slot[slot] for slot in sorted(best_by_slot)]


def _pick_best_by_slot_votes(detections: list[dict], roi_width: int, slot_count: int = 3) -> list[dict]:
    slot_width = roi_width / slot_count
    by_slot_label: dict[tuple[int, str], list[dict]] = {}
    for det in detections:
        slot = int(_center_x(det) / slot_width)
        slot = max(0, min(slot_count - 1, slot))
        by_slot_label.setdefault((slot, det["card"]), []).append(det)

    winners: dict[int, dict] = {}
    for (slot, _card), group in by_slot_label.items():
        best_det = max(group, key=lambda d: d["confidence"])
        # Corner detectors often see both top and bottom indices of one card.
        # A repeated lower-confidence label in the same slot is stronger
        # evidence than a single slightly higher false positive.
        score = sum(d["confidence"] for d in group) + (len(group) - 1) * 0.15
        candidate = {**best_det, "slot_vote_score": round(score, 4), "slot_vote_count": len(group)}
        current = winners.get(slot)
        if current is None or candidate["slot_vote_score"] > current["slot_vote_score"]:
            winners[slot] = candidate

    return [winners[slot] for slot in sorted(winners)]


def _best_label_vote(detections: list[dict]) -> dict | None:
    if not detections:
        return None

    by_label: dict[str, list[dict]] = {}
    for det in detections:
        by_label.setdefault(det["card"], []).append(det)

    best: dict | None = None
    best_score = -1.0
    for group in by_label.values():
        strongest = max(group, key=lambda d: d["confidence"])
        # Multiple corner hits on a sideways card are stronger than one
        # isolated high-confidence false label in the same physical area.
        score = sum(d["confidence"] for d in group) + (len(group) - 1) * 0.12
        if score > best_score:
            best = {**strongest, "label_vote_score": round(score, 4), "label_vote_count": len(group)}
            best_score = score
    return best


def _pick_upright_by_zones(
    detections: list[dict],
    zone_width: float,
    max_cards: int = 2,
    zone_start: float = 0.0,
) -> list[dict]:
    if not detections:
        return []

    slot_width = zone_width / max_cards
    by_slot: dict[int, list[dict]] = {}
    for det in detections:
        slot = int((_center_x(det) - zone_start) / slot_width)
        slot = max(0, min(max_cards - 1, slot))
        by_slot.setdefault(slot, []).append(det)

    picked: list[dict] = []
    for slot in range(max_cards):
        voted = _best_label_vote(by_slot.get(slot, []))
        if voted is not None:
            picked.append(voted)

    if len(picked) >= max_cards:
        return picked[:max_cards]

    for det in sorted(detections, key=lambda d: d["confidence"], reverse=True):
        if len(picked) >= max_cards:
            break
        if all(_iou(det["bbox"], p["bbox"]) < 0.25 and abs(_center_x(det) - _center_x(p)) >= 25 for p in picked):
            picked.append(det)
    return _sort_visual_order(picked[:max_cards])


def _pick_by_fixed_table_zones(
    detections: list[dict],
    roi_width: int,
    zone: str,
    max_cards: int = 3,
) -> list[dict]:
    if not detections:
        return []

    if zone == "player":
        third_end = roi_width * float(os.getenv("CARD_PLAYER_THIRD_ZONE_END", "0.38"))
        upright = [det for det in detections if _center_x(det) > third_end]
        third_candidates = [det for det in detections if _center_x(det) <= third_end]
        picked = _pick_upright_by_zones(upright, roi_width - third_end, 2, third_end)
        third = _best_label_vote(third_candidates)
        if third is not None:
            picked.append(third)
        return _sort_visual_order(picked[:max_cards])

    if zone == "banker":
        third_start = roi_width * float(os.getenv("CARD_BANKER_THIRD_ZONE_START", "0.55"))
        upright = [det for det in detections if _center_x(det) < third_start]
        third_candidates = [det for det in detections if _center_x(det) >= third_start]
        picked = _pick_upright_by_zones(upright, third_start, 2)
        third = _best_label_vote(third_candidates)
        if third is not None:
            picked.append(third)
        return _sort_visual_order(picked[:max_cards])

    return []


def _pick_top_physical_cards(detections: list[dict], max_cards: int = 3) -> list[dict]:
    """Keep the strongest physical-card detections after local duplicate cleanup."""
    return _sort_visual_order(sorted(detections, key=lambda d: d["confidence"], reverse=True)[:max_cards])


def _pick_by_baccarat_layout(
    detections: list[dict],
    roi_width: int,
    roi_height: int,
    zone: str,
    max_cards: int = 3,
) -> list[dict]:
    """Pick card-index detections using the fixed baccarat table layout.

    The detector mostly sees corner indices, not full cards. In this UI the
    useful detections for upright cards are the top indices; bottom indices can
    be lower-confidence duplicates or even wrong suits/ranks. The third card is
    sideways: player side usually appears on the left, banker side on the right.
    """
    if not detections:
        return []

    if _enabled("CARD_FIXED_ZONE_PICK", "true"):
        fixed_zone = _pick_by_fixed_table_zones(detections, roi_width, zone, max_cards)
        if len(fixed_zone) >= 2:
            return fixed_zone

    top_edge_ratio = float(os.getenv("CARD_TOP_EDGE_RATIO", "0.45"))
    min_sideways_conf = float(os.getenv("CARD_SIDEWAYS_MIN_CONF", "0.18"))
    top_limit = roi_height * top_edge_ratio

    upright_top = [
        det
        for det in detections
        if not _is_sideways(det) and det["bbox"][1] <= top_limit
    ]

    chosen: list[dict] = sorted(upright_top, key=lambda d: d["bbox"][0])

    min_upright_cards = int(os.getenv("CARD_MIN_UPRIGHT_CARDS", "2"))
    upright_center_gap = float(os.getenv("CARD_UPRIGHT_MIN_CENTER_GAP", "25"))
    if len(chosen) < min_upright_cards:
        chosen_keys = {(det["card"], round(_center_x(det), 1)) for det in chosen}
        upright_fallback = sorted(
            (
                det
                for det in detections
                if not _is_sideways(det)
                and (det["card"], round(_center_x(det), 1)) not in chosen_keys
            ),
            key=lambda d: d["confidence"],
            reverse=True,
        )
        for det in upright_fallback:
            if len(chosen) >= min_upright_cards:
                break
            if all(abs(_center_x(det) - _center_x(existing)) >= upright_center_gap for existing in chosen):
                chosen.append(det)

    sideways = [det for det in detections if _is_sideways(det) and det["confidence"] >= min_sideways_conf]
    if sideways and len(chosen) < max_cards:
        if zone == "player":
            third = min(sideways, key=lambda d: d["bbox"][0])
        elif zone == "banker":
            third = max(sideways, key=lambda d: d["bbox"][0])
        else:
            third = max(sideways, key=lambda d: d["confidence"])
        if all(_iou(third["bbox"], det["bbox"]) < 0.30 for det in chosen):
            chosen.append(third)

    if len(chosen) >= 2:
        return _sort_visual_order(chosen[:max_cards])

    return _pick_top_physical_cards(detections, max_cards)


def _remove_duplicate_card_labels(detections: list[dict]) -> list[dict]:
    best_by_card: dict[str, dict] = {}
    for det in detections:
        current = best_by_card.get(det["card"])
        if current is None or det["confidence"] > current["confidence"]:
            best_by_card[det["card"]] = det
    return list(best_by_card.values())


def _merge_nearby_same_label_detections(detections: list[dict]) -> list[dict]:
    """Merge duplicate corner hits from the same physical card.

    Multi-deck baccarat can show the same card label more than once, so this is
    intentionally local: only same-label detections with nearby x centers are
    merged. Distant same-label cards remain valid separate physical cards.
    """
    threshold = float(os.getenv("SAME_LABEL_DUP_CENTER_X_PX", "55"))
    detections = sorted(detections, key=lambda d: d["confidence"], reverse=True)
    kept: list[dict] = []
    for det in detections:
        if all(det["card"] != k["card"] or abs(_center_x(det) - _center_x(k)) >= threshold for k in kept):
            kept.append(det)
    return _sort_visual_order(kept)


def _fix_known_sideways_confusions(detections: list[dict]) -> list[dict]:
    if not _enabled("FIX_SIDEWAYS_5D_AS_9D", "false"):
        return detections

    fixed = []
    for det in detections:
        if det["card"] in ("5_diamonds", "5D") and _is_sideways(det):
            det = {**det, "card": "9D" if det["card"] == "5D" else "9_diamonds", "corrected_from": det["card"]}
        elif det["card"] in ("3_diamonds", "3D") and _is_sideways(det):
            det = {**det, "card": "6D" if det["card"] == "3D" else "6_diamonds", "corrected_from": det["card"]}
        fixed.append(det)
    return fixed


def _dedup_cards(
    detections: list[dict],
    roi_width: int,
    roi_height: int,
    zone: str = "unknown",
    iou_threshold: float = 0.45,
) -> list[dict]:
    _debug_stage(zone, "raw", detections)
    detections = sorted(detections, key=lambda d: d["confidence"], reverse=True)
    kept = []
    for det in detections:
        if all(_iou(det["bbox"], k["bbox"]) < iou_threshold for k in kept):
            kept.append(det)
    _debug_stage(zone, "after_iou", kept)

    kept = _merge_nearby_same_label_detections(kept)
    _debug_stage(zone, "after_same_label_nearby", kept)

    if _enabled("CARD_SLOT_VOTE_DEDUP", "false"):
        kept = _pick_best_by_slot_votes(kept, roi_width)
        _debug_stage(zone, "after_slot_vote", kept)
    elif _enabled("CARD_CENTER_DEDUP", "false"):
        center_threshold = float(os.getenv("CENTER_X_DUP_PX", os.getenv("CARD_SLOT_CENTER_THRESHOLD", 55)))
        kept = _dedup_by_center(kept, center_threshold)
        _debug_stage(zone, "after_center", kept)

        kept = _pick_best_by_slot(kept, roi_width)
        _debug_stage(zone, "after_slot", kept)
    elif _enabled("CARD_LAYOUT_AWARE_PICK", "true"):
        kept = _pick_by_baccarat_layout(kept, roi_width, roi_height, zone)
        _debug_stage(zone, "after_layout_pick", kept)
    else:
        kept = _pick_top_physical_cards(kept)
        _debug_stage(zone, "after_top_physical", kept)

    if not _enabled("ALLOW_SAME_CARD_DUPLICATES", "true"):
        kept = _remove_duplicate_card_labels(kept)
        _debug_stage(zone, "after_label", kept)

    kept = _fix_known_sideways_confusions(kept)
    _debug_stage(zone, "after_known_fixes", kept)
    _debug_stage(zone, "deal_order", _sort_deal_order(kept))
    kept = _sort_visual_order(kept)
    _debug_stage(zone, "visual_order", kept)
    return kept[:3]


def get_model() -> YOLO:
    global _model
    if _model is not None:
        return _model

    weights = os.getenv("MODEL_WEIGHTS_PATH", "./models/weights/best.pt")
    if not os.path.exists(weights):
        raise FileNotFoundError(
            f"Model weights not found at '{weights}'.\n"
            "Train a card detector (see README -> 'Getting a model') and point "
            "MODEL_WEIGHTS_PATH at the resulting best.pt, or run `python main.py "
            "--demo` to exercise the game-logic pipeline without a model."
        )

    _model = YOLO(weights)
    logger.info(f"YOLOv8 model loaded: {weights} | classes={len(_model.names)}")
    return _model


def recognize_cards_in_roi(
    frame: np.ndarray,
    roi: tuple[int, int, int, int],
    zone: str = "custom",
) -> list[dict]:
    """Detect and classify cards in an explicit ROI."""
    model = get_model()
    x1, y1, x2, y2 = roi
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        logger.warning(f"Empty crop for zone '{zone}' — check ROI calibration.")
        return []

    conf_threshold = float(os.getenv("MODEL_CONFIDENCE", 0.75))
    results = model.predict(
        source=crop,
        conf=conf_threshold,
        device=resolve_device(),
        verbose=False,
        imgsz=640,
        iou=0.5,
        augment=False,
        max_det=6,
    )

    detected: list[dict] = []
    for r in results:
        for box in r.boxes:
            detected.append({
                "card": model.names[int(box.cls[0])],
                "class_id": int(box.cls[0]),
                "confidence": round(float(box.conf[0]), 4),
                "bbox": box.xyxy[0].tolist(),
            })

    detected = _dedup_cards(detected, crop.shape[1], crop.shape[0], zone)
    logger.debug(f"Zone '{zone}' detected: {[d['card'] for d in detected]}")
    return detected


def recognize_cards(frame: np.ndarray, zone: str) -> list[dict]:
    """Detect and classify cards in the configured player/banker ROI."""
    roi = PLAYER_CARDS_ROI if zone == "player" else BANKER_CARDS_ROI
    height, width = frame.shape[:2]
    roi = scale_roi_for_frame(roi, width, height)
    return recognize_cards_in_roi(frame, roi, zone)
