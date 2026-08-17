# Integration audit — final pass (2026-08-17)

**Status: AUDIT ONLY — no behaviour changed. Awaiting instruction.**

## The user's observation, and the answer

> *"multiple things getting tested, and i am finding they work in its own but not in a sync system,
> hence i cant see the difference"*

That is the correct diagnosis, and it is now measurable. Every component works. They are not
synchronised, and the desynchronisation is **larger than the effect being measured**.

### Why you cannot see the difference — in rupees

| | Amount | Source |
|---|---:|---|
| **Signal** — System − Shadow profit, six weeks | **₹1,541** | `system_track.csv` (+0.39pp) |
| Confound 1 — composition artifact, **one day** (2026-07-10) | ₹1,964 | `ledger.json`, baskets 2.62pp apart |
| Confound 2 — cash drag (undeployed wallet) | ₹2,800 | 0.70pp, `+2.73%` deployed vs `+2.03%` contributed |
| Confound 3 — exposure difference (total deployed) | ₹3,675 | `system_flows.json`, 1.9% more capital |

**A single day of whole-share rounding (₹1,964) exceeds the entire six-week measured effect
(₹1,541).** Signal-to-noise is below 1. The experiment cannot resolve the AI's contribution, and no
amount of additional runtime fixes it — the noise scales with the number of deploy events.

Reproduce:
```bash
uv run python -c "
import json; L=json.load(open('data/autopilot/ledger.json'))
for d in L:
    if d['as_of']=='2026-07-10' and d['book'] in ('SYS','SHD'):
        print(d['book'], d['amount'], d['outcome_return_pct'])"
```

---

## Blocker verdicts

| # | Claim | Verdict |
|---|---|---|
| B1 | Experiment tests a different strategy than the GO rides | **TRUE — but by design** |
| B2 | Shadow is not a clean twin | **TRUE — mechanism identified** |
| B3 | Two baselines, different windows, interchangeable | **FALSE — trio is synchronised** |
| B4 | AI brief feeds nothing | **TRUE** |
| H1 | One book, two returns on one page | **TRUE — both correct, unlabelled** |
| H2 | Hit-rate verdicts mislabeled | **FALSE — ledger is consistent** |
| H3 | Rebalance fired on a trivial benefit / implausible drift | **FALSE — expected behaviour** |
| H4 | "Equity" tile includes cash | **TRUE** |

---

### B2 · TRUE — the tilt changes *what is bought*, not just how much

`scripts/autopilot.py:594` runs both books through the same advisor on the same date, varying only
the amount. Under the pre-registered design the tilt changes **size only**, so both baskets should
post an *identical percentage* return.

From `data/autopilot/ledger.json`, 2026-07-10:

| Book | Deployed | Basket return | Benchmark |
|---|---:|---:|---:|
| SYS | ₹93,750 | **+18.64%** | +1.73% |
| SHD | ₹75,000 | **+21.26%** | +1.73% |

₹93,750 / ₹75,000 = 1.25× — exactly the tilt. But the returns are **2.62pp apart**, which sizing
cannot produce.

**Root cause — `advise_deploy_into_weakness` is amount-dependent in composition:**

1. `max_name_fraction=0.20` ([deploy.py](src/qalpha/live/deploy.py)) drops any name whose *single
   share* exceeds 20% of the deploy → a smaller deploy has a **different investable universe**.
2. Whole-share greedy allocation lands different integer quantities and different tail names.

Both are correct, deliberate advisor features. Both are fatal to this comparison.

**A second, independent confound in the same measurement:** the tranche rule is `fraction × wallet`,
so front-loading shrinks every later tranche. Total deployed converges (₹196,253 vs ₹192,578, 1.9%
apart) — meaning the tilt is really testing **deployment *timing***, not size, which is not what the
pre-registration says it tests.

**System − Shadow therefore conflates three things** — AI directional skill, composition noise, and
timing — with the noise term dominating.

#### Options

| | Approach | Cost |
|---|---|---|
| **A** *(recommended)* | Compute the basket **once at a fixed notional**, then scale executed quantities by the tilt. Composition identical by construction; only size differs. | Re-seed the trio. Current System−Shadow history is void. |
| **B** | Keep the mechanism; stop calling it AI attribution. Report as "AI-paced vs unpaced system" — a joint effect. | No re-seed. Pillar 3 unanswerable. |
| **C** | Retire Shadow. Report System vs Baseline only. | No re-seed. One less question. |

Any choice requires a **disclosed amendment** to `docs/PREREGISTRATION_autopilot.md` (repo rule:
amendments are recorded, never rewritten).

---

### B1 · TRUE, but by design — a labelling fault

| Book | File | Marks | Window | Rebalance |
|---|---|---:|---|---|
| GO (criterion 6) | `data/paper/book.json` | 45 | 2026-06-12 → 08-14 | **annual** |
| System | `data/paper/adaptive_book.json` | 26 | 2026-07-10 → 08-14 | **§4.6-gated, daily eval** |

Genuinely different policies over different windows — but documented and intentional (CLAUDE.md: the
System book is the former smart-rebalance book upgraded in place). **Not a code bug.**

What is wrong is the page's claim that *"the System book above is the full system being proven."* It
proves the adaptive variant; the real-money GO rides the annual book. **Fix: one sentence of
relabelling.**

---

### B3 · FALSE — the trio is synchronised

`data/autopilot/system_track.csv`, first row:

```
2026-07-10, ..., baseline_value=350000.0, baseline_profit=0.0, baseline_return_pct=0.0
```

