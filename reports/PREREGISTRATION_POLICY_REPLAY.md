# Pre-registration — PO-1: replay the policy the money runs, not the ranking

**Registered 2026-09-12, before `scripts/exp_policy_oos.py` was written and before any equity curve
existed.** Nothing above section 7 may be edited once it has run.

---

## 1. The question

> **Does the policy the real money actually runs beat the fund anyone can buy — after costs and
> tax, on a universe that includes the names that died?**

Everything measured here so far has answered a *different* question. `exp_screen_oos.py` says so in
its own docstring: *"Monthly rebalancing is not the live policy. The real book buys with new cash
and holds. This measures the signal, not the strategy."* It reports **+2.65%/yr at k=8 with a
confidence interval that includes zero** — and it re-ranks every month, pays no cost, pays no tax,
and never sells at a loss it has to account for.

The live policy is none of those things. It is buy-and-hold with a monthly allowance, the §4.7
exits, a sector cap, Zerodha's charges and Indian capital-gains tax. Those are different strategies
and **only one of them is being run.**

## 2. The rule under test is the rule itself, not a copy

The replay calls `qalpha.live.runner.step()` — the same function `SYSTEM` calls every day — against
historical `Market` objects. It does not reimplement the screen, the exits, the governor or the
sizing.

This is deliberate and it is the lesson `exp_screen_oos.py` already records: *"testing a copy of the
rule would prove nothing about the rule that runs."* If the replay and the live book ever disagree,
that is a defect in one of them, and it will be visible rather than hidden behind a second
implementation that drifted.

## 3. The universe: survivorship-free, and smaller for it

`data/universes/nifty50_membership_2026.csv` — 85 tickers with dated entries and exits, **36 of
which left the index.** It contains the dead. A name is eligible on a date only if it was in the
index on that date.

**This is not the live universe.** The money runs on `nifty100_watchlist.csv`, a static list of
today's members, whose survivorship is measured at **~3.8%/yr** — more than the entire effect being
looked for. That file cannot be made honest by processing, and the Next-50 change history needed to
build its point-in-time equivalent **is not obtainable**: Wikipedia has no Next-50 change section
and news coverage is fragmentary, so any list assembled from it would have holes, and a hole
silently reintroduces the bias. `scripts/build_nifty100_pit.py` refuses to write for that reason and
that refusal stands.

So the trade is deliberate: **a clean answer on a universe that is not quite the live one, in
preference to a contaminated answer on one that is.** The Nifty-50 PIT universe is a subset of the
live Nifty-100 watchlist, large-cap, and the same screen runs on it unchanged.

## 4. The bar, and the flows

* **`BASELINE_EW`** — the point-in-time **equal-weight** Nifty-50 index, charged **0.41%/yr**, the
  cheapest real expense ratio available (DSP direct). The fund anyone can buy in five minutes.
* **`BASELINE`** — NIFTYBEES, cap-weighted, bought and held. Reported as the floor, **never the
  bar**. 76% of this system's apparent edge over the cap-weighted index *is* the equal-weight
  premium, and that premium is purchasable.
* **Identical flows.** ₹50,000 on the first trading day of each month, to the policy book and to
  both baselines, on the same dates. Same money, same days, only the decisions differ.
* **Costs and tax are charged to the policy book and the fee to the fund.** A gross comparison would
  flatter the side that trades.

## 5. The statistic, fixed now

* **Primary:** terminal wealth of the policy ÷ terminal wealth of `BASELINE_EW`, over the full
  period, expressed as annualised excess return.
* **Reported beside it, always:** max drawdown of each, total tax paid, total cost paid, turnover,
  and the number of §4.7 exits.
* **Sub-periods reported:** each calendar year, so a reader can see whether one regime is carrying
  the whole result. **Not** for selecting a favourable window afterwards — every year is printed.

## 6. What this CANNOT settle, stated before it runs

- **It is not an out-of-sample test of the screen.** The screen's parameters were not chosen blind
  to 2012–2026. This is a **replay of a known configuration**, and its honest claim is "here is what
  this policy would have done", not "here is what an unseen policy did". `CLAUDE.md` already records
  that the headline backtest spent its holdout.
