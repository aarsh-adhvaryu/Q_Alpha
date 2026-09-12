# Which model should read the corpus — measured, 2026-09-11

Run under the decision rule registered in [`PREREGISTRATION_EX3_CORPUS.md`](PREREGISTRATION_EX3_CORPUS.md)
**before** these numbers existed. Both readers were given the **same archived bytes**. Nothing was
written to the corpus: no coverage row, no receipt, no event.

```bash
uv run python scripts/evidence.py compare-readers \
    --readers claude-haiku-4-5,claude-sonnet-5 --sample 150 --workers 8
```

## The result

150 archived filings across 22 names · 1,887,949 characters · 8 concurrent calls.

| | `claude-haiku-4-5` | `claude-sonnet-5` |
|---|---:|---:|
| Wall clock | 52.5 s | 124.5 s |
| Calls | 87 | 89 |
| Input tokens | 788,631 | 1,026,809 |
| Output tokens | 24,745 | 65,443 |
| Cost at list | $0.91 | $2.71 |
| **Verified events** | **59** | **109** |
| High materiality | 16 | 16 |
| **Quotes not in the document** | **86** | **44** |
| **Discard rate** | **59%** (86 of 145 claims) | **29%** (44 of 153 claims) |
| Failed batches | 0 | 0 |

**Agreement between the two: 22%** on `(document, event type, materiality)` — 18 findings in common
out of 81 distinct. A 40-document run the same day gave 24%, so the figure is stable.

## The decision: `claude-sonnet-5`

Rule 1 of the registration decides it and never reaches the others:

> *If either reader discards materially more quotes as not present in the document — the one
> unambiguous error either can make, checked mechanically against the archived bytes — it loses.*

Haiku discarded **twice the share** of its own claims and returned **half as many** verified events
for the same documents. It is not cheaper per finding: $0.91 for 59 events is $0.0154 each, against
$2.71 for 109 at $0.0249 — 1.6× the price for a reader that misses half the events and invents at
twice the rate. On a corpus built once, that is not a trade worth taking.

Rule 3 points the same way independently: at 22% agreement the two are **not substitutable**, so the
choice is a real one rather than a coin toss over equivalent instruments.

Speed was excluded by the rule in advance, and correctly — Sonnet is 2.4× slower per document and
still finishes the whole corpus in about half an hour at eight workers.

## The finding that matters more than the choice

**22% agreement means the reader substantially determines the event stream.** Two competent models
reading the same filing under the same instructions agree on roughly one finding in five. The
registration required this to be published whichever reader won, and it is the reason EX-3 pins the
reader into the version label: a corpus assembled from both would carry this as an invisible
confound, and any later event study over it would be measuring the reader as much as the market.

## What a "discarded quote" actually is — checked, not assumed

A 29% discard rate reads like a 29% fabrication rate. It is not. Seventy documents were re-read and
every failing passage compared against the nearest run of text in the document:

**27 passages: 19 verified · 4 near-miss · 4 no-match · 0 too short.**

None of the eight failures was an invented fact. All eight were the model producing a **true
statement that is not a contiguous verbatim span**:

| What happened | Example |
|---|---|
| **PDF extraction broke the document, not the model** | Model: `CARE Ratings Limited has reaffirmed the credit rating…` — 98% of that run is in the document, which holds `e ratings limited has reaffirmed…`. The extracted text split the word `CARE`. The model read it correctly and the archive is what is wrong. |
| **Clauses joined across a sentence** | Model: `Jio Platforms Limited (JPL), subsidiary of the Company, has today… received the observation letter on the DRHP` — subject and predicate are both in the document, separated. |
| **A sentence composed from real fragments** | Model: `the Company has received an Order from the Office of the Commissioner, Central GST – Udaipur confirming Penalty of Rs. 1,08,04,533` — only the office name is contiguous. |

So the guard is behaving as designed and nothing false reaches policy. Its cost is **recall**: about
30% of genuine findings are dropped, and the loss is **not random** — it is biased against documents
whose PDF text extraction is poor, and against events the model prefers to summarise rather than
quote.

**The corpus will therefore under-count events, systematically.** Recorded here before it is built,
because an event study that reads absence as "no event" would be reading this artefact instead.

## What is NOT being changed, and why

The obvious repair — relax `verify_passage` to accept a high-threshold fuzzy match, or instruct the
model harder to copy a contiguous span — is **not** applied here. Both are changes to the extraction
contract (`extraction.py`: *"Bump on any change to the prompt, the parser, the verification rule or
the event vocabulary"*), so either one is **EX-4** and needs its own registration. Making it quietly
now, in the middle of choosing a reader, is how a label comes to span two rules — which has already
cost this project the first four days of run 2.

The question is live and is worth answering **before** the corpus is paid for, since rebuilding it
later costs the same money again.
