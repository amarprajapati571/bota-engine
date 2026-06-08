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

# 3. Recognize a single saved frame (needs a trained model):
python main.py --image path/to/frame.png

# 4. Watch the screen live and recognize on each WIN badge:
python main.py --live
```

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

## Layout

```
capture/        screen capture, ROI config, calibration
recognition/    YOLOv8 wrapper, EasyOCR reader, confidence filter, device pick
game_logic/     pure baccarat rules engine + OCR/rules validator
pipeline/       frame → structured round result (no side effects)
model/          dataset download, augmentation, YOLOv8 training, cards.yaml
monitoring/     loguru setup
tests/          baccarat engine unit tests
main.py         --demo / --calibrate / --image / --live
```

## Known limitations

- The WIN-badge trigger is a simple gold-HSV ratio; it's sensitive to theme and
  lighting and will need threshold tuning per table.
- OCR on tiny score circles is the weakest link — treat `LOW` confidence rounds
  as unreliable.
- Recognition accuracy is entirely a function of your trained model and ROI
  calibration.
```
