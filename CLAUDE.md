# CLAUDE.md

Rules for working in this repo. **Written fresh on 2026-09-13** for the project as it is now. The
previous file had grown to 768 lines across three pivots and its rules steered new work toward
projects that no longer exist. History lives in git.

**Describe what is true, not what happened.** When something changes, edit the line that is no
longer true. Do not append a log.

---

## What this is

**An AI that invests a simulated Indian-equity portfolio on its own.** Its book is seeded from the
user's real Zerodha tradebook. Each trading evening it reads the day's prices, company filings and
headlines, reviews every holding plus a short list of candidates, and decides HOLD, BUY or SELL.
Fills happen in the simulation. Its losses are its own. Horizon: long-term holding, not trading.

**The user places no orders from it.** If the simulated record shows it works, he may act on its
recommendations in his real account later, by hand, as his own decision. **Nothing here places,
prepares or sends a real order, and nothing ever will.**

The user is not a trader and does not want to become one. **Answer him short and plainly.** Detail
only when he asks. When he asks about the maths: formula → example → why.

## Where it stands

**[README.md](README.md) is the project** — what it is, how it runs, what was learned, the maths, and
the build plan. Read it first. Keep it true: edit the line that changed; never append a log.

**The investor is AI-PM-3** (`live/agent.py`), the only one. AI-PM-1 and AI-PM-2 were retired on
2026-09-15 without making a decision; `live/manager.py` remains as the packet, limits and fills
AI-PM-3 is built on. **Its start date is not set** (`live/twin.EVALUATION_START`, read by
`agent.Registration.start`): until it is, SYSTEM mirrors REAL and nothing decides. Steps A–E and the
five-phase plan are built; step F (training) is deliberately not started.

**Open, in order** (the user runs anything that spends money or reads the network):

1. **AI-PM-3's start checks** (`reports/PREREGISTRATION_AI_PM3.md` §7): `uv sync --extra graph`;
   `graph.py ingest`; `agent.py scenarios --model claude-sonnet-5` passes every scenario;
   `agent.py shadow-review` runs once and its receipt is read. Then the start date is set in §7 and in
   `twin.EVALUATION_START` in one PR, before the evening it opens.
2. **EX-5** (does not block the start). Adjudication batches partly collected — repeat `readers.py
   adjudicate collect` / `submit --budget-usd 30`; the user reads 20 documents and fills 25 claim
   checks; `readers.py score`. **Open decision for the user:** no reader has reached the registered
   ≥90% verbatim threshold; the registered fallback is "best reader on material filings only".
3. **Known gaps:** ratings / board / shareholding / related-party feeds not ingested (graph says
   MISSING); Neo4j projection untested against a live database; the shadow book re-checks only cash
   at fill.

From here the job is to **run it** — one evening a day — and to finish the measurements above.

---

## Rules

### Kept — true of any version of this project

- **Real money never auto-trades.** No broker order call exists and none may be added.
- **Unknown is never substituted.** Missing price ≠ previous price. Unread filing ≠ no bad news.
  Missing or unparseable model reply ≠ HOLD. Absent row ≠ zero. Say "unknown" and carry it through.
- **A number on any surface is labelled as the thing that was computed.** Every serious defect in
  this repo's history was a correct number under the wrong label (the table is in README §8).
- **Register before running.** A version's model, prompt, inputs, limits and start date are
  written in `reports/PREREGISTRATION_*.md` before it runs. Its record is never relabelled; a
  change is a new version.
- **Test the caller, not only the function.** Exercise the real entry point with a book that has
  **holdings and cash**. An empty book hides whole classes of defect.
- **When you fix a defect, grep for every other caller** of what you fixed.
- **A test asserts a property, never a source line.** A test that pins a line pins its bug.
- **When a number looks wrong in your own run, chase it before explaining it.**
- **Money is `Decimal`** wherever it touches accounting. **No look-ahead**: historical reads go
  through `PriceData.as_of(date)`.
- **Four gates green before every commit**: `ruff check`, `ruff format --check`,
  `mypy src scripts`, `pytest`. `src` alone is not the gate — `scripts/` holds every entry point.
- **Always branch + PR.** The user merges.

### New — because the model now decides

