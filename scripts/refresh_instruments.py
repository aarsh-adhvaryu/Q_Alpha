"""Refresh the cached Kite instrument master (tokens + tick sizes) — `data/reference/`.

    uv run python scripts/refresh_instruments.py

``https://api.kite.trade/instruments`` is public (no auth, no key). The full dump is ~8.5 MB across
every segment; only the NSE **equity** rows are kept, which is ~444 KB and all the basket generator
needs. Cached rather than fetched at render time so basket generation stays pure, offline and
testable — a dashboard that reaches the network to price an order is a dashboard that fails at the
worst moment.

Tokens are stable in practice but not guaranteed. A stale cache surfaces as
``UnknownInstrumentError`` naming the symbol, never as an order silently missing from a basket.
"""

from __future__ import annotations

import csv
import io
import sys
import urllib.request
from pathlib import Path

URL = "https://api.kite.trade/instruments"
OUT = Path("data/reference/kite_instruments_nse_eq.csv")
COLUMNS = [
    "instrument_token",
    "exchange_token",
    "tradingsymbol",
    "tick_size",
    "lot_size",
    "instrument_type",
    "segment",
    "exchange",
]


def main() -> int:
    print(f"Fetching {URL} …")
    with urllib.request.urlopen(URL, timeout=120) as response:
        raw = response.read().decode("utf-8")
    rows = [
        r
        for r in csv.DictReader(io.StringIO(raw))
        if r["exchange"] == "NSE" and r["instrument_type"] == "EQ" and r["segment"] == "NSE"
    ]
    if not rows:
        print("no NSE equity rows — refusing to overwrite the cache", file=sys.stderr)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r["tradingsymbol"]):
            writer.writerow({c: row[c] for c in COLUMNS})
    print(f"✓ {len(rows):,} NSE equity instruments → {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
