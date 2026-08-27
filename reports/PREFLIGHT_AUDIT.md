# Pre-flight audit — the week real money went in

**Audited 2026-08-24 and 2026-08-27, against `main`, on live market data refreshed the same mornings.**
Occasioned by ₹5,00,000 being transferred to the author's real Zerodha account.

This repo publishes its negatives. This is one.

---

## 1. The verdict the system gave itself

The deterministic GO scorecard — built so that no judgement call, human or AI, could talk it into a
green — read **NOT YET**.

| Criterion | Status | Reading |
|---|---|---|
| Track length | 🟡 | 50 of 63 trading days |
| **Volatility event withstood** | 🟡 | **never**: worst in-window Nifty pullback −2.2%, gate needs ≤ −10% |
| Forward vs benchmark | 🟡 | strategy **+0.3%** vs Nifty **+3.3%** — trailing by 3.1pp |
| Drawdown behaviour | 🟢 | −3.1% live vs market −2.2%; market-driven, within tolerance |
| Data integrity | 🟢 | dense, largest gap 4 days |

The fake-money experiment agreed: since the 2026-08-18 re-seed the System book sat at **−0.29%**
against plain NIFTYBEES buy-and-hold at **+0.24%** — behind doing nothing, on a run far too short to
mean anything either way.

**Fifty calm days cannot distinguish a good strategy from a bad one.** Every figure above is inside
the noise band, and none of it is evidence the system is broken. It is, however, an honest statement
that the forward evidence is thin and currently points slightly the wrong way, and that the gate
designed to be un-arguable had not opened. The author invested anyway, informed, by choice.

---

## 2. Five defects, and they are all one defect

Every finding is **a number labelled as something it is not**, on a surface where the label becomes an
order. None was caught by the 481 tests passing at the time, because each is a figure reported *about*
the machinery rather than the machinery's own arithmetic.

### 2.1 A stale benchmark graded the scorecard, silently — *fixed, #72*

The benchmark parquet is gitignored and rebuilt per machine. `paper.py daily` refreshes it;
**`paper.py refresh` refreshes prices and not the benchmark.** On a copy 70 days stale, every
comparison moved and nothing warned:

| Reading | Stale series | Fresh series |
|---|---|---|
| Worst Nifty pullback in-window | **0.0%** | −2.2% |
| Benchmark return | **+1.0%** | +3.3% |
| Strategy Δ vs Nifty | −0.8% | **−3.1%** |

The hard volatility gate reported *"no market stress event yet — a calm run can't earn a GO"* when the
truth was *"we have no data for that window"*, and the strategy looked 2.3 points better than it was.
`_benchmark_covers` now refuses to grade the affected criteria and names the dates and the fix.

### 2.2 The breakdown base rate was zero by construction — *fixed, #72*

`universe_breaking_rate` was measured over `universe` — which by that line has had every breaking name
filtered out of it. Always zero, and the sentence it feeds is gated on `> 0`:

> *"For scale: 20% of the whole watchlist is breaking down right now, so this basket is 3.2× more
> concentrated in them than the universe it was drawn from."*

That line never rendered. It is the only thing that makes the health table interpretable — a raw count
("13 of 15") means nothing without a base rate — and it went missing in precisely the case it exists
for: the filter failing open and a 🔴 reaching the basket anyway. Measured pre-filter now; the real
rate on the live watchlist is **20.4%**.

### 2.3 The 30% sector cap breaches below six names — *disclosed, #72*

The cap is enforced on target *weights*, but shares are bought whole and the leftover water-filled:

| Spread | Largest sector | Delivered | vs 30% cap |
|---|---|---|---|
| 3 names | NBFC | **50.0%** | breach |
| 4 names | NBFC | 33.6% | breach |
| 5 names | NBFC | 33.9% | breach |
| 6 names | NBFC | 28.0% | holds |
| 8 names | AUTO | 29.2% | holds |
| 12 names | NBFC | 24.5% | holds |

Below ~6 names the cap is not merely missed, it is **arithmetically unreachable**: at five equal-weight
names one name is already 20%, so any two in a sector is 40%. A clamp that cannot be satisfied would
fail silently or return an empty basket, so the fix is disclosure — the delivered mix is shown, the
breach is flagged, and the note says that spreading wider is the only thing that fixes it.

### 2.4 The deploy heading named the new money while the basket spent the balance — *fixed, #73*

**The most dangerous finding, and it was caught seconds before it became an order.**

A ₹5,00,000 broker balance with ₹1,00,000 typed into Add-money rendered:

> ### Deploy ₹100,000.00 of new money

over a basket totalling **₹5,97,418**, including **64 shares of HCLTECH** where the intended
quantity was **11** — 84% of the opening position in a single stock.

The arithmetic was never wrong and never undocumented: `advise_deploy` spends `portfolio.cash + amount`,
and putting idle cash to work is the function's job. **The heading named only `amount`.**

