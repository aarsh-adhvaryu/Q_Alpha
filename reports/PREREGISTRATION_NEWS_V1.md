# Pre-registration — News adapter v1 (`NEWS-1`): archived headlines as flags

**Frozen 2026-09-10, BEFORE any feed was archived, parsed, mapped or read by a model.**

Written first, for the third time and the same reason. This project has twice adopted a result as
the expected value after seeing it (`shrink` selected on the holdout; `live/valuation.py` built for
VBL and never tested against VBL), and once wrote a rule that could not fail (the evidence adapter's
predecessor). Writing the answer down first is the only thing that has ever stopped it.

**What had been done before this file existed:** four candidate feeds and two dead ones were fetched
once, read-only, to establish which answer at all from this machine and in what shape (§2). No item
was archived, no item was mapped to a name, and no model saw one. The rules in §4 were written
after that inventory and before the first archived fetch.

---

## 1. The claim under test

> Corporate filings are the primary record, and they arrive late. A regulator's order, a rating
> action or a governance failure is usually *reported* before the company discloses it — and the
> screen this system runs buys names that have already fallen, which is precisely the population
> where the reason for the fall matters. Archived headline snippets from Indian market feeds, read
> by a local model into verified-quote labels, can surface holder-relevant negative items on the buy
> list that the filings alone miss, **as flags**.

**This is falsifiable and may fail.** See §5.

## 2. The feed inventory — probed 2026-09-10, before any rule was written

| Feed | Answered | Items | Shape |
|---|---|---|---|
| Google News RSS search, per name | 200 | 59–100 | title + `<source>`; **no article text**; links are `news.google.com` redirects |
| Economic Times — stocks (`2146842.cms`) | 200 | 50 | CDATA title, ~300-char plain summary, `pubDate +0530` |
| Economic Times — markets (`1977021501.cms`) | 200 | 50 | same shape |
| LiveMint — markets (`/rss/markets`) | 200 | 35 | CDATA in title, link, description **and** `pubDate` |
| Business Standard — markets (`markets-106.rss`) | 200 | 35 | CDATA; **403 without a browser user-agent** |
| Moneycontrol — `marketreports.xml`, `business.xml` | 200 | 4, 15 | **DEAD**: newest item 2024-04-23. Excluded. |
| NSE press releases | **404** | — | no RSS at that path. Filings stay `announcements.py`'s job. |

`NEWS-1` reads the four live market feeds plus one Google News search **per in-scope name only**
(screened plus held, ~15–25 requests a day, never all 96).

## 3. Scope — stated so that silence is not mistaken for approval

The adapter reads **snippets**: the headline and, where a feed provides one, its short summary. It
does **not** fetch, parse or read the article. Google News carries no description at all, so a
passage from that feed can only ever be its title.

Explicitly **not covered in v1**: article bodies · paywalled sources · social media · broker
research · earnings-call transcripts · price commentary of any kind. Everything outside §2's feed
list is `NOT_COVERED`, never `UNKNOWN`, and never a clean bill.

## 4. Rules — fixed before the first archived fetch

**Provenance.** The raw bytes of every feed response are written to
`data/evidence/news/<date>/<feed-id>.xml` with a `.provenance.json` sidecar (URL, retrieval time,
HTTP status, sha256, byte length) **before anything parses them**. A row that cannot name the feed
hash it came from is not evidence.

**Dating.** An item whose `pubDate` cannot be parsed is **dropped, never dated by us** — the same
rule `announcements.parse_index` follows, for the same reason: a filing or a headline that cannot be
ordered against a price cannot support a claim about what was knowable when.

**Staleness.** A feed whose newest item is more than 30 days old is `stale`, which is `UNKNOWN` for
that day, not `PASS`. Moneycontrol's two feeds answer 200 and are three years dead; a feed that dies
later must not read as a quiet news day.

**Mapping.** An item reaches a ticker only through the alias table
(`data/universes/nifty100_aliases.csv`), matched **whole-word and case-insensitively**. Family names
alone — Adani, Tata, Bajaj, HDFC, ICICI, SBI, Jio, Mahindra, Birla, Godrej — map to **nothing**,
because "Adani" is eight listed companies and "Tata" is a dozen. Deliberate under-mapping: a missed
item is a gap the coverage row reports, and a mis-mapped item is a flag against the wrong company.

**What the model may say.** One line per item, in the EX-2 grammar, with a verbatim quote:

```
NEWS: ticker=<SYMBOL>; item=<ID>; type=<one of the EVENT_TYPES>; stance=<negative|neutral|positive>;
      materiality=<high|medium|low>; passage="<VERBATIM FROM THE SNIPPET>"; summary=<one clause>
```

`materiality` carries the **same rubric as EX-2** — how much this should worry someone who already
owns the shares, not how newsworthy it is — shared as one string between both prompts so they cannot
drift apart. `stance` is *the direction of this item as the snippet states it*, never a forecast.
**A price move is not an event**: "shares fall 5%" is exactly what the screen already sees, and
rating it is double-counting a number the system computes for itself.

**What is kept.** A line survives only if all three hold: the item id was in the batch, the ticker is
one the **mapper** assigned to that item, and the passage verifies against that item's archived text
by `extraction.verify_passage`. The model cannot introduce a name, cannot move an item to another
company, and cannot quote something that is not there. Everything else is discarded and counted.

**What acts.** Only a verified, current-version item that is **both `high` and `negative`** raises a
flag, and a flag is `WATCH` — advisory. **News can never produce `BLOCK`.** Only NSE's own published
lists exclude a name without a human, and that is asserted in code
(`pretrade.assess_candidate`), not left to review. A model's reading of a headline is the weakest
evidence in this system and gets the weakest power.

