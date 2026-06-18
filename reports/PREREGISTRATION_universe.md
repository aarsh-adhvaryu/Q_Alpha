# Pre-registration — universe expansion (Nifty 100 → 200)

_Registered 2026-06-18, before running. Iron rule: a performance claim must beat 1/N walk-forward,
net of Zerodha cost + capital-gains tax, on a survivorship-free universe; no tuning to manufacture a
finding; a negative result reported honestly is valid._

## Question
Does widening the stock-selection pool from Nifty 50 to **Nifty 100** (and, if that fails, **Nifty
200**) improve the validated 3-factor + shrink strategy, net of cost + tax, vs 1/N — and does
sector-aware allocation over the wider pool help?

## The data constraint (stated up front)
A **survivorship-free point-in-time membership** for Nifty 100/200 is not available for free at the
granularity the Nifty-50 universe was hand-reconstructed (~37 well-documented changes). Nifty 100/200
have many more semi-annual reconstitutions with no clean public change-list. **Therefore this is run in
two stages**, and Stage 1 is explicitly NOT a verdict.

## Stage 1 — survivorship-biased screen (directional only)
- Universe = **current (2026) Nifty 100 constituents** treated as members for the whole 2012–2024
  window (a *static* universe). This is biased two ways: (a) **survivorship** — today's top-100 are
  yesterday's winners; (b) **listing truncation** — several current names IPO'd mid-window (Hyundai,
  Tata Capital, IRFC, Lodha, DMart, Mazagon Dock…) so they have little/no early history and are
  skipped early by the engine.
- **Why it is still informative:** the iron-rule test is *strategy vs 1/N on the same universe*. The
  survivorship tailwind lifts **both** the strategy and its 1/N baseline, so the **gap (strategy −
  1/N)** is far less biased than the absolute returns. We read the **gap**, not the level.
- **Pre-registered decision rules:**
  - If the strategy does **not** beat 1/N on the gap (full window **and** rolling 3y holds) even with
    this survivorship tailwind → **negative**: breadth does not help; do **not** invest in the
    expensive PIT data work. Try Nifty 200 once (more diversification) under the same rule; if it also
    fails, conclude and keep the product at Nifty 50.
  - If the strategy **does** beat 1/N on the gap → **promising, not a GO.** Green-light Stage 2.
- Config is frozen to the validated product config — **annual rebalance · shrink weighting ·
  force_refresh · §4.6 gate 2.0 · dynamic slippage · band 0.10** — and the sector allocator runs over
  the wider sector set. No parameter tuning.
- Engine reused unmodified; experiment writes to a **separate** price cache
  (`data/historical/prices_<tag>.parquet`) so the validated Nifty-50 PIT panel is untouched.

## Stage 2 — proper PIT validation (only if Stage 1 is promising)
Source a genuine survivorship-free Nifty 100/200 membership (NSE reconstitution circulars /
niftyindices historical constituents), reconstruct intervals as in `build_nifty_universe.py`, then
re-run the full walk-forward. Only a Stage-2 pass can promote the wider universe into the product
default. Until then the product stays at the validated Nifty 50.

## Metrics reported
Full-window CAGR / Sharpe / maxDD net cost+tax; rolling-3y-hold distribution; **strategy − 1/N gap**
at both; per-sector exposure of the selected book; price coverage (how many names actually priced
each year, to expose the listing-truncation bias).
