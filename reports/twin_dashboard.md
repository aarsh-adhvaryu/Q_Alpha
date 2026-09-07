# The twin — 2026-09-07

_Generated 2026-09-07 17:47 UTC. Fake money; the real account is the state source and is never traded._

| Book | Net money in | Worth today | Gain | XIRR |
|---|---:|---:|---:|---:|
| REAL | ₹304,144 | ₹297,873 | ₹-6,271 | -48.9%/yr |
| **TWIN_FULL** | ₹304,144 | ₹292,886 | ₹-11,258 | -70.6%/yr |
| TWIN_NO_AI | ₹304,144 | ₹292,668 | ₹-11,476 | -71.3%/yr |
| TWIN_NO_HEDGE | ₹304,144 | ₹292,886 | ₹-11,258 | -70.6%/yr |
| TWIN_NO_EXITS | ₹304,144 | ₹292,575 | ₹-11,569 | -71.6%/yr |
| CORE_V1 | ₹304,144 | ₹303,179 | ₹-965 | -9.7%/yr |
| BASELINE_EW | ₹304,144 | ₹297,854 | ₹-6,290 | -49.1%/yr |
| BASELINE | ₹304,144 | ₹299,416 | ₹-4,728 | -39.6%/yr |

**The gate** (GO criterion 3 — the only comparison that authorises anything):
- **CORE_V1** is ahead of **BASELINE_EW** by ₹5,325 — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is behind **BASELINE_EW** by ₹4,968 (-0.95% relative wealth, G=-0.0096) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.

**Diagnostics — descriptive, never gating.** Four comparisons at 95% confidence throw a false positive about one run in five, so these attribute; they do not authorise:
- **TWIN_FULL** is behind **BASELINE** by ₹6,530 (-1.43% relative wealth, G=-0.0144) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is ahead of **TWIN_NO_AI** by ₹218 (+0.07% relative wealth, G=+0.0007) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is ahead of **TWIN_NO_HEDGE** by ₹0 (+0.00% relative wealth, G=+0.0000) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is ahead of **TWIN_NO_EXITS** by ₹311 (+0.11% relative wealth, G=+0.0011) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **CORE_V1** is ahead of **TWIN_FULL** by ₹10,293 — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is behind **REAL** by ₹4,987 (-1.31% relative wealth, G=-0.0131) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.

---

# GO gate — **NOT YET** (2026-09-07)

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