**States.** `PASS` — feeds read, items mapped, nothing high-negative (the detail says how many).
`PASS` also covers *no item matched*, with the feed count in the detail. `UNKNOWN` — a feed failed,
was stale, or no extraction ran. `NOT_COVERED` — news was not attempted at all. In `NEWS-1` a news
`UNKNOWN` is **rendered but does not govern** the shadow decision: a dead RSS feed must not empty a
basket, and `HUMAN_REQUIRED` is reserved for the account or the evidence feed.

**Counts, never a score.** The surface says "3 negative / 1 positive high-materiality items in 7
days". There is no sentiment number, no index, and nothing in [0, 1]. A score would invite being
compared, ranked or optimised against, and an 8B model labelling headlines has earned none of that.

**Window.** Seven days for what is shown beside a name; the archive keeps everything.

## 5. The pre-registered falsifiers

**(a) Precision.** The first **30** flags raised (`high` + `negative`) are audited by hand against
the linked item. **If more than half are not genuinely adverse to a holder of that stock, `NEWS-1`
has failed** and is retired or re-specified as `NEWS-2` — published either way, not quietly widened
until it looks right.

**(b) Coverage.** Over the first **20 trading days**, if more than **30%** of in-scope names have
zero mapped items, the feed list and the alias table are inadequate for the claim in §1, and no
coverage statement may be made from this adapter until that is fixed. A "no news found" that means
"we could not see the news" is the defect this whole layer exists to avoid.

**(c) The null result is a result.** If the flags are accurate but never fire on a name the screen
proposes, `NEWS-1` is *correct and useless*, and that is to be recorded as such rather than kept for
the look of it.

## 6. What this experiment does not claim

- It says nothing about returns. No book trades on it, no basket changes because of it, and
  `CORE_V1`'s clock is untouched — the evidence and AI layers version independently, which is the
  whole reason they are allowed to change at all.
- It is not sentiment analysis. `Q_alpha.md` §3.11 draws the line: *structured event detection from
  official sources, not opinion mining*. This is one step further from the source than filings are,
  and it is labelled that way everywhere it appears.
- It does not make the model a judge. It reports what a headline says; deterministic policy decides
  what that means, and the policy is in §4 above, written before the first item was read.

## 7. Outcome — recorded 2026-09-10, after the first archived run

**§1–§6 above are unchanged. Nothing in the specification was edited after the data was seen.**

### The transport works

| Item | Result |
|---|---|
| Feeds attempted | 19 — the four market feeds plus one Google News search for each of 15 in-scope names |
| Failed or stale | **0** |
| Items in the last 7 days | 1,011, of which 685 were kept (mapped to a name, or from a market feed) |
| Items about an in-scope name | 482 |
| Names read | 14 of 15 in the time budget; 13 produced at least one labelled item |
| Model | `qwen3-8b-32k`, on this machine. No snippet left it. |

### The labels are not what a "sentiment feed" would produce

Of 90 distinct events at their current revision: **44 low · 42 medium · 4 high**, and
**59 neutral · 16 positive · 15 negative**. Four flagged (`high` **and** `negative`), on one name.
The model is not painting the day negative; most headlines are correctly routine.

### Falsifier (a) — precision — passes so far, on a sample too small to settle it

All four flags, and the nine reports behind them, are the same real story: the Meghalaya High Court
admitted a plea and the state government halted **Shree Cement**'s project pending an inquiry. A
plant or business shut down is `high` in the rubric, and it is adverse to a holder. **4 of 4
correct**, which is 4 of the 30 the falsifier asks for. The audit continues.

### Three findings, all of them about counting rather than about the model

**1. An item is a report, not an event.** Nine separate outlets carried that one court order.
"9 negative items" is arithmetically correct and reads as nine problems. Clustering them would mean
inventing a similarity score, which §4 forbids, so every surface that prints the count now says what
it counts: *reports rather than events, because outlets repeat a story*.

**2. The same headline is labelled differently in different batches.** Nine of the 99 rows written
were re-reads of an event already on file, and they came back at a **lower** materiality. Temperature
is zero, but the batch is part of the prompt, so a snippet read beside twenty others is not read in
the same context twice. The append-only store handles this correctly — a re-read supersedes — and it
means **`NEWS-1` labels are stable within a run and not across one**. Recorded rather than tuned
away; it is a limit of the method, not a bug to fix by re-prompting until the answers agree.

**3. The readers were counting lines, not the record.** Reading every line gave 12 flags; reading
each event at its current revision gives 4. The panel would have printed three times the number the
log holds. Found in a scratch run before any of it shipped, fixed at `flags._rows`, and **the same
defect was already present in the filings reader**, which predates this one (rule 1 in `CLAUDE.md`:
grep every caller of the thing you fixed). Both now read at the current revision.

### One operational limit

Two names came back cut off at the model's `max_tokens` with 60 and 72 headlines in a single call —
a short prompt whose *answer* could not fit. That counts as a failed read and covered neither name,
which is the honest outcome. Calls are now capped at 20 items; the fix is unit-tested and **has not
yet been observed on a live run**.

### Falsifier (b) — coverage — not yet assessable

One day is not the 20 trading days the falsifier specifies. On this day, 13 of 15 in-scope names had
at least one mapped item, which is well inside the bar; the alias table's deliberate
under-mapping of family names has not yet cost a name its coverage.
