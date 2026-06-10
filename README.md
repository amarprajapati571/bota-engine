# Baccarat CV Core

A computer-vision pipeline that reads a baccarat round off a game screen: it
captures the frame, detects the Player/Banker cards with **YOLOv8**, reads the
on-screen score circles with **EasyOCR**, computes the hand result with a pure
baccarat-rules engine, and **cross-validates** the two signals against each
other before reporting a confidence level.

This is the **recognition core only** — built as a CV/ML learning project. The
queue/REST-API/MongoDB/Docker/24-7 deployment layers from the original spec are
intentionally left out.

> **Scope note.** This reads cards *after* a round is decided (it triggers on the
> WIN badge). Baccarat rounds are statistically independent, so the logged
> history has **no predictive value** for future hands — it's a recognition and
> data-extraction exercise, not a betting system.

## Pipeline

```
 screen / image
       │
       ▼
 capture/screen_agent ──(gold WIN-badge trigger)
       │
       ▼
 recognition/card_recognizer   →  YOLOv8 detects cards in Player & Banker ROIs
       │                          (recognition/confidence_filter scores them)
       ▼
 game_logic/baccarat_engine    →  hand values + outcome (pure Python)
       │
       ▼
 game_logic/validator          →  cross-check vs OCR score circles
       │                          (recognition/ocr_reader) + rules consistency
       ▼
 pipeline/recognize            →  structured round dict + HIGH/LOW confidence
```

## Setup

Requires Python 3.10+ (developed/tested on 3.13).

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

`torch`, `ultralytics`, and `easyocr` are large; the first OCR run also downloads
~100 MB of EasyOCR models. None of that is needed for `--demo`.

**macOS:** live capture and `--calibrate` need **Screen Recording** permission
(System Settings → Privacy & Security → Screen Recording) for your terminal.
Without it, captured frames come back black (the code warns when it sees this).

## Running

```bash
# 1. No model/screen needed — confirms the install + game logic works:
python main.py --demo

# 2. Tune the ROI boxes to your window (saves annotated screenshots):
python main.py --calibrate

# 3. Test a model on a whole image, no calibration (see "Quick test without training"):
python main.py --detect path/to/cards.jpg

# 4. Recognize a baccarat frame through the ROI pipeline (needs calibrated ROIs + model):
python main.py --image path/to/frame.png

# 5. Monitor for the WIN popup, recognize on each one, and POST to your API:
python main.py --live
```

## Verifying it works

Work up the ladder — each rung needs more than the last, so a failure pinpoints
the layer that broke.

**Offline (no model, no screen) — one command:**

```bash
bash scripts/smoke_test.sh
```

Runs the engine unit tests, the demo pipeline, and a full storage + API-push
round-trip against a throwaway mock backend (writes to a temp file, so it never
touches your real `results.jsonl`). All green = the entire non-vision pipeline works.

Or step through it manually:

| Check | Command | Proves |
|---|---|---|
| Rules engine | `python tests/test_baccarat_engine.py` | scoring + draw logic (17 tests) |
| Demo pipeline | `python main.py --demo` | recognize→compute→format wiring |
| Storage + API | `python tools/mock_api.py` &nbsp;+&nbsp; `python main.py --demo --send` | `results.jsonl` write, JWT/POST, dedup |
| Screen capture | `python main.py --calibrate` | mss grabs your screen (saves PNG) |
| Model loads/detects | `python main.py --detect card.jpeg` | weights load + cards detected |
| Full live loop | `python main.py --live` | monitor→recognize→store→send |

The last two rows need a model at `models/weights/best.pt` (and `--live` needs ROIs
calibrated to your game). Everything above runs today with zero model.

Run the logic tests with:

```bash
python tests/test_baccarat_engine.py
```

## Calibration

ROIs live in [`capture/roi_config.py`](capture/roi_config.py) (the single source
of truth) and can be overridden via `.env`. The defaults assume an 880×500
window and **will not match your screen**. Workflow:

1. `python main.py --calibrate`
2. Open `calibration_full.png` → read off `GAME_MONITOR_*` for your window.
3. Open `calibration_region_annotated.png` → nudge the card/badge/score ROIs.
4. Repeat until the boxes sit exactly on the cards, the WIN badge, and the
   score circles.
5. Tune the trigger: `python main.py --watch-badge`, trigger the WIN popup
   in-game, and watch `gold_ratio` spike. Set `WIN_BADGE_GOLD_THRESHOLD` between
   the idle value and the spike.

## Quick test without training

You don't have to train to see recognition work — borrow a public model and run
it on a photo of real cards with `--detect` (whole image, no ROI calibration):

```bash
mkdir -p models/weights
# A public YOLOv8 playing-card model (trained on the Roboflow cards dataset):
wget -O models/weights/best.pt \
  https://github.com/noorkhokhar99/Playing-Cards-Detection-with-YoloV8/raw/main/yolov8s_playing_cards.pt

python main.py --detect some_cards_photo.jpg     # prints detections + saves *_detected.jpg
```

`--detect` lists every detected class with its parsed rank/value and writes an
annotated image, so you can tell at a glance whether the model works. Pass
`--conf 0.1` to loosen the threshold or `--weights other.pt` to try another model.

