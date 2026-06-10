"""
Background sender.

A worker thread drains an in-memory queue and POSTs each round via
api_client.client.send_round, so the capture loop never blocks on the network.

Deduplication happens upstream at the trigger boundary (pipeline.dedup), so the
same payload submitted here is always sent.
"""
import queue
import threading

from loguru import logger

from api_client.client import send_round

_q: "queue.Queue[dict]" = queue.Queue()
_stop = threading.Event()
_thread: "threading.Thread | None" = None


def submit(payload: dict) -> None:
    """Queue a round for the background sender to POST."""
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
