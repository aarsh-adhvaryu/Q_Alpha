# Q-Alpha "Daily-Driver Ops Layer" — proactive alerts + capital-aware buy plan

## Context

The user's complaint: if Q-Alpha is to be his *only* tool besides Kite, it must behave like a real
asset-management operation — proactively watch for opportunities, know what capital he has, and say
concretely "you can invest ₹X → buy these shares" without being asked. Exploration confirmed the gap
precisely: **everything analytical exists but the system is 100% pull-based.** The weekday cron
(paper.yml — alive, marks through 2026-07-07 on origin/main) marks the paper book and commits files
with **zero outbound notification anywhere in either repo** (grepped). Idle cash
(`fetch_available_cash`, `src/qalpha/live/holdings.py:98`) feeds only a passive metric tile; the buy
advisor requires typing an amount + clicking a button; market-weakness / hedge-gauge / GO signals are
computed only when the dashboard is opened. The hedge overlay is healthy but silent by design
(0 episodes; gauge 0.46 vs τ 0.7) — if it ever fires, nothing tells him.

**User decisions (2026-07-08):** Telegram bot for alerts · events + Monday digest (silence = all
well) · defer the private cash-snapshot bridge (dashboard-only sizing first) · **AI market brief:
build it — Opus 4.8, daily after market close** (user's ask: "an API that goes through the news
every day, tells the sentiment, explains drivers like why oil is inflated, and points at
opportunistic sectors/stocks").

## Iron rules honored
- **Never auto-trades**; human places every order in Kite. No unattended Kite token (locked).
- Validated 18.2% headline untouched: nothing under `src/qalpha/backtest/` or `accounting/` changes.
- Product never imports research code. Money is Decimal. Four gates green per PR.
- "Take risk" = a **pre-committed written policy** on the already-validated deploy-into-weakness
  lever + the existing satellite sleeve caps — no new alpha claims.
- Repo is **public** (Streamlit Cloud deploys from it): no cash/holdings figures ever committed.

---

## PR-1 — Notification spine + daily opportunity scan ("the analyst")

### New `src/qalpha/live/notify.py`
- `telegram_configured() -> bool`; `send_telegram(text, *, parse_mode="HTML", transport=None) -> bool`.
- Env `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`; stdlib `urllib.request` POST to
  `api.telegram.org/bot<token>/sendMessage`; injectable `Transport = Callable[[str, bytes], int]`
  for tests; `html_escape` helper.
- **Fail-soft absolutely**: any exception / missing env → `False`, never raises — the cron must
  never go red because Telegram hiccuped.

### New `src/qalpha/live/scan.py` — pure, fully unit-testable decision logic
- `AlertState` (frozen dataclass, JSON round-trip like `runlog.py`): last-notified
  `weakness_level`, `weakness_pending`/`weakness_pending_count` (hysteresis), `go_verdict`,
  `was_stale`, `last_rebalance_alert`, `last_digest_week`. Persisted at
  `data/paper/alert_state.json` (tracked dir, no secrets).
- `ScanFacts` (frozen): as_of, weakness, go_verdict, rebalance applied/pending, freshness, stale,
  pre-rendered deploy lines.
- `evaluate(facts, state, today) -> tuple[list[Alert], AlertState]` — all dedupe rules live here.

### Alert taxonomy (the contract)
| Event | Trigger | Edge/dedupe rule |
|---|---|---|
| weakness-escalation | `market_weakness(real benchmark)` level rises | fires immediately on any rise; message states the tranche policy + top out-of-favour names |
| weakness-easing | level falls | only after the lower level holds **3 consecutive scans** (hysteresis vs −5% oscillation noise) |
| rebalance | cron auto-applied orders OR `plan.has_orders` pending | once per event date |
| go-flip | `build_scorecard(...).verdict` changed | any change; NO-GO flagged 🔴 |
| guard-failure | `paper_freshness` stale / data-integrity red | once per stale streak (False→True edge) |
| pipeline-failed | GH Actions job failed | every failure (`if: failure()` step) |
| weekly-digest | Monday, once per ISO week | the liveness heartbeat: book vs TRI, market level, GO progress, next rebalance, idle-cash nudge |

Position-health / satellite alerts stay dashboard-only (deliberate noise control).

### New `scripts/scan_alerts.py` (thin composition)
- Runs in the same cron job after `paper.py daily`: benchmark via the real NIFTYBEES series
  (`paper._load_benchmark_series()` — never the watchlist mean), book via `PaperBook.load`,
  scorecard via `build_scorecard`, freshness via `paper_freshness`.
- Downloads its own fresh watchlist panel in-job (reuse `build_nifty100_watchlist.py --prices`
  logic) for cheapness names in messages (`data/historical/*` is gitignored — can't be committed).
- Flags: `--test` (send test alert), `--force-digest`, `--pipeline-failed "<msg>"`. Exit 0 even on
  send failure; prints actions to the job log.

### `.github/workflows/paper.yml`
- New step after the daily run: `uv run python scripts/scan_alerts.py` with the two Telegram
  secrets in `env`; add `data/paper/alert_state.json` to the commit step's `git add`.
- New `if: failure()` step calling `--pipeline-failed` with the run URL.
- `workflow_dispatch` input `force_digest` for verification.

### Tests
- `tests/test_notify.py`: fake transport asserts URL/chat_id/text; erroring transport → False, no
  raise; missing env → transport never called.
- `tests/test_scan.py` (pure `evaluate`): escalation fires once, repeat scan silent; easing only on
  3rd consecutive lower scan; deep fires even if elevated never notified; GO flip both directions;
  digest exactly once per ISO week, Mondays; stale edge once per streak; state JSON round-trip.

---

## PR-2 — Capital-aware standing buy plan ("the PM") + honest-bug fixes

### `src/qalpha/config.py` — new `DeployPolicyConfig` (§16 pattern, on `Config`)
```
idle_cash_floor = Decimal("5000")   # below this, never nag
alert_tranche_elevated = 0.50       # alert sizes 50% of idle on elevated weakness
alert_tranche_deep = 1.00           # 100% on deep — the pre-committed "calculated risk"
max_names_default = 15
```
The dashboard always shows the full plan for idle cash (DCA framing); the *alert* tranches are the
event-driven risk policy. `scan.py` message text states the policy from PR-1 onward.

### `scripts/dashboard_app.py`
1. **Auto PM brief on the Live tab** — after `_load_live` succeeds, if
   `portfolio.cash >= idle_cash_floor`, auto-run `advise_deploy_into_weakness` (no typing, no
   button): "💰 Idle cash ₹12,430 → market 🟢 normal: buy 2×ITC, 1×NTPC… (₹0 capital-gains tax,
   buys only) · leftover ₹514". Cache in `st.session_state` keyed by `(cash, as_of)` so the 30s
   fragment doesn't recompute; prefill the Add-money amount with available cash. Gated behind the
   existing `assess_advice_inputs` safety guards (reuse `_advisor_with_safety`, don't bypass).
2. **Real-index fix**: delete `index_close = wl_prices.adj_close.mean(axis=1)`
   (`scripts/dashboard_app.py:615`) — thread the real benchmark series into `_advisor_tabs` /
   live brief (the paper `_today_brief` already does it right).
3. **Watchlist staleness fix**: `@st.cache_resource(ttl=6*3600)` on `_watchlist` + pure helper
   `watchlist_is_stale(last_date, today)` in `live/dashboard.py`; re-download the panel when stale.
4. Extract a pure `live_pm_brief_markdown(...)` formatter into `live/dashboard.py` so the brief is
   unit-testable without Streamlit (quantities, ₹0-tax line, floor suppression).

### Tests
- Pure formatter + `watchlist_is_stale` tests; existing AppTest smoke stays green. The live-tab
  auto-brief is user-verified on the box (established pattern — no Kite creds in sandbox).

---

## PR-3 — Research repo: hedge-flip alert
- Duplicate the ~30-line Telegram sender as `src/qalpha_research/notify.py` (repos stay decoupled —
  deliberate copy, say so in a comment).
- `scripts/hedge_paper.py daily`: after `forward_hedge_track`, load
  `data/hedge_alert_state.json`; on `hedge_on` transition (both directions) send: "🛡 Fragility
  gauge 0.74 ≥ τ 0.7 → hedge overlay ON (paper). Consider the tax-free short-futures hedge —
  informational, you decide." Save state.
- `.github/workflows/hedge_paper.yml`: Telegram secrets in env, state file in `git add`, same
  `if: failure()` step, `--test-alert` flag.
- Pure transition-logic test with fake transport (its 28-test suite pattern).

## PR-4 — Research repo: daily AI Market Brief ("the macro analyst")

**Honest framing (locked):** this is an LLM *narrative* layer — context, never a signal. It never
computes numbers, never feeds the deterministic advisor/engine, and never changes allocations
(iron rule: no new alpha without validation). Discretionary ideas it surfaces are explicitly framed
for the existing **satellite sleeve** (≤8% sleeve / ≤2.5% per name — the container built for human
judgment calls). Every brief opens with "🧠 AI market brief — context only, not a signal." It lives
in **Q_Alpha_Research** (keeps the product repo deterministic/LLM-free) and rides the existing
`hedge_paper.yml` cron (12:31 UTC ≈ 18:01 IST — after NSE close, perfect timing).

### New `src/qalpha_research/ai_brief.py`
- One Claude API call per trading day via the official `anthropic` SDK (new research-repo dep only),
  **tuned for minimum token spend** (user requirement):
  `model="claude-opus-4-8"`, `thinking={"type": "adaptive"}` (must be set explicitly on 4.8),
  **`output_config={"effort": "low"}`** (caps thinking + output spend — a headline summary doesn't
  need deep reasoning), **`max_tokens=1500`** (the brief is ≤ ~1,800 chars ≈ ~500 tokens; 1500 is
  headroom, and a hard ceiling on output cost), and the server-side **web search tool** with
  **`max_uses: 4`** (search results bill as input tokens + per-search fee — 3–4 targeted searches
  cover "Nifty today why" + 1–2 driver follow-ups):
  `{"type": "web_search_20260209", "name": "web_search", "max_uses": 4,
  "allowed_domains": ["economictimes.indiatimes.com", "moneycontrol.com", "reuters.com",
  "livemint.com", "business-standard.com"]}`. No RSS parsing needed.
- Prompt is deliberately **short and stable**: a compact fixed markdown template request
  (≤ ~1,800 chars out, Telegram-friendly) — sentiment line (🟢/🟠/🔴 + one sentence) · top 2–3
  drivers each with the *why* (e.g. "crude +4% on X → OMC margins compress, aviation/paint input
  costs rise") · watchlist names affected · 0–2 discretionary ideas tagged "satellite sleeve rules
  apply" · one-line risk note. The watchlist is passed as a **minimal `TICKER:sector` CSV line list**
  (~96 names ≈ ~700 tokens), not a table dump. Instruct "no preamble, template only."
- Injectable client for tests; pure `build_prompt(...)` and `format_for_telegram(text)` helpers.
  `daily` logs `usage` (input/output tokens) to the cron log so real cost is visible per run.
- **Fail-soft everywhere**: missing `ANTHROPIC_API_KEY` → skip with a log line; API error/refusal
  (`stop_reason` checked before reading content) → skip; the cron must never go red because the
  brief hiccuped. Expected cost with these caps: **~₹4–8/day (~₹100–200/month)** — roughly
  ~3–6k input + ~0.5k output tokens/day at $5/$25 per MTok plus ~4 web searches.

### New `scripts/ai_brief.py` (CLI)
- `daily`: call the API → write `reports/ai_brief.md` (committed — the durable archive) → send via
  the PR-3 Telegram sender. `--dry-run` prints without sending. Exit 0 always.

### `.github/workflows/hedge_paper.yml`
- New step after the hedge mark: `uv run python scripts/ai_brief.py daily` with
  `ANTHROPIC_API_KEY` + the two Telegram secrets in `env`; add `reports/ai_brief.md` to `git add`.

### Tests (research repo)
- `build_prompt` includes watchlist names + the context-only preamble; `format_for_telegram`
  truncation + escaping; `daily` with a canned fake client (no network in CI); missing-key and
  API-error paths exit 0 without sending.

## PR-5 — DEFERRED (user decision): private cash-snapshot bridge
Only if "log in to size it" proves annoying: private `Q_Alpha_State` repo, dashboard writes
cash+holdings via GitHub contents API on login, cron reads it (≤7 days old) to put concrete
quantities in alerts. Not built now.

---

## Verification (end-to-end, user-executable)
1. **Spine**: user creates the bot via @BotFather, gets chat_id from `getUpdates`, adds the two
   secrets to both repos' Actions + Streamlit Cloud. Locally:
   `TELEGRAM_BOT_TOKEN=… TELEGRAM_CHAT_ID=… uv run python scripts/scan_alerts.py --test` →
   message arrives on the phone.
2. **Cron path**: Actions → Paper daily → Run workflow: green run, `alert_state.json` committed, no
   alert on a no-edge day; dispatch with `force_digest=true` → digest arrives.
3. **Failure path**: first real failure (or a deliberately broken dispatch) → 🚨 alert with run link.
4. **Dashboard PM**: on the box — Live tab, one-tap Kite login → idle-cash brief renders with
   quantities and prefilled amount; with cash below ₹5,000 the brief stays absent.
5. **Hedge**: dispatch `hedge_paper.yml` with `--test-alert` → test message; real flip fires at τ.
6. **AI brief**: user creates an Anthropic API key (platform.claude.com) and adds
   `ANTHROPIC_API_KEY` to the research repo's Actions secrets. Locally:
   `ANTHROPIC_API_KEY=… uv run python scripts/ai_brief.py daily --dry-run` → brief prints; then a
   real run → arrives on Telegram + `reports/ai_brief.md` committed by the next cron. Verify the
   brief opens with the "context only, not a signal" preamble.
7. Four gates (`ruff`, `ruff format --check`, `mypy src` strict, `pytest`) green in both repos
   before each PR.

## Files
**Create**: `src/qalpha/live/notify.py`, `src/qalpha/live/scan.py`, `scripts/scan_alerts.py`,
`tests/test_notify.py`, `tests/test_scan.py`; research: `src/qalpha_research/notify.py`,
`src/qalpha_research/ai_brief.py`, `scripts/ai_brief.py` + tests.
**Modify**: `.github/workflows/paper.yml`, `scripts/dashboard_app.py`, `src/qalpha/config.py`,
`src/qalpha/live/dashboard.py`; research: `scripts/hedge_paper.py`,
`.github/workflows/hedge_paper.yml`, `pyproject.toml` (add `anthropic` — research repo only).
**Reuse (no new engines)**: `advise_deploy_into_weakness`, `market_weakness`, `cheapness_scores`
(`src/qalpha/live/deploy.py`), `build_scorecard` (`live/go_scorecard.py`), `paper_freshness`
(`live/dashboard.py`), `assess_advice_inputs` (`live/safety.py`), `PaperBook` (`live/paper.py`),
`fetch_available_cash` (`live/holdings.py:98`).
