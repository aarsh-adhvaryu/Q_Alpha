# The twin — 2026-09-03

_Generated 2026-09-03 16:34 UTC. Fake money; the real account is the state source and is never traded._

| Book | Net money in | Worth today | Gain | XIRR |
|---|---:|---:|---:|---:|
| REAL | ₹304,144 | ₹301,643 | ₹-2,501 | -33.7%/yr |
| **TWIN_FULL** | ₹304,144 | ₹296,359 | ₹-7,785 | -73.0%/yr |
| TWIN_NO_AI | ₹304,144 | ₹296,354 | ₹-7,790 | -73.0%/yr |
| TWIN_NO_HEDGE | ₹304,144 | ₹296,359 | ₹-7,785 | -73.0%/yr |
| TWIN_NO_EXITS | ₹304,144 | ₹296,239 | ₹-7,905 | -73.5%/yr |
| BASELINE_EW | ₹304,144 | ₹299,383 | ₹-4,761 | -54.6%/yr |
| BASELINE | ₹304,144 | ₹300,984 | ₹-3,160 | -40.6%/yr |

**The gate** (GO criterion 3 — the only comparison that authorises anything):
- **TWIN_FULL** is behind **BASELINE_EW** by ₹3,024 (-0.29% relative wealth, G=-0.0029) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.

**Diagnostics — descriptive, never gating.** Four comparisons at 95% confidence throw a false positive about one run in five, so these attribute; they do not authorise:
- **TWIN_FULL** is behind **BASELINE** by ₹4,625 (-0.78% relative wealth, G=-0.0079) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is ahead of **TWIN_NO_AI** by ₹4 (+0.00% relative wealth, G=+0.0000) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is ahead of **TWIN_NO_HEDGE** by ₹0 (+0.00% relative wealth, G=+0.0000) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is ahead of **TWIN_NO_EXITS** by ₹120 (+0.04% relative wealth, G=+0.0004) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is behind **REAL** by ₹5,284 (-1.38% relative wealth, G=-0.0139) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.

---

# GO gate — **NOT YET** (2026-09-03)

**6 of 6 criteria are not green.** The system is not validated for real money.

| | Criterion | Reading |
|---|---|---|
| 🟡 | Track length | 0 of 12 months |
| 🟡 | Volatility event withstood | worst in-window fall -0.2%, gate needs ≤ -10% |
| ⚪ | Beats the equal-weight fund | relative wealth -0.29% (₹-3,024), but the pre-registered null has not been run |
| ⚪ | Tax reconciled | no reconciliation on record |
| ⚪ | Corporate action reconciled | no record |
| ⚪ | Data integrity | not checked |

**What would settle each:**
- **Track length** — 12 more months. Calendar time; nothing accelerates it.
- **Volatility event withstood** — a real market fall. Nobody has watched this system through one.
- **Beats the equal-weight fund** — generate the matched null (twin.NULL_P95_LOG_REL_WEALTH names its specification) — without a bar, no gap can be read, and a missing bar is never a bar of zero
- **Tax reconciled** — upload a Console Tax P&L covering a sale
- **Corporate action reconciled** — a live action
- **Data integrity** — run the live reconciliation
