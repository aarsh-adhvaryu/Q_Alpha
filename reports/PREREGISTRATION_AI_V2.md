# Pre-registration — `AI-V2`: the veto becomes policy over verified events

**Frozen 2026-09-11, before the first `AI-V2` verdict was recorded.**

Amends the treatment of **run 2** (`TWIN_FULL` vs `BASELINE_EW`), which is already a
non-authorising operational rehearsal. It does not touch `CORE_V1`, which has `use_ai=False` and
never consults a verdict — that separation is why this change is allowed to happen at all.

---

## 1. What is being replaced, and why

`PR-8c` asks a web-searching model *should this name be kept or dropped*, and requires a DROP to
cite a URL on a primary host. Two things are wrong with that, and only one of them was patched:

- **The judgement is the model's.** Nothing checks that the cited page says what the verdict claims.
  The first real veto (2026-09-03, ADANIENSOL) cited `stockanalysis.com/quote/nse/ADANIENSOL/` — a
  stock *quote page*, evidencing nothing. `PR-8c` fixed the symptom: it demoted anything off a
  primary host. A rule about where a link points is not a rule about what it says.
- **Nothing was archived.** A year from now the page behind that URL may be gone, changed, or
  paywalled, and the verdict becomes unfalsifiable. Re-opening it is the entire purpose of requiring
  a citation.

Both were solved elsewhere, for a different surface: `extraction.py` (EX-2) and `news.py` (NEWS-1)
fetch the document, hash it, keep it, and discard any claim whose verbatim quote is not in the
stored bytes. `AI-V2` is the veto asked as a rule over those rows.

## 2. The treatment — frozen

| Parameter | Value |
|---|---|
| Question asked of a model | **none.** No call, no key, no search |
| Input | `data/evidence/events.jsonl` and `data/evidence/news_events.jsonl`, at each row's current revision |
| DROP condition | a **filing** event that is `verified`, at `EXTRACTION_VERSION`, `materiality == "high"`, and of a veto-shaped type |
| Veto-shaped types | `regulatory_action` · `insolvency` · `auditor_change` · `credit_rating` · `promoter_pledge` |
| Window | 30 days before the decision date |
| Headline events | **never drop.** A matching one is recorded as a demoted *lead*, exactly as `PR-8c` demotes a secondary source |
| Absence | keep — unchanged, and the reason every failure path degrades `TWIN_FULL` to precisely `TWIN_NO_AI` |
| Sizing | none. It can only remove, never add and never resize — the three PR-8 guards stand |
| Books affected | `TWIN_FULL` only |

**Why those five types and not more.** Each is a fact about the company's *standing* rather than
about its business doing badly: a regulator or court acting, insolvency, an auditor leaving, a
downgrade, promoters pledging more. Results, guidance, contract wins and operational news are
excluded because the screen already prices them — and because `EX-1` proved what happens when the
rubric is loose: 77 of 193 events came back `high` and **good news rejected candidates**.

**Why a headline cannot drop.** A snippet read by a local 8B model is secondary evidence: NEWS-1's
own first run showed the same headline labelled differently in different batches. It can put a name
in front of a person; it cannot remove one. Widening this is `AI-V2.1`, and needs its own
registration and its own falsifier.

## 3. What this does NOT change

- `CORE_V1`'s policy, parameters, clock or benchmark. It has `use_ai=False`.
- `EVALUATION_START`, `CORE_EVALUATION_START`, the screen, or `BASELINE_EW`'s construction.
- The dropped name is **not** replaced and survivors are **not** rescaled. So
  `TWIN_FULL − TWIN_NO_AI` still measures *the veto plus the cash drag it causes*, not selection
  skill alone, and the undeployed cash is recorded on every attempt row so the two can be separated
  afterwards rather than argued about.
- Real money. Nothing in this path can reach the account; the user places every order.

## 4. The record

Every run appends to `data/twin/ai_verdicts.jsonl` with `prompt_version = "AI-V2"` and
`model = "rule:AI-V2 over verified EX-2 filings (news demoted to leads)"` — the field names what
produced the call, and it is not a chat model. A day on which the rule matched nothing is recorded
too, as it was under PR-8: *the rule found nothing* and *the rule was never applied* must not both
look like silence.

`PR-8c` rows stay on file and cannot act, the same way `EX-1` rows do. One label, one rule.

## 5. What would falsify it

**(a) It never fires.** If over twelve months no candidate ever matches, `AI-V2` is *correct and
inert*: the screen's names simply do not carry these events at these thresholds. That is a result,
it is to be published as one, and it would mean the veto arm of run 2 measures nothing.

**(b) It fires and is wrong.** Every DROP is auditable by construction — the quote, the document
hash and the archived text are all on file. If a hand-audit of the first ten finds any where the
filing does not support the type assigned, the extractor's labels are not fit for a veto and
`AI-V2` is withdrawn rather than tuned.

**(c) It fires and costs money.** `TWIN_FULL − TWIN_NO_AI` is the measurement. It is not expected to
be positive: a veto that avoids a bad name pays, and a veto that holds cash out of a rising market
does not. Twelve months will not settle it either — the same power problem as everything else here —
so this arm is **descriptive**, and it is registered as descriptive rather than discovered to be so
afterwards.

## 6. Status

First recorded `AI-V2` verdict: none yet. `AUTHORIZING_PAIR` remains `None`; nothing here authorizes
anything, and run 2 remains a rehearsal.
