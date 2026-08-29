# Point forecasting · probabilistic forecasting · RL — registered, not built

**Requested 2026-08-29.** Recorded here rather than implemented, because each is a research
*programme*, not a feature, and adding any of them to the live path without a pre-registered test is
precisely the discipline failure this repo exists to prevent.

Nothing in `src/qalpha/` imports this file's subjects. They graduate by **moving**, when a
pre-registered test passes — [PLAN_REDESIGN.md §2a](../PLAN_REDESIGN.md).

---

## The bar every one of them has to clear

Phase 4 moved it, and it is now high:

| Benchmark | Money-weighted | What it costs to hold |
|---|---:|---|
| NIFTYBEES (cap-weighted) | 11.96%/yr | nothing |
| **Equal-weight index fund** | **16.16%/yr** | 0.41%/yr, zero effort |
| The current screen | 18.13%/yr | daily login, tax handling, in-sample |

**A new method must beat the equal-weight fund by more than the current screen does (+1.98 pp/yr),
out of sample, net of cost and tax.** Beating NIFTYBEES is not an achievement — 76% of that gap is
the equal-weight premium anyone can buy.

---

## 1. Point forecasting (predict next period's return)

**Status: unbuilt. Expected to fail, and worth saying why in advance.**

Equity returns at daily-to-monthly horizons have a signal-to-noise ratio near zero; published R² for
cross-sectional return forecasts is typically **under 1%**. The current screen is deliberately *not* a
forecaster — it ranks on a realised quantity (pullback from a 1-year high) and never predicts.

**Graduates when:** a walk-forward point forecast, trained only on data before each decision date,
produces a portfolio that beats the equal-weight fund out of sample net of the turnover it induces.
**The turnover is the trap** — Phase 4 showed both existing sell rules losing to buy-and-hold once
tax was counted, and a forecaster that updates monthly implies far more trading than either.

---

## 2. Probabilistic forecasting (predict the *distribution*)

**Status: unbuilt. The most promising of the three, and not for returns.**

Forecasting a distribution rather than a point is the right shape for the questions this system
actually has, none of which are "what will INFY return":

- **Position sizing** — how much to deploy given the spread of outcomes, not the mean.
- **Drawdown expectation** — what the worst 5% of paths look like, which is what you size for.
- **The noise floor itself** — already probabilistic (`backtest/significance.py`), already used.

**Note the honest framing: the one probabilistic method in this repo earns its keep by telling you
what is NOT a result.** That is where distributional thinking pays here — quantifying uncertainty,
not manufacturing edge.

**Graduates when:** a calibrated predictive distribution (assessed by CRPS or pinball loss against a
climatological baseline, walk-forward) improves *sizing* enough to beat the equal-weight fund by more
than the current screen does.

---

## 3. Reinforcement learning

**Status: unbuilt. The worst fit of the three, and the most likely to look brilliant in backtest.**

RL needs many independent episodes. This problem offers **one** path of history: ~3,600 trading days,
one macro regime sequence, one COVID. An agent trained on it will learn *that* path — and RL's
capacity to overfit a single trajectory is enormous, while producing a backtest that looks
spectacular.

Three further mismatches specific to this system:

- **The reward is taxed and path-dependent.** FIFO lots mean the cost of an action depends on every
  prior action; the §2(42A) boundary makes the same sell cost 20% or 12.5% depending on the date.
- **The action space is where the money is lost.** Phase 4 showed selling destroys value; an agent
  free to trade will trade.
- **It cannot be explained.** `policy.Decision` refuses to exist without a reason, and this repo's
  entire failure history is surfaces that could not explain themselves. An RL policy's reason is a
  weight vector.

**Graduates when:** it beats the equal-weight fund out of sample on a walk-forward split it never
saw, with turnover and realised tax reported, *and* its decisions can be stated in a sentence.

---

## Why none of these are being built now

Phase 4's result reframes the whole question. The system's honest edge over a purchasable
equal-weight fund is **+1.98 pp/yr, in-sample**, from a screen that has never been walk-forwarded as
a composite. **The open work is validating what exists, not adding methods to it** — and every new
method multiplies the researcher degrees of freedom against a single 13-year path.

The forward twin is the instrument that settles it. Until it has run, a new method has nothing
credible to be compared against.