**Expect a gap on game screens.** These models are trained on *photographed*
cards — great on real-card photos, but they may miss your baccarat game's
*rendered* cards. If `--detect` finds nothing on an actual game frame, that's the
domain gap, and a short fine-tune on your own frames (the `model/` scripts + your
3080) is the fix. Alternative model:
[mustafakemal0146/playing-cards-yolov8](https://huggingface.co/mustafakemal0146/playing-cards-yolov8).

## Training a model

`--image` / `--live` need YOLOv8 weights. The `model/` scripts take you from a
public dataset to a usable `best.pt`.

```bash
pip install -r requirements.txt -r requirements-train.txt
```

**1. Get a dataset.** Create a free [Roboflow](https://app.roboflow.com) account,
find a playing-cards dataset on [Roboflow Universe](https://universe.roboflow.com)
(YOLOv8 export), and copy its workspace/project/version + your API key into
`.env`. Then:

```bash
python model/download_dataset.py     # → ./dataset/ (with its own data.yaml)
```

**2. (Optional) Augment** a small hand-labeled set:

```bash
python model/augment.py --per-image 5
```

**3. Train.** Reads the dataset config and your `.env` training settings, then
copies the best weights to `models/weights/best.pt` automatically:

```bash
python model/train.py
```

**Class names:** card datasets name classes differently (`A_spades`, `AS`, `TH`,
`ace of spades` …). The engine's `parse_rank()` handles all of these, so most
datasets work without renaming — only the **rank** matters for baccarat scoring.
To label your own frames instead, use [`model/cards.yaml`](model/cards.yaml) as
the dataset config (52 classes in the `<rank>_<suit>` convention).

## Sending results to an API (`--live`)

`--live` is the runtime loop: it monitors the screen, recognizes each hand,
stores it, and POSTs the result to your backend. Two triggers:

- `--trigger badge` *(default)* — fires on the gold WIN popup. Cheap (a color
  check), but needs `WIN_BADGE_ROI` + `WIN_BADGE_GOLD_THRESHOLD` calibrated.
- `--trigger cards` — runs the model continuously and fires once the detected
  cards sit unchanged for ~1s (the hand has finished dealing). No badge needed —
  ideal when watching a **video** where the cards themselves are the cue. Costs
  more compute (fine on a GPU). Still needs the card ROIs + a model.

```
WIN popup ─▶ recognize_round ─▶ sender queue ─▶ background thread ─▶ POST {API_BASE_URL}{API_RESULT_PATH}
```

Every recognized round is **also stored locally** — appended as one JSON line to
`RESULTS_FILE` (default `logs/results.jsonl`) — independent of the API, so you get
a durable record even with no backend configured (`RESULTS_ENABLED=false` to turn
it off). Inspect it with `tail -f logs/results.jsonl` or `wc -l logs/results.jsonl`.

Design notes:
- **Non-blocking:** sending runs on a background thread, so a slow/dead API never
  stalls screen capture.
- **Deduped at the trigger:** if the popup lingers and re-fires, the round is
  neither stored nor sent twice (matched on cards + outcome within a short window).
- **Durable:** failed POSTs (after `API_MAX_RETRIES` with backoff) are appended to
  `logs/outbox.jsonl` — nothing is lost while the API is down; replay it later.
- **Deduped:** if the popup lingers and re-triggers, the same round (same cards +
  outcome) isn't posted twice within a short window.
- **Auth:** set `API_JWT_SECRET` for a signed JWT per request, or `API_TOKEN` for a
  static Bearer, or neither for an open backend.
- Leave `API_BASE_URL` empty to disable sending (recognition still runs/prints).

**Test the whole loop with no real backend** — a zero-dependency mock receiver:

```bash
python tools/mock_api.py                       # terminal 1: listens on :8000
# in .env: API_BASE_URL=http://localhost:8000
python main.py --live                          # terminal 2: rounds appear in terminal 1
```

The POST body is the full round dict (cards, values, outcome, `validation_passed`,
`confidence_level`, `round_id`, `timestamp`, …). Point `API_BASE_URL` at your own
server when ready.

## Layout

```
capture/        screen capture, ROI config, calibration
recognition/    YOLOv8 wrapper, EasyOCR reader, confidence filter, device pick
game_logic/     pure baccarat rules engine + OCR/rules validator
pipeline/       frame → structured round result; trigger-boundary dedup
api_client/     JWT/bearer auth, retrying HTTP client, background sender thread
storage/        append each round to logs/results.jsonl (JSON Lines)
model/          dataset download, augmentation, YOLOv8 training, cards.yaml
monitoring/     loguru setup
tools/          mock_api.py — stdlib test receiver
tests/          baccarat engine unit tests
main.py         --demo / --calibrate / --detect / --image / --live
```

## Known limitations

- The WIN-badge trigger is a simple gold-HSV ratio; it's sensitive to theme and
  lighting and will need threshold tuning per table.
- OCR on tiny score circles is the weakest link — treat `LOW` confidence rounds
  as unreliable.
- Recognition accuracy is entirely a function of your trained model and ROI
  calibration.
```
