# Frozen A/B/C wallet experiment — archived 2026-08-17 (PLAN_TRUST_REPAIR.md PR-6, T3.4)

These files have **no reader and no writer** on the live path. They are not deleted, because they are
not junk: they are the final state and track record of a **pre-registered experiment**
(`docs/PREREGISTRATION_autopilot.md`), frozen on 2026-07-12 when the A/B/C wallet books were
superseded by System-vs-Shadow inside the full system.

The repo rule is that pre-registered experiments are archived and their results published, never
quietly removed — deleting the evidence of a superseded study is how a track record becomes a
selection of its own good runs. So they move out of the live tree and stay in git history.

| File | What it was | Last written |
|---|---|---|
| `books.json` | Final state of wallet books A (no AI), B (AI-tilted), C (buy-and-hold) | 2026-07-12 |
| `track.csv` | Daily marks of the A/B/C wallet run | 2026-07-11 |
| `adaptive_track.csv` | Daily marks of the smart-rebalance book, before it was upgraded in place into the System book | 2026-07-12 |

The live successors are `data/autopilot/system_track.csv` and
`data/paper/{adaptive_book,shadow_book}.json`. `load_books` / `save_books` in
`qalpha.live.autopilot` still exist and are still tested, but nothing in production calls them.
