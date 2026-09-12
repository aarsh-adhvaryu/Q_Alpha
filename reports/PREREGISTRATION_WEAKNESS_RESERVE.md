# Pre-registration — WC-2: does holding money back for deep drawdowns actually pay?

**Registered 2026-09-12, before `scripts/exp_weakness_reserve.py` was written and before any
reserve return existed.** Nothing above section 7 may be edited once it has run.

---

## 1. The question WC-1 could not answer

`WC-1` found that money deployed in a deep drawdown beat the fund by a median **+30.3%**, while
money deployed on an ordinary day **lost 3.1%**. That is an opportunity, not a policy.

**Every WC-1 cohort was fully invested on the day it arrived.** Nothing was held back, so WC-1
cannot say whether *withholding* money on ordinary months to have more available in deep ones is
worth doing. It measured which days were good, not whether you can wait for them.

> **Waiting has a price and WC-1 never paid it.** Deep months are **11 of 177 — 6%** — and they
> arrive in clusters with long gaps: there is no `deep` month between **2016-03 and 2020-04**, four
> years. A rule that holds 40% of every instalment back holds it, uninvested, through those four
> years of a rising market. **That cost is the whole experiment.** The upside is already known; what
> is unknown is whether it survives the drag.

## 2. The mechanism, fixed now

Each month ₹50,000 arrives. `market_weakness(index, day).level` — the same function the live screen
calls, using data to that day only — decides what happens to it:

| Market that day | What the month's money does |
|---|---|
| `normal` | deploy `1 − r` of the allowance; **`r` goes to a reserve and stays in cash** |
| `elevated` | deploy the full allowance; the reserve is untouched |
| `deep` | deploy the allowance **and the entire reserve** |

Everything deployed buys the **top-8 by `cheapness_scores`**, equal-weighted, whole shares, Zerodha
costs charged. **Nothing is ever sold** — settled by PO-1, PO-2 and the user.

## 3. The grid, fixed now, and reported whole

`r ∈ {0.00, 0.25, 0.50}` × release on `{deep}` and `{deep, elevated}`.

- **`r = 0.00` is the control and the harness check.** It is "deploy everything, always" — the
  current live behaviour — and it **must reproduce PO-2's top-8 terminal of ₹30,058,634.** If it
  does not, the harness is wrong and no other cell may be read. This is the check that caught
  nothing in PO-2 and everything in PL-1's ablation.
- **Every cell is reported.** Not the best one. A grid searched for its winner and then quoted as a
  result is how this project would overfit fourteen years of one market, and at this effect size
  noise is most of what there is.

## 4. What each outcome means, fixed in advance

| Finding | What follows |
|---|---|
| **Every** reserve cell beats the control | The lever is worth connecting. Wire `market_weakness` to the money under PL-2, registered separately. |
| Some cells beat it, some lose | **Ship nothing.** A rule that works at `r = 0.25` and fails at `r = 0.50` is a tuned parameter, not an effect, and this is exactly the shape noise takes. |
| No cell beats the control | **The lever stays disconnected, and the docstring gets corrected instead.** The timing premise is real (WC-1) and unharvestable by waiting — those are compatible, and the honest conclusion is "deploy steadily". |

## 5. What this cannot settle

- **One path.** Fourteen years of one market, and the deep episodes are ~7 events with COVID four
  of the eleven months. The result will be dominated by whether COVID's reserve release happened to
  land well.
- **The thresholds were not chosen blind.** `market_weakness`'s levels were set before this test,
  but by people who had seen this history.
- **It cannot license real money**, and it authorizes no GO. There is no gate.
- **A reserve is unspent money the user can see.** If this ships, the page must say what is being
  held back and why, every month — an amount that vanishes without explanation reads as a bug, and
  `Mandate.reserved` exists for exactly that reason.

## 6. The honest case against the whole idea

- **It is market timing.** This repository's own strongest proven result is that *trading less* and
  *staying invested* beat the alternatives net of cost and tax. A reserve is the first mechanism
  here that deliberately stays out of the market.
- **It cannot be run without discipline the user has not been asked for.** The reserve has to still
  be there when the drawdown comes.
- **6% of months is a thin target to aim a policy at**, and the next deep drawdown need not resemble
  the seven in this sample.

## 7. Recorded outcomes

*(Append only. Each line dated. Nothing above may be edited after the first run.)*

- **2026-09-12** — registered. Script not yet written. No reserve return exists.

- **2026-09-12, run. The control reproduced ₹30,058,634 — PO-2's top-8 terminal, exactly.** The
  harness check passes, so the rest of the grid may be read.

  | Policy | Terminal | vs control | Mean cash | Releases |
  |---|---:|---:|---:|---:|
  | control — deploy everything, always | ₹30,058,634 | — | 0.1% | 11 |
  | hold 25% on normal, release on **deep** | ₹31,942,979 | **+6.27%** | 3.6% | 11 |
  | hold 50% on normal, release on **deep** | ₹33,736,105 | **+12.23%** | 7.2% | 11 |
  | hold 25%, release on deep+elevated | ₹29,761,855 | −0.99% | 1.4% | 71 |
  | hold 50%, release on deep+elevated | ₹29,642,627 | −1.38% | 2.8% | 71 |