All three books start **2026-07-10 at ₹350,000**, baseline return exactly `0.0`. Return formulas are
identical across all three (`profit / net_contributions`, money-weighted). The trio comparison is
**valid**.

The `+3.69%` Nifty TRI is on the **GO page**, measured from 2026-06-12 — a window 28 days longer.
That is a cross-page mismatch the layout invites, not a measurement error. **Fix: never render two
books' returns side by side without both windows on screen.**

---

### B4 · TRUE — the AI's stock analysis has no consumer

`grep -rn 'ai_brief' --include='*.py' src scripts` → the only importer is its own generator; the
dashboard reads `reports/ai_brief.md` as markdown. The sole machine consumer is `parse_ai_signal` →
`signal_tilt` → deploy **amount**.

So the brief's watchlist (TECHM, HCLTECH, TCS, TATASTEEL, HINDALCO, AXISBANK) has **zero
intersection** with either the GO holdings or the buy list, and no code path. Architecturally
intended — rule (a) keeps the LLM out of the calculator — but the page **implies a link it does not
have**, at ~57k input tokens/day.

**Fix: render only the `SIGNAL:` line and the tilt it produced; collapse the narrative.**

---

### H1 · TRUE — two correct returns for one book, neither labelled

The table says system **+2.03%**; the hedge section says **+2.73%**. Both are right:

- `+2.03%` = `profit / net_contributions` — money-weighted on **all** capital, including the idle wallet.
- `+2.73%` = return on the **flow-adjusted** curve — capital actually deployed.

The 0.70pp gap **is the cash drag**, and it is larger than the entire AI effect being measured
(+0.39pp). Worth showing deliberately, not as an unexplained discrepancy.

---

### H2 · FALSE — verdicts are consistent

`resolve_decision` marks `worked` when `gap > _WORK_TOL`. Against the real ledger:

| Date | Book | Basket | Bench | Verdict | Correct? |
|---|---|---:|---:|---|---|
| 07-13 | SHD | 1.31% | 1.87% | didn't | ✓ |
| 07-14 | SYS | 3.31% | 2.11% | worked | ✓ |
| 07-15 | SYS | 1.31% | 1.70% | flat | ✓ |
| 07-17 | SYS | 8.75% | 0.68% | worked | ✓ |

SYS resolved = 5 (`worked ×4`, `flat ×1`) → **4/5 is correct.** The screenshot's small text was
misread. Standing caveat unchanged: **n = 5**, and the page's "low power early — not a verdict" is
the right framing.

---

### H3 · FALSE — the 79.4% drift is expected

The report reads *"rebalanced — drift 79.4% > threshold and §4.6 net-benefit gate cleared."* That
looks implausible for a six-week-old book only if drift is read as deviation from a held target. It
is deviation from the **core Nifty-50 target**, and the System book deliberately holds opportunistic
watchlist names (VEDL, TRENT, IRFC…) that are *not in that target at all*. Large drift is the
designed consequence of mixing an opportunistic sleeve with a core target. **Not a bug — but it
needs a definition on screen.**

---

### H4 · TRUE — the "Equity" tile is total book value

`data/paper/book.json` stores `equity` inclusive of cash:

```json
{"date": "2026-08-14", "equity": "201903.98", "cash": "7335.38"}
```

Holdings sum ₹193,388 + ₹7,335 cash = ₹200,723 = the tile. Shown beside a separate "Cash" tile it
reads as additive. **Fix: relabel to Book value, or subtract cash.**

---

## Pillar status against the ENDGAME CONTRACT

| Pillar | Evidence today | Status |
|---|---|---|
| 1. Core GO | GO book 45 marks, no volatility event yet | ⏳ accruing |
| 2. System > Baseline | +2.03% vs +0.98% over a synchronised window | 🟢 valid, low power |
| 3. AI verdict | signal ₹1,541 < noise ₹1,964 | 🔴 **unmeasurable as built** |
| 4. Hedge witnessed | `episodes 0`, `+2.73%` vs `+2.73%` identical | ⏳ no stress event |

**Pillar 2 is the one piece of the experiment that is actually sound** — same window, same cash
flows, same return formula, and the gap (+1.05pp) is not swamped by the confounds above, since both
books face the same composition mechanics.

---

## Recommended order

| # | Item | Effort | Blocks a pillar? |
|---|---|---|---|
| 1 | **Decide B2** (A / B / C) + amend the pre-registration | decision; ~half a day for A | **Yes — pillar 3** |
| 2 | Relabel the System book — it is not the GO book | 1 sentence | No |
| 3 | Relabel Equity → Book value | 1 line | No |
| 4 | Show both returns with their basis (`+2.03%` contributed / `+2.73%` deployed) | small | No |
| 5 | Never render two books' returns without windows | small | No |
| 6 | Collapse the AI narrative to the `SIGNAL:` line | small | No |
| 7 | Define "drift" on screen; retire the frozen A/B/C books from the page | small | No |

Items 2–7 are an afternoon and touch presentation only. **Item 1 is a design decision that is
yours** — and under option A it voids the current System−Shadow history, which is the honest cost of
having measured a confounded quantity for six weeks.

## On running code

Everything above was verified against committed data and source; every table is reproducible with
the commands shown. Where a fix needs a run to confirm — e.g. option A's claim that identical-notional
baskets produce identical percentage returns — that is a short scripted check against the existing
panels, and it will be written, run, and its output reported **before** any behaviour changes.

**Nothing has been changed.**
