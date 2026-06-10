"""
Baccarat CV core — entry point.

Modes:
  python main.py --demo            Run the game-logic + validation pipeline on
                                   sample cards. No model/screen/GPU needed —
                                   start here to confirm the install works.
  python main.py --calibrate       Save annotated screenshots to tune the ROIs.
  python main.py --detect PATH     Run the model on a WHOLE image (no ROIs, no game
                                   logic) — the quickest way to test that a model
                                   detects cards at all. Use --weights / --conf.
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


def run_demo(send: bool = False) -> None:
    """
    Exercise the pure pipeline on sample cards — no model or screen needed.

    With send=True, also POST each sample round to your API — a model-free way to
    verify the send path end-to-end against your backend.
    """
    import uuid
    from datetime import datetime, timezone

    from game_logic.baccarat_engine import compute_result, is_rules_consistent

    samples = [
        (["8_hearts", "K_spades"], ["5_clubs", "2_diamonds"]),             # player natural 8 beats 7
        (["2_hearts", "3_spades", "9_diamonds"], ["6_clubs", "K_hearts"]),  # player draws to 4, banker 6 stands
        (["9_hearts", "K_spades"], ["7_clubs", "2_diamonds"]),             # tie, both natural 9
    ]
    logger.info(f"Running DEMO on sample hands (no model required) | send={send}")

    if send:
        from api_client.sender import start_sender, stop_sender, submit
        start_sender()

    for player, banker in samples:
        result = compute_result(player, banker)
        result["rules_consistent"] = is_rules_consistent(player, banker)
        result["round_id"] = f"DEMO-{datetime.now(timezone.utc):%H%M%S}-{uuid.uuid4().hex[:6]}"
        result["timestamp"] = datetime.now(timezone.utc).isoformat()
        print(format_round(result))
        if send:
            submit(result)

    if send:
        stop_sender()


def run_calibrate() -> None:
    from capture.calibrate import capture_and_save

    capture_and_save()


def run_image(path: str) -> None:
    import cv2

    from pipeline.recognize import recognize_round
    from storage.results_store import store_round

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
    store_round(result)
    print(format_round(result))
    print(json.dumps(result, indent=2))


def run_detect(path: str, weights: str | None, conf: float) -> None:
    """
    Run the model on the WHOLE image — no ROI cropping, no baccarat logic.
    Lists every detection (with its parsed rank/value) and saves an annotated
    copy. This decouples "does the model detect cards" from "are my ROIs tuned",
    so you can verify a downloaded model before any calibration.
    """
    import cv2

    from game_logic.baccarat_engine import card_value, parse_rank

    # Cheap checks first — don't pay the torch import just to report a typo.
    if not os.path.exists(path):
        logger.error(f"Image not found: {path}")
        sys.exit(1)

    weights = weights or os.getenv("MODEL_WEIGHTS_PATH", "./models/weights/best.pt")
    if not os.path.exists(weights):
        logger.error(
            f"Model not found: {weights} — download one (see README → "
            "'Quick test without training'), then pass --weights PATH or set MODEL_WEIGHTS_PATH."
        )
        sys.exit(1)

    image = cv2.imread(path)
    if image is None:
        logger.error(f"Could not read image: {path}")
        sys.exit(1)

    from ultralytics import YOLO

    from recognition.device import resolve_device

    model = YOLO(weights)
    logger.info(f"Loaded {weights} | {len(model.names)} classes | device={resolve_device()}")
    results = model.predict(source=image, conf=conf, device=resolve_device(), verbose=False)
    r = results[0]

    dets = sorted(
        ((model.names[int(b.cls[0])], float(b.conf[0])) for b in r.boxes),
        key=lambda d: -d[1],
    )
    print(f"\nDetected {len(dets)} card(s) at conf >= {conf}:")
    for name, c in dets:
        print(f"  {name:<16} conf={c:.2f}   rank={parse_rank(name):<3} value={card_value(name)}")
    if not dets:
        print("  (none — try a clearer image, a lower --conf, or a different model)")

    out = os.path.splitext(path)[0] + "_detected.jpg"
    cv2.imwrite(out, r.plot())
    print(f"\nAnnotated image saved: {out}")


def run_live() -> None:
    from api_client.sender import start_sender, stop_sender, submit
    from capture.screen_agent import run_capture_loop
    from pipeline.dedup import is_new_round
    from pipeline.recognize import recognize_round
    from storage.results_store import results_path, store_round

    start_sender()
    logger.info(
        f"Live mode — monitoring for WIN popup | results -> {results_path()} | Ctrl-C to stop."
    )

    def on_trigger(frame):
        result = recognize_round(frame)
        if result is None:
            return
        print(format_round(result))
        if not is_new_round(result):
            logger.info("Duplicate round (popup re-trigger) — not stored or sent.")
            return
        store_round(result)   # local durable record (JSONL), independent of the API
        submit(result)        # queued; the sender thread POSTs it to the API

    try:
        run_capture_loop(on_trigger_callback=on_trigger)
    finally:
        stop_sender()   # drain pending sends before exit


def main() -> None:
    parser = argparse.ArgumentParser(description="Baccarat CV core")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--demo", action="store_true", help="run pipeline on sample cards (no model)")
    group.add_argument("--calibrate", action="store_true", help="save ROI calibration images")
    group.add_argument("--detect", metavar="PATH", help="run model on a whole image to test it")
    group.add_argument("--image", metavar="PATH", help="recognize a baccarat frame via the ROI pipeline")
    group.add_argument("--live", action="store_true", help="watch screen and recognize on WIN badge")
    parser.add_argument("--weights", metavar="PATH",
                        help="model path (overrides MODEL_WEIGHTS_PATH); used by --detect")
    parser.add_argument("--conf", type=float, default=0.25,
                        help="confidence threshold for --detect (default 0.25)")
    parser.add_argument("--send", action="store_true",
                        help="with --demo: also POST the sample rounds to your API")
    args = parser.parse_args()

    if args.demo:
        run_demo(send=args.send)
    elif args.calibrate:
        run_calibrate()
    elif args.detect:
        run_detect(args.detect, args.weights, args.conf)
    elif args.image:
        run_image(args.image)
    elif args.live:
        run_live()


if __name__ == "__main__":
    main()
