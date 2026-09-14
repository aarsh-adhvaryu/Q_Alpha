# Pre-registration — EX-5: which reader, and which filings need no reading

**Registered 2026-09-14, before any candidate read a sample document and before the reference was
built.** Nothing in sections 1–6 may be edited after the first `scripts/readers.py read` or
`reference submit`; corrections go in a dated section at the bottom.

(EX-4 is taken: it is the tighter-prompt experiment in README §7, reverted. A label is never reused.)

---

## 1. The question

Reading filings with `claude-sonnet-5` (EX-3) costs about $2 a company-year and ran the API key dry.
Two questions, answered on one fixed set:

1. **Reader.** Which is the cheapest reader — local or API — whose readings are good enough to feed
   the investor and the knowledge graph?
2. **Triage.** Which subject-and-length rules can mark a filing *routine, not read* without hiding a
   material event?

Nothing here changes the evening run. A selected reader becomes a corpus label (and pinned digest)
only by a later registration.

## 2. The sample

- **150 archived filings with a text layer** from `data/evidence/announcements/`, drawn by
  `readers.select_sample` with seed `20260914`: 30 that the triage rules call routine, 25 long
  (≥ 30,000 characters), 95 ordinary. Sectors are taken in turn inside each group.
- **Frozen once drawn** (`data/readers/sample.jsonl`). Each document's bytes are re-verified against
  its provenance hash on every load; a changed document is left out and named.
- **Never used to tune a reader.** No prompt, chunk size or rule is changed after looking at it. A
  change is a new experiment on a new sample.

## 3. The candidates

Every candidate uses the unchanged EX-3 prompt, parser and verbatim-quote rule
(`live/extraction.py`). Local models run one request at a time at a **16K window** (Modelfiles in
`docs/ollama/`), with batches sized to that window.

| Reader | Where | Note |
|---|---|---|
| `qwen3.5-9b-16k` | local | default local candidate |
| `gemma4-12b-16k` | local | closest local comparison |
| `qwen3.6-35b-16k` | local | MoE, partly in RAM |
| `qwen3.8-27b-16k` | local | partly in RAM |
| `qwen3-8b-32k` | local | baseline, already installed |
| `claude-haiku-4-5` | Anthropic | |
| `claude-sonnet-5` | Anthropic | the EX-3 reader |
| `deepseek-flash` | DeepSeek | |
| `gemini-3.1-flash-lite` | Google | |

A candidate that cannot finish all 150 documents is reported and **cannot be selected**. Local runs
record the Ollama digest served, tokens/second, and peak VRAM and RAM; API runs record the model name
each response returned, and any mismatch stops the run.

## 4. The reference

1. **Opus 5** (`claude-opus-5`, Batch, adaptive thinking, effort `high`) reads each whole filing with
   the same prompt. A reading cut off at its output limit is not complete and is read again.
2. **Pooling.** Every verified claim from Opus and from every candidate is pooled per document.
3. **Adjudication.** Opus judges each pooled claim against the archived text: TRUE or FALSE, with its
   own type and materiality. Adjudication starts only after every reading is collected.
4. **Events.** TRUE claims about the same document, of the same adjudicated type, whose passages
   contain one another or share ≥ 30% of their words, are one event. Its materiality is the most
   severe given.
5. **Your full-document check.** You read **20 complete documents** (5 long, 4 routine, 11 ordinary,
   seed `20260915`) end to end without looking at any model output, and list every event, with its
   materiality and verbatim sentence. Those events join the reference.
6. **Your adjudication check.** You mark **25 random adjudications** (seed `20260916`) agree or
   disagree.

Opus constructs the reference; its agreement with itself validates nothing. Steps 5 and 6 are the
validation.

## 5. The rule (decided now)

**The reference must pass first.** Otherwise nothing is selected and the reference is rebuilt:

- at least 20 documents marked read, and at least 25 adjudications checked;
- **omission rate ≤ 10%** — of the high and medium events you found, the share with no match in the
  model-built reference;
- **adjudicator disagreement ≤ 10%** of the checked adjudications.

**A reader qualifies only if all hold**, over all 150 documents:

| Measure | Definition | Threshold |
|---|---|---|
| High-materiality recall | reference high events it found (a TRUE claim of its in that event) ÷ all reference high events | **≥ 0.85**, and **≥ 0.90 × the best reader's** |
| Precision | its TRUE claims ÷ its adjudicated claims **plus** its discarded (non-verbatim) quotes | ≥ 0.85 |
| Verbatim rate | verified quotes ÷ all quotes it emitted | ≥ 0.90 |

Reported for every reader but not thresholds: medium recall, failed batches, cost per filing,
tokens/second, peak VRAM and RAM, seconds per filing.

**Among qualifiers the cheapest per filing wins** (local counts as $0; ties go to higher high
recall). **If none qualifies**, the reader with the best high recall is named, used on material
filings only, and the shortfall is recorded as a known limit. The report,
`reports/READER_COMPARISON_EX5.md`, is published either way.

## 6. Triage

Rules `TRIAGE-1` in `live/triage.py`. "Routine, not read" is its own status: never read, never
verified, never counted toward coverage. Ambiguous subjects (`Updates`, `General Updates`, `Press
Release`, `Investor Presentation`) are always read; a routine subject over its length ceiling is read.

**A rule is removed** if the routine documents it matches in the sample contain **any high** reference
event, or **more than one medium** event. A rule with no documents in the sample is reported as
untested and is not used until an audit has tested it. Once in use, a weekly audit reads a random 5%
of skipped filings; a material event found removes that rule.

## 7. Money

Paid work is a one-time research job, reserved at worst case before each request and never drawn
from the monthly operating cap:

| Job | Ceiling set by the command | Expected actual |
|---|---|---|
| `ex5-reader-runs` (the paid candidates) | `--budget-usd` | ~$5–9 for all four API readers |
| `ex5-reference` (Opus readings + adjudication) | `--budget-usd` | ~$15–25 |

Expected figures are estimates from list prices and the EX-3 token counts, not measurements. The
ceiling is hard: settled plus still-reserved spend can never pass it. Because each Opus request
reserves its full output allowance (~$0.40) until collected, a submit may take only part of the
sample; collecting settles the actual cost and frees the rest for the next submit.
