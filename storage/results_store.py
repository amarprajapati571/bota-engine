"""
Local results store.

Every recognized round is appended as one JSON object per line (JSON Lines) to a
configurable file. This is independent of the API push — results are recorded
even when no backend is configured or the API is down.

    RESULTS_FILE     path to the JSONL file (default ./logs/results.jsonl)
    RESULTS_ENABLED  set false/0/no/off to disable local storage

Read it back with `tail -f logs/results.jsonl`, `wc -l logs/results.jsonl`, or
`python -c "import json;[print(json.loads(l)['outcome']) for l in open('logs/results.jsonl')]"`.
"""
import json
import os
import threading

from loguru import logger

_lock = threading.Lock()


def _enabled() -> bool:
    return os.getenv("RESULTS_ENABLED", "true").strip().lower() not in ("false", "0", "no", "off")


def results_path() -> str:
    return os.getenv("RESULTS_FILE", "./logs/results.jsonl")


def store_round(result: dict) -> bool:
    """Append one round to the results file. Returns True if written."""
    if not _enabled():
        return False

    path = results_path()
    try:
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        line = json.dumps(result, ensure_ascii=False)
        with _lock, open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        logger.debug(f"Stored round {result.get('round_id')} -> {path}")
        return True
    except Exception as exc:  # storage must never crash the pipeline
        logger.error(f"Failed to store round to {path}: {exc}")
        return False
