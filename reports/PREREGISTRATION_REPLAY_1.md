# Pre-registration — REPLAY-1: a nine-session rehearsal of AI-PM-2

**Registered 2026-09-15, before any replay has run.** A replay is a plumbing test. It is not a
performance record, and nothing in it can become one.

## 1. What is being tested

Whether the investor, run over real past sessions with real model calls, **researches, decides, fills,
remembers and resumes correctly**, and leaves the evening run's records untouched. A reasoned HOLD on
every name, every session, is a valid result. Activity is not a goal.

What it cannot test: skill. `claude-sonnet-5` may already know how these sessions went, and nine
sessions separate nothing in any case.

## 2. The run

| | |
|---|---|
| Run id | `pilot-1` |
| Window | **2026-09-01 to 2026-09-11** — nine sessions (the exchange traded every weekday) |
| Investor | AI-PM-2 exactly: `claude-sonnet-5`, the mandate in `live/mandate.py`, the prompt in `live/manager.py`. Their digest and the code commit are written into `data/replay/pilot-1/run.json` at registration; a resume under different code, model, mandate, prompt or inputs is refused. |
| Starting book | The close of 2026-09-01, rebuilt from the tradebook and the broker's ledger through that day: 8 names and ₹2,00,532.79 cash. Not today's book copied backwards. |
| Evidence | Filings **published** by each session, from the corpus frozen at registration (`corpus.json`): read later, public then. |
| Spend | A ceiling of **$5** for the whole run, as its own job in `data/spend/ledger.jsonl`, outside every month's operating budget. Expected $1.5–3 (about $0.14 a review, about $0.30 with a research round). |
| Records | `data/replay/pilot-1/` only. |

Command, run by the user:

```powershell
uv run python scripts/replay.py coverage --start 2026-09-01 --end 2026-09-11
uv run python scripts/replay.py run pilot-1 --start 2026-09-01 --end 2026-09-11 --ceiling 5
# press Ctrl+C once after the third session prints, then resume:
uv run python scripts/replay.py run pilot-1
uv run python scripts/replay.py report pilot-1 --out reports/REPLAY_pilot-1.md
```

## 3. Known gaps, stated before it runs

Measured by `replay.py coverage` on 2026-09-15 for the starting book:

- **7 September has no close for 23 of 95 watchlist names**, including held JIOFIN. That review will
  be INCOMPLETE unless prices are re-downloaded first. A re-download after registration changes the
  inputs and is refused — re-download **before** registering, or register and accept the gap.
- **A queued order waits for the one session after its decision.** If that session has no close for
  the name, the order waits indefinitely and every later review is INCOMPLETE ("orders … have not
  filled yet"). This is the evening run's rule, unchanged. If it happens, the run has found it.
- **Headlines** are archived from 2026-09-10. Before that the packet says headline coverage is
  UNKNOWN.
- **Exchange surveillance files** are missing for 1–3 September (UNKNOWN in the packet).
- **PFC**'s filings were never read, so it is not shown as a candidate on 1–3 September. HDFCLIFE has
  no filed results on record (financials UNKNOWN).
- **Candidates** come from today's Nifty-100 watchlist, not each date's membership.
- **Filed documents** in each held name's window were all read (e.g. 34 of 34 on 1 September).

## 4. What counts as working — written before the result

Each is read from `reports/REPLAY_pilot-1.md`:

1. Every session in the window is checkpointed, as *reviewed* or as *incomplete with a reason*. None is
   missing, and none is a HOLD that did not happen.
2. Every queued order fills at the next session's close or waits with a reason; no fill is recorded
   twice.
3. Every decision cites ids from its packet; reviews after the first carry the investor's own notes.
4. Cash never goes negative; purchases stay within ₹50,000 a month; costs and tax are recorded.
5. The interrupted run resumes to a complete record, with no session decided or paid for twice.
6. `data/twin`, `data/evidence` and `data/facts/financials.jsonl` are unchanged (`integrity.jsonl`).
7. Spend stays under the ceiling.

**A failure is a finding.** Stop, record it below, fix it on a branch, and replay under a new run id.
`pilot-1`'s record is never relabelled.

## 5. What follows

If all seven hold, a forward month is registered separately — code, model, prompt and limits frozen;
memory, research and holdings evolving — with its own start date written before it opens. If it starts
from this replay's book rather than the real book, that origin and its value at the boundary are
recorded, and the month is reported apart from the replay.

## 6. Recorded outcomes

*(Append only, dated.)*

- **2026-09-15** — registered. Not run.
