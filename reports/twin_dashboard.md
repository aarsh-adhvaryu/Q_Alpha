# The twin — 2026-09-11

_Generated 2026-09-11 15:22 UTC. Fake money; the real account is the state source and is never traded._

| Book | Net money in | Worth today | Gain | XIRR |
|---|---:|---:|---:|---:|
| REAL | ₹304,144 | ₹290,673 | ₹-13,471 | -66.2%/yr |
| **TWIN_FULL** | ₹304,144 | ₹285,875 | ₹-18,269 | -77.4%/yr |
| TWIN_NO_AI | ₹304,144 | ₹286,306 | ₹-17,838 | -76.5%/yr |
| TWIN_NO_HEDGE | ₹304,144 | ₹285,875 | ₹-18,269 | -77.4%/yr |
| TWIN_NO_EXITS | ₹304,144 | ₹285,321 | ₹-18,823 | -78.4%/yr |
| CORE_V1 | ₹304,144 | ₹296,767 | ₹-7,377 | -44.3%/yr |
| BASELINE_EW | ₹304,144 | ₹294,757 | ₹-9,387 | -52.7%/yr |
| BASELINE | ₹304,144 | ₹294,923 | ₹-9,221 | -52.0%/yr |

**The gate** (GO criterion 3 — the only comparison that authorises anything):
- **CORE_V1** is ahead of **BASELINE_EW** by ₹2,010 (-1.35% relative wealth, G=-0.0136) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is behind **BASELINE_EW** by ₹8,881 (-2.31% relative wealth, G=-0.0233) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.

**Diagnostics — descriptive, never gating.** Four comparisons at 95% confidence throw a false positive about one run in five, so these attribute; they do not authorise:
- **TWIN_FULL** is behind **BASELINE** by ₹9,048 (-2.33% relative wealth, G=-0.0236) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is behind **TWIN_NO_AI** by ₹431 (-0.15% relative wealth, G=-0.0015) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is ahead of **TWIN_NO_HEDGE** by ₹0 (+0.00% relative wealth, G=+0.0000) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is ahead of **TWIN_NO_EXITS** by ₹555 (+0.19% relative wealth, G=+0.0019) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **CORE_V1** is ahead of **TWIN_FULL** by ₹10,891 (+0.12% relative wealth, G=+0.0012) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is behind **REAL** by ₹4,798 (-1.28% relative wealth, G=-0.0129) — **descriptive only**, 0 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.

---

# GO gate — **NOT YET** (2026-09-11)

**6 of 6 criteria are not green.** The system is not validated for real money.

| | Criterion | Reading |
|---|---|---|
| ⚪ | Track length | no cash flows on record |
| 🟡 | Volatility event withstood | worst in-window fall -1.1%, gate needs ≤ -10% |
| ⚪ | Beats the equal-weight fund | no comparison computed |
| ⚪ | Tax reconciled | no reconciliation on record |
| ⚪ | Corporate action reconciled | no record |
| ⚪ | Data integrity | not checked |

**What would settle each:**
- **Track length** — upload the tradebook — the flows are its only source
- **Volatility event withstood** — a real market fall. Nobody has watched this system through one.
- **Beats the equal-weight fund** — seed and mark the twin books
- **Tax reconciled** — upload a Console Tax P&L covering a sale
- **Corporate action reconciled** — a live action
- **Data integrity** — run the live reconciliation
