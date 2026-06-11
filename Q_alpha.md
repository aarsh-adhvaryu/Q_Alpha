# Q-Alpha v3.1 — System Architecture

**Version 3.1 | May 2026**
**Status: Reworked. Incorporates fixes from 3 independent adversarial reviews + architectural decisions. Ready for implementation.**

---

## 0. Personal risk policy

**This section overrides everything. If any rule in this document conflicts with these constraints, these constraints win.**

- **Maximum portfolio drawdown:** 20% from peak. If total portfolio market value drops 20% from its highest recorded value, the system enters FULL FREEZE. All new buys halt (tactical, contingency, rebalancing). Only manual human override can resume activity. This is not a recommendation — it is a hard circuit breaker.
- **Maximum single-position loss:** No single position (core or tactical) may lose more than 5% of total capital (₹10,000 on ₹2L). If circuit-lock or gap-down makes this inevitable, the system escalates to human decision immediately.
- **Maximum tactical exposure:** Tactical losses in any rolling 30-day window must not exceed 8% of total capital.
- **Emergency money:** Capital deployed into Q-Alpha is never emergency money. The system assumes this capital can be locked for 12+ months without personal financial stress.
- **Data disagreement freeze:** If broker data, database state, and exchange data disagree on holdings or prices, no trade recommendation is generated. System outputs "DATA CONFLICT — NO ACTION."
- **System-down assumption:** If the local machine is offline during market hours, no trade happens. The system is designed so that missing a day is always safe.

---

## 1. Core philosophy

**Q-Alpha is a scalable wealth engine. ₹2,00,000 is day one, not the ceiling.**

The long-term objective is a system that compounds capital over a 10+ year horizon — starting from ₹2L of personal savings, growing through fresh capital injections (career income), tactical alpha, and compounding returns. The same codebase that manages ₹2L today manages ₹2Cr in year 8. The mathematical boundaries expand organically as capital grows; the architecture never needs rewriting.

**Why start at ₹2L?** Because it's the hardest environment. Transaction fees are regressive, position sizes are constrained, and a single mistake is expensive relative to capital. A system that survives ₹2L works effortlessly at ₹2Cr, where friction becomes invisible and the optimizer can fully flex. Starting small is the stress test, not the scope.

**v1 scope:** India-only. Zero infrastructure cost. Decision-support terminal first. Earn trust, then expand authority. NSE/BSE equities. Local hardware (RTX 5070 Ti, Docker Compose). Manual execution with system-generated order tickets.

**What this system is:** A quantitative analyst that watches your portfolio 24/7, calculates exact risk-adjusted actions, and tells you precisely what to do, why, and at what price — adapting its strategy, concentration, and risk posture as your capital base deepens.

**What this system is not:** An autonomous trading bot. In v1, every order requires manual human approval.

**Design principles:**

- The math gives you direction, the rules give you safety. Neither alone is sufficient.
- The system's default state is **"do nothing."** Every action must clear a net-benefit threshold after transaction costs and taxes.
- Market value drives all risk decisions. Cost basis drives all accounting decisions. Never mix them.
- No market orders under normal conditions. Limit orders only. (Stop-loss escalation protocol is the sole exception — see Section 4.8.)
- UTC everywhere except the display layer.
- All financial values stored as NUMERIC(15,6), never FLOAT.
- **Backtest before you build.** Strategy validation comes before infrastructure investment.

---

## 2. Capital structure

**Starting capital: ₹2,00,000. Target ratio: 50/25/25 (Core / Tactical / Contingency).**

The ratio stays constant as capital grows. What changes is the system's *behaviour* — as AUM increases, friction drops, the optimizer unlocks, and the risk posture matures.

### 2.0 Capital milestone transitions

The system adapts its constraints automatically based on total AUM. No code changes required — just parameter thresholds.

| AUM | Phase | Core Stocks | System Behaviour |
|---|---|---|---|
| **₹2L–₹10L** | Scrappy Fighter | 5–6 | High friction. Sniper mode. Refuses trades where fees > alpha. Tactical is the primary growth engine. Graduates wins into Core. |
| **₹10L–₹50L** | Tactical Allocator | 8–12 | Friction drops. Core expands organically. Min-variance optimizer runs without being blocked by cost gates on every rebalance. Tax-loss harvesting activates. |
| **₹50L–₹2Cr** | Institutional Grade | 12–15 | Full optimizer flexibility. QUBO/VQE becomes relevant for integer-constrained allocation across 15+ stocks. Slippage replaces DP charges as primary friction. |
| **₹2Cr+** | Wealth Preservation | 15–20 | Capital preservation equals growth in importance. Anomaly detection and Deep Freeze are the most critical systems. Defensive posture. |

**Scaling formula for stock count:**

```
max_core_stocks = min(20, max(5, floor(total_core_capital / 200000) + 4))
```

At ₹1L core: 5 stocks. At ₹10L: 9. At ₹32L: 20 (capped). Ensures no position is ever small enough for flat DP charges to create >1% regressive drag.

### 2.1 Core Portfolio — ₹1,00,000 (starting)

**Purpose:** Long-term strategic allocation. This is the compounding engine — where tactical wins, fresh capital injections, and dividend reinvestments accumulate over 10+ years.

**Governed by:** Sector Allocator + Portfolio Optimizer.

**Behaviour:**

- Invested across NSE/BSE stocks, diversified by sector within the stock-count constraint.
- Rebalanced only when portfolio drift exceeds threshold (5–10% deviation from target weights) AND net benefit after transaction costs and capital gains tax exceeds minimum bar.
- Rarely touched. Weeks or months between rebalances.
- Never sold to fund tactical trades or contingency actions.

**Rule:** Capital never flows out of this pool via selling. It only receives inflows (tactical graduations, contingency defense purchases, fresh capital overflow).

### 2.2 Tactical Fund — ₹50,000

**Purpose:** Short-to-medium term opportunistic trades. Momentum plays, breakout entries, sector rotation opportunities.

**Governed by:** Classical Screener (operating within boundaries set by Sector Allocator).

**Behaviour:**

- Deploys in chunks of ~₹25,000 (two positions max). HDFC's fee structure makes smaller chunks uneconomical.
- Existing tactical positions are not reshuffled to fund new ones. New deployments use remaining free cash (settled only).
- Screener runs a daily "recycle check" — if a tactical position has played out (hit target, stopped out, thesis expired), that capital returns to the pool after T+1 settlement.

**Rule:** Operates only within sectors approved by the Sector Allocator.

### 2.3 Tactical exit rules

Every tactical position has explicit exit conditions evaluated daily. **All evaluations use Total Return-adjusted prices — an ex-date dividend drop does not trigger a stop loss.**

**Volatility-adjusted stop loss (replaces flat 12%):**

The stop distance is set at entry using the stock's Average True Range (ATR):

```
stop_price = entry_price - (k × ATR_20)
```

Where `k` is the risk multiplier (default: 2.0). This means:

- A low-volatility utility stock (ATR = 1.5%) gets a ~3% stop. A 3% drop in a boring stock IS a structural event.
- A volatile small-cap (ATR = 4%) gets an ~8% stop. An 8% drop is just noise for this stock.

**Hard floor:** Stop distance is never wider than 12% regardless of ATR. Capital protection overrides volatility modeling.

**Trailing stop:** Once a position is up 10%+, a trailing stop activates at `2 × ATR_20` below the peak. Locks in gains while letting winners run.

**Profit target:** If a position reaches 25%+ gain, the system recommends taking partial profits (sell 50%, let the rest ride with trailing stop).

**Maximum holding period:** 120 days. If a position hasn't graduated to core or hit any other exit condition, the system forces a review: graduate it, exit it, or explicitly renew the thesis for another 60 days.

**Thesis expiry (2-of-3 confirmation required):**

Thesis is expired only when at least two of these three conditions are true simultaneously:

1. Factor score falls below bottom 40th percentile for **5 consecutive trading days** (not a single-day blip).
2. Price breaks the volatility-adjusted risk level (stop loss).
3. Sector allocator restricts the stock's sector.

This prevents churn from temporary rank shifts when the universe changes.

**Earnings blackout:** No fresh tactical entry within 5 trading days of a stock's scheduled earnings date. Existing positions near earnings get a dashboard notification but no automatic action — user decides.

### 2.4 Contingency Reserve — ₹50,000

**Purpose:** Core portfolio's defense fund. Insurance capital that sits idle until a high-conviction systemic signal fires. Must be held as settled cash — instantly deployable.

