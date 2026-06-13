# Q-Alpha — Industry-Readiness Strategy (researched June 2026)

Companion to [PLAN.md](PLAN.md) (technical track). This answers three questions a consumer-minded,
capital-at-risk founder must answer before this is more than a brainchild: **(1) does nothing like
it really exist? (2) what would make a real user — starting with the founder — trust it with real
money? (3) what is the path to industry-ready, and do we pivot?**

---

## 1. Honest market scan — the founding assumption is half-wrong

"It exists because nothing like it exists" survives contact with the market **only in one specific
place**. The Indian retail quant space is in fact crowded:

| Category | Who | What they sell |
|---|---|---|
| Model-portfolio / smallcase managers | Wright Research (SEBI RA INH000017295, 25k+ users, momentum/multifactor smallcases, ₹7–10k/yr subs), dozens of others on the smallcase platform | **Stock picks.** Signals, baskets, rebalance updates. |
| Advisory/algo apps | Stratzy, Univest, StockGro, Liquide, AlgoBulls ecosystem | **Signals + execution plumbing.** |
| Tax tools | TaxHarvestLab (free, Zerodha/Groww/Upstox reports), Qonfido Tax Optimiser, WealthMunshi | **Point-in-time calculators**: upload a broker report in March, get a harvesting list. |
| Robo/MF platforms | Kuvera, ET Money, INDmoney | MF-centric allocation, some MF-level harvesting nudges. |

**The white space (verified by absence in this scan):** nobody operates a **continuous, tax-aware
portfolio *decision engine*** for Indian direct equities — friction (FIFO lots, STCG/LTCG, the
₹1.25L exemption, real broker costs) modelled **inside** every rebalance decision, year-round,
with an auditable do-nothing baseline. Signal-sellers push updates and the user eats the tax;
tax tools wake up in March. Q-Alpha's §4.6 net-benefit gate — the single component our own
backtests prove is the edge (it flipped NO-GO→GO; rebalance-frequency tax discipline took CAGR
15.2→18.5%) — **is the thing the market does not have.**

The US proves the category: Wealthfront-style tax-loss harvesting / direct indexing is documented
at **~0.8–2.5%/yr of "tax alpha"** (their whitepapers; Berkin & Ye 2003; Sosner et al. 2020), built
into a mass-market product. India is structurally *better* suited: **no wash-sale rule** (sell and
rebuy next day), high STCG/LTCG spread (20% vs 12.5%), and an exemption to manage — yet no Indian
product does it continuously at the engine level.

## 2. The consumer-trust insight — sell certainty, not prediction

From a consumer's perspective there are two kinds of claims a system like this can make:

- **"We beat the market"** — a *prediction* claim. Unprovable for years, easily faked with biased
  backtests (we know — we found survivorship traps, look-ahead bugs and TRI-vs-price games in our
  *own* work), and the claim every crowded competitor already shouts.
- **"We stopped you from burning ₹X in taxes and costs this year"** — an *arithmetic* claim.
  Provable per-trade, per-FY, against the user's own contract notes. Verifiable in months, not
  years. No competitor leads with it.

**Trust is built on the second kind.** Our own evidence base says the same thing: the durable,
reproducible result across every honest re-test was never the alpha (3-factor edge vs 1/N is real
but thin) — it was the **friction discipline** (tax-aware gate, fewer/later taxable events).

**Therefore: not a pivot of the system — a pivot of the headline.** The engine stays exactly as
specced. The value proposition leads with **tax/friction alpha (provable)**, with strategy alpha as
the research upside. "Quant analyst that watches your portfolio" stays; "we predict markets" never
becomes the pitch.

## 3. Regulatory reality (the wall is also the moat)

- **Personal use: unregulated.** Running Q-Alpha on your own money requires nothing.
- **Selling advice/signals** (model portfolios, buy/sell recommendations): **SEBI RA/IA
  registration.** 2025 reforms made this dramatically more accessible — any-discipline graduates +
  NISM certification qualify; compliance burden eased. Wright Research's path (RA → smallcase
  distribution) is replicable by one person.
- **Algo execution** (from April 2026): every automated order needs an exchange **Algo-ID**;
  providers route through brokers (no direct exchange access); **black-box advisory algos require
  RA registration + a research report per strategy**; retail threshold 10 orders/sec. Q-Alpha v1
  is *manual-approval decision support* — deliberately outside this perimeter until we choose to
  enter it.
- **Tax-analytics tools** (TaxHarvestLab et al.) operate as calculators on the user's own data —
  a lighter-touch positioning worth legal confirmation if that distribution path is chosen.

Compliance is a moat for whoever does it right: incumbents *could* build tax-aware engines, but
India-specific FIFO/no-wash-sale/exemption mechanics make US tooling non-portable, and the
signal-sellers' business model (charge for picks) disincentivizes "trade less" advice. **A product
whose core message is "do nothing more often" is structurally hard for a churn-monetized
competitor to copy.**

## 4. The plan — four stages, each with a kill/go gate

