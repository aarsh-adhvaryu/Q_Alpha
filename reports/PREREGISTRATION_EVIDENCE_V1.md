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
