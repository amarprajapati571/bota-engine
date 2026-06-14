"""
Extract 52 playing-card SVG assets from the NPM deck package and render PNGs.

Expected package:
  @younestouati/playing-cards-standard-deck@6.0.1

Output:
  dataset/cards/A_clubs.png
  dataset/cards/2_clubs.png
  ...
  dataset/cards/K_spades.png
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from urllib.parse import unquote

import cairosvg

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = PROJECT_ROOT / "node_modules" / "@younestouati" / "playing-cards-standard-deck"
OUT_DIR = PROJECT_ROOT / "dataset" / "cards"

SUITS = {
    "clubs": "clubs",
    "club": "clubs",
    "c": "clubs",
    "diamonds": "diamonds",
    "diamond": "diamonds",
    "d": "diamonds",
    "hearts": "hearts",
    "heart": "hearts",
    "h": "hearts",
    "spades": "spades",
    "spade": "spades",
    "s": "spades",
}
RANKS = {
    "ace": "A",
    "a": "A",
    "1": "A",
    "11": "J",
    "jack": "J",
    "j": "J",
    "12": "Q",
    "queen": "Q",
    "q": "Q",
    "13": "K",
    "king": "K",
    "k": "K",
    **{str(i): str(i) for i in range(2, 11)},
}


def _iter_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _iter_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_strings(child)


def _decode_svg(text: str) -> str | None:
    if "<svg" in text:
        return text[text.find("<svg") :]
    if "data:image/svg+xml" not in text:
        return None

    payload = text.split(",", 1)[-1]
    try:
        if ";base64" in text[: text.find(",")]:
            decoded = base64.b64decode(payload).decode("utf-8")
        else:
            decoded = unquote(payload)
    except Exception:
        return None
    return decoded if "<svg" in decoded else None


def _rank_suit_from_text(text: str) -> tuple[str, str] | None:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    tokens = [t for t in normalized.split("_") if t]

    rank = None
    suit = None
    for token in tokens:
        if rank is None and token in RANKS:
            rank = RANKS[token]
        if suit is None and token in SUITS:
            suit = SUITS[token]

    compact = "".join(tokens)
    if rank is None or suit is None:
        for raw_rank, mapped_rank in RANKS.items():
            for raw_suit, mapped_suit in SUITS.items():
                patterns = (
                    f"{raw_rank}{raw_suit}",
                    f"{raw_suit}{raw_rank}",
                    f"{mapped_rank.lower()}{raw_suit}",
                    f"{raw_suit}{mapped_rank.lower()}",
                )
                if compact in patterns:
                    rank, suit = mapped_rank, mapped_suit
                    break
            if rank and suit:
                break

    if rank and suit:
        return rank, suit
    return None


def _collect_from_json(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    found: dict[str, str] = {}
    strings = list(_iter_strings(data))
    for idx, text in enumerate(strings):
        svg = _decode_svg(text)
        if not svg:
            continue

        context = " ".join(strings[max(0, idx - 6) : idx + 7])
        parsed = _rank_suit_from_text(context)
        if parsed:
            rank, suit = parsed
            found[f"{rank}_{suit}"] = svg
    return found


def _collect_from_files() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in PACKAGE_DIR.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() == ".svg":
            parsed = _rank_suit_from_text(path.stem)
            if parsed:
                rank, suit = parsed
                found[f"{rank}_{suit}"] = path.read_text(encoding="utf-8")
        elif path.suffix.lower() in {".json", ".js", ".mjs", ".cjs"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if path.suffix.lower() == ".json":
                found.update(_collect_from_json(path))
            for match in re.finditer(r"data:image/svg\+xml[^'\"\s)]+", text):
                start = max(0, match.start() - 160)
                end = min(len(text), match.end() + 160)
                svg = _decode_svg(match.group(0))
                parsed = _rank_suit_from_text(text[start:end])
                if svg and parsed:
                    rank, suit = parsed
                    found[f"{rank}_{suit}"] = svg
    return found


def main() -> None:
    if not PACKAGE_DIR.exists():
        raise SystemExit(
            f"Package not found: {PACKAGE_DIR}\n"
            "Run: npm install @younestouati/playing-cards-standard-deck@6.0.1"
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cards = _collect_from_files()
    expected = [f"{rank}_{suit}" for suit in ("clubs", "diamonds", "hearts", "spades") for rank in (
        "A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"
    )]

    for name, svg in sorted(cards.items()):
        if name not in expected:
            continue
        cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(OUT_DIR / f"{name}.png"))

    written = sorted(p.stem for p in OUT_DIR.glob("*.png"))
    missing = [name for name in expected if name not in written]
    print(f"Detected {len(written)}/52 cards")
    if missing:
        print("Missing:")
        for name in missing:
            print(f"  {name}.png")
        raise SystemExit(1)
    print(f"Saved cards to {OUT_DIR}")


if __name__ == "__main__":
    main()
