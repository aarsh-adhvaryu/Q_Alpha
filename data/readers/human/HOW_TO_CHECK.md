# Reading complete documents for events

Read every file in `documents/` from start to end. For each event that should worry someone who owns the shares, add one row to `omissions.csv`:

- `sha256` — copy it from `documents.csv`
- `event_type` — one of: regulatory_action, litigation, insolvency, auditor_change, board_change, promoter_pledge, related_party, fundraise, acquisition, divestment, credit_rating, guidance_change, results, dividend, operational_disruption, other
- `materiality` — high, medium or low, by the rubric below
- `passage` — copy the sentence from the document exactly

A document with no material event needs no row. When you finish a document, put `yes` in its `read_by_you` column in `documents.csv` — that is how a document with nothing material is told apart from one not yet read. Do not look at any model's output first.

WHAT 'MATERIALITY' MEANS HERE — read this before rating anything:
Materiality is **how much this should worry someone who already owns the shares**. It is NOT how newsworthy, how large, or how interesting the item is.

  high   — a reason to stop and think before buying more: a regulator or court acting against the company or its officers, insolvency, an auditor resigning or qualifying, a default or downgrade, promoter pledges rising sharply, a large related-party transaction, a plant or business shut down, guidance withdrawn or cut sharply, a restatement.
  medium — worth knowing, not alarming on its own: a change of key management, a moderate acquisition or divestment, a fundraise, an ordinary rating affirmation.
  low    — routine disclosure.

THESE ARE NOT MATERIAL, whatever the numbers involved. Rate them 'low' or omit them:
  - quarterly or annual results, however good or bad the growth
  - revenue, EBITDA, margin or profit figures on their own
  - dividends, bonuses, splits and record dates
  - analyst or investor meet intimations, presentations, transcripts
  - trading-window closures, newspaper publications, compliance certificates
  - a contract win, expansion or investment, however large

**Good news is never high materiality.** A company growing 10% is not a reason to worry about owning it. If the only thing it says is that the business did well, it is 'low'.

