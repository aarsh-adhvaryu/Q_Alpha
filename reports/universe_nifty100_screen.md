# Stage-1 breadth screen — Nifty 100 (static, biased)

⚠️ **Survivorship-biased static universe — directional screen, NOT a GO.** Read the **strategy − 1/N gap** — but note 1/N-on-survivors is itself the biggest survivorship beneficiary, so even the gap is contaminated; this is directional context only. See `reports/PREREGISTRATION_universe.md`.

Universe: 98 names, 95 priceable by yfinance. Window 2012-01-01..2024-12-31. Config: annual · shrink · force_refresh · §4.6 gate · dynamic slippage.

## Full-window (net cost + tax)

| series | CAGR | Sharpe | maxDD | vs 1/N | vs Nifty-50 TRI |
|---|---|---|---|---|---|
| **Strategy (Nifty 100 (static, biased))** | 16.4% | 1.06 | -27.5% | **-9.9pt** | +2.2pt |
| 1/N (same universe) | 26.3% | — | -36.6% | — | — |
| Nifty-50 TRI | 14.2% | — | — | — | — |

Realized tax ₹77,884 · 12 rebalances · 41 distinct names traded.

## The honest read: strategy − 1/N gap

- Full-window: **-9.9 pts** → DOES NOT beat 1/N on the gap.
- Rolling 3y holds: strategy ≥ 1/N in **16%** of holds; worst-3y gap **-21.5pt**, median **-7.5pt**.
- Strategy worst-3y **-1.0%** vs 1/N **-1.1%**.

## Price coverage by year (exposes mid-window IPO truncation)

| year | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| priced names | 79 | 79 | 79 | 81 | 82 | 85 | 88 | 88 | 90 | 93 | 93 | 94 | 95 |

## Selected book — sector spread (buys across the run)

- FIN: 8
- CHEMICALS: 7
- CONSUMER: 6
- AUTO: 6
- PHARMA: 5
- POWER: 5
- CEMENT: 5
- ENERGY: 5
- METAL: 4
- IT: 4
- FMCG: 3
- INFRA: 3
- REALTY: 1