**Governed by:** Anomaly Detector (advisory in v1 — human approves all deployments).

**Tranche deployment (never deploy full reserve at once):**

| Tranche | Amount | Trigger |
|---|---|---|
| Tranche 1 | 25% (₹12,500) | Anomaly detector HIGH_CONVICTION + systemic drop confirmed |
| Tranche 2 | 25% (₹12,500) | Market drops another 5–7% from Tranche 1 deployment, OR stabilization for 5 trading days |
| Tranche 3 | 25% (₹12,500) | Recovery confirmation (index recovers 3%+ from trough) |
| Tranche 4 | 25% (₹12,500) | Reserved. Deployed only in extreme event (>30% index drawdown) |

**Deployment modes (in priority order):**

**Mode 1 — Dynamic Target Rebalancing.** A core holding drops in a systemic event. The optimizer recalculates target weights using current conditions. Contingency deploys capital to bring the holding back to the optimizer's *new* target — not the old one. If the optimizer drops TCS's target from 5% to 3% because the crash revealed structural weakness, contingency fills to 3%.

**Mode 2 — Crash opportunity.** Market-wide crash creates buying opportunities in quality stocks not currently held.

**Mode 3 — Rebalance support.** Optimizer says increase a sector allocation, but selling other holdings would incur unfavorable tax. Contingency funds the purchase instead.

**Deployment blacklist (never deploy into):**

- Stocks under ASM/GSM/high surveillance framework
- Companies with pledged promoter holding >40%
- Companies with recent auditor resignation
- Stocks with unresolved corporate action or data quality issue
- Stocks at lower circuit with zero buyers

**Critical:** Systemic vs. idiosyncratic classifier (Section 3.5) must confirm the drop is systemic before contingency deploys. Idiosyncratic drops → blocked.

### 2.5 Capital flow rules

```
Core Portfolio ← (never flows out via selling)
    ↑ receives from: Contingency (Mode 1/3), Tactical (graduation)

Tactical Fund ↔ Contingency Reserve
    → to Contingency: profits from closed positions, bubble exit
    ← from Contingency: crash opportunity (Mode 2)

Contingency Reserve → Core (Mode 1, Mode 3)
                    → Tactical (Mode 2)
                    ← Tactical (absorb profits, bubble exit)
```

**Hard constraint:** Core never flows outward.

### 2.6 Dual-ledger accounting

Two parallel state views. Using the wrong view for the wrong purpose breaks the math.

**Risk/Compute View (Market Value):** Feeds the optimizer, CVaR, drift detection, rebalancing triggers, sector weights, pool ratios for risk. Reflects reality right now.

**Accounting/Routing View (Cost Basis):** Tracks actual capital deployed, unrealized PnL, tax liability, and dictates where fresh capital goes based on target pool ratios.

Per-position fields:

- `cost_basis` (NUMERIC) — what you paid. Accounting view.
- `cumulative_dividends` (NUMERIC) — total dividends received in bank account.
- `effective_cost_basis` (NUMERIC) — cost_basis minus cumulative_dividends. **Display layer only. Never enters any compute layer, risk model, or decision engine.** A stock at ₹90 with effective cost basis ₹80 is still underperforming — the dividend doesn't change the market reality.
- `market_value` (NUMERIC) — current value. Risk view.
- `unrealized_pnl` (NUMERIC) — market_value minus cost_basis. Dashboard display.

**Critical rule: Market value for risk. Cost basis for accounting. Effective cost basis for display only.**

### 2.7 Tax lot FIFO ledger

**Indian demat accounts use strict First-In-First-Out (FIFO) for tax purposes.** The system cannot track a single `entry_date` per position. It must track individual lots.

**`portfolio.tax_lots` table:**

| Column | Type | Purpose |
|---|---|---|
| lot_id | UUID | Primary key |
| ticker | TEXT | Stock symbol |
| isin | TEXT | ISIN for cross-reference |
| broker_trade_id | TEXT | Links to broker's contract note |
| acquisition_date | TIMESTAMP WITH TIME ZONE | Purchase date (UTC) |
| quantity_original | NUMERIC | Shares bought in this lot |
| quantity_remaining | NUMERIC | Shares not yet sold |
| buy_price | NUMERIC | Price per share |
| brokerage | NUMERIC | Brokerage paid |
| stamp_duty | NUMERIC | Stamp duty paid |
| other_costs | NUMERIC | GST, exchange charges, etc. |
| pool | TEXT | core / tactical / contingency |
| corporate_action_adjustments | JSONB | Split/bonus/merger adjustments applied |

**On every sell, the system consumes lots FIFO:**

```
Sell 6 shares of TCS:
  → Lot 1 (Jan 2025, 2 shares, ₹3,700): consume fully. Holding > 365 days → LTCG.
  → Lot 2 (Aug 2025, 4 of 8 shares): consume 4. Holding < 365 days → STCG.
  → Calculate tax per consumed lot.
  → Log to portfolio.lot_consumptions.
```

**STT is NOT deductible when calculating capital gains.** The cost model includes STT for total transaction cost, but the tax engine excludes it from the capital gains computation per Income Tax Department rules.

**Pool assignment is an overlay on the lot ledger.** If the system thinks it's selling "tactical" shares but FIFO consumes "core" lots (because the core lots are older), the dual ledger must reconcile.

**Supporting tables:**

- `portfolio.lot_consumptions` — records which lots were consumed per sell event
- `portfolio.corporate_action_lot_adjustments` — tracks how splits/bonuses modify existing lots
- `portfolio.realized_gain_events` — per-lot realized STCG/LTCG with full cost breakdown

### 2.8 Ratio-based pool scaling

Target ratio: 50/25/25 (Core / Tactical / Contingency).

**Risk assessment:** Ratios computed on market value.
**Fresh capital routing:** Ratios computed on cost basis.

### 2.9 Fresh capital injection routing

When new capital enters (bank → trading account), routed in strict order:

1. Refill Contingency to ratio target (cost basis).
2. Refill Tactical to ratio target (cost basis).
3. Overflow to Core. Optimizer identifies underweight positions. New capital buys into gaps — rebalancing without selling.

### 2.10 Position graduation (Tactical → Core)

**All three must align:**

- Held 60–90+ days and still performing.
- Portfolio optimizer confirms it improves core diversification.
- Sector allocator confirms sector is a long-term target.

Check frequency: weekly. `entry_date` does NOT reset on graduation.

### 2.11 Tactical fund exhaustion — smart recycling

When tactical is fully deployed and a new opportunity appears:

1. Compare new candidate's factor score against existing positions.
2. New stock must score ≥15 percentile points higher than the weakest position.
3. Minimum holding period (15 days) prevents churning.
4. Recycling is a two-day operation (T+1 settlement).

### 2.12 Dividend handling

Dividends in India are credited to the linked savings bank account, not the broker's trading ledger.

- `dividend_received` ledger logs every dividend with ex-date, record date, amount, ticker.
- `cumulative_dividends` on the holding updated for effective cost basis (display only).
- Dividends never enter `settled_cash` or `unsettled_cash`.
- Cash becomes deployable only via manual `capital_injection` event.

### 2.13 Settlement state machine

Every pool's cash exists in one of three states:

- `settled_cash` (NUMERIC) — available for deployment. Only this feeds the decision engine.
- `unsettled_cash` (NUMERIC) — proceeds from a sell, locked until settlement.
- `external_cash` — dividends/profits in bank account. Not visible to the decision engine.

**Settlement types:**

| Type | Duration | Notes |
|---|---|---|
| T_PLUS_1 | Next trading day | Standard equity settlement |
| T_PLUS_0 | Same day | NSE T+0 segment (schema-ready, not used in v1) |
| AUCTION_T_PLUS_2 | T+2 | Auction settlement |
| BROKER_BLOCKED | Manual | Broker-specific holds |

Settlement calendar uses the NSE holiday calendar (Section 11.1). T+1 means next *trading* day.

**Contingency must be settled_cash.** Cannot wait for settlement during a crash.

---

## 3. Compute layers

### 3.1 Architecture: The Funnel

The system processes data in a three-stage funnel. Wide scan, intelligent filter, precise allocation.

```
Stage 1: Screener (100-200 stocks → top 15-20 candidates)
    ↓
Stage 2: Sector Allocator (sets sector weight boundaries)
    ↓
Stage 3: Portfolio Optimizer (finds exact stock weights within boundaries)
```

### 3.2 Classical Screener (GPU — daily)

