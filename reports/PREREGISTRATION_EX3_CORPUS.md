# Pre-registration — EX-3: the historical filing corpus, read by one reader

**Registered 2026-09-11, before the first EX-3 document was read.** Nothing in this file may be
edited after the backfill starts; corrections go in a dated section at the bottom.

This registers a **corpus build**, not a predictive experiment. It says what will be read, by what,
and — more importantly — what may and may not be claimed from the result. The predictive question
(`CLAUDE.md` → Open work, item 4) is a separate experiment and needs its own registration before
anybody looks at a return.

---

## 1. Why a new version label for a prompt that did not change

EX-3's prompt, parser, verification rule and event vocabulary are **EX-2's, unchanged.** The label
moved anyway, and that is the substantive claim here:

> **A version means "these instructions, read by this model". Not the instructions alone.**

The reason is already on file in this repo at a smaller scale. `CLAUDE.md` records that the same
snippet is labelled differently in different batches *by one model at temperature zero*, because the
batch is part of the prompt — recorded as a limit of the method rather than re-prompted away. Two
different models is that same effect with a larger coefficient and no reason to believe it is
smaller.

Until today the corpus was being read by `qwen3-8b-32k` on the user's GPU, at roughly 53 seconds a
document. Finishing the 365-day window for the fifteen names in scope at that rate needed about
**eighty-four evening runs**. Moving to a cloud reader collapses that, but a corpus half-read by one
model and half by another is not one instrument, and an event study over it would carry that
confound before producing its first number.

So the reader is pinned into the label and **enforced in code, not by discipline**:

| Gate | File | What it now requires |
|---|---|---|
| Has this name been read before? | `scripts/evidence.py::_seen_before` | current version **and** `reader == corpus_reader()` |
| Has this document been read before? | `scripts/evidence.py::_already_extracted` | receipt carries the reader |
| Does the buy screen call this name read? | `live/flags.py::filings_read` | coverage row carries the reader |
| May this event raise a flag? | `live/pretrade.py` | event's `model` is the corpus reader |
| May this event be shown to the user? | `live/flags.py::recent_concerns` | same |

**A row with no reader recorded does not match.** Every row written before today predates the field
and was produced by whatever was configured that evening — which is exactly the mixture this
prevents. Absent is unknown; unknown is not the reader.

### What this costs, stated plainly

Every EX-1 and EX-2 row on file stops counting toward coverage. That is **~1,135 documents of
already-completed reading discarded**, and it is the price of the corpus being one thing. The rows
themselves are never deleted — they stay on file as a record, and cannot act.

---

## 2. The reader, and how it gets chosen

**Frozen before the backfill:** `CORPUS_READER_DEFAULT = "claude-haiku-4-5"`.

It is not yet frozen *as the choice*. The choice is made by measurement, and the measurement is
registered here before it is run:

```bash
uv run python scripts/evidence.py compare-readers \
    --readers claude-haiku-4-5,claude-sonnet-5 --sample 40 --workers 8
```

Both readers get **the same archived bytes**. The command writes nothing — no coverage row, no
receipt, no event reaches the log — because a comparison is not a reading of the corpus.

**Decision rule, fixed in advance:**

1. If either reader discards materially more quotes as *not present in the document* (the one
   unambiguous error either can make, checked mechanically against the archived bytes), it loses.
2. Otherwise, if agreement on `(document, event type, materiality)` is **high**, the readers are
   substitutable on this task and the cheaper one wins — that is `claude-haiku-4-5`.
3. If agreement is **low**, they are not substitutable, and the choice is a real one: take
   `claude-sonnet-5`, on the reasoning that the disagreements will be dominated by the harder
   documents and that a corpus is built once.
4. Speed does not enter the rule. At eight concurrent calls both finish the corpus inside one
   session, so latency is not the binding constraint and must not be allowed to pick the reader.

Whatever wins is recorded here, in a dated line, **before** the backfill runs. Setting
`QALPHA_CORPUS_READER` names the corpus in every row it writes, so a run under the loser cannot be
mistaken for a run under the winner.

---

## 3. What is being built

* **Scope:** the 365-day announcement window for every name in the screen's basket plus every held
  name — 15 names, ~2,100 documents, ~5,500 chunks, ~2,000 model calls, ~13.5M input tokens as
  measured from the archive on 2026-09-11.
