# Point-in-time universe (survivorship-bias fix)

Q_alpha.md §5.4: the backtest must, at each historical date, see exactly the stocks that were
investable **on that date** — including names that later delisted, went bankrupt, or were dropped
from the index. Using today's survivors overstates returns.

## What's here

`nifty50_membership.csv` — a genuine point-in-time NIFTY 50 membership for **2012-01-01 → 2024-12-31**,
built by `scripts/build_nifty_universe.py`. 81 distinct names, 83 membership intervals (Vedanta and
Grasim each have two stints), columns `ticker,start_date,end_date,sector`. Consumed by
`Universe.from_csv` (ticker/start/end) and `run_phase0.py --universe-csv` (also lifts the sector map).

It **includes the dead/dropped names** that survivorship bias would erase — Reliance Power, Reliance
Infrastructure, JP Associates, DLF, Yes Bank, Zee, Idea/Vodafone Idea, Vedanta, Indiabulls Housing,
Unitech-era cyclicals, SAIL, NMDC, BHEL, ACC, Ambuja, Lupin, GAIL, HPCL, etc.

## How it's built (reverse-apply from a known endpoint, validated)

We know the **current** NIFTY 50 constituents exactly, and the chronological list of index changes
(NSE reconstitutions, mirrored on Wikipedia's "Index changes" table). Walking the changes *backward*
from the current set reconstructs membership at any past date. Each reverse step **asserts
consistency** — a name being "added" must currently be present (so we can remove it); a name being
"removed" must currently be absent (so we can add it). A failed assertion reveals a gap/error in the
change list instead of letting it silently corrupt the universe. This validation actually caught:

- **4 mis-transcribed Wikipedia rows** (Apr-2018 listed Tata Power & HPCL as Nifty-50 removals; they
  were Nifty-*100* actions — the real Nifty-50 removals were Ambuja, Aurobindo, Bosch). Resolved
  against Business Standard / Moneylife / DNA primary reporting.
- **2 missing exits** Wikipedia omits entirely — Idea Cellular and BHEL both left in the **March 2018**
  review (→ Indiabulls Housing + IOC), pinned via news sources.

After fixes the reconstruction balances to exactly 50 members at every probe date **except one**:

## Known limitations (documented, not hidden)

1. **Bank of Baroda** is an *orphan add* — it entered (Sep 2012) but its later exit isn't in the
   source, so it's kept as a member through window-end (member count reads 51, not 50). BoB is a
   still-listed liquid PSU bank, so this is a membership inaccuracy, **not** a survivorship
   distortion (no dead name is wrongly included or excluded by it).
2. **Unpriceable names (yfinance can't serve them — merged/renamed/delisted away):** `HDFC` (HDFC
   Ltd, merged into HDFC Bank Jul-2023), `TATAMOTORS` (NSE symbol retired post-2025 demerger),
   `CAIRN`, `IDFC`, `STER`, plus `LTIM` (brief 2023-24 stint). They stay in the CSV (membership is
   *true*) but have no price column, so the engine skips them. Crucially these are **survivors or
   merged-into-survivors, not dead names** — their absence makes the test slightly *harder*, not
   easier, so it does not flatter the survivorship correction. (HDFC Ltd is the only material one; it
   is highly correlated with HDFC Bank, which *is* present.)
3. **Transition dates are at reconstitution granularity** and the change list is Wikipedia-sourced
   (corrected where primary sources contradicted it). Early-2012 membership before the first change
   (28 Sep 2012) is assumed constant; it doesn't affect any trade because the strategy's first
   rebalance is ~mid-2013 after its 252+90-day warm-up.

## Rebuild / use

```bash
uv run python scripts/build_nifty_universe.py        # regenerate nifty50_membership.csv (validated)
uv run python scripts/run_phase0.py \
    --universe-csv data/universes/nifty50_membership.csv \
    --benchmark NIFTYBEES.NS --start 2012-01-01 --end 2024-12-31
```

`--benchmark NIFTYBEES.NS` uses the ETF's dividend-reinvested adj-close as the **Nifty 50 TRI** proxy
(the fair bar vs a TR-adjusted strategy); the loader sanitises yfinance bad ticks (§5.1).
