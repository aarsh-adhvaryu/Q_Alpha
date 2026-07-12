# CLAUDE.md

Guidance for Claude Code (and humans) working in this repo.

## 🧭 CURRENT STATE — read this FIRST (2026-07-11, unification)

**The live system is now ONE system in this product repo.** The user's audit verdict: the pieces felt
fragmented (two repos, an invisible wallet, a fetched "Research" tab). Decision (his call): **unify the
live system into the product, break the *organizational* separation, keep the *validation* one.** Two
iron rules were untangled — **(a) the validated 18.2% headline stays provably unchanged; never tune to
manufacture a GO → SACRED, kept.** **(b) two repos / product-never-imports-research → relaxed.**

**Built on branch `unify-live-system` (not yet merged):**
- **Auto-pilot moved in, native.** `src/qalpha/live/autopilot.py` (the fake-money A/B/C core — was the
  research forward study) + `scripts/autopilot.py` (daily runner: fund wallet → deploy via
  `advise_deploy_into_weakness` **imported directly**, A no-AI · B AI-tilted · C buy-and-hold → resolve
  vs Nifty → write `data/autopilot/*` + `reports/autopilot_dashboard.md`). Idempotent per day. Pre-reg
  at `docs/PREREGISTRATION_autopilot.md`.
- **AI brief moved in, quarantined.** `src/qalpha/live/ai_brief.py` + `scripts/ai_brief.py` (Haiku +
  web-search, context-only). It is the **optional `ai` extra** — the engine/factors/backtest/CI never
  import it; its only machine consumer is Book B, which acts on the `SIGNAL` line via a fixed rule. So
  the product stays deterministic where it must be; **rule (a) intact** (AI never computes a number for
  the validated engine).
- **Dashboard = one screen, three tabs:** 📄 Paper book · 🔴 Live (Zerodha) · **🤖 Auto-pilot** (native;
  replaced the fetched Research tab). The Auto-pilot tab has a **wallet with an Add-money button** + a
  **toggleable ₹50k monthly auto-top-up** (the user's confusion — "where do I add money" — is fixed;
  every deposit hits all three books equally so the A/B/C verdict stays fair), the "did it work / did
  the AI help" scoreboard, and today's AI brief.
- **Cron:** `paper.yml` now runs the AI brief + auto-pilot (fail-soft) after the daily mark and commits
  their data. **⚠️ ACTION NEEDED (user):** add **`ANTHROPIC_API_KEY`** to THIS repo's Actions secrets
  (only the research repo had it) — else the brief silently skips and Book B just runs neutral.
- **Research is now the archive:** the hedge forward run + the finished dead-ends (quantum/LPPLS/HMM).
  Its cron no longer runs the AI brief or the study (they live here now). The product no longer fetches
  research over HTTP. Gates green (product 234 tests; ruff/format/mypy). Nothing here trades — fake
  money only; real Zerodha stays 100% manual.

**Auto-pilot follow-ups (2026-07-11, branch `autopilot-trades-rebalance`):** three user-requested
additions, all fake-money, rule (a) intact.
- **Add-money persistence.** The dashboard (Streamlit Cloud) and the cron (GitHub Actions) are
  different machines, so the button used to write only the session. Now it queues the deposit to the
  repo's `data/autopilot/pending_injections.json` via the **GitHub Contents API**; the runner
  (`autopilot.apply_pending`) applies + clears it, staying the sole writer of `books.json`. **⚠️ needs a
  `GITHUB_TOKEN`** (fine-grained, contents:write on Q_Alpha) in the app's **Streamlit secrets** (+
  optional `GITHUB_REPO`, defaults to `aarsh-adhvaryu/Q_Alpha`). No token → the button falls back to a
  session-only add with a loud warning.
