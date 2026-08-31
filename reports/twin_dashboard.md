# The twin — 2026-08-31

_Generated 2026-08-31 19:10 UTC. Fake money; the real account is the state source and is never traded._

| Book | Net money in | Worth today | Gain | XIRR |
|---|---:|---:|---:|---:|
| REAL | ₹304,144 | ₹303,943 | ₹-201 | -5.3%/yr |
| **TWIN_FULL** | ₹304,144 | ₹303,513 | ₹-631 | -15.9%/yr |
| TWIN_NO_AI | ₹304,144 | ₹303,513 | ₹-631 | -15.9%/yr |
| TWIN_NO_HEDGE | ₹304,144 | ₹303,513 | ₹-631 | -15.9%/yr |
| TWIN_NO_EXITS | ₹304,144 | ₹303,513 | ₹-631 | -15.9%/yr |
| BASELINE_EW | ₹304,144 | ₹304,024 | ₹-120 | -3.2%/yr |
| BASELINE | ₹304,144 | ₹304,287 | ₹+143 | +4.0%/yr |

**The gate** (GO criterion 3 — the only comparison that authorises anything):
- **TWIN_FULL** is behind **BASELINE_EW** by ₹511 (-0.17% relative wealth, G=-0.0017) — **descriptive only**, 2 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.

**Diagnostics — descriptive, never gating.** Four comparisons at 95% confidence throw a false positive about one run in five, so these attribute; they do not authorise:
- **TWIN_FULL** is behind **BASELINE** by ₹774 (-0.25% relative wealth, G=-0.0025) — **descriptive only**, 2 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is ahead of **TWIN_NO_AI** by ₹0 (+0.00% relative wealth, G=+0.0000) — **descriptive only**, 2 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is ahead of **TWIN_NO_HEDGE** by ₹0 (+0.00% relative wealth, G=+0.0000) — **descriptive only**, 2 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is ahead of **TWIN_NO_EXITS** by ₹0 (+0.00% relative wealth, G=+0.0000) — **descriptive only**, 2 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.
- **TWIN_FULL** is behind **REAL** by ₹430 (-0.14% relative wealth, G=-0.0014) — **descriptive only**, 2 of 12 months. A window this short is dominated by *when* the money went in, not *what* was picked. No verdict before the locked 12-month evaluation.

---

# GO gate — **NOT YET** (2026-08-31)

**5 of 6 criteria are not green.** The system is not validated for real money.

| | Criterion | Reading |
|---|---|---|
| 🟡 | Track length | 2 of 12 months |
| 🟡 | Volatility event withstood | worst in-window fall -2.2%, gate needs ≤ -10% |
| ⚪ | Beats the equal-weight fund | relative wealth -0.17% (₹-511), but the pre-registered null has not been run |
| 🟡 | Tax reconciled | only a single-lot, all-STCG, no-loss sale has ever matched (₹25.25, Δ ₹0.00) |
| 🟡 | Corporate action reconciled | never |
| 🟢 | Data integrity | tradebook matches the broker; no ungated gaps |

**What would settle each:**
- **Track length** — 10 more months. Calendar time; nothing accelerates it.
- **Volatility event withstood** — a real market fall. Nobody has watched this system through one.
- **Beats the equal-weight fund** — generate the matched null (twin.NULL_P95_LOG_REL_WEALTH names its specification) — without a bar, no gap can be read, and a missing bar is never a bar of zero
- **Tax reconciled** — one multi-lot or LTCG sale, reconciled afterwards. §70 set-off fires on every harvest and has never been confirmed by a third party.
- **Corporate action reconciled** — one split, bonus or dividend applied live and matched. Demerger is not modelled at all.