**Runs on:** RTX 5070 Ti (PyTorch + CUDA)

**Input:** 100–200 NSE/BSE stocks (v1 watchlist). All returns are Total Return-adjusted.

**Pre-screening gates (hard filters before scoring):**

**Volume-Velocity Gate:** Zero trading volume for 3+ consecutive days → hard ban. Catches regulatory halts, SEBI suspensions, insolvency freezes.

**Liquidity Gate (FIXED — v3.0 had a math contradiction):**

The order size cap is 1% of ADV. Therefore, to deploy a ₹25,000 chunk in a single order:

```
Required: 1% × ADV ≥ ₹25,000
Therefore: ADV ≥ ₹25,00,000 (₹25L)
```

Minimum 20-day ADV thresholds:

| Pool | Min ADV |
|---|---|
| Tactical (₹25K chunks) | ₹25L |
| Core (₹20K+ positions) | ₹50L |

Stocks below threshold are excluded entirely. This deliberately excludes illiquid small/mid-caps. For ₹2L capital, skipping illiquid names is safer than modeling slippage.

**Six-factor scoring model with regime-adaptive weights:**

Each factor computed as a percentile rank within sector:

1. **Momentum:** 12-month TR-adjusted return minus most recent 1-month return (skip short-term reversal noise).
2. **Value:** Average of sector-relative percentile ranks for P/E, P/B, and EV/EBITDA. Low = cheap = high score.
3. **Quality:** ROE, debt-to-equity, earnings consistency (σ of quarterly EPS growth over 3 years).
4. **Volatility:** 30-day realized volatility on TR-adjusted returns (annualized). Lower is better. Not sector-normalized.
5. **Liquidity:** 20-day ADV in ₹. Higher is better.
6. **Dividend consistency:** Consecutive years of dividend payment or growth. Consistency, not yield.

**Regime-adaptive weights:**

| Regime | Momentum | Value | Quality | Volatility | Liquidity | Dividend |
|---|---|---|---|---|---|---|
| Bull | 25% | 15% | 20% | 15% | 10% | 15% |
| Bear | 10% | 20% | 25% | 15% | 10% | 20% |
| High Vol | 10% | 15% | 20% | 25% | 15% | 15% |
| Crash | 10% | 25% | 25% | 10% | 10% | 20% |
| Rotation | 25% | 15% | 20% | 15% | 10% | 15% |

**Composite score:** Weighted average of all six factor percentile ranks. Range: 0–100.

**Output:** Ranked stock list, tactical candidates (within approved sectors, above conviction threshold), sector rotation flags.

**Frequency:** Every Indian market day.

### 3.3 Sector Allocator (scipy — weekly)

**Production: scipy constrained optimization. No C++ subprocess in the operational pipeline.**

For v1 with ~12 NSE sectors, this is a convex optimization problem with 12 continuous variables. scipy solves it in milliseconds with guaranteed optimality.

**Input:** Sector-level covariance matrix computed from constituent stock returns. Ledoit-Wolf shrinkage-corrected (Section 3.8).

**Method:** Minimize portfolio variance subject to constraints:

```
minimize: w^T Σ w     (portfolio variance)
subject to:
  Σ w_i = 1           (weights sum to 100%)
  0.05 ≤ w_i ≤ 0.30   (each sector 5%–30%)
```

**Output:** Target sector weights, approved/restricted sector flags for the screener.

**Frequency:** Weekly, or triggered early when screener flags significant sector rotation.

**Authority:** Sets the playing field. The screener cannot override sector boundaries.

**QUBO/VQE lives in `research/` only.** See Section 15.

### 3.4 Portfolio Optimizer (scipy — on drift trigger)

**Production: scipy.optimize.minimize (SLSQP).**

**Method: Minimum-variance optimization.**

This deliberately avoids estimating expected returns. Expected return estimation is the most fragile input to Markowitz — small changes produce wildly different allocations. At ₹2L capital, this creates fake precision. Minimum-variance optimization uses only the covariance matrix (which Ledoit-Wolf stabilizes well) and finds the portfolio with the lowest risk for a given set of constraints.

```
minimize: w^T Σ w
subject to:
  Σ w_i = 1
  w_min ≤ w_i ≤ w_max  (per stock, derived from sector allocator bounds)
  max single stock: 20% of core
```

**Tax-aware transaction cost gate (see Section 4.6):** Before any sell recommendation, computes total cost including brokerage, STT, GST, stamp duty, DP charges, expected slippage, AND capital gains tax (per FIFO lot consumption). If net benefit after ALL costs falls below minimum threshold, recommendation is suppressed.

**STCG→LTCG boundary protection:** If the oldest unconsumed lot for a holding is between 330 and 365 days old, a penalty multiplier is applied. **The penalty decays linearly:**

```
days_remaining = 365 - lot_age
penalty = 1.0 + (2.0 × days_remaining / 35)
```

At 330 days: 3.0× penalty. At 350 days: 1.86× penalty. At 364 days: 1.06× penalty.

**Override:** Any anomaly detector HIGH_CONVICTION signal bypasses the tax penalty entirely. If the math says get out, get out.

**Drift measurement:** Sum of absolute deviations between current weights (market value) and target weights, divided by 2.

**Frequency:** Only when drift > threshold (5–10%).

### 3.5 Anomaly Detector (GPU — daily)

**Runs on:** RTX 5070 Ti (PyTorch). Pure mathematical signal.

**Input:** Rolling correlation matrix of the watchlist. Ledoit-Wolf shrinkage-corrected and EWMA-weighted (half-life ~60 trading days).

**Method:** Tracks the eigenvalue structure of the correlation matrix.

**Eigenvalue normalization (Marchenko-Pastur):** Raw eigenvalues are unreliable when the watchlist size changes (quarterly revisions). The system normalizes the largest eigenvalue against the theoretical upper bound for a random matrix of the same dimensions:

```
λ_MP_upper = σ² × (1 + √(N/T))²

signal_ratio = λ_max_observed / λ_MP_upper
```

When `signal_ratio >> 1`, the largest eigenvalue reflects genuine market-wide correlation clustering (systemic risk). When `signal_ratio ≈ 1`, it's just noise. This is dimensionally stable — adding/removing stocks changes both observed and expected eigenvalues proportionally.

**Crash signal:** `signal_ratio` rising sharply → everything moving together → systemic risk.

**Bubble signal:** A sector's eigenvalue contribution decouples from fundamental Z-scores (EV/EBITDA, P/E relative to 3-year rolling mean). Specifically: sector's eigenvalue loading increases while its fundamental Z-score exceeds +2.5σ.

**Output:**

- Confidence score: 0–100.
- Risk classification: NORMAL (0–39) / ELEVATED (40–69) / HIGH_CONVICTION (70–100).
- Affected sectors identified.

**v1 authority: ADVISORY ONLY.** The anomaly detector alerts, freezes tactical, and recommends contingency deployment. It does NOT auto-deploy contingency. Human approval is required for all contingency actions. After 50+ validated events across multiple regimes, auto-deployment authority may be granted in v2.

**Veto power retained:** Can freeze tactical deployments and pause scheduled rebalances without human approval. Freezing is always safe.

### 3.6 Systemic vs. idiosyncratic drop classifier

**Activation:** When a core holding drops >5% in a day or >15% over 5 trading days (TR-adjusted returns).

**Three checks:**

- Is the stock's sector index also down?
- Are 3+ peer stocks (same sector, similar market cap) also down >3%?
- Is Nifty 50 also down >2%?

**Output:** SYSTEMIC (2–3 met) / IDIOSYNCRATIC (0 met) / AMBIGUOUS (1 met).

- SYSTEMIC → Contingency eligible (human-approved in v1).
- IDIOSYNCRATIC → Contingency blocked.
- AMBIGUOUS → No action. Monitor 2–3 more days.

### 3.7 Monte Carlo risk engine (PyTorch — gated)

**Does NOT run every day.** If core is rarely touched, daily 100K simulations are wasted compute.

**Trigger conditions (at least one):**

1. Daily drift checker flags drift > 5%.
2. Anomaly detector escalates to ELEVATED (40+) or HIGH_CONVICTION (70+).

**If drift < 5% and regime is NORMAL:** Skip. Log yesterday's CVaR. Move on.

**When triggered:**

