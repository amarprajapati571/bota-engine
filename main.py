"""
Baccarat CV core — entry point.

Modes:
  python main.py --demo            Run the game-logic + validation pipeline on
                                   sample cards. No model/screen/GPU needed —
                                   start here to confirm the install works.
  python main.py --calibrate       Save annotated screenshots to tune the ROIs.
  python main.py --image PATH      Run the full CV pipeline on a saved frame.
  python main.py --live            Watch the screen and recognize on each WIN badge.

Heavy deps (torch, ultralytics, easyocr) are imported lazily, so --demo and
--calibrate stay fast and don't require a trained model.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from monitoring.logger_config import setup_logging  # noqa: E402

logger = setup_logging()


def format_round(result: dict) -> str:
    """Human-readable one-block summary of a round result dict."""
    lines = [
        "──────────── ROUND ────────────",
        f"  id        : {result.get('round_id', '(demo)')}",
        f"  player    : {result['player_cards']}  = {result['player_value']}",
        f"  banker    : {result['banker_cards']}  = {result['banker_value']}",
        f"  outcome   : {result['outcome']}"
        + ("  (natural)" if result.get("is_natural") else ""),
    ]
    if "confidence_level" in result:
        lines += [
            f"  ocr P/B   : {result.get('ocr_player_score')} / {result.get('ocr_banker_score')}",
            f"  rules ok  : {result.get('rules_consistent')}",
            f"  validated : {result.get('validation_passed')}  ({result['confidence_level']})",
        ]
    elif "rules_consistent" in result:
        lines.append(f"  rules ok  : {result['rules_consistent']}")
    lines.append("────────────────────────────────")
    return "\n".join(lines)


def run_demo() -> None:
    """Exercise the pure pipeline on sample cards — no model or screen needed."""
    from game_logic.baccarat_engine import compute_result, is_rules_consistent

    samples = [
        (["8_hearts", "K_spades"], ["5_clubs", "2_diamonds"]),             # player natural 8 beats 7
        (["2_hearts", "3_spades", "9_diamonds"], ["6_clubs", "K_hearts"]),  # player draws to 4, banker 6 stands
        (["9_hearts", "K_spades"], ["7_clubs", "2_diamonds"]),             # tie, both natural 9
    ]
    logger.info("Running DEMO on sample hands (no model required)")
    for player, banker in samples:
        result = compute_result(player, banker)
        result["rules_consistent"] = is_rules_consistent(player, banker)
        print(format_round(result))


def run_calibrate() -> None:
    from capture.calibrate import capture_and_save

    capture_and_save()


def run_image(path: str) -> None:
    import cv2

    from pipeline.recognize import recognize_round

    if not os.path.exists(path):
        logger.error(f"Image not found: {path}")
        sys.exit(1)
    frame = cv2.imread(path)
    if frame is None:
        logger.error(f"Could not read image: {path}")
        sys.exit(1)

    result = recognize_round(frame)
    if result is None:
        logger.warning("No round recognized in image.")
        return
    print(format_round(result))
    print(json.dumps(result, indent=2))


def run_live() -> None:
    from capture.screen_agent import run_capture_loop
    from pipeline.recognize import recognize_round

    def on_trigger(frame):
        result = recognize_round(frame)
        if result is not None:
            print(format_round(result))

    logger.info("Live mode — press Ctrl-C to stop.")
    run_capture_loop(on_trigger_callback=on_trigger)


def main() -> None:
    parser = argparse.ArgumentParser(description="Baccarat CV core")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--demo", action="store_true", help="run pipeline on sample cards")
    group.add_argument("--calibrate", action="store_true", help="save ROI calibration images")
    group.add_argument("--image", metavar="PATH", help="recognize a saved frame")
    group.add_argument("--live", action="store_true", help="watch screen and recognize")
    args = parser.parse_args()

    if args.demo:
        run_demo()
    elif args.calibrate:
        run_calibrate()
    elif args.image:
        run_image(args.image)
    elif args.live:
        run_live()


if __name__ == "__main__":
    main()