- **One path.** Terminal wealth over one history is a single draw. The confidence interval on 14
  years of one strategy against one benchmark is wide, and a positive result is **not** evidence the
  edge is real — it is a necessary condition, nothing more.
- **It cannot license real money.** Real money is the user's decision, placed by him. Nothing here
  opens a gate, because there is no gate.

## 7. Decision rule, fixed in advance

| Finding | What follows |
|---|---|
| Policy **beats** `BASELINE_EW` net of cost and tax, and does so in a majority of calendar years | The policy has a first piece of support on a clean universe. Next step is the Nifty-100 PIT universe, which needs the Next-50 data that does not currently exist. |
| Policy **does not beat** `BASELINE_EW` | Written up as a negative, prominently. The honest conclusion would be that the levers already proven here — cost, tax, staying invested — are what this system is worth, and that the stock selection is not adding to them. That is a real and useful answer. |
| Policy beats on gross but **loses after cost and tax** | The most likely failure and the most important one to publish: it would mean the signal is real and unharvestable, which is the single most common way a backtest lies. |

## 8. Recorded outcomes

*(Append only. Each line dated. Nothing above may be edited after the first run.)*

- **2026-09-12** — registered. Script not yet written. No equity curve exists.

- **2026-09-12, run. THE POLICY LOSES, and it loses to both baselines.** Fourteen years, ₹50,000 a
  month, ₹8,850,000 contributed, identical flows to every line:

  | | Terminal | vs contributed | CAGR | Max DD | Tax |
  |---|---:|---:|---:|---:|---:|
  | **POLICY, as configured** | **₹12,333,754** | +39.4% | +2.49% | −41.2% | ₹2,095,762 |
  | `BASELINE_EW` — **the bar** | ₹27,549,986 | +211.3% | +8.04% | −35.8% | ₹0 |
  | `BASELINE` / NIFTYBEES — floor | ₹21,799,934 | +146.3% | +6.33% | −35.5% | ₹0 |
  | *diagnostic:* same policy, exits OFF | ₹20,023,958 | +126.3% | +5.72% | −42.2% | ₹25,777 |

  **Against the bar: −₹15,216,232, or −55% of the fund's terminal wealth.** This is the second row
  of the decision table, and it is unambiguous.

- **2026-09-12, where the loss comes from — two separate failures, not one.**
  1. **The §4.7 exits cost ₹7.7 million.** 5,488 exits and ₹2,095,762 of tax with them on; 0 exits
     and ₹25,777 with them off. The screen buys names that are *down* and the exit sells names that
     are *down* — they fight, and the book churns. This reproduces, on a clean universe and through
     the live code path, what `CLAUDE.md` already lists as proven: **selling to manage risk loses to
     the tax.**
  2. **Even with the exits off it still loses.** ₹20.0M against the fund's ₹27.5M and NIFTYBEES's
     ₹21.8M. Turning off the worst component does not rescue it. **The stock selection is not
     adding to the passive alternative** — it is subtracting from it, on this universe over this
     period.

- **2026-09-12, the harness was wrong twice before it was right, and both were mine.** The first run
  reported a −89.9% drawdown on NIFTYBEES, which never happened: I read the raw benchmark parquet
  instead of `paper._load_benchmark_series()`, which repairs two ₹13.02 prints against a true ~₹129.
  That series paces the deploy, so an unrepaired benchmark does not merely mis-draw a chart — it
  changes what the policy buys. And I passed `rebase_from=None`, so every stock split read as a 50%
  crash and fired a §4.7 exit. Both were failures to reuse what the live system does. Neither
  changed the direction of the result; both would have made the report a lie about its size.

- **2026-09-12, what this does not say.** The policy was replayed on the **point-in-time Nifty-50**,
  not the Nifty-100 the money actually runs on, because the Next-50 change history needed to build
  a point-in-time Nifty-100 is not obtainable and a list with holes silently restores the bias. The
  screen's parameters were not chosen blind to 2012–2026, so this is a replay of a known
  configuration rather than a clean out-of-sample test. And it is one path. None of that rescues
  the result: −55% and −27% are not marginal numbers, and they point the same way in both variants.
