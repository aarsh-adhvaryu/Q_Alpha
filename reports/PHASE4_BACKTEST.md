# Phase 4 — the whole system, backtested

**Run 2026-08-29 · pre-registered in [PLAN_REDESIGN.md](../PLAN_REDESIGN.md) §5/§6 before the first
execution. ⚠️ CORRECTED 2026-08-30 — every number below is a re-run; see §0.** Reproduce with
`uv run python scripts/backtest_phase4.py --null 60`.

Point-in-time Nifty-50 membership (dead names included), 2013-07 → 2026-06, 156 monthly deploys,
₹1,00,000 lump + ₹50,000/month, Zerodha costs and real capital-gains tax throughout.

---

## 0. ⚠️ Correction, 2026-08-30 — the SIP accounting was wrong, and one conclusion reversed

An external review found that this script marked the book **shares-only** and computed drawdowns on
the **rupee curve with contributions still in it**. Two consequences, both real:

**A. Cash that a sale produced disappeared from the book.** `_mark` valued holdings and ignored
`portfolio.cash`, so proceeds vanished from the curve until the next monthly deploy re-spent them.
Buy-and-hold barely noticed (**+₹807** on ₹2.85 crore). Anything that *sells* was penalised hard:

| | terminal, old accounting | terminal, corrected | difference |
|---|---:|---:|---:|
| Screen only (never sells) | ₹2,85,25,560 | ₹2,85,26,367 | +₹807 |
| **Screen + §4.7 exits** | ₹2,08,03,470 | ₹2,10,46,350 | **+₹2,42,880** |

**B. Contributions were counted as returns.** `max_drawdown_pct`'s docstring promised they were
stripped; the code ran `cummax` straight down the rupee curve and stripped nothing. Deposits landing
during a fall keep that curve making new highs, so drawdowns were understated — and for a selling
strategy the vanished cash *manufactured* extra drawdown on top. Both now run on a **unitized
(time-weighted) NAV**, the arithmetic a fund uses to report a NAV while money flows in and out.

**The reversal.** §2 below used to state that the §4.7 exits "endured a deeper drawdown than never
selling at all" — **−42.2% vs −34.0%**. Corrected, the exits fall **−33.9%** against buy-and-hold's
**−35.2%**: the exits were *marginally shallower*, not deeper. That extra 8.3 points of drawdown was
the sale proceeds being written off, not anything the market did.

**What survives.** The return conclusion is untouched and remains overwhelming: the exits still
finish **₹74.8 lakh behind** buy-and-hold (was ₹77.2 lakh) after paying ₹13.3 lakh of tax to get
there. "Low realised turnover is the edge" stands on that evidence. Its *drawdown* half does not, and
has been withdrawn.

**Isolation method.** The old and new code were run against the **same price panel** via a git
worktree, so every difference above is the accounting fix alone. That check also exposed something
separate: the figures published here on 2026-08-29 no longer reproduce on today's data at all
(NIFTYBEES ₹1,80,57,394 → ₹1,80,98,746; the exits leg moved ₹6.8 lakh and its trade count 689 → 692)
**with the original code**. Yahoo revises history. Until the input panels are hashed and pinned, every
number in this report is reproducible only to about half a percent — see §6.

---

## 1. The headline, and why it is smaller than it looks

| Plan | Final | Return | Worst fall | Tax paid | Trades |
|---|---:|---:|---:|---:|---:|
| NIFTYBEES (do nothing) | ₹1,80,98,958 | +130.6% | −36.3% | ₹0 | 156 |
| Equal-weight index (no fee) | ₹2,52,77,875 | +222.0% | −35.8% | ₹0 | 156 |
| **Screen only (buy & hold)** | **₹2,85,26,367** | **+263.4%** | **−35.2%** | **₹0** | 437 |
| Screen + §4.7 exits | ₹2,10,46,350 | +168.1% | −33.9% | ₹13,25,747 | 692 |
| Screen + annual trim | ₹2,81,77,376 | +258.9% | −37.6% | ₹7,70,925 | 708 |
| ⚠️ static Nifty-100 (**BIASED**) | ₹5,94,57,989 | +657.4% | −39.5% | ₹0 | 391 |

**The screen beats doing nothing by ₹1,04,27,409.** It also beat **all 60** no-skill draws
(best random draw: ₹85,48,296), so *p* < 1/61 ≈ **0.016**.

⚠️ **The 60-draw null below has NOT been re-run since the §0 correction** — the numbers in this
subsection are the 2026-08-29 figures. The fix moves a null draw's terminal value by roughly the
buy-and-hold amount (**+₹807** — random baskets never sell, so the residual-cash correction barely
touches them), so the decomposition's *shape* is unaffected. The absolute figures are nonetheless
stale on two counts — the accounting fix and the data drift in §0 — and the null is being regenerated
at ≥1,000 draws under the specification frozen in
[PREREGISTRATION_TWIN_RUN2.md](PREREGISTRATION_TWIN_RUN2.md).

