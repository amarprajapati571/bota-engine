"""
Device resolution for Torch / YOLO / EasyOCR.

The original spec passed MODEL_DEVICE straight through as the string "0", which
breaks on machines without CUDA (e.g. an Apple-Silicon Mac). This resolves a
sensible device from the env var, with "auto" picking CUDA → MPS → CPU.

Accepted MODEL_DEVICE values: auto | cpu | mps | cuda | cuda:0 | 0 | 1 ...
"""
import functools
import os


@functools.lru_cache(maxsize=1)
def has_cuda() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:
        return False


@functools.lru_cache(maxsize=1)
def has_mps() -> bool:
    try:
        import torch

        return bool(getattr(torch.backends, "mps", None)) and torch.backends.mps.is_available()
    except Exception:
        return False


def resolve_device(preference: str | None = None):
    """
    Return a device spec YOLO/Torch understands: an int GPU index, or one of
    "cpu" / "mps" / "cuda" / "cuda:N".
    """
    pref = (preference if preference is not None else os.getenv("MODEL_DEVICE", "auto"))
    pref = str(pref).strip().lower()

    if pref in ("", "auto"):
        if has_cuda():
            return 0
        if has_mps():
            return "mps"
        return "cpu"

    if pref in ("cpu", "mps"):
        return pref
    if pref.startswith("cuda"):
        return pref if has_cuda() else "cpu"
    if pref.isdigit():
        return int(pref) if has_cuda() else "cpu"
    return pref
