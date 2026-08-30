# The twin — 2026-08-30

_Generated 2026-08-30 05:17 UTC. Fake money; the real account is the state source and is never traded._

| Book | Net money in | Worth today | Gain | XIRR |
|---|---:|---:|---:|---:|
| REAL | ₹304,144 | ₹303,943 | ₹-201 | -6.9%/yr |
| **TWIN_FULL** | ₹304,144 | ₹303,513 | ₹-631 | -20.1%/yr |
| TWIN_NO_AI | ₹304,144 | ₹303,513 | ₹-631 | -20.1%/yr |
| TWIN_NO_HEDGE | ₹304,144 | ₹303,513 | ₹-631 | -20.1%/yr |
| TWIN_NO_EXITS | ₹304,144 | ₹303,513 | ₹-631 | -20.1%/yr |
| BASELINE_EW | ₹304,144 | ₹304,027 | ₹-117 | -4.0%/yr |
| BASELINE | ₹304,144 | ₹304,287 | ₹+143 | +5.2%/yr |

**The gate** (GO criterion 3 — the only comparison that authorises anything):
- **TWIN_FULL** is behind **BASELINE_EW** by ₹514 — but 2 month(s) of history is dominated by *when* the money went in, not *what* was picked. No verdict before 12 months.

**Diagnostics — descriptive, never gating.** Four comparisons at 95% confidence throw a false positive about one run in five, so these attribute; they do not authorise:
- **TWIN_FULL** is behind **BASELINE** by ₹774 — but 2 month(s) of history is dominated by *when* the money went in, not *what* was picked. No verdict before 12 months.
- **TWIN_FULL** is ahead of **TWIN_NO_AI** by ₹0 — but 2 month(s) of history is dominated by *when* the money went in, not *what* was picked. No verdict before 12 months.
- **TWIN_FULL** is ahead of **TWIN_NO_HEDGE** by ₹0 — but 2 month(s) of history is dominated by *when* the money went in, not *what* was picked. No verdict before 12 months.
- **TWIN_FULL** is ahead of **TWIN_NO_EXITS** by ₹0 — but 2 month(s) of history is dominated by *when* the money went in, not *what* was picked. No verdict before 12 months.
- **TWIN_FULL** is behind **REAL** by ₹430 — but 2 month(s) of history is dominated by *when* the money went in, not *what* was picked. No verdict before 12 months.

---

# GO gate — **NOT YET** (2026-08-30)

**5 of 6 criteria are not green.** The system is not validated for real money.

| | Criterion | Reading |
|---|---|---|
| 🟡 | Track length | 2 of 12 months |
| 🟡 | Volatility event withstood | worst in-window fall -2.2%, gate needs ≤ -10% |
| 🔴 | Beats the equal-weight fund | gap ₹-514 inside the ±₹8,362,315 noise floor |
| 🟡 | Tax reconciled | only a single-lot, all-STCG, no-loss sale has ever matched (₹25.25, Δ ₹0.00) |
| 🟡 | Corporate action reconciled | never |
| 🟢 | Data integrity | tradebook matches the broker; no ungated gaps |

**What would settle each:**
- **Track length** — 10 more months. Calendar time; nothing accelerates it.
- **Volatility event withstood** — a real market fall. Nobody has watched this system through one.
- **Beats the equal-weight fund** — a gap larger than luck produces. The bar is the fund anyone can buy, not the index.
- **Tax reconciled** — one multi-lot or LTCG sale, reconciled afterwards. §70 set-off fires on every harvest and has never been confirmed by a third party.
- **Corporate action reconciled** — one split, bonus or dividend applied live and matched. Demerger is not modelled at all.