### ⚠️ But three-quarters of that gap is not stock-picking

The null replaces the screen with **random selection from the same point-in-time universe**, holding
sizing, cadence, costs, tax and whole-share granularity identical. Only the *choosing* is destroyed.
Sixty draws:

> median **₹78,55,243** · p05 ₹73,48,304 · **p95 ₹83,62,315** · max ₹85,48,296

A random basket of 15 Nifty-50 names beats the cap-weighted index by **₹78.6 lakh**. That is the
**equal-weight premium**, not skill — and this repo already knew it (1/N returned 17.7% against the
index's 14.5%). Decomposing:

| Source of the ₹1,04,27,409 gap | Rupees | Share |
|---|---:|---:|
| Equal-weighting 15 names instead of cap-weighting 50 | ₹78,55,243 | **76%** |
| **The screen's actual selection** | **₹25,30,813** | **24%** |

**The selection edge is real and statistically clean — and it is a quarter of the headline.** Anyone
quoting "+262% vs +130%" as the screen's achievement is crediting it with the equal-weight premium
it did not create.

⚠️ **This number is no longer GO criterion 3's bar, and must not be used as one.** It was estimated
over thirteen years and ₹78.5 lakh of contributions **against NIFTYBEES**, and was then applied to a
₹3 lakh twin book over twelve months **against the equal-weight fund** — mismatched in scale, horizon
and benchmark, and unreachable by construction. The gate now uses a **scale-free** statistic,
log relative wealth `G = ln(V_TWIN_FULL / V_BASELINE_EW)`, judged against a matched null. See
[PREREGISTRATION_TWIN_RUN2.md](PREREGISTRATION_TWIN_RUN2.md). The decomposition above remains valid
as *description* of this backtest; it is simply not a live bar.

### The comparison that actually decides whether to bother

76% of the gap is the equal-weight premium — and **that premium is purchasable**. Nifty-50
equal-weight index funds exist (DSP 0.41% direct; HDFC and SBI higher). So the fair benchmark for
this system is not the cap-weighted index. It is a fund anyone can buy in five minutes.

| Plan | Money-weighted | Final on ₹78.5L contributed |
|---|---:|---:|
| NIFTYBEES (cap-weighted) | 11.96%/yr | ₹1,80,57,394 |
| **Nifty-50 equal-weight index fund** (net 0.41%/yr) | **15.78%/yr** | **₹2,38,94,453** |
| The screen | **18.13%/yr** | ₹2,84,43,450 |

**The system's real case is +2.35 pp/yr — ₹45,48,996, or 19.0% more terminal wealth — against a
passive equal-weight fund. Not +6.17 pp against the index.**

*(The equal-weight leg is built by `equal_weight_pit`, which rebalances monthly over the names
actually in the index that month, so it holds no name before it entered and none after it left. An
earlier hand-approximation from the null median gave ₹38.8L; this is the rigorous figure.)*

That is a substantial number — over half the contributions again. But it is the number the effort has
to justify: daily Kite logins, tradebook uploads, tax handling and the operational risk of all of it.
And **it is in-sample**, since the screen was developed with this data visible. An in-sample edge is
routinely halved or worse out of sample, which puts the honest forward expectation nearer
**+1 pp/yr, possibly nothing**.

**Two things the fund does that the system cannot**, which sharpen the comparison rather than soften
it: it rebalances internally with **no capital-gains tax at the fund level**, and it requires no
correct behaviour from the investor. **Two the system does that the fund cannot**: tax-loss
harvesting, and never paying a fee that compounds forever.

---

## 2. Selling destroys value, and the better exit rule loses harder

| | vs buy & hold | Tax paid to get there | Drawdown |
|---|---:|---:|---:|
| §4.7 idiosyncratic exits | **−₹74,80,017** | ₹13,25,747 | −33.9% (vs −35.2%) — *marginally shallower* |
| Annual trim to equal weight | −₹3,48,991 | ₹7,70,925 | −37.6% — worse |

**Both selling mechanisms lose, and the §4.7 test — the more discriminating of the two — loses by
far the most.** It paid ₹13.3 lakh of capital-gains tax to finish ₹74.8 lakh behind.

⚠️ **This paragraph used to end "*and* endured a deeper drawdown than never selling at all." That was
an accounting artefact and is withdrawn — see §0.** The exits' drawdown is in fact a shade *better*
than buy-and-hold's. The case against selling now rests entirely on return and tax, where it is not
close; there is no drawdown argument to add to it, and adding one was wrong.

This is the strongest confirmation yet of the repo's one robust finding: **low realised turnover is
the edge.** It also lands directly on two live decisions:

* **The drawdown exit (§4)** was to be tested before shipping. On this evidence a *stop* is very
  unlikely to survive, because the better-targeted §4.7 rule already fails badly. It stays
  twin-only, and the burden of proof sits on it.
* **`position_health` as a buy-side filter is untouched by this.** The test above ablates it as an
  *exit*; the screen already uses it to exclude breaking names *before buying*, which costs no tax.

---

## 2a. The hedge: real protection, at a price the docstring did not name

Measured on the screen's own equity curve — the same book hedged and unhedged, so the difference is
the overlay and nothing else, including roll cost and the 30% F&O business-income tax. τ=0.7,
persist=3, h=0.5.

| | unhedged | hedged |
|---|---:|---:|
| Terminal (×, time-weighted) | **8.441** | 6.627 |
| Worst drawdown | **−35.2%** | **−25.2%** |

**Episodes fired: 18** over thirteen years.

> **The overlay cost 21.5% of terminal wealth to cut the worst fall by 10.0 points.**

⚠️ **The multiples above were ×286.2 and ×224.8 when first published.** They were computed from
`equity_curve.pct_change()` on the contribution-bearing rupee curve, so every ₹50,000 deposit entered
as a one-day *return* — into an early ₹1,00,000 book, a +50% day — and thirteen years of those
compounded into ×286. That was never a return multiple; it was the deposits. On the corrected
time-weighted NAV the book grows **×8.441**, which is what a 263% return on staged contributions
actually looks like. The overlay's transaction cost fell with it: **0.7233 → 0.0267** of book value.

**The 21.5% is unchanged, and that is not luck.** The spurious deposit-days appeared in the hedged
and unhedged compounding alike and cancelled in the ratio. So the headline figure was *correct*, but
nothing in the old run established that it was — it was right by an accident nobody had checked.

That is real insurance at a real premium — not the free lunch the module's own docstring implies.
`live/hedge.py` says the hedge cut the COVID drawdown *"with ~no return given up"*, and for **that one
episode** it may well be true. Run continuously for thirteen years it fires **18 times**, and most
firings are not crashes: **you pay for every false alarm.** The docstring has been corrected.

**What this does *not* settle.** The model uses a **continuous notional** — no lot size — which
§4b-i shows is unattainable below ~₹19L, so nobody could have held exactly this position. And a
drawdown-reduction of 10.6 points for 21.5% of terminal wealth is a **preference**, not a verdict:
it is the right trade for someone who would otherwise sell in a panic, and the wrong one for someone
who would hold. The twin's `−HEDGE` ablation measures it forward; this sets the prior.

---

## 3. Survivorship: the bias is 2.5×

The same screen on **today's** Nifty-100 held fixed for fourteen years returns **+655.0%** against
**+262.3%** point-in-time. Every name in that list is one that survived.

**⚠️ The ₹5.92 crore figure must never be quoted.** It is reported here solely to size the
distortion, exactly as `BACKTEST_SIP.md` reports its own.

*This was caught the hard way: the first run of this file used the static watchlist and produced the
inflated number before it was noticed.*

---

## 4. The AI cannot be backtested, and this run does not pretend it can

Generating historical verdicts means asking a model whose **training data contains the outcome**. A
2015 verdict from a 2025 model is a memory, not a forecast, and any backtest built on one is
measuring hindsight.

**There is no honest historical test of the AI — only the forward one.** That is what `TWIN_FULL`
against `TWIN_NO_AI` exists for, and why the AI's verdict cannot arrive before the twin has run.
Anyone reporting a backtested AI edge on this system is reporting leakage.

---

## 5. A data defect found while running this

The committed benchmark carries **two corrupt prints**: 2019-12-19 and 2019-12-20 read **₹13.02** and
**₹13.03** against a true **₹129.25** — a factor-of-ten feed error. `_load_benchmark_series()`
repairs them; reading the parquet directly does not.

The first run of this file read it directly and reported **NIFTYBEES falling 89.9%**, which is
impossible. The true figure is **−36.3%** (COVID). Every baseline here would have been poisoned by a
table that looked entirely plausible.

**Lesson, for the third time in this repo: chase the number that cannot be true.**

---

## 6. What this does NOT establish

- **One window, one universe, one parameterisation.** No walk-forward across sub-periods here; the
  validated funnel has that, this composite does not yet.
- **The screen was developed with this data visible.** The selection edge is therefore not
  out-of-sample, and 24% of a gap is exactly the size that in-sample development can manufacture.
- **60 null draws** is enough to say *p* < 0.016 and no more — and that null predates the §0
  correction; it is being regenerated at ≥1,000 draws.
- **The inputs are not pinned.** Re-running the *unchanged* code on today's panel moves the exits leg
  by ₹6.8 lakh and its trade count by three, because Yahoo revises history. Until the price panels
  carry recorded hashes, treat every rupee figure here as reproducible to roughly half a percent, and
  never compare a number in this report against one computed on a different day's download.
- **No slippage sensitivity.** Costs use the Zerodha model at default impact.
- **Nothing here is forward evidence.** GO criterion 1 still needs 12 months of real cash flows, and
  criterion 2 still needs a −10% event that has never arrived.

**The gate is not open, and nothing in this document opens it.** This sets the bar that the live
comparison must clear; it does not clear it.
