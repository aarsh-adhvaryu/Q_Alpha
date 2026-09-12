# Pre-registration — SYSTEM: one book, deciding for itself

**Registered 2026-09-12, two days before the window opens.** The direction matters: every day in
the measured window is, at the time of writing, unobserved. Nothing below may be edited once
2026-09-14 arrives; corrections go in a dated section at the bottom.

---

## 1. The question

> **Does the whole system, deciding for itself, beat the fund anyone can buy in five minutes?**

One question, one statistic, one bar. Not *which component helps* — that is a harder question than
this one and this one is already hard.

## 2. The books

| Book | What it is |
|---|---|
| `SYSTEM` | The whole thing deciding: the screen, the evidence layer, the governor, the §4.7 exits, Zerodha costs and Indian capital-gains tax, all acting on fake money |
| `BASELINE_EW` | The Nifty-50 **equal-weight index fund**, charged the cheapest real expense ratio (DSP direct, 0.41%/yr) |
| `BASELINE` | NIFTYBEES — the cap-weighted index, bought and held. The do-nothing floor, **never the bar** |
| `REAL` | The user's tradebook replayed. What he actually did |

**Why `BASELINE_EW` is the bar and not the index.** Phase 4 found that **76% of the screen's gap
over NIFTYBEES is the equal-weight premium**, and that premium is purchasable. Beating the
cap-weighted index is not the achievement it looks like; a system that cannot beat the best cheap
passive alternative should not run.

### What was deleted to get here, and why

It was **nine books and a GO gate**, removed 2026-09-12:

- **Three ablations** (`TWIN_NO_AI`, `TWIN_NO_HEDGE`, `TWIN_NO_EXITS`) asked which single component
  earns its keep. If separating the whole system from chance needs two hundred years, separating one
  of its three parts needs longer.
- **`CORE_V1`**, a second clock for a second experiment nobody could finish either.
- **The gate** — six criteria, a matched null, an authorising pair — graded a verdict that could
  never arrive. `AUTHORIZING_PAIR` was `None` and would have stayed `None`. Six criteria reading
  ⚪ CANNOT ASSESS for ever is not honesty; it is a surface that teaches its reader to stop looking.

## 3. One start, and it is the user's own

**`SYSTEM` is seeded as a copy of `REAL`, not as cash.** It holds precisely what the user holds,
follows the tradebook until the window opens, and only then begins to choose.

This is the substantive design change. Previously nine books were each funded by the user's deposits
on the user's dates — the tradebook as a **cash-flow tap** rather than a starting portfolio — so
every book's record was entangled with *when he happened to add money*. Two books from one state
means every later difference between them is **a decision**, not a different starting point.

* **State at t0:** the tradebook replayed — 13 trades from 2026-06-15, ₹304,144.01 net invested.
* **Verified on registration day:** `SYSTEM − REAL = ₹0`. Identical holdings, identical value.
* **`EVALUATION_START = 2026-09-14`** — the day `SYSTEM` starts deciding, and therefore the day the
  measured window opens. Forward-dated by two days *on purpose*: starting an experiment on days
  whose outcome is already known is selection on the outcome, and this project has twice adopted a
  result as the expected value after seeing it.
* **Future cash flows go to every book on the same date**, enforced by `assert_identical_flows`.
  The user does not intend to invest for some time, so the comparison is not expected to be
  disturbed by deposit timing either way.

## 4. What may be claimed, and what may not

**May be claimed:** what happened. The gap between two books over a stated window, labelled as a
description.

**May NOT be claimed:**

- **That any gap is evidence of skill.** The backtested edge over this benchmark is **0.42%/yr**
  against **5.3%/yr** of drift between a 15-name basket and the fund. Detecting it at 95% needs
  roughly **two hundred years**. A twelve-month result — in either direction — is consistent with
  chance, and saying so afterwards is not a caveat, it is the finding.
- **That this authorizes anything.** Nothing here opens a gate, because there is no gate. Real money
  remains the user's own decision, placed by him, as it always has been.
- **Nothing about the AI layer's value.** `AI-V2` drops a name from this book on a verified filing
  event. Whether acting on those events beats not acting is the **event study**, which is
  unregistered and unrun. Until it is, the AI's contribution here is untested and is not separable
  from the rest — by construction, since the ablation that would have separated it is gone.

## 5. What would make this worth reading

The honest answer is **the event study, not this book.** One portfolio over twelve months is *one
observation* of a small signal inside large noise. The corpus built on 2026-09-12 — 3,898 filings,
4,776 verified events — moves the same question to the event level, where there are thousands of
observations and significance is reachable in months rather than centuries.

This book is the operational record. It is worth keeping because a system that cannot be watched
cannot be trusted, and because the day it does something stupid, the record will say so. It is not
the evidence.

## 6. Recorded outcomes

*(Append only. Each line dated. Nothing above may be edited after 2026-09-14.)*

- **2026-09-12** — registered. Books seeded from the tradebook; `SYSTEM − REAL = ₹0` verified.
  Window opens 2026-09-14. Not yet autonomous.