- **Quasi-Monte Carlo (Sobol sequences):** 10,000 scenarios via `torch.quasirandom.SobolEngine`. Sobol sequences converge at O(1/N) vs O(1/√N) for pseudo-random. 10K Sobol ≈ 100K pseudo-random in accuracy. Cuts compute time by ~90%.
- Distribution: Student-t (4–5 df) with jump-diffusion component for overnight gaps.
- Correlated scenarios via Cholesky decomposition of Ledoit-Wolf covariance matrix.
- CVaR at 95% confidence.

**Per-pool risk metrics:**

- Core CVaR: 30-day horizon.
- Tactical CVaR: 7-day horizon.
- Total CVaR: combined, accounting for cross-pool correlations.

### 3.8 Matrix conditioning (Ledoit-Wolf + EWMA)

**Mandatory preprocessing before any matrix enters a compute layer:**

1. EWMA weighting on returns (half-life ~60 trading days).
2. Ledoit-Wolf shrinkage on the covariance matrix (`sklearn.covariance.LedoitWolf`).
3. Applied before eigenvalue analysis, sector allocator, and portfolio optimizer.

### 3.9 Circuit breaker awareness

Indian exchanges enforce price bands (5%, 10%, 20% circuits).

**Circuit cascade estimation:** When a tactical position hits lower circuit, the system immediately calculates worst-case loss assuming 3 more circuit-locked days. If that worst case exceeds 5% of total capital, the system escalates to human decision rather than queuing a standard limit sell.

**Impact on Monte Carlo:** Jump-diffusion component models gap-down events with no intermediate prices.

### 3.10 Corporate action gatekeeper

**Before processing any price drop >10% in a single day, check for corporate actions.**

**Covered corporate actions (v3.1 expanded list):**

| Action | Impact | Handling |
|---|---|---|
| Stock split | Price/quantity adjustment | Adjust all tax lots, stops, factor data |
| Bonus issue | Quantity increase | Create new lot with ₹0 cost basis |
| Rights issue | Offer to buy at discount | Alert user, pause automated analysis |
| Dividend | Ex-date price drop | TR adjustment in data pipeline |
| Merger | Shares converted | Adjust lots, create merger_credit transaction |
| Demerger | New shares issued | Create demerger_credit lots |
| Symbol/ISIN change | Ticker changes | Update all references |
| Buyback | Tender offer | Alert user — different tax treatment from exchange sale |
| Delisting | Trading suspended | Freeze ticker, escalate to human |
| ASM/GSM movement | Surveillance framework | Add to deployment blacklist |
| Face value change | Nominal adjustment | Adjust lot records |

**Transaction types for the tax engine:**

```
exchange_buy, exchange_sell, buyback_tender, bonus_credit,
split_adjustment, rights_issue, merger_credit, demerger_credit,
delisting_exit, face_value_change
```

If a corporate action is detected, the "drop" is reclassified as a data adjustment, not a market event. All downstream signals operate on adjusted data.

**Unrecognized corporate action:** Freeze that ticker. No recommendations until manually resolved.

### 3.11 Corporate event scanner (governance risk filter)

**Purpose:** Catches factual governance and regulatory events that price/volume data won’t show until it’s too late. This is not sentiment analysis — it’s structured event detection from official sources.

**Sources (machine-readable, not opinion pieces):**

- NSE circulars and announcements
- BSE corporate announcements
- SEBI orders and enforcement actions
- Exchange surveillance actions (ASM/GSM stage changes)

**Events tracked:**

| Event | Severity | Action |
|---|---|---|
| Auditor resignation | CRITICAL | Freeze ticker. No deployment until manually reviewed. |
| SEBI investigation opened | CRITICAL | Freeze ticker. |
| Credit rating downgrade | HIGH | Flag on dashboard. Block new tactical entry. |
| Promoter pledge increase > 40% | HIGH | Add to contingency deployment blacklist. |
| Management change (CEO/CFO) | MEDIUM | Dashboard alert. No automatic action. |
| Related-party transaction flagged | MEDIUM | Dashboard alert. |
| ASM/GSM stage change | HIGH | Update deployment blacklist. Freeze if Stage 2+. |
| Bulk/block deal by promoter (selling) | MEDIUM | Dashboard alert with context. |

**Authority:** Can block and flag. Can never generate a buy signal. It only says “wait” or “be careful,” never “go.”

**Integration with learning pipeline (Tier 1):** Over time, the feedback table tracks whether corporate event flags actually predicted negative outcomes. If promoter pledge alerts are consistently followed by drops, the quarterly review notes this. If SEBI investigation alerts are noise 80% of the time, the flag severity may be downgraded from CRITICAL to HIGH.

**For holdings you own:** Immediate dashboard alert. If CRITICAL severity, ticker is frozen from any new deployment.

**For screener recommendations:** Recommendation is held and annotated. "The screener rates this stock highly, but note: promoter pledging increased 12% last week.”

---

## 4. Decision engine

Deterministic rule book. Default output: **"no change today."**

### 4.1 Authority hierarchy

```
Priority 1: Personal Risk Policy (Section 0) — absolute override
    ↓
Priority 2: Anomaly Detector (advisory + freeze power)
    ↓
Priority 3: Sector Allocator (boundary setting)
    ↓
Priority 4: Screener (stock selection) + Optimizer (weight adjustment)
```

### 4.2 Decision sequence (every market day)

1. **Check personal risk circuit breakers.** Portfolio drawdown > 20%? → FULL FREEZE. Skip everything.

2. **Check data confidence.** Cross-validate HDFC holdings vs. database state vs. bhavcopy prices. If discrepancy → DATA CONFLICT, no recommendations.

3. **Check anomaly flags.**
   - HIGH_CONVICTION + crash → freeze tactical, recommend contingency deployment (human approves). Skip to step 6.
   - HIGH_CONVICTION + bubble(sector) → recommend pulling tactical from sector. Continue.
   - ELEVATED → continue, pre-compute contingency plans.
   - NORMAL → continue.

4. **Process tactical.** Check exits first (ATR stop, trailing stop, profit target, max hold, thesis expiry). Check earnings blackout. Check if settled_cash ≥ ₹25,000. If candidate available and passes cost gate → generate recommendation.

5. **Check core drift.** If drift > threshold → optimizer → FIFO tax-aware cost gate → if net benefit positive → generate rebalance recommendation.

6. **Package and deliver.** Each recommendation includes: limit price, expiry window (±3%), settlement-aware execution date, FIFO tax impact estimate, reason codes, do-nothing baseline comparison.

### 4.3 Pre-open sanity gate (9:14 AM IST)

Polls NSE pre-open equilibrium price for every pending recommendation:

- Within 2%: recommendation stands.
- 2–5%: flagged stale. Warning notification.
- Greater than 5%: automatically invalidated. Sent for recalculation.

If Nifty 50 pre-open is down >3%, ALL pending recommendations held until anomaly detector runs fresh.

### 4.4 Confidence thresholds

0–39 (NORMAL): routine. 40–69 (ELEVATED): increased monitoring, pre-computed plans, no action. 70–100 (HIGH_CONVICTION): contingency recommendations, tactical freezes, crash protocols.

Calibrated via backtesting against historical events (2020 COVID, 2022 rate hikes, 2024 yen carry trade).

### 4.5 Cooldown periods

- Contingency tranche: 5 trading days between tranches.
- Tactical swap: 15 trading days.
- Rebalance: 30 trading days.
- Override: only anomaly detector HIGH_CONVICTION breaks a cooldown.

### 4.6 Tax-aware transaction cost model

Every sell recommendation passes through this model with FIFO lot consumption.

Total cost = sum of:

- Brokerage (HDFC rate)
- STT (0.1% delivery) — tracked as cost but **excluded from capital gains computation**
- GST (18% on brokerage)
- SEBI turnover fee (0.0001%)
- Exchange transaction charges (~0.00345%)
- Stamp duty (~0.015% buy side)
- DP charges (₹15–20 per sell)
- Expected slippage (based on bid-ask spread and ADV)
- Capital gains tax per FIFO lot: STCG at 20% (holding < 365 days) or LTCG at 12.5% (≥ 365 days, above ₹1.25L annual exemption)

Running tally of realized LTCG in current financial year (April–March). Once ₹1.25L exemption exhausted, all subsequent LTCG sales incur 12.5%.

**Net benefit rules:**

- Core rebalance: risk improvement must exceed 2× total cost.
- Tactical exit (stop loss): cost never overrides a stop. You exit regardless.
- Tactical entry: one-way cost factored into expected return.

### 4.7 Regime-specific policies

