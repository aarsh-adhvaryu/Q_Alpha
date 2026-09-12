# Pre-registration — ES-1: do verified filing events predict anything?

**Registered 2026-09-12, before any return was computed.** The script that answers this
(`scripts/exp_event_study.py`) was written after this file and has not been run. Nothing above
section 6 may be edited once it has.

---

## 1. The question

> **After a verified, high-materiality, veto-shaped filing event, does the name underperform?**

This is the question `AI-V2` already acts on. It drops a name from `SYSTEM`'s basket when such an
event lands, and **nothing has ever tested whether that helps.** The rule is registered as a rule
over verified events, not as a predictor — which is honest, and also means its contribution is
unmeasured.

It is also the reason the corpus was built. A portfolio over twelve months is *one* observation of a
small signal inside large noise; the same information at the event level is many observations, and
significance is reachable in months rather than centuries.

## 2. The statistic

For each event, **abnormal return** over horizon *h*:

```
AR(h) = ln(P_name[t0+h] / P_name[t0]) − ln(P_bench[t0+h] / P_bench[t0])
```

* `t0` = **the first trading day on which the information was actionable** (§3).
* `P_bench` = the **equal-weight** portfolio of the 15 corpus names, rebalanced daily. Not
  NIFTYBEES: the corpus names are large-cap and equal-weighted, and 76% of this system's apparent
  edge over the cap-weighted index is the equal-weight premium. Benchmarking against the index would
  credit the events with a premium they did not create.
* Horizons `h` ∈ **{5, 20, 60}** trading days, fixed now, all three reported. Reporting only the
  one that looks best is the failure mode this file exists to prevent.

**Primary test:** mean AR(20) over high-materiality veto-shaped events is **< 0**.

## 3. t0 is dissemination, not the event date — and this matters

The extractor returns `event_date`: the date the event *refers to*. In this corpus those run from
**2014-08-07 to 2026-11-21** — the second is in the future, because a filing announcing a board
meeting carries that meeting's date. Using it as t0 would measure returns before and after dates the
market had no information on.

So **t0 is the dissemination timestamp** — when the exchange published the filing, which is when the
price could react. And because NSE closes at 15:30 IST, a filing disseminated after the close is
only actionable the **next** trading day; t0 shifts accordingly. Failing to shift would credit the
strategy with a move it could not have traded, which is look-ahead in its purest form.

## 4. The unit of observation, and why the sample is far smaller than it looks

4,776 verified events sounds like a large sample. It is not:

| | Count |
|---|---:|
| Verified EX-3 events | 4,776 |
| Distinct (name, date) pairs | **734** |
| Distinct names | **15** |

Events cluster: one filing can yield several, one day can carry several filings, and **VEDL alone
accounts for 269 of the veto-shaped events.** Treating 4,776 as independent would overstate
significance by roughly the square root of the clustering — the classic way an event study
manufactures a result.

So:

* **One observation per (name, t0).** Multiple events on one name-day collapse to one.
* **Two tests, both reported.** A pooled t-test with standard errors **clustered by name**, and a
  per-name aggregate test across the 15 names (14 df). The second is weak by construction and is
  reported anyway, because it is the one that does not assume away the dependence.
* **N is printed beside every number**, at all three levels.

## 5. What this study CANNOT settle, stated before it runs

**The corpus is survivorship-contaminated.** All 15 names are in today's basket or holdings —
selected because they are here now. `CLAUDE.md` records survivorship on the live universe as worth
**~3.8 points a year**, more than the entire signal being looked for. Every number this produces
carries that bias, and it biases *toward* making the names look good after bad news, because the
names that did not recover are not in the sample.

**Therefore ES-1 is a first read on method and direction, not evidence.** It can:

- show whether the pipeline end-to-end produces a measurable number at all;
- show the *sign* and rough magnitude, as a hypothesis;
- show whether the clustering leaves any usable power.

It cannot support a change to how real money is deployed, and it cannot license `AI-V2` to keep
dropping names. A clean answer needs a point-in-time universe including names that left the index —
which is open-work item 1 (`NEXT_50_CHANGES`), still an empty list.

**A null result is the expected outcome and gets published either way.** At this sample size, the
absence of a detectable effect is the most likely honest finding, and it is not a reason to widen
the window, change the horizon, or switch the benchmark afterwards.

## 6. Decision rule, fixed in advance

| Finding | What follows |
|---|---|
| Mean AR(20) < 0, clustered *p* < 0.05, **and** per-name test agrees in sign | `AI-V2`'s drop rule has a first piece of support. Still not licensed for real money; the next step is the point-in-time universe. |
| Interval includes zero (**expected**) | The rule is unsupported. Written up as a negative. Whether `SYSTEM` keeps dropping names becomes the user's explicit choice, made knowing it is unmeasured — not a default that nobody examined. |
| Mean AR(20) > 0 at *p* < 0.05 | The rule is **backwards** — it is dropping names that go on to outperform. `AI-V2` comes out of `SYSTEM` immediately. |

## 7. Recorded outcomes

*(Append only. Each line dated. Nothing above may be edited after the first run.)*

- **2026-09-12** — registered. Script written, not yet run. No return has been computed.

- **2026-09-12, run. NULL — the middle row of the decision table.** Primary test, mean AR(20) after
  a high-materiality veto-shaped event: **−0.62%, t = −0.77** clustered by name (61 name-days, 14
  names); per-name test **t = −0.22**. The interval includes zero at every horizon and on both
  tests. **`AI-V2`'s drop rule is unsupported by this corpus.** Full numbers in
  [`EVENT_STUDY_ES1.md`](EVENT_STUDY_ES1.md).

- **2026-09-12, three things in the detail that the headline hides.**
  1. **The 5-day sign is positive** (+0.68%, t = +1.49; and +0.84%, t = +1.97 across all
     high-materiality days). If anything, names drift *up* just after the events the rule drops them
     for. Not significant, and not a finding — but it is the opposite of the rule's premise, and it
     is the direction a larger sample would have to overturn.
  2. **The 60-day number is an artefact of clustering, and the test caught it.** Pooled it reads
     −3.61% (t = −1.22); averaged within name first it is **−0.09% (t = −0.04)**. The pooled figure
     was VEDL and a handful of names repeating, which is precisely the effect the registration named
     in advance as "the classic way an event study manufactures a result".
  3. **Conditioning adds nothing.** Every event day, unconditionally, gives AR(20) = −0.54%; the
     high-materiality veto-shaped subset gives −0.62%. Selecting on the model's materiality label
     moves the number by 8 basis points on a standard error many times that.

- **2026-09-12, what the sample actually was.** 4,252 verified events collapsed to **463 name-days**,
  and the primary test rests on **61**. That is the number to remember. It is not a failure of the
  corpus — the corpus is 15 names over one year, and 61 conditioning events is what one year of 15
  large caps produces. It is a statement about how much this design can ever resolve.
