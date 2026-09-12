# Pre-registration — PL-1: the policy `SYSTEM` runs from 2026-09-14

**Registered 2026-09-12, before any of the code below was written, and two days before
`EVALUATION_START`.** Nothing above section 8 may be edited once the window opens.

---

## 1. Why this is being changed now and never again

`PO-1` replayed the live policy — through `runner.step`, the same function `SYSTEM` calls every
evening — over fourteen years on the point-in-time Nifty-50. It finished **55% behind the fund it is
supposed to beat.** `PO-2` then decomposed that loss and found the ranking underneath it finishing
**+9.1% ahead**. Every layer built on top of the ranking destroyed value, and each of those layers
is a deliberate design choice this repository can name.

**`SYSTEM` begins deciding on 2026-09-14.** Today is the 12th. A policy change made now costs
nothing — no window is open, no clock restarts, no result is invalidated, because there is no result.
The same change made on the 15th would be a treatment changing inside its own window, which is
exactly the defect that demoted run 2 to a rehearsal.

**So this is the last honest moment to change it, and after 2026-09-14 it is frozen.** Not "frozen
unless something looks bad" — frozen. If the policy registered here loses for twelve months, it
loses, and that is the finding.

## 2. What changes, and the measurement behind each

| | Change | Measured cost of the current behaviour |
|---|---|---|
| **A** | **§4.7 exits OFF.** `Policy.use_exits = False` | **−₹7.7M** (PO-1), and independently **−₹74.8 lakh over 13 years, paying ₹13.3 lakh of tax to do it** in the frozen backtest. Two measurements, different engines, same sign. |
| **B** | **`exclude_breaking` becomes a flag, not a filter.** The name still appears on the page, marked. | **−₹2.2M** (PO-2): +9.1% falls to +1.1% when the filter is applied to an otherwise identical basket. The deepest-pulled-back names trip the breakdown test, and those are the names that paid. |
| **C** | **Basket size 15 → 8.** | PO-2, monotone in concentration: top-8 **+9.1%**, top-15 **+6.3%**, top-30 **+1.7%**. |
| **D** | **Fresh money buys the cheapest, not the most underweight.** The month's target is sized over the top-K by cheapness, not over the whole held roster. | The residual of PO-1's decomposition, **−₹7.9M** — the largest single item. A rebalancing rule wearing a cheapness rule's name. |

**B is not a new principle.** This repository's own iron rule is *flag, don't veto*, and
`exclude_breaking` is the one place the live screen breaks it.

