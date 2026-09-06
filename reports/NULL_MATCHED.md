# The matched null — and what it says about the gate

**Generated 2026-09-06, from 2,000 draws.** Specification frozen in
`PREREGISTRATION_TWIN_RUN2.md` §2 and `PREREGISTRATION_CORE_V1.md` §4. Values in
`reports/NULL_MATCHED.json`; generator `scripts/exp_null.py`.

```
NULL_P95_LOG_REL_WEALTH = 0.071877
```

Computed **before `CORE_V1`'s window opened**, so no observation existed to tune it toward. That is
stronger than the frozen spec alone: the spec stopped the bar being fitted to a result, and the
timing means there was no result to fit to.

---

## 1. It behaves like a null

| | |
|---|---:|
| draws | 2,000 |
| mean $G$ | +0.00111 |
| median $G$ | +0.00090 |
| 5th–95th percentile | −0.0591 … +0.0600 |
| **beat the fund** | **51.2%** |

Random selection through identical machinery wins about half the time and averages about zero,
which is what a null must do.

### The first version did not, and that is why these two numbers are asserted in the suite

The first run returned mean $G = -0.68$ with **0 of 20 draws beating the fund**. The value series
applied the *final* basket across the whole window, so the book looked flat while eleven deposits
kept arriving and the unitized NAV divided by an ever-growing unit count. A null where nothing ever
wins is not a null; it is a bug reporting itself.

A second defect followed: the benchmark leg was **frictionless**, while the pre-registration says
*"the equal-weight fund net of its fee"*. Correcting it moved the beat-rate from 33% to 50%. A
frictionless benchmark is not one anyone can hold, and it biases the bar in the direction that
flatters the strategy.

---

## 2. ⚠️ The bar is 17× the edge the strategy claims

This is the finding, and it is not comfortable.

| | |
|---|---:|
| the bar, $p_{95}(\|G\|)$ | **0.0719** |
| the backtest's edge over the **gating** benchmark | **0.0042 / yr** |
| ratio | **17.0×** |
| **P(criterion 3 fires in one 12-month window, if the edge is entirely real)** | **3.0%** |
| P(false positive, by construction) | 5.0% |
| one-year gap that *would* clear it | **7.5%** |
| years to detect the claimed edge at 95% | **~196** |

**You are more likely to clear this criterion by luck than by having the edge.**

The edge used here is the backtest's own headline against the benchmark the gate actually compares
against: 18.2% versus 17.7% CAGR for equal-weight 1/N. Not the +3.7% over the cap-weighted index —
that comparison does not gate, and 76% of it is the equal-weight premium, which is purchasable.

The arithmetic is unremarkable once stated. A 15-name basket tracks a 50-name equal-weight fund with
about **3.6% annual standard deviation**. Twelve months gives you one observation of a 0.42% signal
inside 3.6% of noise. No amount of care in running the experiment changes that ratio.

---

## 3. What is *not* being done about it

**The bar is not being adjusted.** It was computed to a frozen specification and it is correct.
What it reveals is that a twelve-month window cannot resolve this effect size — a fact about the
*test*, not a reason to move it. Widening the bar to let the strategy through would be tuning a
parameter to manufacture a GO, which is an iron rule.

**Criterion 3 is not being quietly dropped.** It reads what it reads.

---

## 4. What this leaves open — a decision, not a fix

The gate was designed to answer *"is this better than the fund?"* with twelve months of data. That
question is not answerable with twelve months of data. Three honest responses:

1. **Accept it.** Criterion 3 will almost certainly not go green. The GO gate then never opens on
   statistical significance, and the decision to keep running rests on the other five criteria plus
   the judgement already recorded: *plan at the index's ~11–12%, treat the backtest's excess as
   unproven upside, size the first year as tuition.*

2. **Re-register a longer window** before `CORE_V1` opens. A legitimate specification change *only*
   while no observation exists — which is now. Note that even five years leaves power near 15%.

3. **Change the question to one the data can answer.** Instead of *"is the edge significant?"* ask
   *"is the strategy materially **worse** than the fund?"* — a non-inferiority test. With
   $\sigma = 0.036$/yr, twelve months can rule out underperformance beyond about 6% with
   confidence, and that is genuinely useful: the live risk is not failing to be brilliant, it is
   paying costs and tax for nothing.

**Option 3 is the one that matches what the money is actually exposed to**, but it is a change to a
registered experiment and it is the user's call, not this file's. Whichever is chosen must be
recorded before the window opens on **2026-09-08**.

---

## 5. Reproducing it

```bash
uv run python scripts/exp_null.py --draws 2000 --seed 20260906
```

Deterministic given the seed, the panel and the membership table, all named in the JSON.