- **Show the trades.** The Auto-pilot tab now has a per-book holdings + last-buy panel.
- **Smart-rebalance experiment book.** A 4th fake book (`data/paper/adaptive_book.json`, ₹2L,
  `StrategyParams.rebalance_freq="ADAPTIVE"`): runs the validated core strategy but **evaluates every
  run and rebalances only when the §4.6 tax-benefit gate clears** — self-timed, not annual, not
  forced-frequent (the user's ask: "a smart one that doesn't lose money"). Run by the auto-pilot runner
  (`_run_adaptive_book`, fail-soft), tracked in `adaptive_track.csv`, shown in a "🏁 All engines,
  side-by-side" table (validated ₹2L annual core + smart-rebalance + A/B/C wallet books, each vs Nifty).
  **NEVER the validated GO book** (`data/paper/book.json`) — a separate book, headline untouched.

**Unified advisor + hedge (2026-07-11, branch `unified-advisor-hedge`):** the "one coherent system" pass.
- **Add-money = math + AI.** The Add-money advisor (Live + Paper) now surfaces the AI's market read and
  applies the same `signal_tilt` Book B uses to suggest *how much* of the idle cash to deploy now vs
  hold as dry powder (a tranche by market-weakness × AI lean). **Names + tax stay 100% deterministic;
  the AI never picks a stock or computes a number.** "Deploy all now (time-in-market)" is the honest
  default; the AI-paced option is offered with a market-timing caveat. Idle cash = demat cash (injected
  or freed by a sell). The auto-pilot's Book B forward-tests whether acting on the AI actually helps.
- **Hedge promoted from research → `src/qalpha/live/hedge.py`** (`stress_gauge` [drawdown→[0,1], the
  product-native gauge; the cross-asset fragility gauge stays the research upgrade path] + `hedge_active`
  + `apply_futures_hedge`, the validated tax-free short-futures overlay; `tests/test_hedge.py` incl.
  no-look-ahead). Wired into the auto-pilot as a **downside-protection overlay on the smart-rebalance
  book** (`_run_hedge_overlay`, stateless/recomputed, τ≥0.7 h=0.5) → shows hedged-vs-unhedged return +
  **drawdown** in the Auto-pilot dashboard. **Fake money — never a real F&O trade.** *Why this and not
  "sell defensively":* selling to dodge a drawdown was tested (research HMM overlay) and LOST to the
  capital-gains tax; the hedge keeps the shares (₹0 CG tax) and cuts the crash. Coincident gauge → in a
  calm window it stays off and curves match; its value shows only in a real stress event.
- **Plots:** an "all engines" return-% line chart in the Auto-pilot tab (A/B/C + smart-rebalance).
- Gates green (241 tests). Rule (a) intact throughout (AI never the calculator; validated headline +
  ₹2L GO book untouched; the hedge/auto-pilot are fake-money experiments).

**THE SYSTEM BOOK (2026-07-12, branch `system-book`) — the closed trust loop.** The user's demand:
*"I can only trust the advisor if it takes the decision AND acts on it — no paperbook, no autopilot
separate, all in one; the optimizer must handle the real world, not just a scheduled time."* Built:
- **ONE fake-money book runs the entire system on its own advice** (`scripts/autopilot.py`, fully
  rewritten): cash in (monthly ₹50k + Add-money queue) → **AI-paced deploys into weakness** (the exact
  Add-money advice, executed on itself; `signal_tilt` sizes it) → **§4.6 tax-gated adaptive rebalance
  evaluated EVERY day** (trades only when worth the tax — it may later consolidate opportunistic buys
  into the core target, again only when worth the tax) → **hedge overlay readout** (flow-adjusted).
  The System book = the former smart-rebalance book upgraded in place (`data/paper/adaptive_book.json`,
  its ₹2L history carries over).
- **Two comparators, identical cash flows:** `data/paper/shadow_book.json` (cloned at first run; AI
  OFF → System−Shadow = the AI's added value) and `data/autopilot/baseline_book.json` (NIFTYBEES
  buy-and-hold → System−Baseline = the system's value over doing nothing). The A/B/C wallet books are
  **FROZEN** (prereg carries a disclosed amendment note; same questions, now asked of the full system).
- **Dashboard = TWO tabs:** 🧠 **The system** (wallet + Add-money, scoreboard from
  `reports/autopilot_dashboard.md`, race chart from `data/autopilot/system_track.csv`, per-book
  holdings, AI brief expander, and the **validated ₹2L core-GO view unchanged in an expander
  underneath**) · 🔴 **Live (Zerodha)** (unchanged; the human places every order).
- **Load-bearing valuation detail:** the system book holds core + watchlist names, so it's valued on a
  **merged panel** (`_merge_panels`, everything ffilled — causal) — an index/session mismatch between
  panels must never silently drop a holding's mark (found in smoke: a stale core panel cratered equity
  −88% until the ffill fix). Money-weighted returns: wallet→book deploys are logged as flows
  (`data/autopilot/system_flows.json`) and stripped from the curve before hedge/return math.
- The clean ₹2L GO book (`data/paper/book.json`) is **untouched** — still the criterion-6 evidence.
  Rule (a) intact: AI paces size only; the engine computes everything. Gates green;
  cmd_daily smoke-tested end-to-end locally (deploys executed, gate refused a same-day rebalance with
  its reason logged, idempotent re-run).

## 🧭 CURRENT STATE — (2026-07-11, Ops Layer)

**Everything below this block is the older working log; this block is what's true now.** The
**"Daily-Driver Ops Layer"** in [PLAN_OPS_LAYER.md](PLAN_OPS_LAYER.md) is **built and its product half
is merged + live.** Four gates green; the paper cron pushes daily.

**MERGED to `main` (product side of the Ops Layer):**
- **PR-1 (#33) — Telegram notification spine + daily opportunity scan.** `src/qalpha/live/notify.py`
  (stdlib `urllib` Telegram sender, **fail-soft**: missing config/error → `False`, never raises),
  `src/qalpha/live/scan.py` (pure edge-triggered `evaluate` — weakness escalation w/ tranche policy,
  easing w/ 3-scan hysteresis, rebalance-due, GO flip, guard-failure, Monday digest; `AlertState`
  JSON), `scripts/scan_alerts.py` (runs in the paper cron after the daily mark; `--test` /
  `--force-digest` / `--pipeline-failed`). `paper.yml` wired + `if: failure()` alert +
  `data/paper/alert_state.json` committed. Verified live to the user's phone.
- **PR-2 (#34) — capital-aware auto buy-brief + two real bug fixes.** `DeployPolicyConfig` in
  `config.py` (idle_cash_floor ₹5000, tranches 50%/100%, max_names 15); `live/dashboard.py`
  `live_pm_brief_markdown` + `watchlist_is_stale`; `dashboard_app.py` auto PM brief on the Live tab
  (zero typing, gated by `assess_advice_inputs`). **Bug fixes:** the live advisor was fed the watchlist
  `adj_close.mean()` as the "index" instead of the real Nifty TRI (now threaded through); `_watchlist`
  was cached forever → added 6h ttl + stale re-download. Namespaced advisor widget keys (paper/live).
- **Dashboard plain-English clarity (#35).** `live/dashboard.py` `plain_summary_markdown` /
  `performance_read` (ahead/behind/tracking vs Nifty) / `glossary_markdown`; wired into
  `dashboard_app.py` (In-plain-English banner atop the Paper tab + good/bad caption under the metrics +
  a "Jargon" expander). **Presentation only — engine/headline untouched. Merging it auto-deployed to
  the user's Streamlit Cloud dashboard (live on his phone).**

**Telegram bot @qalphastocks_bot** (chat_id 8936117519); repo Actions secrets `TELEGRAM_BOT_TOKEN` /
`TELEGRAM_CHAT_ID` set. The weekday paper cron now marks the book AND pushes edge-triggered alerts.

**The research repo carries the rest of the Ops Layer + new work (see its CLAUDE.md):** PR-3 hedge-flip
alert + PR-4 daily AI market brief (Haiku 4.5, context-only) merged & live on the hedge cron; a
whole-system integration layer (`system_check` + `mission_control_app`) + a Streamlit deploy fix; and a
**pre-registered A/B/C "did it work?" forward study** (WIP on branch `forward-study`). **The product
never imports research** — integration is via committed data (the research mission-control *fetches*
this repo's public `reports/paper_dashboard.md`; it does not import). **This repo's clean ₹2L paper GO
run is deliberately UNTOUCHED by any of the ops/AI/study work** — so a real-money GO stays credible.

**Iron rules reaffirmed with the user (2026-07-11):** Zerodha = **execution + funding only**, he places
every real order; **real money NEVER auto-trades** (auto-invest is fake-money/paper only, to build
trust); the LLM is **context-only, never the calculator or the validator of the math**; keep the
validated 18.2% headline provably unchanged. §14 scorecard unchanged (crit-6 forward paper run + a
volatility event remain the calendar blockers).

## 🧭 CURRENT STATE — (2026-06-19)

**⏭️ QUEUED NEXT BUILD (2026-07-08, planned + user-approved scope, NOT yet implemented):** the
**"Daily-Driver Ops Layer"** — full plan in [PLAN_OPS_LAYER.md](PLAN_OPS_LAYER.md) (execute it
PR-by-PR next session). Why: the user's audit verdict — everything analytical exists but the system
is 100% pull-based (zero outbound notification in either repo; idle cash shown but never acted on;
buy advisor needs typed amount + button; weakness/hedge/GO signals computed only when the dashboard
is opened). Four PRs, all in `live/`+`scripts/`+workflows (engine/headline provably untouched, never
auto-trades): **PR-1** Telegram spine + edge-triggered daily opportunity scan in the paper cron
(weakness escalation w/ tranche policy, rebalance due, GO flip, guard/pipeline failure + Monday
digest; hysteresis on de-escalation); **PR-2** capital-aware auto buy-brief on Live-tab login
(`fetch_available_cash` → `advise_deploy_into_weakness`, zero typing) + `DeployPolicyConfig`
(pre-committed tranches: 50% idle on elevated, 100% on deep) + two real bug fixes (live advisor fed
watchlist-mean instead of the real index @ dashboard_app.py:615; `_watchlist` cached forever →
stale); **PR-3** (research repo) hedge-flip Telegram alert; **PR-4** (research repo) daily AI market
brief — Opus 4.8 + web-search tool, min-token config (effort=low, max_tokens=1500, max 4 searches,
~₹4–8/day), **context-only/never a signal**, satellite-sleeve framing for discretionary ideas.
Deferred by user decision: private cash-snapshot repo (PR-5). User decisions locked 2026-07-08:
Telegram · events+Monday digest · dashboard-only cash sizing · AI brief daily on Opus 4.8. Both
crons verified alive (daily marks through 2026-07-07 on both repos' origin/main).

**For the full, interviewer-level overview read [README.md](README.md) — it now carries the complete
story (plain-language + the math + an explicit "biases & decisions" section).** This CLAUDE.md is the
detailed *working log* below; the README is the front door.

**Where we are:** Phase 0 (backtest validation) is **complete and defensible** — 18.2% CAGR / Sharpe
1.13, beats Nifty 50 TRI *and* 1/N net of cost+tax, in-sample + on the 2025–26 holdout + every rolling
3y window. The **live system is built and deployed** on the user's real Zerodha account via Streamlit
Cloud: deterministic tax-smart advisor (sell / raise-cash / deploy), §70 loss set-off, corporate
actions, live holdings + tradebook reconciliation (crit-4 reconciled to the paise), a notional paper
book that **auto-runs and self-certifies**, and four watch tabs (🎯 GO readiness · 🩺 position health ·
🛡 systemic risk · realtime ticks). **Both repos green** (qalpha 169 tests, research 28; ruff/format/
mypy/pytest all pass).

**§14 scorecard: `1✅ 2✅ 3✅ 4✅ 5🟡 6⏳ 7✅ 8✅ 9🟡 10✅`.** No unbuilt engineering on the critical
path. What remains is **calendar + real-world events**: crit-6 (the ~6-month forward paper run + ≥1
volatility event, unskippable) · crit-4/5 (reconcile one real multi-lot/loss sell + one real corporate
action — engines done & tested) · crit-9 (observe one *scheduled* cron firing; dispatch already proven
green). The system **never auto-trades** — it advises; the human places the order.

**Iron rules still hold:** no tuning to manufacture a GO · all four gates green before commit · money is
`Decimal` · no look-ahead · keep the validated headline provably unchanged (new tax features are wired
into the advisor/live layer, never the backtest engine). The research track lives in the separate
`Q_Alpha_Research` repo and the product **never imports from it**.

The dated working log below is the full history (every decision, fix, and dead-end) — skim it for *why*
something is the way it is; trust this block + the README for *what is true now*.

---

## What this is

Q-Alpha — a quantitative wealth-management system for Indian (NSE/BSE) equities. The full system
architecture is specified in [Q_alpha.md](Q_alpha.md) (v3.1). The codebase is built **phase by
phase**; the spec mandates that **Phase 0 (strategy validation by backtest) must beat baselines
after costs and taxes before any production infrastructure is built**.

**Current state: Phase 0 COMPLETE + live build well underway — all on `main`.** Beyond the validated
Phase-0 GO, the repo now has the live layer (Kite auth, replay harness), a running **paper-trading
book** (notional, started 2026-06-12) with a **dashboard + autonomous daily pipeline**. The
**research track (quantum QUBO/QAOA, + planned regime/bubble & agentic work) now lives in a separate
repo** — `github.com/aarsh-adhvaryu/Q_Alpha_Research` — which imports this engine as a dependency, so
this repo stays product-clean. See the "NEXT SESSION" block for the active plan (a
deterministic tax-smart advisor + a live Zerodha-wired dashboard). Phase-0 evidence:
`reports/PHASE0_VERDICT.md`. The original headline (6-factor, 24 survivors, vs Nifty *price*)
was stress-tested through two fairness fixes (point-in-time universe + TRI benchmark) and an
out-of-sample walk-forward; the edge survived once rebalancing slowed to low turnover. §14 gates
**1 ✅ (OOS) · 2 ✅ · 3 ✅**; criteria 4-10 are Phases 1-6 (infra/broker/paper-trading) — the
real-money GO is still months away. The 6-factor PIT run is data-blocked (fundamentals for ~75 names
incl. dead ones) but is *not* a GO-blocker. **⚠️ But the 2025-26 out-of-time HOLDOUT
(`scripts/holdout_2025.py`) is a YELLOW FLAG:** frozen config on genuinely unseen data was flat
(0.7% vs TRI 0.6%) and **trailed 1/N badly (7.1%) with worse drawdown** — the alpha did NOT
generalize. Root cause: the §4.6 tax gate **froze rebalancing after 2019** (only 5 rebalances ever),
so the in-sample 18.5% was largely stale 2013-19 winners riding the 2020-24 bull. Low power (17.5mo,
flat market) so not proof of failure, but not confirmation either. **Ossification fixed**
(`run_backtest(force_refresh=True)`: scheduled rebalance always executes, band-limited): un-froze the
book (5→13 rebalances), **neutral in-sample** (18.4 vs 18.5) and **fixed holdout drawdown −24→−13%**
— but holdout return still flat (1.1%) and still trails 1/N (7.1%). So ossification was a real flaw
(→ `force_refresh` should be the production default) but NOT the reason alpha was absent OOS.
**Then Track A SOLVED it (`scripts/exp_breadth.py`):** the literature's anchor-to-1/N shrinkage —
`weighting="shrink"` (½ min-var + ½ equal over the picks) — **beats 1/N in-sample (18.3 vs 17.7),
on the holdout (8.1 vs 7.1), AND across rolling 3y holds** (dominates every percentile, worst-3y
+3.6% vs 1/N −8.7%, ≥1/N in 67%). First optimiser change to clear the iron-rule bar *and* survive
the out-of-time holdout. So the edge is BOTH the tax engine AND a modest robust 1/N-anchored return
tilt — not pure index-tracking after all. No DB / broker / dashboard yet. CI green.

## ⏯️ NEXT SESSION — START HERE (a brainstorm; build is paused here)

**✅ HARDENING SPRINT (2026-06-19) — every *code-fixable* GO blocker closed; what remains is calendar
time + a couple of real trades, not engineering.** The user's brief: "solve every problem so the only
thing left is waiting 3–6 months." Five things shipped (both repos' four gates green — qalpha 144
tests, research 23):
- **Realtime tick-streaming — Stage-2 SOLVED, session-scoped** (`src/qalpha/live/ticker.py`,
  `tests/test_ticker.py`). *Why:* Stage-2 looked impossible on Streamlit Cloud because a 24/7 socket
  dies on idle-sleep — but realtime is only needed **while the user is watching**. So the `KiteTicker`
  socket's lifetime is tied to the **browser session** (parked in `st.session_state`): on login a
  background thread opens the socket, subscribes to the held instruments, and pushes ticks into a
  thread-safe `TickStore` the fragment reads; when the session ends the thread stops. Wired into the
  live view as a **best-effort overlay** — any failure (no creds/socket) silently falls back to the
  30s `ltp()` polling, so it can never break the working page. `KiteTicker` is lazy-imported so the
  pure `TickStore`/`resolve_tokens` are unit-tested. **Cannot be verified in the agent sandbox (no
  socket/creds) → user verifies on the box** (established pattern). `🔴 streaming` vs `⏱ polling` badge.
- **Hedge promoted to product as a READ-ONLY watch tab** ("🛡 Systemic risk" sidebar view;
  `live/dashboard.py:systemic_risk_markdown` + tests). *Why:* the user reversed the earlier "keep the
  hedge in research" decision and asked for "just a tab where I watch, no action, like the paper
  money." Shows the systemic-risk level (🟢/🟠/🔴 from Nifty drawdown vs 1y high) and, when elevated,
  notes the research-proven tax-free futures hedge "would suggest *considering* a hedge" — **purely
  informational, never trades, no derivatives placed.** *How (iron rule intact):* uses the
  **product-side** `deploy.py:market_weakness` signal, **does NOT import research** (`The product never
  imports from here`). The richer cross-asset fragility gauge stays in research as the upgrade path.
- **Fail-loud system-safety guards** (`live/safety.py`, `tests/test_safety.py`). *Why:* the user asked
  to "remove all problems that can cause a loss from a system failure." Key insight: **the system never
  auto-trades**, so a system failure can only lose money by **showing wrong data the user acts on**.
  So the fix is fail-loud guards — `price_freshness_guard` (stale feed), `price_completeness_guard`
  (a held name with no/zero quote that would be silently dropped from the tax/cash math),
  `broker_session_guard` (dead/expired token) → `assess_advice_inputs`/`SafetyReport`. The dashboard
  advisor is now **gated** (`dashboard_app.py:_advisor_with_safety`): bad inputs **withhold the
  recommendation behind a banner** instead of computing on them.
- **STCG/LTCG loss set-off** (`accounting/capital_gains.py:net_capital_gains_tax`/`net_tax_total`,
  tests in `test_capital_gains.py`) — the real **criterion-4 correctness gap**. Full §70 rules: STCL
  sets off against STCG first (20%) then LTCG (12.5%); LTCL against LTCG only; ₹1.25L exemption on the
  net LTCG; carry-forward reported (8-AY carry not applied — Phase-0 deferral). *Why additive:* it is a
  **pure FY-aggregation function wired ONLY into the advisor** (`advise_sell` now nets loss lots
  against gain lots and shows the `setoff_saving`) **+ reconciliation — deliberately NOT into
  `compute_sell`/the backtest engine**, so the validated 18.2% headline is **provably unchanged**.
  Residual: cross-event FY netting + carry-forward still deferred.
- **hedge.py open-episode tax bug FIXED** (research repo — see its CLAUDE.md). Optimistic edge case,
  no published number affected, fixed for correctness + test.

**✅ AUTONOMY SPRINT (2026-06-19, branch `hardening-sprint` then continued) — the paper run now executes
itself and self-certifies.** User's brief: "I can't code every time / no AI / all from the dashboard /
if it works in ~5 months it should provide a GO."
- **Paper rebalance-cadence gate + auto-apply — a real bug fixed** (`live/paper.py`,
  `scripts/paper.py`, `tests/test_paper.py`). The live path had **no rebalance schedule**:
  `decide_rebalance` returns `execute=True` every call when `force_refresh` is on, and the daily cron
  called it daily → the dashboard proposed a full ~40% rebalance EVERY day ("drift 41%" nag), and
  auto-applying it would have churned the book daily and destroyed the validated low-turnover tax edge.
  (The backtest avoids this only because its loop calls `decide_rebalance` *solely* on annual
  `_rebalance_dates`.) Fix: `PaperBook.scheduled_rebalance_due(as_of)` = the online mirror of
  `_rebalance_dates` — a rebalance is due only when `as_of` enters a new annual period; `plan()` HOLDS
  between scheduled dates. `paper.py daily` now **auto-applies** a scheduled, actionable plan to the
  NOTIONAL book (zero real money; the gate guarantees ~once a year, never daily) so criterion-6 tests
  the live strategy, not a frozen June basket. **Engine untouched → headline unchanged.**
- **Deterministic GO scorecard + "🎯 GO readiness" dashboard tab** (`live/go_scorecard.py`,
  `tests/test_go_scorecard.py`, wired into `live/dashboard.py:go_readiness_markdown` + `dashboard_app`).
  A real multi-criterion verdict (NOT a countdown), pure arithmetic, **no LLM/no judgement**: flips to
  GO the moment the evidence clears (earlier than 6mo if it does), NO-GO if the strategy misbehaves.
  Criteria, all must be 🟢: **track-length power floor** (~3mo, a floor not a date) · **volatility-event
  withstood** (HARD gate — must survive a ≥10% Nifty pullback in-window; a calm curve can't earn a GO) ·
  **forward vs benchmark net** (red = NO-GO) · **drawdown behaviour** within the backtest envelope ·
  **data integrity** (dense marks). On the real book today: **NOT YET** (4/63 days, no vol event yet).

**What's left after this sprint (NOT code — this is the honest GO picture):** (a) **calendar,
irreducible** — criterion 6, the ~6-month forward paper run surviving ≥1 volatility event; (b) **one
real-world event each (days, user-triggered)** — criterion 4 final hardening needs *one* real
multi-lot/loss/LTCG sell + its Tax P&L to reconcile against the new set-off code; criterion 9 needs
*one* observed scheduled-cron firing (dispatch ≠ cron); (c) **still open** — criterion 5 corporate
actions (not started); (d) **data-blocked, off the critical path** — fundamentals/value factor + PIT
Nifty-100/200 membership. **Nothing here is committed yet** (offer the user a branch per repo).

**✅ DEPLOYED & LIVE (2026-06-18) — the dashboard runs on Streamlit Community Cloud, on the user's REAL
Zerodha account, from his phone.** This is the headline state. AWS was abandoned mid-attempt (EC2
security-group / SSH / IAM / status-checks = a beginner wall; `deploy/DEPLOY_AWS_BEGINNER.md` +
`DEPLOY.md` Docker path kept as portable fallbacks, `DEPLOY_LIGHTNING.md` too). **Streamlit Cloud won**
(deploy straight from the public GitHub repo, no server/SSH/Docker, free, `…streamlit.app` URL,
auto-redeploys on every `main` push so the daily paper cron keeps it fresh): `deploy/DEPLOY_STREAMLIT.md`,
root `requirements.txt` (`-e .` + streamlit). The user funded the account; the **Live Zerodha view shows
his real holding (INFY ×5)** with live `ltp()`.
- **What the deployed dashboard does (all from one screen, PRs #17–#22):** password gate (`APP_PASSWORD`);
  paper-run **freshness panel** (`live/dashboard.py:paper_freshness`); **in-app Kite credentials form**
  (`_ensure_kite_credentials` — enter api_key/secret in the UI, no `.env`) + **one-tap login**
  (`request_token` captured from Kite's redirect via `st.query_params`); **auto-refresh** (`st.fragment
  run_every=30`); **self-bootstraps** the gitignored price panels on a fresh host (`_ensure_data` →
  `paper.py daily` for prices **and** benchmark; `_watchlist()` lazily downloads the Nifty-100 panel);
  Streamlit-secrets→env **bridge** (`_bridge_secrets`). Advisor tabs: **Sell** (exact tax) · **Raise
  cash** (least-tax order) · **Add money** = the **buy side** — wired to `advise_deploy_into_weakness`
  (Nifty-100, diversified, cheapness-tilted, **₹0-tax buys**) with a **"spread across N stocks" slider**
  (`max_names`, default 15) so the user dials concentration↔diversification (he flagged 43×1-share was
  over-diversified). Tradebook-CSV upload → exact dated tax. **Only the order placement stays in Kite
  (by design).**
- **Honest gaps surfaced live (worth knowing next session):** (1) the tax advisor is *trivial* on a
  1-tiny-holding-at-a-loss account — it earns its keep with a real multi-name book; (2) "cheap" = a
  **technical** pullback proxy, not fundamental P/E (data-blocked); (3) the **deploy advisor on the live
  account** uses the watchlist panel, not the model funnel target. **Kite reality (locked):** daily
  one-tap login; **no** compliant unattended token (auto-TOTP declined). **Streamlit gotcha seen:** after
  a code merge the app can hot-reload the page but keep an **old imported module** in memory → spurious
  `TypeError` → fix is **Manage app → Reboot** (forces a clean re-import).
- **✅ SUPERSEDED (2026-06-19) — Stage-2 true tick-streaming BUILT, session-scoped** (`live/ticker.py`).
  The old blocker ("Streamlit Cloud sleeps → kills a 24/7 socket") was dissolved by tying the
  `KiteTicker` socket to the **browser session** (lives only while the tab is open — exactly when
  realtime is needed), not to a 24/7 server. No paid always-on host required. **User verifies the live
  socket on the box.** Also now done: the research fragility gauge promoted as a **read-only "🛡 Systemic
  risk" advisory tab** (product-side signal, no research import). Still deferred: fundamentals/value factor.

**Next session = brainstorming, not a queued build.** Everything below is current. **All PRs are
merged** — the earlier "#10 then #11 awaiting manual merge" note is resolved: #10 `cleanups` merged,
#11 `tradebook-upload` re-landed as **#12** (merged), plus #13/#14/#15. Nothing is pending.

**✅ CRITERION 4 RECONCILED (2026-06-18) — the FIFO engine matches the real Zerodha Tax P&L to the
paise.** The user made a **real SELL** (HDFCBANK 5 @ ₹790.50 on 17 Jun, bought on BSE / sold on NSE),
exported the Console **Tax P&L** (`data/taxpnl-…xlsx`) + **Tradebook** (`data/tradebook-…csv`), and
the reconciliation now runs end-to-end: new **`src/qalpha/live/taxpnl.py`** (`parse_taxpnl` +
`reconcile_gross`), **`scripts/reconcile_taxpnl.py`** → `reports/crit4_reconciliation.md`, tests in
`tests/test_taxpnl.py`; `ReplayResult` gained `realized_gains`. **Gross realized P&L (zero-cost replay)
== Zerodha STCG ₹25.25, Δ ₹0.00** — proves FIFO lot-matching + STCG/LTCG classification + the BSE-buy/
NSE-sell ISIN merge are correct. Our **net** taxable gain sits below gross by our modelled deductible
transfer charges (DP charge dominant, ₹14.36 ≈ Zerodha's ₹15.34 "Other Credits & Debits"; STT
correctly excluded) → STCG tax ₹2.18. Caveat: a tiny, single-sell, all-STCG case — it validates the
*plumbing* exactly; a multi-lot / LTCG / loss-set-off case will exercise more (LTCG loss set-off still
unimplemented — fix before a sell that triggers it). **§14 criterion 4 → ✅.**

**On `main` (9 PRs merged, 2026-06-13):** Phase 0 (validated GO) + a **live layer** (`src/qalpha/live/`:
Kite auth, replay harness, shared `decide_rebalance`) + a **paper-trading runner** (`scripts/paper.py`,
notional ₹2L book started 2026-06-12, 5 holdings) + a **dashboard + autonomous daily GitHub Actions
pipeline** (`paper.yml`) + the **deterministic tax-smart advisor** + a **live Streamlit dashboard**.
(The quantum research track was moved to the separate `Q_Alpha_Research` repo.) Four gates green.

**🏁 FINALIZATION (2026-06-18) — Nifty-100 deploy-in-weakness, the manual-investor solution.** The
user's real need: diversify + find better entries; Nifty-50 large-caps are rarely cheap outside a
crash, so the *opportunity set* must widen to Nifty 100. Built (branch `nifty100-advisor-deploy`):
**`scripts/build_nifty100_watchlist.py` → `data/universes/nifty100_watchlist.csv`** (96 current names
+ sectors — a *forward-looking* watchlist, so survivorship is irrelevant: it lists what's investable
*today*, not a backtest universe); **`src/qalpha/live/deploy.py`** (tested) — three deterministic
price-based layers on top of the validated `advise_deploy` (₹0-tax greedy buys): (1) `market_weakness`
(index drawdown from 1y high → normal/elevated/deep "when to deploy more" advisory; a self-contained
signal — the richer research **fragility gauge** is the upgrade path), (2) `cheapness_scores` (pullback
below each name's 1y high — a **technical** out-of-favour proxy, *honestly NOT* fundamental P/E, which
stays data-blocked), (3) `deploy_target` (diversified equal-weight + sector-capped water-filling, tilted
to cheaper names) → `advise_deploy_into_weakness`. CLI: **`advisor.py deploy-weakness AMOUNT [--tilt]`**.
`tests/test_deploy.py`. **This is the tax-free "buy cheap, diversify" lever** — new money only, ₹0
capital-gains tax. **Honest framing locked in:** the *validated backtested strategy* default stays
Nifty 50 (no proven alpha from breadth — see the research breadth/QUBO findings); this widens only the
*manual investor's* opportunity set, which the advisor/tax engine already serve on any holdings.
**Watchlist prices — INGESTED (verified working):** `build_nifty100_watchlist.py --prices` downloads
the 96 names → `data/historical/prices_watchlist.parquet` (95/96 priced; only retired TATAMOTORS.NS
fails); `deploy-weakness` loads that panel so it actually sees the full Nifty 100 incl. the Next-50
midcaps (62/96 → **95/96**; the missing midcaps were the whole point). Also added an **anti-dominance
guard** (`max_name_fraction=0.20`): drops a name whose single share exceeds that fraction of the deploy,
so a pricey share (e.g. SHREECEM ₹24,825) can't swallow a small ₹50k deploy — it now spreads across
~14 names. **"Closed" = build-complete
v1; the real-money GO remains gated by the unskippable forward paper run** (criterion 6) — that calendar
time cannot be compressed. QUBO/breadth stay in research; the fragility-gauge promotion (as a read-only
"systemic risk" advisory) is the clean next integration if revisited.

**🚀 DEPLOY STAGE 1 (2026-06-18) — phone-accessible hosted dashboard.** User wants a URL on his phone,
always-on, realtime, with the paper-run shown (not trusted). Built (`deploy/`: Dockerfile +
entrypoint.sh [bootstraps the gitignored price panels on first boot] + docker-compose.yml + DEPLOY.md
[AWS EC2-free-tier / Lightsail step-by-step, security-group-to-own-IP, Caddy HTTPS option]). Dashboard
gains: **password gate** (`APP_PASSWORD` env, open if unset for local dev), **paper-run freshness panel**
(`live/dashboard.py:paper_freshness` + test — weekday-aware stale flag, the "see it's alive" piece),
**phone one-tap Kite login** (captures the `request_token` from Kite's redirect via `st.query_params`,
paste fallback — no CLI), and **auto-refresh** (`st.fragment(run_every=30)` on the live view →
near-realtime ltp). **Kite reality (locked):** the daily session needs a one-tap human login — there is
NO compliant fully-unattended token (declined auto-TOTP as ToS-violating/insecure). **Can't verify a
live server here** (sandbox blocks ports; no AWS/Kite creds) → AppTest-smoke + pure-fn tests only; user
verifies on the box. **✅ STAGE 2 NOW BUILT (2026-06-19, `live/ticker.py`): true tick-streaming via Kite
`KiteTicker`** — a background thread → thread-safe `TickStore` → fragment reads it, exactly as planned,
but **session-scoped** (socket lives with the browser session, not a 24/7 host) so it needs no always-on
server; best-effort overlay over the 30s polling. Built here, **verified on the box** (no live socket in
the sandbox). Stage-1 auto-refresh is the pre-connect fallback.
**HOSTING = LIGHTNING AI (user's choice, `deploy/DEPLOY_LIGHTNING.md`)** — we're already in a Lightning
Studio (repo+data present), so the Streamlit plugin gives a 1-click public URL; **auto-start** = always-
on, pay-per-use (idle-sleep + cold-start). Caveat: auto-start's idle-off is fine for Stage-1 auto-refresh
but **kills a Stage-2 always-on WebSocket** → true-ticks need a persistent Studio (continuous credits) or
the AWS free-tier box. Lightning note: the GH-Actions paper cron commits to GitHub, so the Studio app
needs a periodic `git pull` for the freshness panel to show fresh marks. The Docker/AWS scaffold
(`deploy/DEPLOY.md`) stays as the portable any-VPS path.

**⭐ USER MADE FIRST REAL TRADES (2026-06-13):** funded YHK037, **HDFCBANK BUY 5 @₹785.45 COMPLETE**
(CNC/delivery), INFY BUY 5 still OPEN/pending; cash ₹445.75. **A same-day delivery buy sits in
`positions()` day-book, NOT `holdings()`** (→ T+1 it lands in `holdings()` as `t1_quantity`), so
`--source live` (which reads `holdings()`) shows EMPTY until tomorrow. Possible quick win:
also read `positions()` for same-day visibility (offered, not built). Kite token expires daily
~06:00 IST → re-mint `python -m qalpha.live.auth --manual`. **Streamlit server can't run in the agent
harness** (sandbox kills port-binding, exit 144); the user runs it + forwards port 8501 via VSCode
PORTS. I verify rendering with Streamlit `AppTest` (in-process, no socket).

**🎯 USER'S VISION + AGREED NEXT PLAN (the active direction — build this):** the user trades **manually
(all his own decisions)** and wants an **advisor + proper live web dashboard wired to his REAL Zerodha
account** — it reads his holdings (`kite.holdings()`) + live prices, reflects every trade *he* makes,
and tells him the **tax-smart move**. It NEVER auto-executes. Tax math is **deterministic** (exact/
auditable — NOT an LLM computing numbers; an LLM "concierge" that routes NL questions to the engine is
an optional *later* flourish, never the calculator). **Build order:**
1. ✅ **DONE — Deterministic tax-smart advisor** (= §14 criterion 10, the recommendation layer):
   `src/qalpha/live/advisor.py`. Three modes, all on the validated FIFO/cost/tax engine (no LLM, no
   second formula), source-agnostic (takes a `Portfolio`): `advise_sell` (STCG/LTCG split, exact tax,
   exemption shelter, largest ₹0-tax quantity, wait-out-365 flag), `advise_raise_cash` (least-tax
   source order — losers/long-term first — vs naive pro-rata), `advise_deploy` (route new money to
   underweights, buys-only ₹0 tax, vs a taxable full rebalance). CLI `scripts/advisor.py`
   (`sell`/`raise-cash`/`deploy`). `Portfolio` gained `clone()`, public `sell()`/`buy()`,
   `preview_sell()`. Tests `tests/test_advisor.py`.
2. ✅ **DONE — Live web dashboard** (Streamlit): `scripts/dashboard_app.py` — equity vs Nifty 50 TRI,
   holdings, today's recommendation, and the advisor as interactive tabs. Read-only (never trades).
   Source = paper book now → `kite.holdings()` later (the `_load` seam). `streamlit` is an optional
   **`dashboard`** extra (UI-only, not in CI/pipeline). Run: `uv run --extra dashboard streamlit run
   scripts/dashboard_app.py`. `AppTest` smoke test skips dev-only (CI) / without on-disk data.
3. ✅ **DONE — Live Zerodha holdings reader** (PR #10): `src/qalpha/live/holdings.py` reads
   `kite.holdings()` + `ltp()` + `margins()` into the same `Portfolio`. Source swap is a sidebar toggle
   (dashboard) / `--source live` (CLI). **Caveat:** `holdings()` has no purchase dates → undated lots
   (tax short-term-assumed) flagged via `LiveHoldings.lots_dated`/`.tax_caveat`.
4. ✅ **DONE — Tradebook upload → exact dated tax** (PR #11, the criterion-4 reconstruction half):
   `src/qalpha/live/tradebook.py` (`parse_tradebook` path-or-file, `replay_tradebook`→`ReplayResult`,
   `reconcile_positions`). Dashboard Live view has an `st.file_uploader`; upload the Console tradebook
   CSV → exact dated FIFO lots + realized tax + holdings reconciliation; advisor uses the accurate book.
**Trust gate** before real-money reliance: **criterion 4** = reconcile our realized tax vs the real
Zerodha **Tax P&L** export. **✅ DONE (2026-06-18)** — real SELL made, Tax P&L parser built, gross
reconciles to the paise (₹25.25 STCG, Δ ₹0.00); see the crit-4 block above + `reports/
crit4_reconciliation.md`. Remaining hardening: a multi-lot/LTCG/loss case (this one was single-lot,
all-STCG) and LTCG loss set-off. **Parked (declined/deferred):** auto-execution, LLM-for-numbers,
Monte Carlo, GPU, more quantum.

**✅ PAPER CRON FIXED (2026-06-15, PR [#14](https://github.com/aarsh-adhvaryu/Q_Alpha/pull/14), merged).** Root cause of the never-firing
schedule: `cron: "0 12"` was the **top of the hour** — GitHub throttles/silently-drops on-the-hour
scheduled workflows under load. Moved to `"23 12 * * 1-5"` (off-hour). Proved the pipeline works
end-to-end via a manual `workflow_dispatch` run (green; it marked the book + pushed the track record,
commit `1a799e1`). First scheduled firing expected next weekday 12:23 UTC — **still verify it fires
on schedule** (dispatch ≠ cron). The job itself was always sound; only the trigger timing was broken.

**🅿️ PARKED VISION (2026-06-15, user said "do later") — autonomous system + Nifty 100–200.** The
user wants the product to become **autonomous data→scoring→recommendation, human approves + trades
manually** (never auto-executes — already the design). Daily data refresh + a weekly decision/advisor
run (two cron cadences; the `paper.yml` skeleton already does the no-AI-in-loop pattern). Scale the
universe **5 → Nifty 100–200** (user's chosen scope). Two findings that reshape this:
1. **Kite Connect API does NOT expose fundamentals/Tijori** (verified vs kite.trade/docs/connect/v3:
   categories are auth/orders/GTT/alerts/portfolio/quotes/WebSocket/historical-candles/MF/margin — no
   fundamentals). Tijori on Zerodha is the **consumer Kite UI only**; programmatic Tijori = its own
   **separate paid API**. So fundamentals can't ride the existing Kite integration.
2. **The validated edge is 3-factor (price/volume) — it needs ZERO fundamentals.** So scaling to
   Nifty 100–200 is **data-cheap** (price history via yfinance + the bad-tick sanitizer; no data
   deal). Fundamentals/6-factor stays the *optional later* enhancement (only then weigh Tijori-API vs
   NSE/BSE-filings parsing). **Critical path for the expansion (a fresh, pre-registered Phase-0 pass —
   the Nifty-50 result does NOT auto-transfer):** (a) extend the PIT universe 50→~200 via
   `build_nifty_universe.py`; (b) add the **square-root slippage law** `impact≈k·σ·√(value/ADV)`
   *before* trusting mid-cap numbers (flat 0.2% is too optimistic off large-caps — see §13 / the
   open-threads slippage item); (c) re-validate 3-factor net cost+tax, walk-forward, **vs 1/N**. Run
   as a **validation experiment**; promote the new universe into the product default **only after it
   clears the bar** (keep qalpha pristine — see the research-untouched rule). **Trap to avoid:** a
   "weekly decision" cadence must NOT loosen the §4.6 gate — weekly *monitoring* is fine, but actual
   trades must stay rare (low realized turnover is the validated edge).
   - **▶ STAGE-1 BREADTH SCREEN DONE (2026-06-18) — INCONCLUSIVE, and instructively so.** Pre-reg
     `reports/PREREGISTRATION_universe.md`; `scripts/build_static_universe.py` (current Nifty-100,
     98 names) + `scripts/exp_universe_breadth.py` (parameterized walk-forward on a **separate** price
     cache → validated panel untouched) → `reports/universe_breadth_findings.md`. Ran the validated
     config (annual·shrink·force_refresh·dynamic-slippage) on a **static current-constituents** Nifty
     100. Result: strategy 16.4% CAGR / Sharpe 1.06 (≈ its clean PIT-50 18.2%/1.13, **no visible
     breadth bonus**), but "loses to 1/N by −9.9pt." **The −9.9pt is an artifact:** 1/N on a static
     survivorship-biased universe (26.3% CAGR — implausible) is the *largest* survivorship beneficiary
     (buy-and-hold-all-future-survivors), so it inflates **more** than a point-in-time factor strategy
     → the gap is contaminated, not a real loss. **Methodological lesson: never benchmark vs 1/N on a
     survivorship-biased universe; a static screen cannot adjudicate breadth.** Did NOT run Nifty 200
     (same contamination → motion, not evidence). **The only valid path = Stage 2: a real PIT
     Nifty-100/200 membership (NSE reconstitution circulars / niftyindices) — the data-blocked piece.**
     Given no visible bonus even with the survivorship tailwind, the EV of that data effort is modest;
     **keep the product at the validated Nifty 50** unless/until Stage-2 data is sourced. Not a
     next-week item.

**🧠 OTHER OPEN THREADS** — same-day `positions()` reading; crit-4 hardening (multi-lot/LTCG/loss
case + LTCG loss set-off — the single-sell gross reconciliation is ✅ done); corporate-actions (crit 5);
the tax-alpha whitepaper; LLM "concierge"
routing NL → the deterministic engine; an equity-curve chart + dashboard screenshot in the README
(the only "last-mile" polish for resume-readiness — repo is otherwise resume-ready: 100 tests green,
CI green, honest README). Let the user steer.

**The validated config is now the default** of `scripts/run_phase0.py` (no args needed):
PIT universe + **Nifty 50 TRI** benchmark + **annual** rebalance + **`weighting=shrink`** (½ min-var +
½ equal, the anchor-to-1/N edge) + **`force_refresh=True`** (anti-ossification) + §4.6 gate 2.0 + band
0.10. Reproduce the headline (**18.2% CAGR / Sharpe 1.13 / GO**, beats Nifty TRI 14.5% and 1/N 17.7%):
```bash
uv run python scripts/build_nifty_universe.py        # regenerate the PIT universe CSV (gitignored)
uv run python scripts/run_phase0.py --end 2024-12-31 # the validated run → reports/phase0_report.md
```
Engine low-level defaults were left neutral (minvar / monthly / no-refresh) so the test-suite stays
green; the *application* layer (run_phase0) carries the validated defaults.

**What's proven vs not:** the strategy edge is validated as far as *simulation* can go (walk-forward +
2025-26 holdout + shrink beats 1/N). What remains is **live-only** validation that no simulator can
replace — data-feed integrity, real fills/slippage, FIFO-vs-broker tax reconciliation, the
human-in-the-loop process, and certainty of no look-ahead (we found one look-ahead bug already). That
is the unskippable forward paper run; it can be *de-risked* fast (replay the production code over
history; validate FIFO vs a real Zerodha Tax P&L) and run *in parallel* with the build, but the
forward calendar time itself (pipeline survives N days + ≥1 volatility event) cannot be simulated away.

_(Superseded — those original "three candidate moves" are done: branch pushed/merged, Stage-1
founder-as-user build + paper clock live, QUBO/QAOA built. The active plan is the advisor-first one
above. The tax-alpha whitepaper remains a good resume capstone once the advisor exists.)_

**Read-me-first docs:** `reports/PHASE0_VERDICT.md` (full evidence chain + verdict), `STRATEGY.md`
(market scan, regulatory reality, 4-stage industry-ready plan), `PLAN.md` (technical track).
Experiment scripts: `walkforward.py`, `calibrate_gate.py`, `holdout_2025.py`, `exp_breadth.py`,
`exp_frequency_lookback.py`, `build_nifty_universe.py`.

### Original static result (Phase 0b, 2012–2024, net of cost + tax) — vs Nifty *price*
| | final ₹ (from ₹2L) | CAGR | Sharpe | max abs DD |
|---|---|---|---|---|
| Q-Alpha (6-factor, tax-aware) | 1,412,776 | 16.6% | 1.06 | -34.5% |
| Nifty 50 (price) | 992,378 | 13.4% | 0.85 | -38.4% |
| Equal-weight 1/N | 1,579,511 | 17.7% | 1.09 | -35.6% |

### Phase A: survivorship-free universe + fair Nifty 50 **TRI** benchmark (3-factor, fully reproducible)
The six-factor model can't yet be run on the PIT universe (needs fundamentals for ~75 names; only 7
of 25 Screener files are even in the repo), so the clean A/B is on the **3-factor (0a)** model:
| run | universe | CAGR | Sharpe | max DD | cost+tax | vs Nifty 50 TRI (14.5%, 0.98) |
|---|---|---|---|---|---|---|
| static-0a | 24 survivors | 14.6% | 0.98 | -33.6% | ₹10k | CONDITIONAL (ties Sharpe) |
| **PIT-0a** | **76, dead names in** | **15.2%** | **0.92** | **-28.1%** | **₹165k** | **NO-GO (loses Sharpe)** |
| 1/N (PIT, frictionless) | — | 17.7% | 1.06 | -39.0% | 0 | — |

Honest read: **survivorship bias was *not* inflating the edge** — fixing it actually *raised* return
(14.6→15.2%) and cut drawdown. At **monthly** rebalancing the strategy loses Sharpe vs TRI because
turnover/tax explodes (₹2.7k→₹117k) — the §4.6 gate at 2.0 is far too lenient at this universe size.

### Phase A follow-up: **rebalance frequency** is the single biggest lever (PIT-0a vs TRI, net cost+tax)
| rebalance | # rebal | tax | CAGR | Sharpe | maxDD | verdict |
|---|---|---|---|---|---|---|
| Monthly | 47 | ₹117k | 15.2% | 0.92 | -28.1% | NO-GO (loses Sharpe) |
| Quarterly | 22 | ₹76k | 16.7% | 1.04 | -24.6% | GO |
| **Annual** | **5** | **₹20k** | **18.5%** | **1.13** | **-24.1%** | **GO — beats TRI *and* 1/N** |

**Trading less improves *every* metric monotonically** in the full window. Mechanism is durable:
lower tax (LTCG not STCG, fewer events) + less noise-trading + tax savings compounding. Frequency is
a CLI knob (`run_phase0.py --rebalance M|Q|Y`). Reports: `reports/phase0_pit_report.md` (monthly),
`reports/phase0_pit_annual_report.md` (annual), `reports/phase0_static0a_report.md` (static/TRI).

### WALK-FORWARD VALIDATED (`scripts/walkforward.py`) — thesis holds OOS; frequency is *not* a magic number
Two out-of-sample views on the PIT universe, net cost+tax:
- **Rolling 3-yr holding periods (every entry day):** Annual dominates the *whole distribution* —
  worst-ever 3y **+4.4%** (never a losing 3y stretch) vs Monthly +2.6%, Nifty-TRI **−2.9%**, 1/N
  **−8.7%**. Annual ≥ TRI in **93%** of holds, ≥ 1/N in **69%**, ≥ Monthly in 70%. Best downside of
  any option — the consumer-relevant headline ("even if you started at the worst time…").
- **3 independent sub-period backtests (distinct regimes):** Annual **beat both TRI and 1/N in all
  three** windows (vs 1/N: +4.8, +2.4, +6.9). BUT the M<Q<Y ranking is **not** monotonic OOS —
  Monthly won 2015-21 (its gate suppressed trades → low realized turnover anyway), Quarterly was
  erratic (great 2012-18, *lost* to benchmarks 2018-24 when it under-traded to ₹0 tax).
- **Refined, validated conclusion:** the driver is **low *realized* turnover, not the nominal
  frequency** — annual achieves it structurally, the §4.6 gate achieves it adaptively; both win,
  pure-monthly-churn loses, and zero-turnover (stuck) also loses. So: **"trade less, tax-aware,
  beats index + 1/N net of friction" is validated OOS**; "annual is *the* optimal frequency" is not
  — annual/quarterly is the robust *zone*, pick by the tax/Sharpe trade-off, don't over-fit the point.

## Key decisions (deviations from the spec, deliberate)

- **Broker = Zerodha (Kite Connect), not HDFC.** Notably ₹0 delivery brokerage, which changes the
  cost-gate math. Cost constants live in `src/qalpha/accounting/costs.py`.
- **Tax-aware optimizer** (`run_backtest(tax_aware=True)`): the spec's §4.6 net-benefit gate done
  properly — a rebalance is suppressed unless its annual risk reduction (₹) beats 2× its real
  cost + FIFO capital-gains tax. This is the core edge: friction is modelled *inside* the decision,
  not bolted on. It turned a NO-GO (5.4% CAGR, taxed to death) into beating Nifty 50 net (14.6%).
- The **accounting engine** (`src/qalpha/accounting/`) is standalone so the future live decision
  engine reuses the exact same FIFO/cost/tax code.
- **Dynamic drawdown control** (`src/qalpha/backtest/drawdown.py`, spec §0 amended): the flat
  "20% = FULL FREEZE" was *replaced* (evidence: it misfires almost only at crash bottoms). New rule
  is market-relative — absolute DD → defensive posture; **adaptive excess-DD vs benchmark** (beyond
  the strategy's own 95th-pct, sustained ≥60d) → strategy-failure halt; catastrophic (~-40%) →
  human alert. The spec is a *proposal we improve*, not scripture — amend it when evidence warrants.

## Commands

```bash
uv sync --extra dev                       # set up venv + deps
uv run pytest                             # tests (must stay green)
uv run ruff check . && uv run ruff format --check .   # lint + format
uv run mypy src                           # strict type-check
uv run python scripts/run_phase0.py       # run the backtest + print go/no-go report
uv run python -m qalpha.data.ingest --tickers TCS INFY --start 2012-01-01   # pull prices
uv run python -m qalpha.data.fundamentals --raw data/fundamentals/raw       # ingest Screener xlsx
uv run python scripts/advisor.py deploy 50000      # tax-smart advice (sell / raise-cash / deploy)
uv run --extra dashboard streamlit run scripts/dashboard_app.py   # the live web dashboard
```

All four gates (ruff, ruff-format, mypy strict, pytest) must pass before committing.

## Architecture (the funnel)

```
data/         price panel (yfinance→Parquet), point-in-time universe, Screener fundamentals
factors/      momentum, volatility, liquidity (0a) + value, quality, dividend (0b); regime; scoring
alloc/        Ledoit-Wolf+EWMA covariance conditioning → scipy sector allocator → scipy optimizer
accounting/   FIFO tax lots + Zerodha costs + capital-gains tax + corporate_actions (split/bonus/dividend, crit 5)   (reused live; Portfolio.to_state persists a book)
backtest/     walk-forward engine, portfolio accountant, baselines, metrics, report; decision.py = shared decide_rebalance
live/         Kite auth + replay harness + paper book (PaperBook) + dashboard renderer (+ systemic_risk_markdown, read-only hedge watch) + advisor.py (tax-smart layer, crit 10; now nets §70 loss set-off) + holdings.py (live reader) + tradebook.py (Console CSV → dated FIFO, crit 4) + taxpnl.py (Tax P&L reconcile) + safety.py (fail-loud staleness/data/session guards) + ticker.py (session-scoped KiteTicker realtime stream)
scripts/      run_phase0, paper, advisor (CLI), dashboard_app (Streamlit, `dashboard` extra), build_nifty_universe, experiments
config.py     every tunable parameter (Q_alpha.md §16) in one place
              (the research track — QUBO/QAOA §15 + planned regime/agentic — lives in the separate Q_Alpha_Research repo)
```

Data flow each rebalance: `as_of` slice (no look-ahead) → liquidity gate → factor scores under the
regime's weights → top-N selection → sector allocator → portfolio optimizer → tax-aware execution.

## Conventions

- **Money is `decimal.Decimal`** everywhere it touches accounting; never float (spec §5.2). Factor
  / covariance math uses numpy float64.
- **No look-ahead, ever.** All historical reads go through `PriceData.as_of(date)`; fundamentals
  carry an `effective_date = report_date + 90d` lag. There is a test that fails on look-ahead.
- **Reuse before adding.** The sector-percentile ranker, cost engine, and FIFO ledger are shared;
  prefer extending them. Match the surrounding style; keep functions typed (mypy strict).
- Reference the spec by section (e.g. "§4.6") in comments so code maps back to the architecture.
- Phase 0a (3 price/volume factors) runs without fundamentals; Phase 0b (6 factors) activates when
  Screener exports are present in `data/fundamentals/raw/`. The scorer renormalises over whatever
  factors exist, so the same code path serves both.

## Path to a real GO — §14 scorecard

"GO" = the spec's §14 (10 criteria, all true before real money), spanning Phase 0 → Phase 6.
Status: **1 ✅ walk-forward validated (low-turnover 3-factor PIT beats TRI in 93% of 3y holds & beat
TRI+1/N in all 3 independent sub-periods, best downside; the *thesis* holds OOS though not a magic
frequency — see Phase A) |
2 ✅ | 3 ✅ PIT universe built (Phase A) | 4 ✅ **reconciled to the paise (2026-06-18)** — real SELL +
Tax P&L parser (`taxpnl.py`); gross == Zerodha STCG ₹25.25 (`reports/crit4_reconciliation.md`).
**§70 loss set-off now implemented (2026-06-19, `net_capital_gains_tax`, advisor/reconcile only — not
the engine, headline preserved).** Remaining hardening needs a *real* multi-lot/LTCG/loss sell + Tax
P&L to reconcile the new netting; 8-AY carry-forward still deferred |
5 🟡 corp-actions ENGINE + live wiring done, tax-correct (2026-06-19, `accounting/corporate_actions.py`
+ `FIFOLedger.apply_split/apply_bonus`, `Portfolio.apply_corporate_action`, detector
`live/corporate_actions_feed.py`, **interleaved into `tradebook.replay_tradebook` so a held name that
splits/bonuses reshapes its lots at the ex-date** + reconciles): splits preserve cost+holding-period,
bonus = ₹0-cost lots at the ex-date (→ STCG even when originals are LTCG), dividends = income cash. 10
tests incl. end-to-end through the replay. Remaining: reconcile ONE real corporate action on the account |
6 ⏳ paper clock STARTED 2026-06-12, accumulating (3–6 mo, unskippable) |
7 ✅ | 8 ✅ (dynamic rule) | 9 🟡 pipeline built, needs the live run | 10 ✅ deterministic tax-smart
advisor + live dashboard built (`advisor.py`, `dashboard_app.py`)**. Phase A cleared survivorship (3)
and — once rebalancing slowed to annual — re-cleared criterion 1 on the *fair* test. Remaining for a
defensible Phase-0 GO: **walk-forward validation** of the rebalance frequency (don't trust one
bull-heavy window), then optionally the 6-factor PIT run. The *real-money GO* remains months away,
gated by a mandatory paper-trading run.

## Brainstorming / open threads (what we're actively deciding)

- **Survivorship-free universe — DONE (Phase A).** Built `data/universes/nifty50_membership.csv`
  (point-in-time Nifty 50, 2012–24, dead names included) via `scripts/build_nifty_universe.py`
  (reverse-apply from current set, validated — caught 4 Wikipedia errors + 2 missing exits). Wired
  `run_phase0.py --universe-csv`. Also fixed a **look-ahead bug in the 1/N baseline** (it front-ran
  future index entrants → fake 22.4%; now `equal_weight_pit` respects membership) and added a fair
  **Nifty 50 TRI** benchmark (`--benchmark NIFTYBEES.NS`, adj-close = divs reinvested) + a §5.1
  yfinance bad-tick sanitizer. Finding: survivorship wasn't flattering the edge, but vs TRI the
  3-factor model loses Sharpe (see status table). **Blocker for the real verdict: fundamentals for
  the ~75 PIT names** (a Screener-ingest data task, like the original 0b) to run 6-factor-on-PIT.
  Large-cap survivorship bias is genuinely *modest* (delistings ≈0.81% of Nifty-500 mcap) — confirmed.
- **"A better optimizer" — DONE: shrinkage hybrid (`weighting="shrink"`).** ½ min-var + ½ equal-weight
  over the picks (DeMiguel/Tu-Zhou anchor-to-1/N) is the validated winner — beats 1/N in-sample, on
  the 2025-26 holdout, and across rolling 3y holds (dominates every percentile). `select_and_weight`
  now supports `minvar|equal|score|shrink`; engine takes `weighting=` + `n_stocks_override=`. Pure
  broad-equal and score-tilt LOST (dilute/concentrate) — only the principled blend won. **Remaining
  optimizer ideas:** HRP/NCO (another robust route), and QUBO/VQE as the §15 research showcase
  (AUM-gated ₹50L+; now in the `Q_Alpha_Research` repo). Discipline held: it cleared the "beat 1/N
  walk-forward net of cost+tax" bar.
- **Defensive engine — two modes tested (`run_backtest(defensive=...|governance_events=...)`).**
  (1) *Price-based* idiosyncratic-drawdown exit (§3.6, `defensive.py:idiosyncratic_exit_flags`):
  on the annual core it cuts drawdown (-24%→-19%) and plugs the 2022 hole (-10%→+11%) but costs
  ~3pts CAGR (18.5→15.6) and *raises* tax (₹20k→₹46k) by whipsawing blue-chips (RELIANCE, ITC,
  MARUTI…) that recover — Sharpe ~flat (1.13→1.11), so it trades return for drawdown, not a free
  win. (2) *Event-driven* governance freeze (§3.11, `defensive.py:GovernanceEvents`, seed
  `data/events/governance_events.csv`): surgical by construction (only ever touches a broken
  business), but a **backtest no-op here** — the momentum/quality factors already never bought
  Yes Bank / Zee (collapsing momentum → never selected). Lesson: the opportunistic engine already
  does most of the defending; event-defence's real value is per-position risk control + a
  human-escalation trigger, and it's gated on a full historical event feed. Also fixed a real
  engine bug surfaced here: idle settled cash was locked out of redeployment by the §4.6 variance
  gate (cash→stocks looks like a risk rise) — now idle cash above the no-trade band always deploys
  (§2.9 fresh-capital routing), which also benefits real capital injections.
- **§4.6 gate multiplier — OOS-calibrated, verdict: DON'T tune it (`scripts/calibrate_gate.py`).**
  Swept {1,2,3,5} at monthly across the 3 sub-periods: **no value generalizes** (best flips
  1.0/3.0/2.0 by window) and turnover is a *knife-edge* (mult 2.0→47 rebalances/₹117k, 3.0→4/₹13k);
  monthly+gate loses to 1/N in ~half the windows. The robust turnover lever is **structural
  frequency (annual)**, not the multiplier — kept at spec default 2.0. (Iron rule: did not tune to
  manufacture a GO.) Side effect found+fixed: idle-cash redeploy lockout (monthly full 15.2→16.7%).
- **Size-aware slippage — ✅ DONE (2026-06-17).** Replaced the flat 0.2% with the **square-root law**
  `slippage = impact_k·σ_daily·√(value/ADV)` (spec §13): new `accounting/slippage.py`
  (`SquareRootSlippage`/`FlatSlippage`, `square_root_impact_pct`, tested), a `slippage_model` on
  `Portfolio` used in `_sell`/`_buy`/`_affordable_qty`, and `run_backtest(dynamic_slippage=True)` which
  sets a **causal as-of** per-rebalance ADV+vol snapshot (no look-ahead). Config in `CostConfig`
  (`impact_k=1.0`, floor 2bps, cap 2%). At k=1 the law equals the old 0.2% exactly at the §3.3
  order-size cap (1% of ADV, 2% daily vol), so it's a principled generalisation. **`run_phase0`
  defaults it ON** (`--no-dynamic-slippage` reverts). **Honest Phase-0 impact (PIT, annual, shrink,
  end 2024): headline barely moves — GO holds, Sharpe 1.13→1.14, CAGR ~18.2→18.3%, maxDD −25.2 flat,
  still beats Nifty TRI + 1/N — but charged cost DROPS ₹22.2k→₹9.5k** because the strategy trades
  small fractions of ADV in deep large-caps, so realistic impact is *below* the flat 0.2%. The model's
  teeth are for the **Nifty 100–200 expansion**, where thin mid-caps in size get charged more — the
  gate/optimiser then avoid them. Slippage is an execution *cost*, not portfolio risk.
- **Benchmark fairness.** Move to **Nifty 50 TRI** (total-return, free from niftyindices.com) — raises
  the bar ~1.5%/yr; the strategy still clears it.
- **BSE→NSE canonical-ticker robustness — ✅ DONE (2026-06-17).** A holding/trade is keyed by ISIN in
  demat (exchange-agnostic), and NSE is our single source of truth (panel/universe/factors/slippage)
  and the liquid venue. So `live/holdings.py` `to_ticker(symbol, exchange)` → **`canonical_ticker(symbol)`**
  that always resolves to `.NS` (a BSE INFY buy tracks as `INFY.NS`); `Holding.exchange` keeps the real
  venue for the live `ltp()` call. `tradebook.py` uses it too (a BSE leg + its NSE counterpart reconcile
  to one lot). Deliberately did **NOT** build full dual-exchange (NSE+BSE) calibration — same companies,
  thinner BSE book, Sensex⊂Nifty, BSE-only = illiquid small-caps → complexity tax, zero alpha, bloats
  the clean repo. Tests in `test_holdings.py` (BSE→.NS, exchange preserved). 107 tests green.
- **§4.6 gate tax-date bug — ✅ FIXED (2026-06-17).** `decision._net_benefit_ok` dry-ran the gate's
  cost/tax estimate at wall-clock `date.today()` instead of the rebalance `as_of`, so in a historical
  backtest every lot looked long-term → STCG under-estimated as LTCG → the gate traded too readily.
  Now threads `as_of` (live, `as_of`≈today, so also correct). **Validated headline unaffected**
  (force_refresh short-circuits the gate); only non-force-refresh `tax_aware` runs (older Phase A
  monthly/quarterly tables, `calibrate_gate`) would shift slightly if re-run — qualitative conclusions
  hold. 106 tests green.
- **Tax-engine validation (criterion 4) — ✅ DONE (2026-06-18).** FIFO engine reconciled vs the real
  **Zerodha Console → Tax P&L** export: gross == ₹25.25 STCG to the paise (`taxpnl.py`,
  `scripts/reconcile_taxpnl.py`, `reports/crit4_reconciliation.md`). The first sell was a single
  STCG gain (no loss), so loss set-off wasn't exercised. **✅ §70 loss set-off now IMPLEMENTED
  (2026-06-19, `net_capital_gains_tax`/`net_tax_total`):** STCL→STCG then LTCG, LTCL→LTCG only,
  exemption on net, carry-forward reported (8-AY carry not applied). Additive — wired into the advisor
  (`advise_sell` nets losses + shows `setoff_saving`) + reconcile only, NOT the backtest engine, so the
  headline is unchanged. **Still needs a *real* multi-lot/LTCG/loss sell + Tax P&L to reconcile the netting.**
- **Risk-tolerance reckoning.** Backtest the full **50/25/25** pool structure (not 100% core) to see
  the blended drawdown, then confirm the real tolerance (long-only equity ≈ -30% in crashes; a hard
  ≤20% implies a hedging overlay = a v2 feature).

## Iron rules (don't violate)

- Do **not** auto-tune parameters to manufacture a GO — that defeats Phase 0. Validate out-of-sample.
- Keep all four gates green (ruff, ruff-format, mypy strict, pytest) before every commit.
- Surface honest caveats in the report; never let a survivor-only universe silently earn a GO.
