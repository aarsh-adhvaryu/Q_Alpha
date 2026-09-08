# The twin — 2026-09-08

_Generated 2026-09-08 13:55 UTC. Fake money; the real account is the state source and is never traded._

| Book | Net money in | Worth today | Gain | XIRR |
|---|---:|---:|---:|---:|
| REAL | ₹304,144 | ₹297,352 | ₹-6,792 | -48.8%/yr |
| **TWIN_FULL** | ₹304,144 | ₹292,430 | ₹-11,714 | -69.0%/yr |
| TWIN_NO_AI | ₹304,144 | ₹291,981 | ₹-12,163 | -70.4%/yr |
| TWIN_NO_HEDGE | ₹304,144 | ₹292,430 | ₹-11,714 | -69.0%/yr |
| TWIN_NO_EXITS | ₹304,144 | ₹292,282 | ₹-11,862 | -69.4%/yr |
| CORE_V1 | ₹304,144 | ₹303,198 | ₹-946 | -8.8%/yr |
| BASELINE_EW | ₹304,144 | ₹297,088 | ₹-7,056 | -50.1%/yr |
| BASELINE | ₹304,144 | ₹298,136 | ₹-6,008 | -44.6%/yr |

**The gate** (GO criterion 3 — the only comparison that authorises anything):
- **CORE_V1** is ahead of **BASELINE_EW** by ₹6,109 (+0.00% relative wealth, G=+0.0000) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is behind **BASELINE_EW** by ₹4,659 (-0.85% relative wealth, G=-0.0085) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.

**Diagnostics — descriptive, never gating.** Four comparisons at 95% confidence throw a false positive about one run in five, so these attribute; they do not authorise:
- **TWIN_FULL** is behind **BASELINE** by ₹5,706 (-1.16% relative wealth, G=-0.0117) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is ahead of **TWIN_NO_AI** by ₹449 (+0.15% relative wealth, G=+0.0015) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is ahead of **TWIN_NO_HEDGE** by ₹0 (+0.00% relative wealth, G=+0.0000) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is ahead of **TWIN_NO_EXITS** by ₹148 (+0.05% relative wealth, G=+0.0005) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **CORE_V1** is ahead of **TWIN_FULL** by ₹10,768 (+0.00% relative wealth, G=+0.0000) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is behind **REAL** by ₹4,922 (-1.29% relative wealth, G=-0.0130) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.

---

# GO gate — **NOT YET** (2026-09-08)

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
