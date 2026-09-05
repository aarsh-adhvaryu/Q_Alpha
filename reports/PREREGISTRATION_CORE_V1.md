# Pre-registration — CORE_V1, the deterministic screen's own clock

**Frozen 2026-09-05. The measured window opens 2026-09-08 and closes 2027-09-08.**

Registered before the book was created and before any day inside the window was observed.

---

## 1. Why this experiment exists separately

Run 2 gates `TWIN_FULL` against `BASELINE_EW`. `TWIN_FULL` is the whole system: the screen, the AI
veto, the exits, the hedge signal. Every improvement to any of those is a treatment change, and a
treatment change restarts a twelve-month clock.

That is the trap this project has been in. Each fix made the system better and the evidence date
later, so the closer the work got to finished, the further away the answer moved.

`CORE_V1` breaks the coupling by answering a narrower question with a treatment that **inherits from
nothing**:

> Does the deterministic screen beat the equal-weight fund anyone can buy?

The AI, the evidence adapter and the risk governor can now be built, versioned and replaced without
touching this clock, because none of them reaches this book.

**`CORE_V1` is not `TWIN_NO_AI`.** Every `TWIN_*` book is defined as the composite minus one flag, so
it moves whenever the composite moves. Wiring the governor into `TWIN_FULL` would change `TWIN_NO_AI`
too. A book carrying a twelve-month clock cannot be defined relative to something under construction.

## 2. The treatment — frozen

| Parameter | Value |
|---|---|
| Selection | `advise_deploy_into_weakness`, unchanged |
| `use_ai` | `False` |
| `use_hedge` | `False` |
| `use_exits` | `True` (the §4.7 idiosyncratic-breakdown test) |
| `max_names_default` | 15 |
| `idle_cash_floor` | ₹5,000 |
| `max_sector_weight` | 0.30 |
| `max_name_fraction` | 0.20 |
| Cash flows | identical to every other book, from the user's real tradebook |

Exits are **on** because they are part of the process the real money runs. There is no stop-loss,
deliberately: the screen buys names that are down, so a stop sells what it just bought.

## 3. The gating statistic

$$G = \ln\frac{\mathrm{NAV}_{\text{CORE\_V1}}}{\mathrm{NAV}_{\text{BASELINE\_EW}}}$$

Unitized NAVs from `CORE_EVALUATION_START`, exactly as in run 2 and for the same reason: raw book
values are not contribution-invariant, so a monthly SIP would walk a ratio of them toward zero.

`BASELINE_EW` is unchanged — the point-in-time equal-weight Nifty-50 fund, net of a 0.41% fee. It is
the harder baseline and the only one that gates. Beating cap-weighted NIFTYBEES is not the
achievement it looks like, because 76% of the screen's historical gap over it is the equal-weight
premium, and that premium is purchasable.

## 4. The null — specification frozen, value not yet computed

Identical in construction to run 2's: **≥1,000 draws**, matched on the same flow dates and the same
investable universe, `p95` of $G$ under the null taken as the threshold. Computing it later cannot
be tuned to the result because the specification is fixed here.

Until it exists, criterion 3 reads ⚪ CANNOT ASSESS. It must exist before 2027-09-08.

## 5. What resets this clock, and what does not

**Resets it — a new `CORE_V2` with a new start date:**
- any change to `advise_deploy_into_weakness` selection or ranking
- any change to a parameter in §2
- any change to `BASELINE_EW`'s construction

**Does NOT reset it:**
- AI prompt, model, parser or evidence-rule versions
- the evidence adapter, its feeds, or its thresholds
- the risk governor and its rules
- new sleeves, new engines, new dashboards
- anything at all in `TWIN_FULL` or the run-2 ablation family

This list is the whole point of the experiment. It is not a convenience.

## 6. Known properties, stated in advance

**The book is created on 2026-09-05, three days before the window opens.** The deterministic entry
therefore completes before measurement starts, so the first weeks are not dominated by a book sitting
in cash beside a fully-invested fund. The window date is registered here in advance and may not be
moved to suit a result. **Any cash still idle when the window opens stays in the record and is not
corrected for.**

`CORE_V1` will differ from `TWIN_NO_AI` despite similar policies, because their entry dates differ.
That is expected and is not a defect.

## 7. What this experiment does not claim

- It says nothing about whether the AI veto adds value. That is a separate, separately versioned
  track.
- It says nothing about the governor, which enforces nothing yet.
- It is **not** a validation of the backtest headline. That headline is not out-of-sample: `shrink`
  was selected by requiring it to beat 1/N on the 2025–26 holdout, which makes the holdout
  validation data.
- The screen the real money runs has never been backtested out-of-sample at all. **This forward run
  is the only clean evidence route that exists**, and it is why the clock must stop being restarted.

## 8. Status at T−3 (2026-09-05)

Book not yet created. Window not open. `NULL_P95_LOG_REL_WEALTH` is `None`. No verdict before
2027-09-08.
