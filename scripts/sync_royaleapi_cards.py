"""Download the public RoyaleAPI card catalogue used for simulator audits.

The game client files remain the source for server-side numeric combat values.
This snapshot is the independent, player-visible source for card identity,
elixir, type, evolution links, and current card descriptions. Keeping it in
the repository makes mechanics review reproducible instead of memory-based.

    python scripts/sync_royaleapi_cards.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen


URL = "https://royaleapi.github.io/cr-api-data/json/cards.json"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "royaleapi" / "cards.json"


def download(url: str = URL) -> bytes:
    request = Request(url, headers={"User-Agent": "HastyCR simulator audit"})
    with urlopen(request, timeout=30) as response:  # nosec B310: fixed HTTPS URL
        payload = response.read()
    parsed = json.loads(payload)
    if not isinstance(parsed, list) or not parsed:
        raise ValueError("RoyaleAPI returned no card catalogue")
    if not all(isinstance(card, dict) and card.get("key") for card in parsed):
        raise ValueError("RoyaleAPI catalogue has an invalid card record")
    return payload


def sync(output: Path = DEFAULT_OUTPUT) -> dict:
    payload = download()
    cards = json.loads(payload)
    record = {
        "source": URL,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "cards": cards,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    temporary.replace(output)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    record = sync(args.output)
    print(f"saved {len(record['cards'])} RoyaleAPI cards to {args.output}")
    print(f"sha256 {record['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