| Regime | India VIX | Core Policy | Tactical Policy | Contingency Policy |
|---|---|---|---|---|
| Bull | <20 | Rebalance normally. | Full deployment. | Idle. |
| Bear | 20–25 | Only if drift significant. | Higher conviction threshold. | Alert. Ready. |
| High Vol | 25–35 | Only if drift > 15%. | Reduced size. Tighter ATR multiplier. | Standby. |
| Crash | >35 | **Hold. Do not panic-sell.** (See below.) | Freeze new entries. | Tranche deployment (human-approved). |
| Rotation | Any | Sector allocator runs 2×/week. | Increased scanning. | Idle. |

**Crash core policy (clarified):**

Do not panic-sell core holdings solely due to market-wide drawdown. If a holding becomes overweight by market value, do not rebalance via selling during crash unless company-specific risk is detected. Use fresh cash or contingency to dilute concentration only after quality and liquidity gates pass.

**Exception:** If portfolio drawdown hits 20% (Section 0), FULL FREEZE overrides this policy.

### 4.8 Execution rules

**No market orders under normal conditions.** Every order is a limit order.

- Buy limit: `Ask + (Ask × 0.002)` — 0.2% max slippage.
- Sell limit: `Bid - (Bid × 0.002)`.
- Order size: never exceed 1% of ADV.

**Stop-loss escalation protocol (replaces rigid auto-cancel):**

| Time | Action |
|---|---|
| Stop triggered | Place limit sell at `Bid - (Bid × 0.002)` |
| 2:30 PM unfilled | Widen limit to `Bid - (Bid × 0.01)` (1% below bid) |
| 3:00 PM unfilled | Widen limit to `Bid - (Bid × 0.02)` (2% below bid) |
| 3:10 PM unfilled | Alert user. If thesis is dead, manual market-order decision. |
| 3:15 PM | Auto-cancel remaining. Position held overnight with critical alert. |

This prevents the trap where 0.2% slippage protection costs you a 15% overnight gap-down.

**Non-stop-loss orders:** Auto-cancel at 3:15 PM. Re-evaluate next morning via pre-open gate.

### 4.9 Order reconciliation loop (NEW)

**Runs every market day after 3:45 PM IST (market close + 15 min buffer).**

1. Pull actual holdings and order history from HDFC API.
2. Compare against database state: position quantities, cash balances, pending orders.
3. Check for partial fills (₹12K of a ₹25K order filled).
4. Check for price deviations (executed at different price than limit).
5. Verify auto-cancels actually cancelled.

**If any discrepancy:**

- Flag in `portfolio.reconciliation_snapshots`.
- Adjust database to match broker reality (broker is always source of truth).
- If discrepancy affects risk calculations, alert user.
- If partial fill leaves position below minimum viable size, flag for review.

### 4.10 Summary output (replaces LLM in v1)

**v1: TypeScript template strings.** The recommendation JSON structure is fully known. A well-written template covers 100% of v1 cases without API calls, latency, or failure modes.

```typescript
// Example template
`${action} ${quantity} shares of ${ticker} at limit ₹${price}.
Reason: ${reason_codes.join(', ')}.
Tax impact: ${tax_type} on lot from ${lot_date}, estimated ₹${tax_amount}.
If you do nothing: ${do_nothing_baseline}.`
```

**If unavailable:** Dashboard shows raw JSON. System never blocks on the summary layer.

**Future:** LLM integration (Claude Haiku or local model) for natural-language explanations of *why* the anomaly detector fired. Deferred to v2.

---

## 5. Data architecture

### 5.1 Data sources and cross-validation

**The #1 risk in the original architecture was silent data corruption from yfinance.** This is fixed with mandatory cross-validation.

| Data Type | Primary Source | Validation Source | Tolerance |
|---|---|---|---|
| Live prices/quotes | HDFC API | — | Real-time, no validation needed |
| Holdings/positions | HDFC API | Database (reconciliation loop) | Must match exactly |
| Historical OHLCV | yfinance | NSE Bhavcopy (free daily CSV) | Closing price within 0.5% |
| Corporate actions | NSE corporate actions calendar | BSE + HDFC API | Must agree on type and date |
| Earnings calendar | NSE/Moneycontrol | — | Used for blackout window only |

**Data confidence score (computed daily per ticker):**

| Score | Meaning | Action |
|---|---|---|
| 100 | All sources agree | Normal operations |
| 70 | One source stale (>1 day old) | Proceed with caution flag |
| 40 | Corporate action pending or data mismatch | No new recommendations for this ticker |
| 0 | Source conflict on price/quantity | Ticker frozen until manually resolved |

**yfinance for training/backtesting:** Acceptable. Over 15 years, a few missed dividends are absorbed as noise. The VAE and backtester will learn the macro-shape correctly.

**yfinance for live decisions:** Never trusted alone. Always cross-validated against bhavcopy.

### 5.2 Database — PostgreSQL 16 + TimescaleDB

**All financial values: NUMERIC(15,6), never FLOAT.** IEEE 754 drift will cause ₹25,000.00 to become 24999.99999999998. All equality checks use epsilon (1e-6). `decimal.Decimal` in Python.

Single database. Three schemas. Alembic for all migrations from day one.

**`market` schema:**

- `market.prices` — hypertable. Daily OHLCV (NUMERIC). `close_raw` and `return_total_adjusted`. UTC timestamps. Retention: 3 years full, compressed beyond.
- `market.sectors` — NSE sector mapping + conglomerate exception table.
- `market.factor_scores` — daily computed scores per stock.
- `market.correlation_matrix` — daily Ledoit-Wolf corrected snapshot.
- `market.regime` — daily classification with India VIX, breadth, momentum.
- `market.dividends` — ex-date, record date, amount per share.
- `market.corporate_actions` — expanded list (Section 3.10) with ex-dates and action types.
- `market.nse_holidays` — holiday calendar, refreshed daily.
- `market.earnings_calendar` — scheduled earnings dates for blackout window.
- `market.data_confidence` — daily per-ticker confidence score.
- `market.corporate_events` — governance/regulatory events from NSE/BSE/SEBI with severity and ticker mapping.

**`portfolio` schema:**

- `portfolio.pools` — three pools. `settled_cash`, `unsettled_cash`, `unsettled_release_timestamp`, `settlement_type`.
- `portfolio.holdings` — per position: ticker, pool, quantity, cost_basis, cumulative_dividends, effective_cost_basis, market_value, unrealized_pnl, entry_price, maturity_days, graduation_eligible, atr_stop_price, trailing_stop_peak, trailing_stop_price.
- `portfolio.tax_lots` — FIFO ledger (Section 2.7).
- `portfolio.lot_consumptions` — sell events mapped to consumed lots.
- `portfolio.corporate_action_lot_adjustments` — lot modifications from corporate actions.
- `portfolio.realized_gain_events` — per-lot realized STCG/LTCG.
- `portfolio.rotations` — rotation memory with re-entry conditions.
- `portfolio.transactions` — full audit trail with transaction_type, timestamp (UTC), cost basis impact, tax impact, reason codes.
- `portfolio.capital_injections` — amount, date, routing breakdown.
- `portfolio.dividend_received` — dividends received in bank. Not deployable.
- `portfolio.realized_gains_ytd` — running LTCG/STCG tally (April–March).
- `portfolio.reconciliation_snapshots` — daily broker vs. database comparison.
- `portfolio.data_quality_checks` — cross-validation results.
- `portfolio.system_freeze_events` — when and why the system froze.

**`compute` schema:**

- `compute.sector_allocation` — target weights, approved/restricted flags.
- `compute.portfolio_weights` — target stock weights.
- `compute.anomaly_signals` — confidence score, eigenvalue data, signal_ratio, affected sectors.
- `compute.screener_output` — daily rankings.
- `compute.recommendations` — with limit price, expiry window, FIFO tax estimate, settlement date, reason_codes, strategy_version, data_snapshot_id, do_nothing_baseline, human_approval_status.
- `compute.outcomes` — feedback loop. 30-day outcomes, hit/miss.
- `compute.backtest_runs` — backtest parameters and results.
- `compute.paper_orders` — paper trading order log.
- `compute.paper_fills` — paper trading fill simulation.
- `compute.strategy_versions` — tracks parameter changes over time.

### 5.3 ML pipeline storage (separate from operational DB)

Training data for backtesting and future ML models (VAE anomaly detector, etc.) stored as **Parquet files**. Columnar, compressed, reads into PyTorch DataLoader orders of magnitude faster than SQL queries.

