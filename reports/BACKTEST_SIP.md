# The buy screen, finally backtested (2026-08-20)

The Add-money screen had never been measured against anything. This is that measurement, run on the
user's actual plan — a lump sum followed by a monthly SIP — reproducible with
`uv run python scripts/backtest_sip.py`.

## Headline

₹100,000 initial + ₹50,000/month, **2013-07 → 2026-06**, 156 deploys, ₹7,850,000 contributed.
Costs included (Zerodha model). No selling, so no capital-gains tax on either plan.

| Plan | Ended at | Return | Worst fall |
|---|---:|---:|---:|
| NIFTYBEES (do nothing) | ₹17,763,342 | +126.3% | −35.2% |
| **The screen — point-in-time Nifty-50** | **₹24,307,875** | **+209.7%** | **−34.9%** |
| The screen — today's Nifty-100 | ₹62,096,785 | +691.0% | −42.3% |

**The third row is survivorship-biased and must never be quoted.** It holds today's Nifty-100
constituents fixed across 14 years — every name in it is one that survived to 2026. It is reported
only to size that bias, which is large: it roughly triples the apparent result.

The second row is the honest one. Point-in-time membership, so a name is investable only while it was
actually in the index, and the 36 names that left stay in the simulation for exactly as long as they
were members.

## It is not one lucky stretch

| Start | Contributed | Index | Screen | Worst fall (index / screen) |
|---|---:|---:|---:|---|
| 2013-07 | ₹7,850,000 | +126.3% | +209.7% | −35.2% / −34.9% |
| 2015-01 | ₹6,950,000 | +102.8% | +190.7% | −34.7% / −37.7% |
| 2018-01 | ₹5,150,000 | +64.6% | +131.5% | −33.1% / −30.3% |
| 2021-01 | ₹3,350,000 | +26.0% | +62.4% | −12.8% / −14.9% |
| 2023-01 | ₹2,150,000 | +10.1% | +23.7% | −11.8% / −10.7% |

Five start dates, five wins, with drawdown broadly matching the index rather than being bought with
extra risk. Nor is it knife-edge on the concentration dial — 5, 8, 12 and 20 names give +231%, +210%,
+197%, +221%, all comfortably ahead of +126%.

## What the health filter actually does

| | Return | Worst fall |
|---|---:|---:|
| Core rule only | +220.7% | **−48.3%** |
| With the breakdown filter | +209.7% | **−34.9%** |

It **costs about 11 points of return and removes 13 points of drawdown.** It is a risk control, not a
return enhancer, and it should be described that way. Anyone optimising for the headline number would
switch it off; anyone who has to live through the drawdown probably should not.

## Does an optimizer earn its keep? No — and this is the most useful result here

Same plan, same dates, same money. The only change is whether anything is ever **sold**, with the
real capital-gains bill applied through the validated FIFO/tax engine.

| Plan | Return | Worst fall | Trades | CG tax paid |
|---|---:|---:|---:|---:|
| NIFTYBEES (do nothing) | +126.3% | −35.2% | 156 | ₹0 |
| **Buy & hold + SIP** *(what the advisor does today)* | **+209.7%** | **−34.9%** | 299 | **₹0** |
| + sell what breaks down | +149.5% | −42.4% | 455 | ₹997,724 |
| + annual rebalance to equal weight | +206.3% | −37.0% | 489 | ₹930,456 |

**Selling the broken names costs 60 points of return and makes the drawdown worse** (−34.9% →
−42.4%). It is the intuitive move and it is wrong twice over: ₹9.98 lakh goes to capital-gains tax,
and selling after a fall realises the loss and forfeits the recovery. Annual rebalancing is
near-neutral before tax and clearly negative after it — ₹9.3 lakh to move money between names that
were already fine.

This reproduces, on a different strategy, the finding the research repo already reached with the HMM
defensive overlay: **in a taxable Indian account, selling to manage risk loses to the tax.**

The distinction that matters, because it is easy to get backwards:

* Using the breakdown test **to decide what to buy** — worth it. Cuts drawdown 48% → 35%.
* Using the same test **to decide what to sell** — costs 60 points of return.

So the right answer for the real-money account is the one already implemented: **new money is the
only lever.** Route each contribution to what is underweight and healthy, and never sell to fix
anything. Not selling *is* the optimiser. The advisor's Sell and Raise-cash tabs remain for when the
user needs the money — which is a different question from optimisation, and is priced exactly.

## Rebalancing with the inflow instead of the sell button

The user's follow-up, and the right one: *"it knows the distribution of the portfolio — instead of
selling it, it balances it in the next buy."* That is rebalancing with a ₹0 tax bill, which is the
only kind the table above says is affordable.

The routing already did some of this — the largest position reached 10.8%, not 30%. The gap was the
**tail**: a holding that slipped out of the fresh `max_names` ranking was stranded at whatever weight
it happened to reach and never topped up again. So `max_names` now caps how many *new* names may be
opened, while every healthy holding stays eligible for the inflow.

| | before | after |
|---|---:|---:|
| largest position | 10.8% | **7.8%** |
| smallest | 0.7% | **1.9%** |
| top-3 concentration | 29.4% | **22.1%** |
| positions under 2% | 3 | **1** |

**On return it is a wash, and that should be stated plainly** — +215.6% / +185.1% / +131.4% / +59.6%
from 2013 / 2015 / 2018 / 2021, against +209.7% / +190.7% / +131.5% / +62.4% before. Mixed in both
directions by about three points, which is noise, not evidence.

So this is a **portfolio-quality** change, not an alpha change: better balanced, no dust positions,
less single-name concentration, zero tax, no extra selling. Worth having on those grounds alone, and
not worth claiming anything more for.

## What this does not establish

- **Five merged names have no price data** — CAIRN, HDFC, IDFC, LTIM, STER (all absorbed into other
  listed entities, none a failure). The simulation could never buy them. A real gap, though mergers
  generally realise value, so the direction of the bias is not obviously favourable.
- **The guards were designed in August 2026 and then run over 2013–2026.** The continuity guard,
  breakdown filter and stickiness rule are therefore not cleanly out-of-sample. The *core* rule
  (furthest below its own 1-year high, sector-capped, equal-weight-ish) predates this work, and the
  core rule alone is what produces most of the return — which is the more reassuring reading.
- **One backtest is not a strategy.** No walk-forward, no parameter-stability study, no transaction
  slippage beyond the modelled costs, and the whole thing is a value/mean-reversion tilt inside the
  Nifty 50 — a well-documented factor that has had long periods of underperformance elsewhere.
- **It says nothing about the next 13 years.**

## A data defect found along the way

The NIFTYBEES benchmark carried **two corrupt prints** — ₹13.02 against a true level near ₹129 on
2019-12-19 and 2019-12-20, then a snap back. Left in, they gave the baseline a fake −89.9% drawdown
and told `market_weakness` the index was 90% below its 1-year high, which would have deployed an
entire wallet on a typo. `repair_price_spikes` now fixes round trips like that — and *only* round
trips: a fall that persists is left completely alone, so the 2020 COVID crash (−36.3%) survives
untouched. Wired into the live benchmark loader as well as this backtest.
