# Pre-registration — WC-1: does buying into weakness actually pay?

**Registered 2026-09-12, before `scripts/exp_weakness_cohorts.py` was written and before any cohort
return existed.** Nothing above section 7 may be edited once it has run.

---

## 1. The question, which is the system's founding claim and has never been tested

> **Money deployed while the market is down — does it eventually beat money deployed on an ordinary
> day? And does it beat the fund bought on the same day?**

The screen is called *deploy into weakness*. `market_weakness` classifies the index's drawdown from
its rolling one-year high as `normal`, `elevated` or `deep`, and the whole design leans on the
premise that **deeper drawdowns are better entry points for fresh capital.** That premise is stated
in `deploy.py`'s own docstring as a historical fact and has never been measured in this repository.

`PO-2` showed the ranking carries signal (+9.1% at top-8, monotone in concentration). This asks the
next question: is the *timing* premise real, or is the edge entirely in the cross-section?

## 2. The unit: a cohort is one month's money

Each month, ₹50,000 buys the top-8 by `cheapness_scores`, equal-weighted, whole shares, Zerodha
costs charged. **Nothing is ever sold** — settled by PO-1 and PO-2, and by the user.

Every month's purchase is tracked as its own **cohort** for the rest of the history. A cohort's
result is what that ₹50,000 is worth today, against **what the same ₹50,000 put into `BASELINE_EW`
on the same day** would be worth today. Same money, same day, only the choice differs.

## 3. The split, fixed now

Cohorts are grouped by `market_weakness(index, purchase_date).level` **as it was on the day the
money went in** — `normal`, `elevated`, `deep`. That classification uses only data up to that day,
so there is no look-ahead in the grouping.

**Reported for each group:** number of cohorts, median and mean multiple on contribution, median and
mean excess over the fund bought the same day, and the share of cohorts that beat the fund.

**Median is the headline, not mean.** Cohorts have wildly different holding periods — 2012 money has
had fourteen years to compound, 2026 money has had weeks — and a mean is dominated by the oldest. The
median is reported alongside the **age-matched** comparison (each cohort against the fund over its
*own* holding period), which is the number that is actually comparable across groups.

## 4. What each outcome means, fixed in advance

| Finding | What follows |
|---|---|
| `deep` and `elevated` cohorts beat `normal` cohorts, **age-matched** | The timing premise is real. Deploying more into drawdowns is worth building, and the current design's instinct is right even though its implementation loses. |
| All three groups are alike | **The edge is entirely cross-sectional.** The ranking works, the timing does not, and `market_weakness` is decoration. The honest response is to deploy steadily and stop pretending the regime call adds anything. |
| `deep` cohorts do **worse** | Buying the dip is costing money on this data, and the screen's founding premise is backwards. |

## 5. The universe, and the answer to "Nifty-50 is a small thing"

**Headline: point-in-time Nifty-50** — 85 tickers, 36 of which left the index. Survivorship-free,
and the only universe in this repository that is.

**Reported beside it, clearly labelled and never as the headline: the static Nifty-100 watchlist** —
the universe the money actually runs on. It is a list of *today's* members, so it is
survivorship-contaminated, measured at **~3.8%/yr**. Running it answers "what does the bigger
universe look like" while the label answers "and why you may not believe it".

**The point-in-time Nifty-100 does not exist and cannot currently be built.** NIFTY 100 = NIFTY 50 +
NIFTY Next 50, and the Next-50 reconstitution history is not obtainable: Wikipedia carries no
Next-50 change section, and news coverage is fragmentary, so any list assembled from it would have
holes — and a hole silently restores the bias it was built to remove.
`scripts/build_nifty100_pit.py` refuses to write for that reason and the refusal stands.

## 6. What this cannot settle

- **One path.** Fourteen years of one market. 176 cohorts, heavily overlapping in what they hold.
- **India, 2012–2026**, which contained no 2008-style event. The deepest drawdown in the sample is
  the 2020 COVID fall, and one crash is not a sample of crashes.
- **Parameters not chosen blind.** The thresholds inside `market_weakness` were set before this test
  and not by it, but they were set by people who had seen this history.
- **It cannot license real money.** Nothing here opens a gate; there is no gate.

## 7. Recorded outcomes

*(Append only. Each line dated. Nothing above may be edited after the first run.)*

- **2026-09-12** — registered. Script not yet written. No cohort return exists.

- **2026-09-12, run. THE TIMING PREMISE IS REAL** — first row of §4's table. Point-in-time Nifty-50,
  177 cohorts, each against the fund bought the same day (age-matched):

  | Market on the day money went in | Cohorts | Median multiple | Median vs fund | Beat the fund |
  |---|---:|---:|---:|---:|
  | **deep** | 11 | ×5.16 | **+30.3%** | 7/11 (64%) |
  | **elevated** | 60 | ×3.17 | +2.0% | 30/60 (50%) |
  | **normal** | 106 | ×3.11 | **−3.1%** | 44/106 (42%) |

  **Monotone on all three measures** — multiple, excess over the fund, and hit rate. Money deployed
  into deep drawdowns beat the fund by a median 30%; money deployed on an ordinary day *lost* to it.

- **2026-09-12, and the useful part is the shape, not the headline.** The effect lives almost
  entirely in `deep`. `elevated` — 34% of all months — returns **+2.0%**, which is nothing, and its
  hit rate is a coin toss. `normal` loses. So "lean into weakness" as currently practised is not
  what pays: **being opportunistic in genuinely deep drawdowns is, and those are 11 of 177 months —
  6% of the time.** A rule that tilts on `elevated` is tilting on noise.

- **2026-09-12, how thin the deep sample really is.** Eleven cohorts, but from about **seven
  distinct episodes**: 2012-06, 2015-09, 2016-02/03, COVID (2020-04 through 07, four of the eleven),
  2022-07, 2025-03, 2026-04. COVID alone is a third of the group. Seven episodes is not a sample of
  crashes, and India 2012–2026 contained no 2008-style event. The two most recent cohorts have had
  months rather than years to compound, so they drag the median **down** — the result is not an
  artefact of old money having longer to run.

- **2026-09-12, the bigger universe agrees and must not be believed.** The static Nifty-100 — the
  list the money actually runs on — gives deep +82.2% (9/9), elevated +15.3% (76%), normal +2.4%
  (53%). Same monotone shape, roughly triple the magnitude. **It is contaminated asymmetrically and
  in exactly the direction that flatters this strategy:** survivorship keeps the beaten-down names
  that *recovered* and drops the ones that did not, and the strategy's whole method is buying
  beaten-down names. A 100% hit rate on deep cohorts is the tell. The direction replicating across
  both universes is worth something; the magnitude in the second table is worth nothing.