- `data/historical/` — 15+ years of OHLCV and fundamentals for Nifty 200.
- `data/bhavcopy/` — daily NSE bhavcopy archives.
- `data/backtest_universes/` — point-in-time index compositions (see Section 5.4).

### 5.4 Survivorship bias protection

**The screener's watchlist contains stocks that exist today. Stocks that delisted, went bankrupt, or were suspended are invisible.** This systematically overstates backtest returns.

**Fix:** For backtesting, use a point-in-time universe. At each historical date, the universe includes whatever was in the relevant index on *that* date, including stocks that later delisted. NSE publishes historical index composition changes.

This is implemented in the backtest engine (Phase 0), not the live system.

### 5.5 Total Return data pipeline

On every data ingestion cycle:

1. Pull raw OHLCV from yfinance.
2. Pull bhavcopy from NSE. Compare closing prices. Flag divergences > 0.5%.
3. Check `market.dividends` for ex-dates. Compute TR adjustment.
4. Store both `close_raw` and `return_total_adjusted`.
5. All downstream compute uses `return_total_adjusted` exclusively.

### 5.6 Dimensional alignment

Runs as the first operation before any matrix computation:

1. Ticker reconciliation (compare today vs. yesterday).
2. Missing ticker: remove from matrices, alert if it's a current holding.
3. New ticker: expand matrices with neutral entries. Excluded from anomaly detector for 60 days.
4. Dimension lock assertion: matrices, vectors, index arrays must match. Fail → halt → alert.
5. NaN handling: use last known price, flag as "interpolated." 3+ days → Volume-Velocity Gate.

### 5.7 Timezone enforcement

UTC everywhere except display. `TIMESTAMP WITH TIME ZONE`. Docker: `TZ=UTC`. Naive datetime → rejected, logged.

---

## 6. Feedback and learning

### 6.1 Outcome tracking (active from day one)

Every recommendation stores its full context at decision time AND its 30-day outcome:

**Stored at recommendation time:**

- Strategy version, regime classification, factor scores, anomaly detector state
- Data snapshot ID (which prices/fundamentals were used)
- Broker snapshot ID (what the broker showed)
- Tax lot snapshot (which lots would be consumed)
- Reason codes, expected cost, expected tax, expected slippage
- Do-nothing baseline (what happens if we skip this trade)

**Stored at 30-day review:**

- Tactical buy: positive return? Outperformed Nifty 50? By how much?
- Tactical exit: well-timed? Stock continued falling (good) or reversed (bad)?
- Contingency deployment: recovered to target weight within 90 days?
- Core rebalance: lower CVaR post-rebalance?
- Regime at time of outcome: same regime as recommendation, or did it change?

This creates a structured feedback table that enables data-driven quarterly reviews from day one — and feeds the automated learning tiers when they activate.

### 6.2 Three-tier learning architecture

The system learns from its mistakes — but never by experimenting on live capital. All learning happens on historical or logged data, is validated out-of-sample, and is promoted to production only when it demonstrably outperforms the current static rules.

**Why not reinforcement learning:** RL agents learn by exploring — trying random actions to observe rewards. In trading, exploration means losing real money on experimental trades. An RL agent needs millions of episodes to converge; this system generates ~50–100 events per year. Markets are non-stationary, so what the agent learned about 2020 may not apply to 2025. Every major quant fund that tried pure RL on live capital has the same story: overfits to recent conditions, blows up in the next regime change. RL is the wrong learning mechanism for this system.

**What works instead:**

**Tier 1 — Feedback-calibrated outcome table (v1, from day one)**

The outcome tracking in Section 6.1 enables structured quarterly reviews. After 12 months, you can answer: "When the screener recommended a momentum-heavy stock in a high-volatility regime, did it work?" If consistently no, that’s a factor-weight calibration insight. No automation — your judgment with 50 data points, organized in a clean table, beats any algorithm with 50 data points.

**Tier 2 — HMM/GMM regime classifier (activates after 12+ months of live data)**

The current regime detection uses hardcoded VIX thresholds (Bull < 20, Bear 20–25, etc.). This is brittle — the right threshold for “crash” shifts over time.

The upgrade: a Hidden Markov Model (HMM) or Gaussian Mixture Model (GMM) trained on historical + logged live data. It clusters market periods into states unsupervised. It might discover 4 natural regimes or 6, and learn that the transitions between them follow probabilistic patterns.

Instead of hardcoded factor weights per regime, the system learns: "Regime 3 (high VIX, correlation clustering, negative momentum) historically favored factor weights [10/25/25/15/10/15]."

**Promotion gate:** Walk-forward backtest must show the HMM-selected weights outperform the static weight table across multiple regimes, with no increase in max drawdown or turnover. Validated out-of-sample before replacing the static table.

**Tier 3 — VAE anomaly detector (activates when validated — see Section 15.2)**

Replaces hardcoded Z-score thresholds for bubble detection with a learned model that understands the “shape” of normal market behaviour. When reconstruction loss spikes, the market is entering a regime the historical data didn’t prepare for.

**Promotion gate:** Must catch bubbles earlier than Z-scores without more false positives, validated on out-of-sample historical periods.

| Tier | Method | Activates | What It Learns | Safety Gate |
|---|---|---|---|---|
| 1 | Feedback table | Day one | Which recommendations work in which regimes | Human reviews quarterly. No automation. |
| 2 | HMM/GMM regime classifier | 12+ months live data | Market states, factor weights per state | Walk-forward beats static table. Out-of-sample validated. |
| 3 | VAE anomaly detector | Validated backtest | "Normal" market geometry. Anomalies via reconstruction loss. | Catches bubbles earlier than Z-scores. Fewer false positives. |

**The iron rule:** The live system always runs proven parameters. Learning happens offline. Promotion requires evidence. The system never explores with your money.

---

## 7. Broker integration

### 7.1 v1 — India only

**Broker:** HDFC Securities (InvestRight Open API).
**Coverage:** NSE/BSE equities.

### 7.2 API authentication — exponential backoff

- Attempt 1 fails → wait 1 minute.
- Attempt 2 fails → wait 5 minutes.
- Attempt 3 fails → wait 30 minutes.
- Attempt 4 fails → full stop. Critical alert. Disconnected mode.

**Disconnected mode:** Compute continues on cached data. All recommendations flagged "UNVERIFIED — broker disconnected." No order ticket generation.

**Failure type distinction:**

- 401 → try refresh first.
- 403 → count immediately.
- Timeout / 5xx → retry without incrementing backoff.

### 7.3 Broker adapter (concrete India implementation)

```python
class HdfcBrokerAdapter:
    """Concrete, India-specific. No abstract interface.
    When US expansion happens, extract common interface then."""

    def get_holdings(self) -> list[Position]
    def get_quote(self, ticker: str) -> Quote  # {ltp, bid, ask, volume}
    def get_historical(self, ticker: str, period: str) -> pd.DataFrame
    def get_dividends(self, ticker: str, period: str) -> list[Dividend]
    def get_order_history(self, date: str) -> list[Order]  # For reconciliation
    def get_trade_book(self, date: str) -> list[Trade]     # For tax lot seeding
    def place_limit_order(self, ticker, side, qty, price) -> str  # order_id
    def cancel_order(self, order_id: str) -> str
    def get_order_status(self, order_id: str) -> OrderStatus
```

**No RegionalModule interface.** No AlpacaAdapter stub. Build concrete India code. Extract abstractions when you have two implementations.

### 7.4 Execution deployment

- **Phase 1 (Read-only):** Recommendations as notifications. Manual execution in HDFC app.
- **Phase 2 (Semi-auto):** System generates limit order tickets. User approves each one manually.
- **No Phase 3 in v1.** Full auto-execution is removed from scope. SEBI algo trading guidelines may require exchange approval for automated order placement. For ₹2L on a laptop, manual approval is a safety layer, not a limitation.

---

## 8. Orchestration

**Prefect** (lightweight Python orchestrator, replaces raw cron/APScheduler for the daily pipeline).

```python
@flow(name="daily_pipeline", retries=2)
def daily_pipeline():
    check_market_day()          # NSE holiday check. If holiday → exit.
    validate_data_sources()      # Cross-validate HDFC + bhavcopy.
    ingest_data()               # OHLCV, TR adjustment, dimensional alignment.
    run_anomaly_detector()       # Eigenvalue analysis.
    run_drift_checker()          # Lightweight weight deviation check.
    if drift_exceeded() or regime_elevated():
        run_monte_carlo()       # Sobol QMC, only when needed.
    run_screener()              # Factor model.
    run_decision_engine()       # Full rule book.
    reconcile_orders()          # Post-market broker comparison.
    push_notifications()        # HIGH priority only.
```

