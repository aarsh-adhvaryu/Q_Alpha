# The twin — 2026-09-09

_Generated 2026-09-09 17:04 UTC. Fake money; the real account is the state source and is never traded._

| Book | Net money in | Worth today | Gain | XIRR |
|---|---:|---:|---:|---:|
| REAL | ₹304,144 | ₹293,879 | ₹-10,265 | -61.1%/yr |
| **TWIN_FULL** | ₹304,144 | ₹291,076 | ₹-13,068 | -70.2%/yr |
| TWIN_NO_AI | ₹304,144 | ₹290,614 | ₹-13,530 | -71.5%/yr |
| TWIN_NO_HEDGE | ₹304,144 | ₹291,076 | ₹-13,068 | -70.2%/yr |
| TWIN_NO_EXITS | ₹304,144 | ₹290,210 | ₹-13,934 | -72.6%/yr |
| CORE_V1 | ₹304,144 | ₹301,290 | ₹-2,854 | -22.7%/yr |
| BASELINE_EW | ₹304,144 | ₹295,901 | ₹-8,243 | -53.0%/yr |
| BASELINE | ₹304,144 | ₹296,038 | ₹-8,106 | -52.3%/yr |

**The gate** (GO criterion 3 — the only comparison that authorises anything):
- **CORE_V1** is ahead of **BASELINE_EW** by ₹5,389 (-0.23% relative wealth, G=-0.0023) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is behind **BASELINE_EW** by ₹4,825 (-0.91% relative wealth, G=-0.0092) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.

**Diagnostics — descriptive, never gating.** Four comparisons at 95% confidence throw a false positive about one run in five, so these attribute; they do not authorise:
- **TWIN_FULL** is behind **BASELINE** by ₹4,962 (-0.93% relative wealth, G=-0.0093) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is ahead of **TWIN_NO_AI** by ₹462 (+0.16% relative wealth, G=+0.0016) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is ahead of **TWIN_NO_HEDGE** by ₹0 (+0.00% relative wealth, G=+0.0000) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is ahead of **TWIN_NO_EXITS** by ₹866 (+0.30% relative wealth, G=+0.0030) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **CORE_V1** is ahead of **TWIN_FULL** by ₹10,214 (-0.17% relative wealth, G=-0.0017) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is behind **REAL** by ₹2,803 (-0.58% relative wealth, G=-0.0058) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.

---

# GO gate — **NOT YET** (2026-09-09)

**6 of 6 criteria are not green.** The system is not validated for real money.

| | Criterion | Reading |
|---|---|---|
| ⚪ | Track length | no cash flows on record |
| ⚪ | Volatility event withstood | no benchmark series covering the window |
| ⚪ | Beats the equal-weight fund | no comparison computed |
| ⚪ | Tax reconciled | no reconciliation on record |
| ⚪ | Corporate action reconciled | no record |
| ⚪ | Data integrity | not checked |

**What would settle each:**
- **Track length** — upload the tradebook — the flows are its only source
- **Volatility event withstood** — refresh the benchmark — a stale copy once read a −2.2% fall as 0.0%
- **Beats the equal-weight fund** — seed and mark the twin books
- **Tax reconciled** — upload a Console Tax P&L covering a sale
- **Corporate action reconciled** — a live action
- **Data integrity** — run the live reconciliation