* **Command:** `uv run python scripts/evidence.py backfill --workers 8`
* **Caps lifted, and only here:** 2,000 documents per name instead of 25, four hours instead of
  fifteen minutes, eight concurrent calls instead of one. The nightly run keeps its own caps.
* **Document text leaves this machine.** `prefer_local=False` is passed at exactly one call site,
  and the run prints that it did.

### The one property that makes concurrency admissible

Concurrency must change the wall clock and **nothing else**. Outcomes are accounted in batch order
regardless of completion order, so the events, the discard count, the transcript and every token
counter are identical at one worker and at eight. This is asserted directly
(`tests/test_ex3_corpus.py::test_eight_workers_and_one_worker_produce_identical_output`), including
through the truncation-retry path. **If that test ever fails, the backfill is not a faster reading —
it is a second instrument, and this registration is void.**

---

## 4. What may be claimed from the result, and what may not

**May be claimed:**

- That the filings in the window were read, by a named reader, under named instructions, with every
  quote checked against archived bytes.
- Counts and rates over those events, labelled as what they are.

**May NOT be claimed, and this is the point of registering it:**

- **Nothing about returns.** This corpus is an input to a future experiment, not a result. Reading
  more filings does not make the screen better and is not evidence that it is.
- **Nothing about the twelve-month clock.** `CLAUDE.md` is explicit that the AI and evidence layers
  version independently, precisely so that improving them does not restart the experiment.
  `EVALUATION_START`, `CORE_EVALUATION_START`, the screen's parameters and `BASELINE_EW` are
  untouched. `AUTHORIZING_PAIR` remains `None` and every gate criterion remains ⚪ CANNOT ASSESS.
- **Nothing predictive.** The AI still reads and reports; deterministic policy still decides. `AI-V2`
  is a rule over verified events, not a predictor. Whether events plus price context beat the
  price-only screen is question 4 in the open-work list, it is unregistered, and no part of this
  corpus build may be presented as progress on it.
- **Nothing about survivorship.** The universe problem (`NEXT_50_CHANGES`, open-work item 1) is
  untouched by this and remains worth ~3.8 points a year — more than the entire measured signal.

### The negative that will be published either way

If the comparison finds **low agreement between the two readers**, that is a finding about the
method and it gets written up whichever reader is chosen: it would mean the event stream this system
produces is partly a property of which model read the filing, and any later event study has to carry
that as a stated limitation rather than discover it afterwards.

---

## 5. Recorded outcomes

*(Append only. Each line dated. Nothing above this section may be edited.)*

- **2026-09-11** — registered. Comparison not yet run; `CORPUS_READER_DEFAULT` stands at
  `claude-haiku-4-5` pending it. Backfill not yet run.

- **2026-09-11, later** — comparison run on 150 archived filings across 22 names. **Rule 1 fired and
  decided it: `claude-sonnet-5` is the corpus reader.** Haiku discarded 86 of 145 claims as not in
  the document (59%) against Sonnet's 44 of 153 (29%), and returned 59 verified events to Sonnet's
  109 — half the findings at twice the miss rate. Rule 3 agrees independently: agreement between the
  two is **22%**, stable across a second run at 40 documents (24%), so they are not substitutable.
  `CORPUS_READER_DEFAULT` set to `claude-sonnet-5`. Full numbers:
  [`READER_COMPARISON_EX3.md`](READER_COMPARISON_EX3.md).

- **2026-09-11, the negative this registration promised to publish either way** — 22% agreement means
  **the reader substantially determines the event stream**. Any event study over this corpus carries
  that as a stated limitation from the start rather than discovering it afterwards.

- **2026-09-11, a limitation found while checking the discard rate** — the 29% of Sonnet's quotes that
  fail verification are **not fabrications**. Seventy documents were re-read and all eight failures
  were true statements that are not contiguous verbatim spans: clauses joined across a sentence, a
  summary composed from real fragments, and one case where the PDF text extraction had split a word
  and the *archive* was wrong rather than the model. The guard is working as designed; its cost is
  **recall**, roughly 30% of genuine findings, biased against documents with poor text extraction.
  **The corpus will under-count events, systematically and non-randomly.** Absence in it is not
  evidence of no event. Relaxing the verification rule or tightening the prompt would both be
  **EX-4** and need their own registration; neither is applied here, because a label that spans two
  rules has already cost this project four days of run 2.