**Why Prefect over raw scripts:** Automatic retries on network failures, dependency management, execution logging, and alerting via webhook. If NSE bhavcopy download times out, Prefect waits 60 seconds and retries without crashing the whole pipeline.

---

## 9. Service architecture

Three services, Docker Compose. All local.

### 9.1 Backend service (always-on, CPU)

**Runtime:** FastAPI (Python).
**Responsibilities:** HDFC API integration, scheduling via Prefect, decision engine, REST API, JWT auth, structured logging (structlog, JSON).

### 9.2 Compute service (on-demand, GPU)

**Runtime:** Python (PyTorch). Strict subprocess isolation — each task spawns as isolated process. OS reclaims 100% GPU memory on exit.

**Job priority:**

1. Anomaly detector (daily)
2. Drift checker (daily, lightweight)
3. Monte Carlo (gated — only on drift/elevated)
4. Screener (daily)
5. Portfolio optimizer (only on drift + Monte Carlo confirmation)
6. Sector allocator (weekly, scipy)

### 9.3 Frontend (static, mobile-first)

**Runtime:** Next.js 15 + TypeScript + Tailwind + shadcn/ui

**Dashboard panels:**

- Three pool cards (cost basis, market value, PnL, cash states, data confidence)
- CVaR gauge (per-pool and aggregate)
- Drawdown tracker (current vs. 20% freeze threshold)
- Allocation bars: current vs. target sector weights
- Holdings table with pool, tax lot details, STCG/LTCG status, ATR stop levels
- Recommendation cards with limit price, tax estimate, reason codes, do-nothing comparison
- Template-string summary (plain English)
- Earnings blackout calendar
- Reconciliation status (last broker sync)
- Anomaly detector signal (current regime, signal_ratio)
- Dividend income tracker
- Push notifications: HIGH priority for crash/contingency/stop-loss only

---

## 10. Security

### 10.1 Dashboard access

**External (Cloudflare Tunnel):** Read-only. Shows portfolio state, recommendations, risk metrics. No order placement. No broker credentials.

**Security layers:**

- Cloudflare Access (free, up to 50 users) in front of the tunnel — email-based authentication at the edge.
- JWT auth on FastAPI backend (short expiry, 15 min).
- CSRF protection.
- Rate limiting.

**Local only:** Order ticket generation, broker API calls, approval workflow. Never exposed through the tunnel.

### 10.2 Secrets management

- Broker API credentials: encrypted at rest, never in frontend code, never in version control.
- `.env` file with restricted permissions, loaded via `python-dotenv`.
- Database credentials: separate from application secrets.

### 10.3 Audit log

Every system action logged with timestamp, actor (system/user), action type, and full context. Immutable append-only table. Used for debugging, compliance, and post-mortem analysis.

### 10.4 Backup

Daily PostgreSQL backup. Stored locally + one cloud copy (encrypted). Retention: 90 days.

---

## 11. Indian market infrastructure

### 11.1 NSE holiday calendar

At 8:00 AM IST daily, ping NSE holiday calendar. If holiday → scheduler sleeps. Settlement calendar uses this — T+1 = next trading day.

**Muhurat Trading:** Diwali evening session. System ingests exact start/end times dynamically, runs truncated cycle.

**Sudden holidays:** If detected, system sleeps. Previous day's data marked as last valid.

### 11.2 Deployment

Docker Compose on RTX 5070 Ti laptop (WSL Ubuntu 24.04):

- PostgreSQL + TimescaleDB container
- FastAPI backend container
- Compute service container (GPU-enabled)
- Next.js frontend container
- Prefect orchestrator

**Laptop reliability:** The system assumes if the laptop is offline, no trade happens. This is safe because v1 is manual-approval only. The worst case is: you miss a recommendation for one day. No stale recommendations auto-execute.

---

## 12. Quality gates

Non-negotiable from day one:

- Linting: ruff
- Type checking: mypy (strict)
- Pre-commit hooks: ruff + mypy + formatting
- Testing: pytest (unit + integration)
- CI: GitHub Actions
- Logging: structlog (JSON in prod)
- Migrations: Alembic (versioned, CI-tested)

---

## 13. Implementation phases

**Philosophy: Prove the strategy works before building infrastructure around it.**

| Phase | Focus | Deliverable | Duration (est.) |
|---|---|---|---|
| **0: Strategy Validation** | Does this strategy beat doing nothing? Backtest the factor model + allocation logic on 10+ years of historical data using VectorBT. Point-in-time universe (survivorship-bias-free). Compare vs. Nifty 50, SIP, equal-weight. If it can't beat these baselines after costs and taxes: stop. Rethink strategy. | Backtest report. Sharpe ratio, max drawdown, win rate across bull/bear/crash/rotation regimes. Go/no-go decision. | 2–3 weeks |
| **1: Foundation** | PostgreSQL + TimescaleDB. All three schemas including tax lots. Alembic. Docker Compose. UTC enforcement. NUMERIC types. Quality gates. Data pipeline: yfinance + bhavcopy cross-validation. Corporate action gatekeeper. NSE holiday calendar. Dimensional alignment. Data confidence scoring. | Data flowing, cross-validated, stored correctly. | 3–4 weeks |
| **2: Portfolio Import + Capital Engine** | HDFC API integration (with exponential backoff). Import current holdings. Seed tax lots from trade book / contract notes. Three-pool model. Settlement state machine. Dual ledger. Dividend tracking. Capital flow rules. Basic read-only dashboard (local only, no Cloudflare yet). | You can see your actual portfolio, tax lots, and pool allocations on a dashboard. | 2–3 weeks |
| **3: Screener + Risk** | Six-factor model on GPU. ATR calculations. Anomaly detector with Marchenko-Pastur normalization. Drift checker. Monte Carlo (Sobol QMC). Earnings blackout. Corporate event scanner. All output is logged, nothing executes. | System generates daily signals and logs them. You can review what it would have recommended. | 3–4 weeks |
| **4: Decision Engine + Recommendations** | Full rule book. Authority hierarchy. Pre-open sanity gate. Tactical exit rules (ATR stops). Smart recycling. FIFO tax-aware cost gate. Corporate event flags integrated into recommendations. Outcome tracking table (Tier 1 learning). Template-string summaries. Reconciliation loop. | Full recommendation pipeline with full context logging for every decision. | 2–3 weeks |
| **5: Paper Trading** | Live data, real recommendations, no execution. Minimum evidence threshold: 50+ recommendation events AND at least one volatility spike AND walk-forward validation across multiple regimes. | Clean log of every recommendation, what would have happened, comparison vs. baselines. | 3–6 months |
| **6: Go/No-Go** | Analyze paper trading results. Does the system beat Nifty 50 after costs? Are tax lots matching broker contract notes? Max drawdown within 20% tolerance? Data confidence blocking trades when sources disagree? | Written go/no-go analysis. If no-go: iterate on strategy. | 1 week |
| **7: Semi-Live** | Cloudflare Tunnel with Cloudflare Access (read-only external). Order ticket generation. User approves manually. Full reconciliation loop. Security hardening. | You're live. System recommends, you execute, system verifies. | Ongoing |

---

## 14. Go/no-go criteria (all must be true before real money)

1. Backtest beats do-nothing AND Nifty 50 after costs and taxes.
2. No look-ahead bias in backtest.
3. No survivorship bias in backtest.
4. Tax-lot FIFO engine matches broker contract notes exactly.
5. Corporate-action engine handles split, bonus, dividend, merger/demerger.
6. 50+ paper trading recommendation events with clean logs.
7. Manual execution only. No auto-trading.
8. Max drawdown in paper trading is within 20% personal tolerance.
9. Data confidence score successfully blocks trades when sources disagree (verified by at least one real incident).
10. Every recommendation includes: why buy/sell, why now, why this size, when to exit, what can go wrong, what happens if you do nothing.

---

## 15. Research track (Quantum + ML)

**Separate from production. Lives in `research/` directory. Each component has a defined AUM trigger for promotion to production.**

### 15.1 QUBO / VQE (Quantum portfolio optimization)

**Production trigger:** Core AUM crosses ₹50L+ with 15+ stocks. At this scale, the gap between the true integer optimum and classical greedy rounding becomes financially meaningful.

