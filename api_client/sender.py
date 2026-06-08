"""
Background sender.

A worker thread drains an in-memory queue and POSTs each round via
api_client.client.send_round, so the capture loop never blocks on the network.

A short-window content dedup avoids double-posting the same physical round when
the WIN popup lingers on screen long enough to re-trigger the capture loop.
(This is keyed on the actual cards + outcome, not just the score values — two
different rounds that happen to share a score are still both sent.)
"""
import queue
import threading
import time

from loguru import logger

from api_client.client import send_round

_q: "queue.Queue[dict]" = queue.Queue()
_stop = threading.Event()
_thread: "threading.Thread | None" = None

_last_sig: "str | None" = None
_last_sig_time = 0.0
_DEDUP_WINDOW_SECS = 15.0


def _signature(payload: dict) -> str:
    return (
        f"{payload.get('player_cards')}|{payload.get('banker_cards')}|"
        f"{payload.get('outcome')}"
    )


def submit(payload: dict) -> None:
    """Queue a round for sending (deduped against the immediately previous one)."""
    global _last_sig, _last_sig_time
    sig = _signature(payload)
    now = time.time()
    if sig == _last_sig and (now - _last_sig_time) < _DEDUP_WINDOW_SECS:
        logger.debug("Duplicate round within dedup window — not queued.")
        return
    _last_sig, _last_sig_time = sig, now
    _q.put(payload)


def _loop() -> None:
    logger.info("API sender thread started")
    while not _stop.is_set() or not _q.empty():
        try:
            payload = _q.get(timeout=1)
        except queue.Empty:
            continue
        try:
            send_round(payload)
        except Exception as exc:  # never let the sender thread die
            logger.error(f"Sender error: {exc}")
        finally:
            _q.task_done()
    logger.info("API sender thread stopped")


def start_sender() -> "threading.Thread":
    global _thread
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="ApiSender", daemon=True)
    _thread.start()
    return _thread


def stop_sender(drain: bool = True, timeout: float = 10.0) -> None:
    """Signal the worker to finish; by default waits for the queue to drain."""
    _stop.set()
    if _thread and drain:
        _thread.join(timeout=timeout)