The first fix was to correct the label. That was not enough — the remedy it offered was *"move the rest
of your money out of the broker account"*, a monthly chore the software should absorb. So `advise_deploy`
gained `spend_idle_cash`: on the real-money surface the typed amount is now a **hard budget**, with a
checkbox to opt back in. The library default stays `True`, because the autopilot depends on it.

**Why a switch and not a smarter default:** a broker balance is not self-describing. Cash parked for
next month's SIP instalment and cash awaiting deployment are indistinguishable from inside the advisor.
Only the person who put it there knows which is which.

### 2.5 The Equity tile counted cash as shares — *fixed, #74*

`_live_overview` used `portfolio.market_value()`, which includes cash.

```
ACCOUNT WITH THE SIP MONEY PARKED, NOTHING BOUGHT
  shipped  ->  Equity ₹500,000              <- the SIP money, called Equity
  fixed    ->  Equity (shares only) ₹0
               Cash / available margin ₹500,000  (100.0% of ₹500,000)

AFTER THE ₹1,00,000 BASKET FILLS
  shipped  ->  Equity ₹600,877              <- ₹4L of unspent cash, called Equity
  fixed    ->  Equity (shares only) ₹100,693   [8 names]
               Cash / available margin ₹500,184  (83.2% of ₹600,877)
               Unrealised P&L ₹1,175  (+1.18% on ₹99,517 invested)
```

The third tile was `Holdings: 5` — a count standing where a basis belongs, on a row that showed no
return, no cost, and no day's move at all.

---

## 3. The process finding, which is worth more than the fixes

**Defect 2.4 was hit during the audit itself and explained away.** An early scratch run produced a
₹1.99 lakh basket on a ₹1 lakh deploy. It was attributed to a test-harness mistake — the portfolio had
been seeded with cash *and* passed an amount — and the session moved on. That diagnosis was correct and
irrelevant: the same arithmetic is what the live screen does, with the user's real balance.

Had it been chased instead of rationalised, the 64-share order would never have been rendered.

**Rule adopted:** when a number looks wrong in your own scratch output, chase it before explaining it
away.

**Corollary, now an iron rule:** four of the five defects only appear when `portfolio.cash > 0`. Every
test fixture used a zeroed portfolio. That is why 481 tests missed all of them, and why audits must
instantiate the *account shape* — idle cash and holdings — not a clean book.

---

## 4. Standing limitations — true on the first order, not fixable by more code

- **Nobody has watched this system fall.** Every live day so far has been calm. The behaviour that
  matters most — what it recommends when the market is down 15% and the holdings are red — has never
  been observed outside a simulation.
- **The buy screen has one backtest behind it.** 16.4%/yr vs the index's 11.8% over thirteen years, but
  the concentrated variants lean on a watchlist of names that exist *today*, and every guard protecting
  that result was written in the month before the money went in. One backtest by one author is a
  hypothesis, not a finding.
- **Most of the tax engine has never met a broker statement.** Exactly one sell has been reconciled:
  single-lot, all-STCG, no loss — matched to the paise (₹25.25, Δ ₹0.00). The multi-lot, LTCG, loss
  set-off and exemption paths are unit-tested and unconfirmed. The page warns when a sale touches them;
  that sale must be reconciled afterwards against the Tax P&L.
- **No corporate action has ever been reconciled live** (criterion 5).

---

## 5. What was built in response

| PR | What |
|---|---|
| **#71** | `live/track_record.py` — the real account vs the same rupees on the same days in NIFTYBEES, money-weighted (XIRR). Built so it **can report "behind by ₹X"**, and so it refuses a verdict under 12 months. |
| **#72** | The three fixes in §2.1–2.3. |
| **#73** | `spend_idle_cash` — the typed amount becomes a hard budget on the real-money surface. |
| **#74** | `account_overview` — shares and cash separated, every figure carrying its basis. |

**503 tests, 0 skipped.** Rule (a) intact throughout: no backtest path imports any of it, and the
validated ₹2L GO book and the 18.2% headline are untouched.

---

## 6. The recommendation given

Invest, but not for the reason one would hope.

The **mechanics** are well-evidenced: the screen decides rather than defers, filters names in
idiosyncratic decline, corrects demerger artifacts, caps sectors, won't re-buy deliberate exits, and
computes tax that reconciled to the paise. The **stock selection** is unproven, and 50 forward days say
nothing.

The case for proceeding is not "the picks will beat the index" — it is that the realistic downside
versus an index fund is *tracking error on eight large-cap names*, not ruin, while the tax layer is a
real and verified edge either way. The worst case is doing some work for nothing.

Conditions attached: **expect ~11–12%**, hold at ₹5,00,000 until the track record has twelve months in
it, and do not scale up because month three is green — that number is noise, and the panel says so.
