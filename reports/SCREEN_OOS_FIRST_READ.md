# The live screen, measured — a first read

**Generated 2026-09-08 by `scripts/exp_screen_oos.py`.** Development evidence. Not out-of-sample
evidence in the pre-registered sense, and it must never be quoted as such.

## The question

`live/deploy.py` ranks names by how far they sit below their own 1-year high (`cheapness_scores`) and
paces deploy size by an index drawdown regime (`market_weakness`). **That is what the ₹5,00,000
runs on, and it had never been tested.** Does the ranking separate future winners from future losers
at all?

## Method

At each month end, rank the eligible universe by cheapness, take the top K, hold one month, and
measure against **the equal-weighted return of the whole eligible set** — 1/N, the benchmark the gate
compares against. Not the cap-weighted index: Phase 4 found 76% of the apparent edge over that index
*is* the equal-weight premium, which anyone can buy.

Universe is `nifty50_membership_2026.csv`, which carries dated entries and exits, so the headline is
point-in-time honest. Non-overlapping monthly periods, so the t-statistic is not inflated by reusing
months. 163 months, 2013-01 → 2026-07, median 49 eligible names.

## The result

| K | mean monthly spread | annualised | t | 95% block-bootstrap CI | months won |
|---:|---:|---:|---:|---|---:|
| 8 | +0.218% | +2.65% | +0.60 | [−0.406%, +0.959%] | 81/163 (50%) |
| 15 | +0.120% | +1.45% | +0.54 | [−0.277%, +0.597%] | 82/163 (50%) |
| 30 | +0.122% | +1.48% | +1.13 | [−0.085%, +0.336%] | 83/163 (51%) |

**Every interval includes zero, and the screen picks winners in half of all months.** On this sample
the ranking cannot be distinguished from 1/N. That is not the same as "it has no edge" — the sample
cannot resolve an edge this small, which is the same power problem `NULL_MATCHED.md` describes — but
it is emphatically not evidence that it works.

## Two things worth more than the headline

**1. Survivorship bias is larger than the entire signal.** The same test on
`nifty100_watchlist.csv` — today's members applied to the past, which is the universe the live screen
*actually runs on* — reports **+6.44%/yr instead of +2.65%/yr**. The bias is worth ~3.8 points a
year, and it is not removable by processing. The live universe cannot be tested honestly until
point-in-time Nifty-100 membership exists.

**2. The regime breakdown is a trap, and it is recorded here so nobody falls into it later.**

| regime | n | mean | sd | t | wins |
|---|---:|---:|---:|---:|---:|
| normal | 95 | −0.128% | 4.06% | −0.31 | 45/95 |
| elevated | 59 | +0.445% | 5.10% | +0.67 | 30/59 |
| **deep** | **9** | **+2.383%** | **7.03%** | **+1.02** | **6/9** |

"Buying weakness pays 2.4%/month in deep drawdowns" is the sentence this table invites. It is not
supportable. Four of those nine months are the 2020 sequence, and inside it the spread ran
**+9.13%, −7.61%, +9.44%, −7.06%** — one episode, sampled four times. Three basket sizes by three
regimes is nine looks at one dataset.

## What this does and does not license

- It does **not** say the strategy is broken. It says the strategy is unproven, which was already
  written in `CLAUDE.md`, now with a number attached.
- It does **not** include costs, tax or slippage, and monthly re-ranking implies turnover the real
  book never pays. Every figure above is an upper bound.
- It does **not** test the live *policy* — buy with new cash and hold. It tests the *signal*.
- It does mean that a full gate-4 replay is worth building, and that its first job is point-in-time
  Nifty-100 membership, without which the live universe cannot be measured at all.

## Reproducing

```bash
uv run python scripts/exp_screen_oos.py                          # the headline, ~10s
uv run python scripts/exp_screen_oos.py --k 8 --biased-universe-too   # with the bias comparison
```