**What it solves:** The integer-constrained portfolio optimization problem. Classical continuous optimizers say "buy 2.347 shares of TCS." In reality, you buy 2 or 3. At ₹2L capital, this rounding error significantly impacts the portfolio. QUBO formulates this as a binary optimization that a quantum computer solves natively.

**The Hamiltonian:**

```
H = γ Σᵢⱼ xᵢ Σᵢⱼ xⱼ   (minimize risk)
  - Σᵢ μᵢ xᵢ            (maximize return)
  + λ(Σᵢ Pᵢ xᵢ - B)²    (budget constraint: spend exactly ₹1L)
```

Where xᵢ ∈ {0,1} represents whether to buy a specific lot of a stock at price Pᵢ.

**Validation approach:** Solve the same problem with both scipy (continuous relaxation + greedy rounding) and CUDA-Q VQE. Compare results. Document where quantum finds a better integer solution.

**Tools:** CUDA-Q, Qiskit, Qiskit-Finance, Qiskit-Optimization.

**Portfolio narrative:** "Built a production system with classical optimization. In parallel, formulated the same problem as a QUBO Hamiltonian and validated VQE against the classical solution. Results match at n=12 sectors. Architecture is designed so that when the problem scales to 50+ global sectors where classical brute force breaks down (2^50 states), one backend swap activates the quantum pipeline."

### 15.2 VAE anomaly detector (GPU ML)

**Production trigger:** 12+ months of live anomaly detector data collected, AND validated backtest showing VAE catches bubbles earlier than Z-scores without more false positives. AUM-independent — this is a data-quantity gate, not a capital gate.

**Future upgrade for the anomaly detector.** Instead of hardcoded Z-score thresholds for bubble detection, train a Variational Autoencoder on 15+ years of market data.

**Input features per stock:** Log returns (1d, 5d, 20d), realized volatility, valuation Z-score, volume ratio, index correlation.

**Training:** VAE learns to compress "normal" market behavior into a latent space. When a stock enters a regime the VAE hasn't seen (bubble, structural break), reconstruction loss spikes.

**Production integration path:** Replace hardcoded bubble Z-score with VAE reconstruction loss. Higher loss = higher anomaly confidence. Threshold calibrated via backtest.

**Prerequisite:** 15+ years of clean historical data (Parquet), validated backtest showing the VAE catches bubbles earlier than Z-scores without more false positives.

---

## 16. Open decisions (resolved during implementation)

- India VIX regime thresholds — validate via backtest (Phase 0).
- Anomaly confidence thresholds (40/70) — calibrate via backtest.
- ATR risk multiplier k (default 2.0) — validate against Indian market volatility.
- Cooldown durations — validate.
- Drift threshold (5% vs 10%) — validate via backtest.
- Tactical conviction threshold — calibrate.
- Graduation maturity threshold (60 vs 90 days) — validate.
- Student-t degrees of freedom — fit to Indian market data.
- HDFC API capabilities and rate limits — verify against docs.
- Watchlist composition (Nifty 200 constituents? manual curated?) — decide in Phase 0.
- Onboarding UI vs config file — decide during Phase 2.

---

## 17. Changelog

### v3.0 → v3.1 (Post-review rework: 30 fixes across 3 independent adversarial reviews)

**Critical fixes (could lose money):**

1. **Data cross-validation.** yfinance never trusted alone. Bhavcopy as validation source. Data confidence scoring.
2. **ADV math fixed.** Liquidity gate raised from 25× to 100× position size. Minimum ADV = ₹25L for tactical.
3. **Stop-loss escalation protocol.** Limit orders widen progressively. No more overnight holding of breached positions due to rigid auto-cancel.
4. **Order reconciliation loop.** Daily post-market broker vs. database comparison. Partial fill handling.
5. **Tax lot FIFO ledger.** Lot-level tracking with FIFO consumption. STT excluded from capital gains. Per-lot STCG/LTCG calculation.
6. **Portfolio drawdown circuit breaker.** 20% max drawdown → FULL FREEZE.
7. **Earnings blackout window.** No tactical entry within 5 trading days of earnings.
8. **Circuit cascade estimation.** Worst-case multi-day circuit-lock loss calculation.

**Structural improvements:**

9. **Minimum-variance optimization.** Removes fragile expected return estimation. Covariance-only approach.
10. **Marchenko-Pastur eigenvalue normalization.** Dimensionally stable anomaly detection across watchlist changes.
11. **Anomaly detector downgraded to advisory.** No auto-deployment of contingency. Human approval required.
12. **Contingency tranche deployment.** Never full reserve at once. Four tranches with defined triggers.
13. **Volatility-adjusted stops.** ATR-based, not flat percentage. Stock-specific risk recognition.
14. **Thesis expiry 2-of-3 confirmation.** Reduces churn from temporary rank shifts.
15. **Tax penalty decay.** 3× multiplier decays linearly from day 330 to 365. Anomaly detector overrides entirely.
16. **Effective cost basis isolated.** Display layer only. Never enters compute.
17. **Corporate actions expanded.** Merger, demerger, buyback, ASM/GSM, ISIN change, face value change.
18. **T+0 settlement awareness.** Schema supports T+0 when HDFC enables it.
19. **Deployment blacklist for contingency.** ASM/GSM, pledged promoters, auditor resignations.
20. **Crash policy clarified.** "Dilute, don't exit" rewritten unambiguously.

**Over-engineering removed:**

21. **C++ solver → scipy.** 12 sectors = convex optimization. scipy guaranteed optimal. No subprocess maintenance.
22. **RegionalModule interface deleted.** Concrete India implementation. Abstract when needed.
23. **Bayesian adaptation removed from v1.** Manual quarterly review. Automated only after 100+ events.
24. **LLM → template strings.** Zero failure modes. LLM deferred to v2.
25. **Auto-execution removed from v1.** Phase 2 (semi-auto with manual approval) is the ceiling.
26. **Core stock count constrained.** 5–6 at ₹2L. Scaling formula as capital grows.
27. **Sobol QMC replaces pseudo-random Monte Carlo.** 10K Sobol ≈ 100K pseudo-random. 90% compute reduction.

**Infrastructure additions:**

28. **Prefect orchestration.** Replaces raw scripts. Retries, logging, alerting.
29. **Cloudflare Access.** Edge authentication before traffic reaches backend.
30. **Parquet for ML pipeline.** Separate from operational PostgreSQL.

**Personal risk policy added as Section 0 — overrides all other rules.

**Scaling and learning additions (post-review discussion):**

31. **Capital milestone transitions.** Scrappy Fighter → Tactical Allocator → Institutional Grade → Wealth Preservation. System behaviour adapts automatically at AUM thresholds.
32. **Stock count scaling formula.** `max_core_stocks = min(20, max(5, floor(capital / 200000) + 4))`. No manual adjustment needed.
33. **Three-tier learning architecture.** Feedback table (day one) → HMM/GMM regime classifier (12+ months) → VAE anomaly detector (validated backtest). No reinforcement learning. System never experiments on live capital.
34. **Corporate event scanner.** Structured detection of governance/regulatory events from official sources. Blocks and flags, never generates buy signals. Not sentiment analysis.
35. **AUM-gated future upgrades.** Every future component has a defined capital or evidence trigger for promotion. No calendar-based upgrades.**

---

## 18. Future (AUM-gated progression)

Each upgrade unlocks at a specific capital or evidence threshold — not on a calendar.

| Upgrade | Trigger | What Changes |
|---|---|---|
| Tax-loss harvesting | AUM > ₹10L | Strategically sell losing lots to offset STCG/LTCG on winners. |
| Black-Litterman returns | AUM > ₹20L + 100+ outcome events | Upgrade from min-variance to return-aware optimization. |
| QUBO/VQE production | AUM > ₹50L + 15+ core stocks | Integer-constrained optimization via quantum backend. |
| HMM/GMM regime classifier | 12+ months live data + walk-forward validation | Replace hardcoded VIX thresholds with learned regime states and factor weights. |
| VAE anomaly detector | HMM validated + additional backtest | Replace Z-score bubble detection with learned reconstruction-loss model. |
| US market expansion | India module proven + regulatory clarity | Alpaca API. Separate module, own tax/broker/currency. |
| Auto-execution | 12+ months semi-auto + SEBI confirmation | Phase 3 unlocked. Hardware 2FA for every order. |
| Multi-region intelligence | 2+ regional modules live | Cross-market correlation, global anomaly detection, currency hedging. |