**Stage 0 — Finish the proof (now → ~3 months).** *Technical PLAN.md continues unchanged.*
✅ **Walk-forward done (`scripts/walkforward.py`): thesis PASSES out-of-sample** — the low-turnover,
tax-aware, survivorship-free strategy beat Nifty TRI in 93% of all 3-year holding periods and beat
both TRI and 1/N in all three independent sub-periods, with the best worst-case (never a losing 3y
stretch). Caveat kept honest: the *specific* "annual is optimal" claim did **not** generalize — the
real driver is low *realized* turnover (annual or gate-throttled), so we don't over-fit the frequency.
✅ **§4.6 multiplier OOS-calibrated** (`scripts/calibrate_gate.py`): no value generalizes → keep
spec 2.0, rely on the robust structural frequency lever (iron rule respected). ✅ **Phase-0 verdict
rendered** (`reports/PHASE0_VERDICT.md`): **defensible Phase-0 GO on the fair test** (gates 1-3, OOS).
Remaining for *full* Stage 0: 6-factor PIT run — **data-blocked** (historical fundamentals for ~75
names incl. dead ones; not a GO-blocker since 3-factor already clears criterion 1 OOS). **Gate
result: PASSED.** Next is Stage 1 (founder-as-user infra) — the real-money path.

**Stage 1 — Found-er-as-user (months 3–9).** Build spec Phases 1–5 *for one user*: data integrity
(bhavcopy cross-validation, confidence scores), Zerodha integration, FIFO validated against real
Tax P&L exports (§14 criterion 4), dashboard, **3–6 months mandatory paper trading (50+ events)**,
then real ₹2L. Every reconciliation loop and audit log built here *is* the industry-grade
foundation — institutional readiness and personal trust are the same checklist. **Gate: §14
scorecard fully green on personal money.**

**Stage 2 — The tax-alpha whitepaper (parallel, months 4–8).** Productize the *evidence*: a
Wealthfront-style study quantifying Q-Alpha's friction engine on Indian data — naive monthly
rebalance vs tax-aware vs tax-aware+LTCG-timing, on PIT universes, multiple windows, expressed as
**₹ saved and %/yr tax alpha**. Publish it (blog/SSRN/GitHub). This is simultaneously the research
validation, the marketing asset, and the RA-application research backbone. **Gate: tax alpha ≥
~1%/yr robustly, or the product story dies and Q-Alpha stays a personal system (a fine outcome —
that's what it was born as).**

**Stage 3 — Choose distribution (months 9–15, only if Stages 1–2 pass).** Three researched routes,
decided then, by evidence:
- **(a) B2C tax-aware companion** ("the engine watches *your* portfolio and tells you what a
  rebalance really costs") — TaxHarvestLab-plus positioning; lightest regulatory path (confirm with
  counsel); monetize subscriptions.
- **(b) SEBI RA registration → tax-aware smallcase/model portfolio** — Wright Research's proven
  channel, differentiated by "lowest-friction rebalancing in India," with our honest-validation
  culture as brand.
- **(c) B2B engine licensing** — the §4.6 gate + FIFO engine as an API for RIAs/PMS/platforms who
  must demonstrate client-level tax efficiency. Smallest market, deepest moat.

**Stage 4 — Industry hardening (post-PMF only).** Security audit, encrypted secrets/backup DR,
immutable audit trail (spec §10 already specifies), SEBI compliance for the chosen route, Algo-ID
pipeline if execution ever enters scope, SLA-grade data redundancy (paid feed replacing yfinance).

## 5. What we explicitly do NOT do

- Don't sell predictions, ever. The brand is the honest-backtest culture (we publish our negative
  results — the price-overlay failure, the 1/N losses — because that *is* the differentiation).
- Don't touch custody. Decision support only; user's money stays at their broker.
- Don't auto-execute in v1 (SEBI perimeter + trust ladder).
- Don't chase the signal-seller market on their terms (crowded, churn-incentivized, trust-poor).

## Sources

- [Wright Research on smallcase](https://www.smallcase.com/manager/wright-research) · [wrightresearch.in](https://www.wrightresearch.in/)
- [Stratzy review 2026](https://randomdimes.com/stratzy-review-2026-analysis-of-quant-investing-platform/)
- [SEBI algo rules 2026 (Algo-ID, broker-mediated, RA for black-box)](https://www.sahi.com/blogs/sebi-algo-trading-rules-2026-what-every-retail-trader-must-know-before-april) · [SEBI 2025 framework guide](https://cskruti.com/sebis-2025-algo-trading-framework-a-practical-guide/)
- [SEBI IA/RA 2025 reforms (eligibility widened)](https://www.gripinvest.in/blog/sebi-ia-ra-regulations)
- [TaxHarvestLab](https://taxharvestlab.com/) · [Qonfido tax optimiser](https://www.qonfido.com/qontent/tax-loss-harvesting-in-india) · [WealthMunshi TLH tools guide](https://wealthmunshi.com/automated-tax-loss-harvesting-tools-indian-investments-2026/)
- [Wealthfront US Direct Indexing whitepaper](https://research.wealthfront.com/whitepapers/stock-level-tax-loss-harvesting/) · [TLH results 2025](https://www.wealthfront.com/blog/tlh-results-2025/) · [Tax-alpha ranges incl. Berkin & Ye, Sosner et al.](https://www.embarkfunds.com/insights/tax-loss-harvesting-tax-alpha-explained)
- [India TLH mechanics, no wash-sale rule](https://www.sahi.com/blogs/why-tax-loss-harvesting-matters-for-indian-investors-and-traders)
