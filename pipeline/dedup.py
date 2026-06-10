"""
Round deduplication.

The WIN popup can stay on screen long enough for the capture loop to fire more
than once for the same physical round. This guards the trigger boundary so a
re-detected round is neither stored nor sent twice.

Keyed on the actual cards + outcome (not just the score values), so two genuinely
different rounds that happen to share a score are both treated as new.
"""
import threading
import time

_lock = threading.Lock()
_last_sig: "str | None" = None
_last_sig_time = 0.0
_DEFAULT_WINDOW_SECS = 15.0


def _signature(result: dict) -> str:
    return (
        f"{result.get('player_cards')}|{result.get('banker_cards')}|"
        f"{result.get('outcome')}"
    )


def is_new_round(result: dict, window_secs: float = _DEFAULT_WINDOW_SECS) -> bool:
    """
    True if this round differs from the last one seen, or enough time has passed.
    Updates the remembered signature as a side effect.
    """
    global _last_sig, _last_sig_time
    sig = _signature(result)
    now = time.time()
    with _lock:
        if sig == _last_sig and (now - _last_sig_time) < window_secs:
            return False
        _last_sig, _last_sig_time = sig, now
        return True
