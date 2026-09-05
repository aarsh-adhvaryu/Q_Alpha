# Pre-registration — Evidence adapter v1: the NSE regulatory-indicator file

**Frozen 2026-09-05, BEFORE the `REG_IND` file was downloaded or parsed.**
Written first on purpose. This project has twice adopted a result as the expected value after
seeing it (`shrink` selected on the holdout; `live/valuation.py` built for VBL and never tested
against VBL). Writing the answer down first is the only thing that stops a third instance.

---

## 1. The claim under test

> NSE's daily regulatory-indicator file (`REG_INDDDMMYY.csv`, per circular NSE/SURV/64402) carries
> the cautionary indicators the exchange itself publishes — including the P/E > 50 caution that
> Zerodha surfaced on VBL — and can therefore serve as a deterministic, primary-source pre-trade
> evidence feed.

**This is falsifiable and may fail.** See §5.

## 2. Scope of v1 — stated so that silence is not mistaken for approval

The adapter evaluates **only** dimensions carried by `REG_IND` and the NSE surveillance
(ASM/GSM) lists. Everything else is reported `NOT_COVERED`, never `UNKNOWN` and never
`HUMAN_REQUIRED`. Explicitly **not covered in v1**: fundamentals, earnings quality, debt, cash
flow, promoter pledges, related-party transactions, auditor changes, corporate announcements.

## 3. The five states

| State | Meaning | Effect on a candidate |
|---|---|---|
| `PASS` | Every required feed was fresh and no indicator is active | screen may consider it |
| `WATCH` | An advisory indicator is active | `HUMAN_REQUIRED`; never an automatic buy |
| `BLOCK` | A hard regulatory condition is active | deterministic exclusion |
| `UNKNOWN` | A **required** feed failed, or is staler than tolerance | `HUMAN_REQUIRED` |
| `NOT_COVERED` | This version does not evaluate that dimension | reported, never blocking |

`UNKNOWN` and `NOT_COVERED` are distinct and must never collapse into each other. `UNKNOWN` means
we should know and do not. `NOT_COVERED` means we never claimed to.

## 4. Classification rules — fixed before parsing

- **BLOCK** — any of: ASM Stage II or above · GSM Stage 2 or above · trade-to-trade (T2T/BE)
  surveillance · suspension · an active insolvency (IRP) listing.
- **WATCH** — any of: the P/E-above-50 cautionary indicator · ASM Stage I · GSM Stage 1 · any other
  cautionary message in `REG_IND` not listed as BLOCK above.
- **PASS** — file fetched, security present in the day's universe, no indicator active.
- **UNKNOWN** — file unreachable, or dated more than 4 calendar days before the decision date.
- **NOT_COVERED** — every dimension in §2's exclusion list.

**A caution is a warning, not a disqualifier.** The exchange mandates a pop-up, not a prohibition.
Blocking a trade on a figure that contradicts the one the user's own broker displays is worse than
flagging it. This is a decision, recorded before the data was seen, and it is the reason VBL's
expected outcome below is `WATCH` and not `BLOCK`.

## 5. Expected fixture outcomes — FROZEN

| # | Fixture | Expected |
|---|---|---|
| 1 | **VBL on the real-money purchase date (2026-08-27)** | **`WATCH`** |
| 2 | A security at ASM Stage II or above on that date | `BLOCK` |
| 3 | A security with no active indicator on that date | `PASS` |
| 4 | `REG_IND` unreachable, or stale > 4 days | `UNKNOWN` |
| 5 | Any dimension in §2's exclusion list | `NOT_COVERED` |

Fixtures 2 and 3 are instantiated by applying the §4 rules mechanically to the downloaded file.
The **rules** precede the instances; the instances are not chosen to make the test pass.

### The pre-registered falsifier

**If VBL carries no active indicator in `REG_IND` on 2026-08-27, fixture 1 has failed.**

That outcome is to be recorded as a negative and published, not explained away, not patched by
widening the rule until VBL appears. It would mean this adapter does not cover the case that
motivated it — the same failure as `live/valuation.py`, which was built for VBL, does not catch
VBL, and is wired to nothing.