**D does not repeal the stickiness rule** (2026-08-20, the user's: *"if a company is good, and
getting a good deal, why not add to it?"*). A held name that is still cheap is still in the top-K
and still gets bought. What stops is a held name absorbing this month's money **because it drifted
below a target weight**, with cheapness playing no part in the decision.

## 3. What is deliberately NOT changed, and why

- **No weakness tilt.** `WC-1` found deep-drawdown money beats the fund by a median 30% — and that
  the effect is confined to `deep`, 11 of 177 months from ~7 episodes. Acting on it means holding
  cash back on ordinary days to have more on deep days, **which no experiment here has measured**.
  PO-2's +9.1% is a *fully invested* result. Building the tilt on WC-1 alone would be adopting a
  result as an expected value after seeing it — the thing this project has already done twice.
- **The optimizer and sector allocator stay exactly as they are.** Neither PO-2 nor WC-1 exercises
  `alloc/`. They are unmeasured, and unmeasured is not a licence to change them either way.
- **The 30% sector cap stays.** It is a risk limit, not a return bet. PO-2 ran without it and that
  is a reason to distrust PO-2's magnitude, not a reason to remove the cap.
- **Nothing auto-trades.** Unchanged and unchangeable.

## 4. The honest case against this change

Stated now, before the numbers, so it cannot be quietly dropped later:

- **One path.** Fourteen years of one market. PO-1 and PO-2 are a single history, and the parameters
  were not chosen blind by people who had not seen it.
- **+9.1% over fourteen years is ≈0.6%/yr.** It is not significance and it is not permission.
- **This is selection on a backtest.** Four changes each chosen because a replay liked them is four
  degrees of freedom spent on one dataset. That is exactly how overfitting looks from the inside.
- **Turning off exits raises drawdown.** The backtested worst fall is already **−47.5%** against the
  index's −36.3%, and removing the exit rule can only make the trough deeper, not shallower. This
  buys return with pain the user has never experienced. **Nobody has watched this system fall.**
- **B removes the one filter that refuses visibly broken companies.** A name in §4.7 breakdown
  sometimes breaks down because it is genuinely impaired, and averaged over fourteen years the
  survivors paid for the casualties. That average is not a promise about any one name.

## 5. The test this must pass before it ships

**Re-run PO-1 unchanged — the same harness, through the real `runner.step` — with the new policy.**
Registered before it runs:

| Result | What follows |
|---|---|
| Terminal materially above ₹12.33M and the mechanism attributable line by line | The change does what PO-2 says it does. Ship it. |
| Terminal barely moves | **The change is not the change I think it is.** Something else dominates the live path and PO-2's decomposition was reasoning about a concept, not a call site. Do not ship; find it. |
| Terminal falls | Ship nothing. Report it. |

**This is rule 4 — test the caller, not the function.** PO-2 measured a hand-written loop. The thing
that must improve is `runner.step`, which is what actually runs.

**Passing this test authorizes nothing.** It confirms the edit reached the code path it was aimed at.
It is not evidence the policy works, and this file may never be cited as such.

## 6. The real-money screen changes too, and that is the point

`SYSTEM` and the user's buy screen share one deploy path. These changes reach **the basket he is
handed in Kite**: fewer names (8, not 15), names the breakdown test dislikes now *appear marked*
instead of vanishing, and the month's money goes to the cheapest rather than the most underweight.

He still places every order himself. But he must be told this before the 14th, not discover it.

## 7. What would make this wrong

- If `SYSTEM` beats `BASELINE_EW` over twelve months, **that is one observation** and the matched
  null says it is consistent with chance. It does not validate PL-1.
- If it loses, PL-1 is not rescued by re-running PO-1 with different switches until it looks better.
  **That is the specific thing this registration exists to forbid.**

## 8. Recorded outcomes

*(Append only. Each line dated. Nothing above may be edited after the window opens 2026-09-14.)*

- **2026-09-12** — registered. No code written. PO-1 under the new policy has not been run.

- **2026-09-12, all four built, then §5 ran and REFUSED TWO OF THEM.** The first replay of the
  four-change policy came back at **₹15,273,237** against the ₹20,023,958 the same harness scores
  with the exits merely switched off — a fall, which is §5's third row: ship nothing.

- **2026-09-12, the ablation, one switch at a time.** All rows with `use_exits=False`, so the exits
  are not confounding anything. **Row one is the harness check and it reproduced ₹20,023,958 to the
  rupee**, which is the only reason the rest of the table may be read at all:

  | Configuration | Terminal | vs old | vs fund |
  |---|---:|---:|---:|
  | OLD settings — *harness check* | ₹20,023,958 | — | −27.3% |
  | **C** only — basket 15 → 8 | ₹20,138,663 | **+0.6%** | −26.9% |
  | **B** only — breakdown flagged, not filtered | ₹15,380,523 | **−23.2%** | −44.2% |
  | **D** only — buy cheapest, not most underweight | ₹19,919,119 | **−0.5%** | −27.7% |
  | all three | ₹15,273,237 | −23.7% | −44.6% |

  **B is the entire damage** and the other two are noise.

- **2026-09-12, why B reversed sign, which is the finding worth keeping.** `PO-2` measured the
  breakdown filter *costing* 8 points (+9.1% → +1.1%). Through `runner.step` it is worth **+23.2%**.
  Both measurements are honest and they were not measuring the same switch.

  `universe` is screened **before** the roster is chosen, so `exclude_breaking` is not only a
  buy-list filter — **it is the only thing that evicts a collapsing holding**, which this repo
  already asserts in `test_a_holding_that_breaks_down_loses_its_slot`. With change A the exits are
  off and nothing sells. With B as well, a name that breaks down keeps its slot and is topped up
  all the way down — and "cheapest" means "fallen furthest", so next month's money is aimed at it
  again. PO-2's loop could not see this: it held no roster and re-picked from scratch each month.

  **Rule 1, again: a fix reasoned about as a concept and applied at one call site.** The
  decomposition was real; the thing it decomposed was not the program that runs.

- **2026-09-12, what ships: A and C. B is reverted, D stands down.**

  | | Change | Verdict |
  |---|---|---|
  | **A** | §4.7 exits OFF | **ships** — ₹13,191,363 → ₹20,138,663, +52.7% |
  | **C** | basket 15 → 8 | **ships** — +0.6%, and it ends a split-brain: `SYSTEM` read the frozen config's 15 while the user's own screen read the mandate's 4, so the book built to replicate what he does had never used his basket size |
  | **B** | breakdown as a flag | **REJECTED**, −23.2%. The iron rule *flag, don't veto* loses here to the fact that the veto is also the eviction |
  | **D** | buy cheapest, not underweight | **not shipped**, −0.5%. Implemented, tested and off: a change that buys nothing measurable is risk without evidence |

  Confirming replay of exactly what ships: **₹20,138,663**, CAGR **+5.76%**, tax **₹53,924**,
  worst fall **−37.7%**. Against the registered PO-1 headline of ₹12,333,754 that is **+63%**.

- **2026-09-12, and it still loses to both baselines. This is the number that matters.**
  ₹20,138,663 against `BASELINE_EW`'s ₹27,549,986 is **−26.9%**, and against NIFTYBEES's
  ₹21,799,934 it is **−7.6%**. **The best configuration measurable through the live code path
  still loses to buying the index and doing nothing.** PL-1 makes a losing policy lose less. It
  does not make it a winning one, and nothing here may be quoted as if it did.

  PO-2's +9.1% is **not reachable through this code path at any setting of these three switches.**
  The ~36-point gap between PO-2's loop and this replay is in the sizing machinery neither PL-1 nor
  PO-2 varied — target-weight shortfall sizing, the sector cap, the roster. That is the next
  experiment, and it is not this one.

- **2026-09-12, one warning in §4 was overstated.** §4 said removing the exits buys return with a
  deeper trough. Measured: **−37.7% against NIFTYBEES's −35.5%** — about two points, not the
  collapse implied. The −47.5% figure in `CLAUDE.md` is from the frozen backtest on a different
  universe and does not transfer. Still: **nobody has watched this system fall.**
