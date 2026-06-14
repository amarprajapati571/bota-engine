#!/usr/bin/env python3
"""Run the recognition pipeline over raw frames and write an audit report.

This is a faster batch version of:
  python main.py --image dataset/raw_frames/frame.png

It does not append to logs/results.jsonl. It writes one JSON object per image to
logs/frame_audit.jsonl and prints the frames that need review.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import cv2
from dotenv import load_dotenv
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from pipeline.recognize import recognize_round  # noqa: E402


def _card_summary(result: dict | None) -> dict:
    if result is None:
        return {
            "recognized": False,
            "validation_passed": False,
            "confidence_level": "NONE",
        }

    return {
        "recognized": True,
        "validation_passed": result.get("validation_passed"),
        "confidence_level": result.get("confidence_level"),
        "player_cards": result.get("player_cards"),
        "banker_cards": result.get("banker_cards"),
        "player_value": result.get("player_value"),
        "banker_value": result.get("banker_value"),
        "score_player": result.get("score_player"),
        "score_banker": result.get("score_banker"),
        "score_source": result.get("score_source"),
        "display_player_score": result.get("display_player_score"),
        "display_banker_score": result.get("display_banker_score"),
        "display_score_source_player": result.get("display_score_source_player"),
        "display_score_source_banker": result.get("display_score_source_banker"),
        "display_outcome": result.get("display_outcome"),
        "display_badge_agree": result.get("display_badge_agree"),
        "score_outcome": result.get("score_outcome"),
        "score_badge_agree": result.get("score_badge_agree"),
        "trusted_display_badge": result.get("trusted_display_badge"),
        "score_classifier_player_conf": result.get("score_classifier_player_conf"),
        "score_classifier_banker_conf": result.get("score_classifier_banker_conf"),
        "card_outcome": result.get("card_outcome"),
        "final_outcome": result.get("final_outcome"),
        "winner_badge_outcome": result.get("winner_badge_outcome"),
        "winner_badge_match": result.get("winner_badge_match"),
        "rules_consistent": result.get("rules_consistent"),
        "player_match": result.get("player_match"),
        "banker_match": result.get("banker_match"),
        "player_conf": result.get("player_conf"),
        "banker_conf": result.get("banker_conf"),
    }


def _needs_review(item: dict) -> bool:
    return (
        not item.get("recognized")
        or not item.get("validation_passed")
        or item.get("confidence_level") != "HIGH"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit recognition over raw frame images")
    parser.add_argument(
        "images",
        nargs="*",
        default=[],
        help="Images to audit. Defaults to dataset/raw_frames/*.png",
    )
    parser.add_argument("--limit", type=int, default=0, help="Only audit first N images")
    parser.add_argument("--out", default="logs/frame_audit.jsonl", help="JSONL output path")
    parser.add_argument("--quiet", action="store_true", help="Hide per-frame progress")
    args = parser.parse_args()

    # Keep batch output readable; the result itself is saved in JSONL.
    logger.remove()
    logger.add(sys.stderr, level=os.getenv("AUDIT_LOG_LEVEL", "ERROR"))

    image_paths = [Path(p) for p in args.images]
    if not image_paths:
        image_paths = sorted((PROJECT_ROOT / "dataset" / "raw_frames").glob("*.png"))
    if args.limit:
        image_paths = image_paths[: args.limit]

    out_path = PROJECT_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    totals = {
        "total": 0,
        "recognized": 0,
        "high": 0,
        "failed": 0,
        "unrecognized": 0,
    }
    review: list[dict] = []

    with out_path.open("w", encoding="utf-8") as fh:
        for idx, image_path in enumerate(image_paths, 1):
            frame = cv2.imread(str(image_path))
            if frame is None:
                item = {
                    "image": str(image_path.relative_to(PROJECT_ROOT)),
                    "recognized": False,
                    "error": "unreadable",
                    "validation_passed": False,
                    "confidence_level": "NONE",
                }
            else:
                result = recognize_round(frame)
                item = {
                    "image": str(image_path.relative_to(PROJECT_ROOT)),
                    **_card_summary(result),
                }

            totals["total"] += 1
            if item.get("recognized"):
                totals["recognized"] += 1
            else:
                totals["unrecognized"] += 1
            if item.get("validation_passed") and item.get("confidence_level") == "HIGH":
                totals["high"] += 1
            if _needs_review(item):
                totals["failed"] += 1
                review.append(item)

            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
            if not args.quiet and (idx == 1 or idx % 25 == 0 or idx == len(image_paths)):
                print(
                    f"[{idx}/{len(image_paths)}] high={totals['high']} "
                    f"review={totals['failed']} current={image_path.name}",
                    flush=True,
                )

    print("\nAudit complete")
    print(json.dumps(totals, indent=2))
    print(f"Report: {out_path}")
    if review:
        print("\nNeeds review (first 30):")
        for item in review[:30]:
            print(
                f"- {item['image']} | valid={item.get('validation_passed')} "
                f"conf={item.get('confidence_level')} cards={item.get('player_cards')} / "
                f"{item.get('banker_cards')} score={item.get('score_player')}/"
                f"{item.get('score_banker')} badge={item.get('winner_badge_outcome')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