It would **not** mean the evidence spine is worthless. Insolvency, pledges, defaults, listing
non-compliance, surveillance stage and corporate filings remain valuable and remain unbuilt. It
would mean this *adapter*, or this *date*, or this *source*, is the wrong one, and the next step is
to find which feed does carry the caution rather than to assume one does.

## 6. Provenance requirements

Every fetch stores, before any parsing: the unmodified original bytes, the retrieval timestamp
(UTC), the source URL, the HTTP status, and the SHA-256 of the raw file. An assessment that cannot
name the document hash it was derived from is not evidence and must read `UNKNOWN`.

---

## 7. Outcome — recorded 2026-09-05, after the fetch

**§1–§6 above are unchanged. Nothing in the prediction was edited after the data was seen.**

### The transport works

| Item | Result |
|---|---|
| Discovery | `https://www.nseindia.com/api/daily-reports?key=CM` lists the file |
| Location | `https://nsearchives.nseindia.com/content/cm/REG1_INDDDMMYY.csv` |
| Access | plain GET with a browser user-agent; no session, no cookie jar |
| Size | ~600 KB/day, 3,140 securities, 60 indicator columns |
| History | fetched back to 2025-07 without difficulty |

**One correction to the circular's naming.** `REG_IND` and `REG1_IND` are both published. The P/E
column exists **only in `REG1_IND`**; `REG_IND` carries 28 columns and none of them is the P/E
caution. The adapter reads `REG1_IND`.

### Fixture 1 — FAILED

| | |
|---|---|
| Predicted | `WATCH` |
| Actual | **`PASS`** |

VBL's `Scrip PE is greater than 50 (4 trailing quarters)` column reads `100`, meaning clear, on
2026-08-27. It is also clear on 2026-09-04, the day the twin bought 36 more shares.

**The rule was not widened afterwards to make VBL appear.** The failure is recorded in
`tests/test_evidence.py::test_fixture_1_vbl_reads_pass_not_the_predicted_watch`, which asserts the
actual value and names the failed prediction in its docstring.

### Why the failure is informative rather than fatal

The indicator **does** fire on VBL, just not on the purchase date. Sampling the mid-month file:

| Period | P/E > 50 caution on VBL |
|---|---|
| 2025-07 → 2025-12 | ACTIVE |
| 2026-02 → 2026-04 | clear |
| 2026-05 → 2026-06 | ACTIVE |
| 2026-07 → 2026-08 | clear |

So the adapter covers the case. The caution had lapsed roughly two months before the money went in,
which is consistent with earnings having grown while the price fell — a de-rating from an expensive
level rather than a business deteriorating. That is precisely the distinction the price-only screen
cannot draw, and it is visible here.

### What this means for the documented premise

`CLAUDE.md` and `PLAN_SYSTEM.md` both state that Q-Alpha would have encouraged a trade on which
*"Kite's own nudge said don't."* On 2026-08-27 the exchange was **not** cautioning on VBL. Either
the nudge was seen earlier, in the 2026-05/06 window when the caution was live, or it was a
different message. **This needs the user's recollection before either document is corrected.** It is
flagged, not rewritten.

### The adapter is not blind to the VBL class of problem

On 2026-08-27, **532 of 3,140** securities carry the P/E caution. Five of them are names Q-Alpha has
bought or shortlisted:

`ADANIENSOL` · `DMART` · `JIOFIN` · `MAXHEALTH` · `SHREECEM`

**`JIOFIN` is in the basket the live screen recommends today** and reads `WATCH`. So the first
non-price input the system has ever had produces a live, actionable flag on the current
recommendation, on its first run.

### Fixtures 2–5

| # | Fixture | Expected | Actual |
|---|---|---|---|
| 2 | `BLISSGVS`, long-term ASM stage 4 | `BLOCK` | `BLOCK` |
| 3 | `20MICRONS`, no active indicator | `PASS` | `PASS` |
| 4 | file absent, and file stale > 4 days | `UNKNOWN` | `UNKNOWN` |
| 5 | seven unbuilt dimensions | `NOT_COVERED` | `NOT_COVERED` |

Fixtures 2 and 3 were instantiated by applying the §4 rules mechanically to the file. The rules
preceded the instances.