- **2026-09-12, the verdict by §4 is SHIP NOTHING, and it stands.** Some cells beat the control and
  some lose, which is the second row of the table fixed in advance. Nothing is wired today.

- **2026-09-12, but the split is structural, not noise, and that has to be said too.** §4's second
  row gave its reason: *"a rule that works at `r = 0.25` and fails at `r = 0.50` is a tuned
  parameter"*. **That is not what happened.** The hold-back fraction is **monotone and wins at both
  values** (+6.27% → +12.23%); the grid splits entirely on the **release rule**.

  And the mechanism is visible in the release counts: **71 releases against 11.** Releasing on
  `elevated` empties the reserve at the first mild dip, so it is never there when the market is
  actually deep — that variant is barely a reserve policy at all, which is why it lands within 1.4%
  of the control. **`WC-1` had already characterised `elevated` as noise (+2.0%, coin-toss hit rate)
  before this ran.** So the losing half of the grid is a policy WC-1 predicted would not work.

  **This is exactly the reasoning a pre-registration exists to distrust**, so it changes nothing
  today. It is recorded because the next experiment needs it, not because it licenses this one.

---

## 8. WC-2b — the robustness test, registered 2026-09-12 *after* seeing the above and *before* it ran

**§1–7 are closed. This section is a new registration and the rule below was fixed before the
script was written.** It exists because "release on `deep` only" now looks good on one fourteen-year
path, and this project has twice adopted a result as an expected value after seeing it.

**The question:** is the deep-only reserve an effect, or is it fitted to this history?

**Two attacks, both of which it must survive:**

1. **Period split.** 2012-01 → 2019-06 and 2019-07 → 2026-09. Both halves contain deep episodes
   (2012-06 / 2015-09 / 2016-02–03, and COVID / 2022-07 / 2025-03 / 2026-04).
2. **Threshold perturbation.** `market_weakness` calls `deep` at −12%. Re-run at **−10% and −15%**.
   A rule that works only at −12% is fitted to where this particular history's drawdowns fell.

**The decision rule, fixed now:**

| Finding | What follows |
|---|---|
| Beats the control in **both halves** at **both** `r`, and at **all three** thresholds | Wire it. `Mandate.deployable` gains a reserve; `Mandate.reserved` already exists to show it. |
| Wins overall but fails **any** half or **any** threshold | **The lever stays disconnected**, and this is recorded as a fourteen-year-path artefact. |
| COVID alone carries it — the 2019–2026 half wins and 2012–2019 does not | **Do not wire it.** One crash is not a sample of crashes, and a reserve built for COVID is a reserve built for the last war. |

**No further cells.** If it fails, the answer is no, not a third grid.


## 9. WC-2b recorded outcome

*(Append only. §8's decision rule was fixed before the script was written and is not renegotiable.)*

- **2026-09-12, run. THE LEVER STAYS DISCONNECTED.** 4 of 18 cells lost to their own control — both
  `r` values at the **−15% threshold, in both halves**. §8's rule: *wins overall but fails any half
  or any threshold → the lever stays disconnected.* It ships nothing. The classifier agreed with
  `market_weakness` on all **177** paydays before any row was computed.

  Terminal vs its own control, at `r = 50%`:

  | Period | `deep` ≤ −10% | `deep` ≤ −12% | `deep` ≤ −15% |
  |---|---:|---:|---:|
  | full 2012–2026 | +6.20% | **+12.23%** | +10.44% |
  | first half 2012–2019 | +1.70% | +0.89% | **−1.60%** |
  | second half 2019–2026 | +1.28% | +1.49% | **−1.09%** |

- **2026-09-12, and the failed cells are not the worst of it.** The full period wins on every
  threshold while **both halves win barely or lose**. A real effect does not behave like that. The
  gap is the accumulation: in the full run the reserve has been building since 2012 when COVID
  arrives in 2020, so eight years of withheld instalments go in at the bottom at once. Split the
  period and that accumulation never gets to build — the second half starts empty in 2019-07 with
  eight months of savings before the crash — and the effect collapses from +12.23% to **+1.49%**.

  **So WC-2's headline is substantially one alignment: having eight years of savings ready in March
  2020.** §5 of this registration named that risk before the first run — *"substantially a statement
  about whether one reserve release in 2020 happened to land well"* — and §8's third row named the
  verdict. Both were right.

- **2026-09-12, what is true at the end of it.** `WC-1`'s finding stands: **money deployed in a deep
  drawdown really is better money** (+30.3% median vs the fund, monotone, survivorship-free). What
  fails is the attempt to *harvest* it by waiting. Those are compatible, and together they say
  something useful: **the good entry points are real and you cannot reliably save up for them.**

  The honest consequence is the boring one this repository keeps arriving at — **deploy steadily**.
  That is also what the proven results already said: trading less and staying invested beat the
  alternatives net of cost and tax, and a reserve is the first mechanism here that deliberately
  stays out of the market.

- **2026-09-12, what would change the answer**, so nobody re-runs this hoping for a better day:
  a **longer history containing more than seven deep episodes**, or a universe with independent
  paths. Neither exists here. Re-running this grid on this data is not a new experiment, and a
  third grid is explicitly refused by §8.
