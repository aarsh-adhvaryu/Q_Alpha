# Universe breadth (Nifty 100) — Stage-1 findings

_2026-06-18. Pre-reg: `reports/PREREGISTRATION_universe.md`. Raw screen: `reports/universe_nifty100_screen.md`._
_Engine reused unmodified; validated Nifty-50 panel untouched (separate cache)._

## Result (Nifty 100, static current constituents, 2012–24, net cost + tax)

| series | CAGR | Sharpe | maxDD | vs Nifty-50 TRI |
|---|---|---|---|---|
| Strategy (3-factor + shrink, annual) | 16.4% | 1.06 | −27.5% | +2.2pt |
| 1/N (same static universe) | **26.3%** | — | −36.6% | — |
| Nifty-50 TRI | 14.2% | — | — | — |
| _(reference) Strategy on clean PIT Nifty-50_ | _18.2%_ | _1.13_ | _−25.2%_ | _+3.7pt_ |

Strategy − 1/N gap: **−9.9pt** full-window; strategy ≥ 1/N in only **16%** of rolling 3y holds.

## Verdict: INCONCLUSIVE — and the screen design is *why*

The naive read ("strategy loses to 1/N by ~10pt → breadth hurts") is **wrong**, and recognizing that
is the actual finding:

1. **The 1/N baseline here is a survivorship artifact, not a benchmark.** 26.3% CAGR is implausible
   for a real diversified Indian basket (Nifty TRI did ~14%). It's high because equal-weighting
   *today's* Nifty-100 from 2012 holds **every name that survived into the 2026 index**, tilted toward
   the smaller survivors that ran the hardest. Buy-and-hold-all-survivors is the **single largest
   beneficiary** of survivorship bias.
2. **The pre-registered "gap is bias-clean" assumption broke.** I assumed strategy and 1/N share the
   bias symmetrically. They don't: a point-in-time factor strategy *cannot see the future*, so it does
   **not** preferentially front-load the eventual winners; 1/N-on-survivors does, by construction. So
   the bias inflates 1/N **more** than the strategy → the −9.9pt gap is dominated by baseline
   contamination, not by the strategy being worse.
3. **The strategy's own numbers are unremarkable, not damning.** 16.4% / Sharpe 1.06 on biased
   Nifty-100 is *slightly below* its clean PIT Nifty-50 (18.2% / 1.13) — even *with* a survivorship
   tailwind. So there is **no visible breadth bonus**, but this is confounded (biased universe, mid-cap
   noise, the §4.6 tax gate trading only 12× while frictionless 1/N rebalances monthly).
4. **Listing truncation is real:** only 79 of 98 names priced in 2012, rising to 95 by 2024 — the
   static universe is also a moving target early, further muddying any read.

**Net:** a static current-constituents universe *cannot adjudicate breadth*, because its 1/N baseline
is unbeatable-by-construction. Running Nifty 200 the same way would be **equally uninterpretable** (an
even more survivorship-inflated 1/N), so it was not run — that would be motion, not evidence.

## What would give a real answer (Stage 2 — the only valid path)
A **survivorship-free point-in-time Nifty-100/200 membership** (NSE semi-annual reconstitution
circulars / niftyindices historical constituents), reconstructed into intervals like
`build_nifty_universe.py`, then the same walk-forward. That is the genuine **data-sourcing effort** —
the blocker named in the pre-reg. Only a Stage-2 pass can move the product off Nifty 50.

## Recommendation
- **Do not** promote a wider universe on this evidence (iron rule: no survivorship-biased GO).
- **No visible breadth bonus** even with the survivorship tailwind → the expected value of the Stage-2
  data effort is **modest**, not obviously worth it before the live paper run. The validated Nifty-50
  edge stands; breadth is a *maybe*, gated on real PIT data.
- If pursued later, Stage 2 needs the PIT membership source first; it is **not** a next-week item.
- Honest methodological takeaway worth keeping: **never benchmark against 1/N on a survivorship-biased
  universe** — the baseline wins by construction.