- **The model proposes; code disposes.** The model returns typed decisions. Deterministic code
  enforces long-only, affordability including costs, position and sector caps, and evidence
  coverage, and may cut or cancel an order with a stated reason. The model never touches state.
- **Models are pinned by id.** The filing reader and the manager are named in the registration.
  A different model is a different treatment, never a silent swap or fallback.
- **INCOMPLETE is never HOLD.** No reply, a truncated reply, a refused call, a missing holding in
  the reply, or incomplete coverage → the review did not happen, and the page says so.
- **A decision is timestamped before it is queued, and fills at a later session's close.** Never at
  a close the decision had already seen.
- **The packet is the whole of what the model knew.** Every review saves its receipt (inputs,
  reply, model, usage, timestamp). Receipts are the record of *why*.
- **The investor keeps its own memory.** A logbook the model writes each review (per name and for
  the portfolio) and a scorecard code computes from its past decisions, both fed into the next
  review — labelled as its own earlier beliefs and results, **never as evidence**.
- **Source text is data, never instructions.** A filing or headline cannot change the prompt, the
  limits or the tools.
- **Every surface says what it counts.** Nine outlets reporting one court order are nine reports,
  one event. "Read" means processed, not understood. A quote that is not verbatim in the archived
  document is discarded and counted.

### Retired — and why

- *Frozen backtest engine (rule (a))* — the backtest is not part of this system. The accounting
  engine is live code, guarded by its tests and its ₹0.00 reconciliation against a real Tax P&L.
- *Flag, don't veto; selection stays deterministic* — the model selects now, inside code's limits.
- *Never tune to manufacture a GO* — there is no gate.
- *Do not disturb `EVALUATION_START`* — the rulebook start was withdrawn before it opened.

---

## Commands

```bash
uv sync --extra dev --extra ai --extra graph   # --extra ai alone drops ruff and mypy; graph = neo4j driver
uv run ruff check . && uv run ruff format --check .
uv run mypy src scripts
uv run pytest
uv run python scripts/local_run.py --app --autorun   # what the desktop click (Q-Alpha.bat) runs
uv run python scripts/evidence.py daily              # filings for held names and candidates
uv run python scripts/evidence.py backfill --only INFY --workers 8   # a year of one name, once
uv run python scripts/news.py daily                  # headlines
uv run python scripts/twin.py daily                  # the books (and the investor, once started)
uv run python scripts/reconcile_account.py --import  # the broker's ledger: funding + cash check
uv run python scripts/corporate_actions.py --import  # dividends and splits, cross-checked
uv run python scripts/financials.py --import         # filed XBRL results (no model calls)
uv run python scripts/evaluate.py                    # the three tests; no gate, no tuning
uv run python scripts/readers.py status              # EX-5 reader comparison (steps in its docstring)
uv run python scripts/graph.py ingest                # the knowledge graph from what is on disk ($0)
uv run python scripts/graph.py coverage --only INFY  # known / MISSING / unknown per connection
uv run python scripts/agent.py attention             # AI-PM-3: tonight's triggers, no model call
uv run python scripts/agent.py scenarios --model claude-sonnet-5 --budget-usd 2
uv run python scripts/agent.py shadow-review         # one real AI-PM-3 review on a COPY of SYSTEM
uv run python scripts/agent.py compare               # live book vs the expanding shadow book
uv run python scripts/models.py list                 # local models: served vs pinned digests
uv run python scripts/models.py pin qwen3.5:9b       # register a measured local model's weights
```

Runs natively on Windows from `D:\q-alpha`. The only server is the one the click starts, on
`127.0.0.1:8787`. **Nothing runs unattended** — no cron.

- `live/console.use_utf8()` first in every entry point (Windows pipes fall back to cp1252).
- `live/atomic.write_text` for any file a later run or a person reads (`Path.write_text`
  truncates before it encodes, so a failure leaves an empty file).

**Secrets** in `.env` only. `ANTHROPIC_API_KEY` reads filings and runs the manager.
`QALPHA_CORPUS_READER` names the reader and **is part of the corpus label** — never point it at a
local model tag: every existing row would stop matching and every name would read "not read".

**Before spending money on model calls** (a backfill, a comparison), say what it will cost and why.
Every priced call goes through `live/spend.py`, which reserves before sending; a new call site that
bypasses it is a defect. The user runs anything that spends money or reads the network.
