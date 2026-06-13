"""
Baccarat CV core — entry point.

Modes:
  python main.py --demo            Run the game-logic + validation pipeline on
                                   sample cards. No model/screen/GPU needed —
                                   start here to confirm the install works.
  python main.py --calibrate       Save annotated screenshots to tune the ROIs.
  python main.py --watch-badge     Live gold-ratio read-out for the WIN badge, so you
                                   can set GOLD_PIXEL_THRESHOLD (trigger the popup and
                                   watch it spike). No model needed.
  python main.py --detect-screen   Capture the screen and run the model on it in one
                                   shot (saves screen_detected.jpg). "capture + detect".
  python main.py --detect PATH     Run the model on a saved image (no ROIs, no game
                                   logic) — quickest way to test a model. --weights/--conf.
  python main.py --image PATH      Run the full CV pipeline on a saved frame.
  python main.py --live            Monitor the screen, recognize each hand, store + send.
                                   --trigger badge : fire on the gold WIN popup (default)
                                   --trigger cards : fire when cards appear (no badge;
                                                     runs the model continuously)

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
        from storage.results_store import ensure_results_file, store_round
        ensure_results_file()
        start_sender()

    for player, banker in samples:
        result = compute_result(player, banker)
        result["rules_consistent"] = is_rules_consistent(player, banker)
        result["round_id"] = f"DEMO-{datetime.now(timezone.utc):%H%M%S}-{uuid.uuid4().hex[:6]}"
        result["timestamp"] = datetime.now(timezone.utc).isoformat()
        print(format_round(result))
        if send:
            store_round(result)   # local JSONL
            submit(result)        # API push

    if send:
        stop_sender()


def run_calibrate() -> None:
    from capture.calibrate import capture_and_save

    capture_and_save()


def run_watch_badge() -> None:
    """
    Live read-out of the WIN-badge gold ratio — for tuning GOLD_PIXEL_THRESHOLD.

    Watch the idle value, trigger the WIN popup in-game, watch the ratio spike,
    then set GOLD_PIXEL_THRESHOLD between the two. Ctrl-C to stop.
    """
    import time

    from capture.roi_config import GOLD_PIXEL_THRESHOLD, WIN_BADGE_ROI
    from capture.screen_agent import capture_frame, is_win_badge_visible

    logger.info(f"Watching WIN badge | ROI={WIN_BADGE_ROI} | current threshold={GOLD_PIXEL_THRESHOLD}")
    print("Trigger the WIN popup in-game and watch the ratio spike. Ctrl-C to stop.\n")
    try:
        while True:
            _, ratio = is_win_badge_visible(capture_frame())
            above = ratio >= GOLD_PIXEL_THRESHOLD
            bar = "#" * min(int(ratio * 50), 50)
            print(f"gold_ratio={ratio:6.3f} |{bar:<50}| {'TRIGGER' if above else '       '}",
                  end="\r", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopped.")


def run_image(path: str) -> None:
    import cv2

    from pipeline.recognize import recognize_round
    from storage.results_store import ensure_results_file, store_round

    if not os.path.exists(path):
        logger.error(f"Image not found: {path}")
        sys.exit(1)
    frame = cv2.imread(path)
    if frame is None:
        logger.error(f"Could not read image: {path}")
        sys.exit(1)

    ensure_results_file()   # create it now if not found
    result = recognize_round(frame)
    if result is None:
        logger.warning("No round recognized in image.")
        return
    store_round(result)
    print(format_round(result))
    print(json.dumps(result, indent=2))


def _resolve_weights(weights: str | None) -> str:
    weights = weights or os.getenv("MODEL_WEIGHTS_PATH", "./models/weights/best.pt")
    if not os.path.exists(weights):
        logger.error(
            f"Model not found: {weights} — download one (README -> 'Quick test "
            "without training') or train one (README -> 'Training a model'), then "
            "pass --weights PATH or set MODEL_WEIGHTS_PATH."
        )
        sys.exit(1)
    return weights


def _detect_and_report(image, weights: str, conf: float, out_path: str) -> None:
    """Load weights, run YOLO on the WHOLE image, print detections, save annotated copy."""
    import cv2

    from game_logic.baccarat_engine import card_value, parse_rank
    from recognition.device import resolve_device
    from ultralytics import YOLO

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
        print("  (none — try a lower --conf, or a model trained on these cards)")

    cv2.imwrite(out_path, r.plot())
    print(f"\nAnnotated image saved: {out_path}")


def run_detect(path: str, weights: str | None, conf: float) -> None:
    """Run the model on a SAVED image (whole image, no ROIs)."""
    import cv2

    if not os.path.exists(path):
        logger.error(f"Image not found: {path}")
        sys.exit(1)
    weights = _resolve_weights(weights)
    image = cv2.imread(path)
    if image is None:
        logger.error(f"Could not read image: {path}")
        sys.exit(1)
    _detect_and_report(image, weights, conf, os.path.splitext(path)[0] + "_detected.jpg")


def run_detect_screen(weights: str | None, conf: float) -> None:
    """Capture the screen and run the model on it in one shot. Saves screen_detected.jpg."""
    weights = _resolve_weights(weights)
    from capture.screen_agent import capture_frame

    logger.info("Capturing screen...")
    image = capture_frame()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screen_detected.jpg")
    _detect_and_report(image, weights, conf, out)


def _cards_triggered_loop(handle) -> None:
    """
    Detection-based trigger (no WIN badge needed).

    Runs the model continuously; once the detected cards stay unchanged for ~1s
    (i.e. the hand has finished dealing and is sitting on screen), fires
    handle(frame) exactly once. Resets when the table clears, ready for the next
    hand. Ideal when watching a video where the trigger is the cards themselves.
    """
    import time

    from capture.roi_config import CAPTURE_FPS
    from capture.screen_agent import capture_frame
    from recognition.card_recognizer import recognize_cards

    interval = 1.0 / max(CAPTURE_FPS, 1)
    stable_needed = max(int(CAPTURE_FPS), 2)   # ~1s of unchanged cards = hand settled
    last_sig, stable, logged_sig, empty = None, 0, None, 0

    while True:
        try:
            frame = capture_frame()
            player = [d["card"] for d in recognize_cards(frame, "player")]
            banker = [d["card"] for d in recognize_cards(frame, "banker")]
            sig = f"{sorted(player)}|{sorted(banker)}"

            if player and banker:
                empty = 0
                stable = stable + 1 if sig == last_sig else 1
                last_sig = sig
                if stable >= stable_needed and sig != logged_sig:
                    logged_sig = sig          # don't re-fire while the same hand is up
                    handle(frame)
            else:
                empty += 1
                if empty >= stable_needed:    # table cleared — arm for the next hand
                    last_sig, stable, logged_sig = None, 0, None

            time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Stopped by user.")
            break
        except Exception as exc:
            logger.error(f"Cards-trigger error: {exc}")
            time.sleep(1)


def run_live(trigger: str = "badge") -> None:
    weights = os.getenv("MODEL_WEIGHTS_PATH", "./models/weights/best.pt")
    if not os.path.exists(weights):
        logger.error(
            f"Model not found: {weights} — --live needs a model. See README "
            "('Quick test without training' or 'Training a model')."
        )
        sys.exit(1)

    import cv2

    from api_client.cse_sender import (
        cse_enabled,
        cse_frame_dir,
        start_cse_sender,
        stop_cse_sender,
        submit_cse_review,
    )
    from api_client.sender import start_sender, stop_sender, submit
    from pipeline.dedup import is_new_round
    from pipeline.recognize import recognize_round
    from storage.results_store import ensure_results_file, store_round

    results_file = ensure_results_file()   # create it now if not found
    start_sender()
    start_cse_sender()

    def save_cse_frame(frame, round_id: str) -> str:
        frame_dir = cse_frame_dir()
        frame_dir.mkdir(parents=True, exist_ok=True)
        path = frame_dir / f"{round_id}.png"
        if not cv2.imwrite(str(path), frame):
            raise RuntimeError(f"Could not save CSE frame: {path}")
        return str(path)

    def handle(frame):
        result = recognize_round(frame)
        if result is None:
            return
        print(format_round(result))
        if not is_new_round(result):
            logger.info("Duplicate round — not stored or sent.")
            return
        if cse_enabled():
            try:
                image_path = save_cse_frame(frame, result["round_id"])
                result["source_image_path"] = image_path
                result["source_image_name"] = os.path.basename(image_path)
                submit_cse_review(image_path, result)
            except Exception as exc:
                logger.error(f"CSE frame/send queue failed | round={result.get('round_id')}: {exc}")
        store_round(result)   # local durable record (JSONL), independent of the API
        submit(result)        # queued; the sender thread POSTs it to the API

    logger.info(
        f"Live mode | trigger={trigger} | results -> {results_file} | Ctrl-C to stop."
    )
    try:
        if trigger == "cards":
            _cards_triggered_loop(handle)
        else:
            from capture.screen_agent import run_capture_loop
            run_capture_loop(on_trigger_callback=handle)
    finally:
        stop_sender()   # drain pending sends before exit
        stop_cse_sender()


def main() -> None:
    parser = argparse.ArgumentParser(description="Baccarat CV core")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--demo", action="store_true", help="run pipeline on sample cards (no model)")
    group.add_argument("--calibrate", action="store_true", help="save ROI calibration images")
    group.add_argument("--watch-badge", action="store_true", help="live gold-ratio readout to tune the WIN-badge threshold")
    group.add_argument("--detect-screen", action="store_true", help="capture the screen and run the model on it (one shot)")
    group.add_argument("--detect", metavar="PATH", help="run model on a saved image to test it")
    group.add_argument("--image", metavar="PATH", help="recognize a baccarat frame via the ROI pipeline")
    group.add_argument("--live", action="store_true", help="watch screen and recognize on WIN badge")
    parser.add_argument("--weights", metavar="PATH",
                        help="model path (overrides MODEL_WEIGHTS_PATH); used by --detect")
    parser.add_argument("--conf", type=float, default=0.25,
                        help="confidence threshold for --detect (default 0.25)")
    parser.add_argument("--send", action="store_true",
                        help="with --demo: also POST the sample rounds to your API")
    parser.add_argument("--trigger", choices=["badge", "cards"], default="badge",
                        help="--live trigger: 'badge' (gold WIN popup) or 'cards' "
                             "(detect cards directly, no badge — runs the model continuously)")
    args = parser.parse_args()

    if args.demo:
        run_demo(send=args.send)
    elif args.calibrate:
        run_calibrate()
    elif args.watch_badge:
        run_watch_badge()
    elif args.detect_screen:
        run_detect_screen(args.weights, args.conf)
    elif args.detect:
        run_detect(args.detect, args.weights, args.conf)
    elif args.image:
        run_image(args.image)
    elif args.live:
        run_live(trigger=args.trigger)


if __name__ == "__main__":
    main()
