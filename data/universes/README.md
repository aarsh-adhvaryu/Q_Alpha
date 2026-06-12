# Point-in-time universe (survivorship-bias fix)

Q_alpha.md §5.4: the backtest must, at each historical date, see exactly the stocks that were
investable **on that date** — including names that later delisted, went bankrupt, or were dropped
from the index. Using today's survivors overstates returns.

## File format

A CSV consumed by `Universe.from_csv(path)`:

```csv
ticker,start_date,end_date
RELIANCE.NS,2010-01-01,
SUZLON.NS,2010-01-01,2017-08-31     # dropped from the index / collapsed — MUST be present
TATAMOTORS.NS,2010-01-01,
```

- `ticker` — yfinance NSE symbol (`.NS`).
- `start_date` — first date the name was an index member (ISO `YYYY-MM-DD`).
- `end_date` — last date as a member; **blank means still a member**.

`Universe.from_csv` sets `point_in_time=True`, which lets the go/no-go report clear the §14
criterion-3 (survivorship) gate.

## ⚠️ Honesty note — why the current run is still CONDITIONAL

The curated 25-name watchlist in `scripts/run_phase0.py` is **today's survivors**. Writing a CSV for
just those names (all continuously listed since before 2012) would **not** remove the real bias:
the dead/dropped companies are simply absent from the data. Flipping `point_in_time=True` on a
survivor-only file would falsely earn a GO. We deliberately do **not** do that.

A genuine fix needs **historical index constituents including names that later left/died**, e.g.
the Nifty 50 / Nifty 200 membership history. Sources:

- NSE index "reconstitution" / review circulars (free, but must be assembled into the CSV above).
- Community datasets of historical NSE index membership (verify accuracy).
- A paid vendor with point-in-time constituents.

This is a **data-acquisition task** analogous to the Screener.in fundamentals — until that data is
in this folder, the backtest universe stays static and the verdict stays CONDITIONAL by design.

## Usage

```bash
uv run python scripts/run_phase0.py --universe-csv data/universes/nifty_membership.csv
```
