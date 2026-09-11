# EX-4 rejected: telling the model harder to quote verbatim made it worse

**2026-09-11.** A published negative, per the standing rule. The change was built, measured against
its own baseline on identical documents, and reverted. The corpus is built on **EX-3**.

## What was proposed and why

EX-3's discard rate — quotes the model reports that are not found in the archived document — runs
25–29% for `claude-sonnet-5`. A separate study of 120 documents established that these are **not
fabrications**: every failing passage was a true statement that simply was not a contiguous verbatim
span. The model normalised a currency symbol, merged two column headings into `reaffirmed/assigned`,
inserted `today`, wrote `The Parent Company` for a company's actual name.

Two repairs were possible. A graded "close enough" verification threshold was built first and
**rejected on its own evidence before costing anything**: shingle-coverage of the failing passages
ran continuously from 0.59 to 0.96 with no gap to cut at, so any threshold would have been a tuned
parameter, and what it would have bought is paraphrase admitted as quotation — the one thing the
guard exists to refuse.

That left the prompt. EX-4 restated the quote rule: copy and paste rather than retype, one unbroken
run from a single document, change nothing inside it, with the four observed mistakes named
explicitly, and an instruction to emit no line at all rather than a quote that would not check out.

## The measurement

Paired. **The same 220 archived filings — 3,164,235 characters, confirmed identical in both runs —
the same reader, the same archive state, one prompt changed and nothing else.**

| | Events kept | Discarded | Claims | **Discard rate** | Calls | Input | Output |
|---|---:|---:|---:|---:|---:|---:|---:|
| **EX-3** | **200** | 67 | 267 | **25.1%** | 159 | 1,777,350 | 128,138 |
| **EX-4** | 155 | 83 | 238 | **34.9%** | 162 | 1,866,881 | 146,496 |

**EX-4 lost on both axes**: 23% fewer events kept, and a discard rate ten points *higher* than the
rule it was written to fix.

## The part that should have been caught earlier

An initial run on **120** documents (579,064 characters) showed the opposite:

| 120 documents | Events kept | Discarded | Discard rate |
|---|---:|---:|---:|
| EX-3 | 36 | 11 | 23.4% |
| EX-4 | 37 | 6 | **14.0%** |

That read as a 40% improvement and it was reported internally as one. It was a smaller, shallower
sample — round-robin across tickers reaches only each name's first few filings, which are short and
formulaic. The 220-document sample reaches deeper into each archive, into annual reports and rating
letters, and reverses the sign.

**A sample small enough to be cheap was large enough to be confidently wrong.** That is the finding
worth keeping from this exercise, more than the prompt result itself.

## Why it might have failed — hypotheses, untested

1. **Naming an error can induce it.** EX-4 quoted four concrete malformed strings as things not to
   do. Putting `reaffirmed/assigned` and `The Parent Company` in the prompt may have made them more
   available, not less.
2. **One instruction traded recall away deliberately**: *"If you cannot find an unbroken run that
   carries the fact, emit NO line for it."* That explains 155 events against 200. It does **not**
   explain the discard rate rising, so it cannot be the whole mechanism.
3. **Instruction bloat.** The quote rules went from four lines to fourteen, inside a prompt that also
   carries the materiality rubric and up to 24,000 characters of filing.

None of these was tested. A milder variant — the "one unbroken run" sentence without the list of
malformed examples — is a reasonable next idea and is **not** being tried on this sample. Picking
the best of several variants measured on the same documents is fitting to the test set, which is the
failure mode this project has already committed twice. It would need its own registration and a
sample held out in advance.

## What stands

* **The corpus is built on EX-3, as registered.** No version bump, no prompt change.
* **The 25–29% discard rate stands as a stated limitation.** It is a recall cost, not a precision
  failure: nothing false reaches policy, and some genuine findings never arrive. **Absence in this
  corpus is not evidence of no event.**
* **One unrelated fix was kept**, because it is not a prompt question and was independently wrong:
  `MAX_FETCH_PER_NAME` was 200 while VEDL filed 228 documents in the window, so that name fetched
  200, read 194, and could never satisfy `documents_read >= filings_in_window`. It would have read
  "Filings NOT read" on the buy screen for ever and every rebuild would have paid to reproduce it.
  Raised to 1,000 — above the busiest window NSE has shown us, still bounded.
