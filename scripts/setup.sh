#!/usr/bin/env bash
#
# One-command setup for Ubuntu (e.g. the 3080 box). From the project root:
#   bash scripts/setup.sh              # core (capture + recognition + API + storage)
#   bash scripts/setup.sh --train      # also install training extras (roboflow, albumentations)
#
# Installs OpenCV's system libs, creates a venv, installs Python deps (the Torch
# CUDA wheel is pulled automatically on Linux), seeds .env, and runs the smoke test.

set -e
cd "$(dirname "$0")/.."

WANT_TRAIN=0
[ "${1:-}" = "--train" ] && WANT_TRAIN=1

echo "== Baccarat CV core — setup =="

# 1. System libraries (OpenCV + venv). Skipped if apt/sudo unavailable.
if command -v apt-get >/dev/null 2>&1; then
  echo "-- installing system packages (may prompt for sudo) --"
  sudo apt-get update -y
  sudo apt-get install -y \
    python3-venv python3-pip python3-dev \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    git wget curl
else
  echo "-- apt-get not found; make sure libGL + python3-venv are present --"
fi

# 2. Virtualenv
echo "-- creating venv --"
python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip

# 3. Python dependencies (first run also downloads EasyOCR models on use)
echo "-- installing Python deps (torch/ultralytics/easyocr — this is the big one) --"
pip install -r requirements.txt
if [ "$WANT_TRAIN" = "1" ]; then
  echo "-- installing training extras --"
  pip install -r requirements-train.txt
fi

# 4. .env
if [ ! -f .env ]; then
  cp .env.example .env
  echo "-- created .env from .env.example --"
fi

# 5. GPU check
echo "-- GPU check --"
python -c "import torch; print('torch', torch.__version__, '| CUDA available:', torch.cuda.is_available())" || true
command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true

# 6. Offline smoke test
echo "-- smoke test --"
bash scripts/smoke_test.sh || true

cat <<'EOF'

== Setup complete ==
Activate the venv in each new terminal:   source venv/bin/activate

Next steps:
  python main.py --calibrate              # check ROIs line up on your screen
  python main.py --detect calibration_full.png   # does the model see the cards?
  python main.py --live                   # run it (waits for the WIN popup)
EOF
