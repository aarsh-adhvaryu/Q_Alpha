# Phase 4 — the whole system, backtested

**Run 2026-08-29 · pre-registered in [PLAN_REDESIGN.md](../PLAN_REDESIGN.md) §5/§6 before the first
execution.** Reproduce with `uv run python scripts/backtest_phase4.py --null 60`.

Point-in-time Nifty-50 membership (dead names included), 2013-07 → 2026-06, 156 monthly deploys,
₹1,00,000 lump + ₹50,000/month, Zerodha costs and real capital-gains tax throughout.

---

## 1. The headline, and why it is smaller than it looks

| Plan | Final | Return | Worst fall | Tax paid | Trades |
|---|---:|---:|---:|---:|---:|
| NIFTYBEES (do nothing) | ₹1,80,57,394 | +130.0% | −35.2% | ₹0 | 156 |
| **Screen only (buy & hold)** | **₹2,84,43,450** | **+262.3%** | **−34.0%** | **₹0** | 437 |
| Screen + §4.7 exits | ₹2,14,79,617 | +173.6% | −42.2% | ₹13,21,383 | 689 |
| Screen + annual trim | ₹2,80,73,012 | +257.6% | −35.9% | ₹7,71,431 | 722 |
| ⚠️ static Nifty-100 (**BIASED**) | ₹5,92,71,355 | +655.0% | −39.1% | ₹0 | 391 |

**The screen beats doing nothing by ₹1,03,86,056.** It also beat **all 60** no-skill draws
(best random draw: ₹85,48,296), so *p* < 1/61 ≈ **0.016**.

### ⚠️ But three-quarters of that gap is not stock-picking

The null replaces the screen with **random selection from the same point-in-time universe**, holding
sizing, cadence, costs, tax and whole-share granularity identical. Only the *choosing* is destroyed.
Sixty draws:

> median **₹78,55,243** · p05 ₹73,48,304 · **p95 ₹83,62,315** · max ₹85,48,296

A random basket of 15 Nifty-50 names beats the cap-weighted index by **₹78.6 lakh**. That is the
**equal-weight premium**, not skill — and this repo already knew it (1/N returned 17.7% against the
index's 14.5%). Decomposing:

| Source of the ₹1,03,86,056 gap | Rupees | Share |
|---|---:|---:|
| Equal-weighting 15 names instead of cap-weighting 50 | ₹78,55,243 | **76%** |
| **The screen's actual selection** | **₹25,30,813** | **24%** |

**The selection edge is real and statistically clean — and it is a quarter of the headline.** Anyone
quoting "+262% vs +130%" as the screen's achievement is crediting it with the equal-weight premium
it did not create.

**GO criterion 3's noise floor is ₹83,62,315** on this window and scale. A live gap inside it is not
a result. The twin's `Gap.noise_floor` takes this number.

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
| §4.7 idiosyncratic exits | **−₹69,63,833** | ₹13,21,383 | **worse** (−42.2% vs −34.0%) |
| Annual trim to equal weight | −₹3,70,438 | ₹7,71,431 | worse (−35.9%) |

**Both selling mechanisms lose, and the §4.7 test — the more discriminating of the two — loses by
far the most.** It paid ₹13.2 lakh of capital-gains tax to finish ₹69.6 lakh behind, *and* endured a
deeper drawdown than never selling at all.

This is the strongest confirmation yet of the repo's one robust finding: **low realised turnover is
the edge.** It also lands directly on two live decisions:

* **The drawdown exit (§4)** was to be tested before shipping. On this evidence a *stop* is very
  unlikely to survive, because the better-targeted §4.7 rule already fails badly. It stays
  twin-only, and the burden of proof sits on it.
* **`position_health` as a buy-side filter is untouched by this.** The test above ablates it as an
  *exit*; the screen already uses it to exclude breaking names *before buying*, which costs no tax.

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
- **60 null draws** is enough to say *p* < 0.016 and no more.
- **No slippage sensitivity.** Costs use the Zerodha model at default impact.
- **Nothing here is forward evidence.** GO criterion 1 still needs 12 months of real cash flows, and
  criterion 2 still needs a −10% event that has never arrived.

**The gate is not open, and nothing in this document opens it.** This sets the bar that the live
comparison must clear; it does not clear it.
