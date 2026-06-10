"""
Download the 52 card face images from the game and save them as
dataset/cards/<rank>_<suit>.png — the format model/synth_dataset.py expects.

FIND THE URL PATTERN FIRST:
  Open the game in Chrome -> DevTools (F12) -> Network -> "Img" filter, let a
  hand deal, then click one card image to copy its URL. Build a --template from
  it using {rank} and {suit} placeholders.

EXAMPLES:
  # card loads from https://seam.zisego.com/img/cards/9C.png
  python scripts/fetch_card_assets.py \
    --template "https://seam.zisego.com/img/cards/{rank}{suit}.png" \
    --rank-format 10 --suit-format CDHS

  # https://seam.zisego.com/assets/cards/9_clubs.png
  python scripts/fetch_card_assets.py \
    --template "https://seam.zisego.com/assets/cards/{rank}_{suit}.png" \
    --suit-format clubs

  # preview the 52 URLs without downloading:
  python scripts/fetch_card_assets.py --template "...{rank}{suit}.png" --dry-run

Rank presets:  10 (A,2..10,J,Q,K)   |   T (A,2..9,T,J,Q,K)
Suit presets:  CDHS | cdhs | clubs | Clubs
"""
import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(PROJECT_ROOT, "dataset", "cards")

CANON_RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
CANON_SUITS = ["clubs", "diamonds", "hearts", "spades"]

SUIT_TOKENS = {
    "CDHS": {"clubs": "C", "diamonds": "D", "hearts": "H", "spades": "S"},
    "cdhs": {"clubs": "c", "diamonds": "d", "hearts": "h", "spades": "s"},
    "clubs": {s: s for s in CANON_SUITS},
    "Clubs": {s: s.capitalize() for s in CANON_SUITS},
}


def _rank_token(rank: str, style: str) -> str:
    if rank == "10":
        return "T" if style == "T" else "10"
    return rank


def _urls(template: str, rank_format: str, suit_format: str):
    """Yield (canonical_name, url) for all 52 cards."""
    suit_map = SUIT_TOKENS[suit_format]
    for suit in CANON_SUITS:
        for rank in CANON_RANKS:
            url = template.format(rank=_rank_token(rank, rank_format), suit=suit_map[suit])
            yield f"{rank}_{suit}", url


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch the 52 card images from the game")
    ap.add_argument("--template", required=True,
                    help="URL with {rank} and {suit}, e.g. https://host/cards/{rank}{suit}.png")
    ap.add_argument("--rank-format", choices=["10", "T"], default="10")
    ap.add_argument("--suit-format", choices=list(SUIT_TOKENS), default="CDHS")
    ap.add_argument("--referer", help="Referer header, if the server requires one")
    ap.add_argument("--dry-run", action="store_true", help="print the 52 URLs and exit")
    args = ap.parse_args()

    pairs = list(_urls(args.template, args.rank_format, args.suit_format))

    if args.dry_run:
        for name, url in pairs:
            print(f"{name:<12} {url}")
        print(f"\n{len(pairs)} URLs. Remove --dry-run to download.")
        return

    import cv2          # lazy: --dry-run needs no deps
    import numpy as np
    import requests

    os.makedirs(OUT_DIR, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0"}
    if args.referer:
        headers["Referer"] = args.referer

    ok, failed = 0, []
    for name, url in pairs:
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200 or not resp.content:
                failed.append((name, url, f"HTTP {resp.status_code}"))
                continue
            img = cv2.imdecode(np.frombuffer(resp.content, np.uint8), cv2.IMREAD_UNCHANGED)
            if img is None:  # not a raster image (e.g. SVG) — keep raw for manual conversion
                with open(os.path.join(OUT_DIR, name + ".raw"), "wb") as fh:
                    fh.write(resp.content)
                failed.append((name, url, "not a raster image (saved .raw)"))
                continue
            cv2.imwrite(os.path.join(OUT_DIR, name + ".png"), img)  # normalize to PNG
            ok += 1
            print(f"  ok   {name}")
        except Exception as exc:
            failed.append((name, url, str(exc)))

    print(f"\nDownloaded {ok}/52 to {OUT_DIR}")
    if failed:
        print(f"{len(failed)} failed — fix --template / --rank-format / --suit-format:")
        for name, url, why in failed[:8]:
            print(f"  {name}: {why}   [{url}]")
        if len(failed) > 8:
            print(f"  ... and {len(failed) - 8} more")
    if ok:
        print("\nNext: python model/synth_dataset.py --count 2000")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
