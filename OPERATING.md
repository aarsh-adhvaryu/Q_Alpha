# Operating Q-Alpha

**This is the page you use it from.** Everything else in this repo is background. How it was built, what was tried and what failed lives
elsewhere; you do not need any of it to run the thing.

**The build is not "closed".** It said so here for two days and that was not true — four defects
were found afterwards, one of which made this very page's evidence panel call a company "clear"
when nobody had read its filings. What is true is narrower and more useful: **nothing here places
an order, every path to your money runs through you, and the monthly loop below works.**

Nothing here places an order. Nothing ever will. You place every order yourself.

---

## 1. Once a month, when the ₹50,000 goes in

1. **Double-click Q-Alpha** on the desktop. It runs on this machine, writes one page, and opens it.
   Nothing is hosted, nothing is left running, and closing the page closes nothing.
2. **If it says Kite was not reachable**, run it once with `--login` (or `./qalpha.sh --login`) —
   the session expires around 6am IST, so most days it will ask.
3. **Read "Today's basket"** on the page. It is sized to this month's allowance — ₹50,000 — not to
   the whole balance, however much cash is sitting there.
4. **Place the orders yourself in Kite.** CNC / delivery. **No stop-loss. No target.**
5. **Drop the tradebook export into `data/tradebooks/`** afterwards. Console → Reports → Tradebook.
   Overlapping date ranges are safe; it de-duplicates on Zerodha trade ids. Until an export covers a
   holding, its lots have no purchase date and its tax is labelled an estimate rather than exact.

Money for future instalments **stays in the broker account**. The page counts it, holds it back from
the basket, and says how much it is holding back.

**Why no stop-loss.** The screen buys names that have already fallen. A stop sells exactly what it
just bought, realises a loss, triggers tax, and fires on ordinary volatility. The exit that does
exist is the §4.7 breakdown test, which can tell a name-specific fall from the whole market falling.
A stop cannot.

## 2. Any day you feel like looking

Open the dashboard and read the holdings and the track record. That is all.

**If you upload a tradebook after a sale, check the tax figure against Zerodha's own Tax P&L.** The
engine has been reconciled against exactly one real sale — single lot, all short-term, no loss.
Multi-lot, long-term and loss set-off are unit-tested and have never met a broker statement. The
first time you sell something complicated, that number needs checking by hand.

## 3. What runs by itself

**The local run does not.** It runs when you click it, on this machine, and stops when it finishes.
Miss two days and nothing is lost: the next run reads what changed, resumes what it had not
finished, and says what moved while it was off.

**But the old cron is still on**, and saying otherwise here was wrong — this section claimed "no
cron, no cloud" on 2026-09-09 while `.github/workflows/paper.yml` was running every weekday, doing
hosted AI calls and stepping the twins. It still is. Retiring it is the next step and it has not
happened yet; until it does, two systems are running and only one of them is the one you click.

The one thing the local run needs from you is the Kite login. Market history and filings need no
session at all — only your holdings and cash do — so the analysis runs without one, and it will say
plainly that the account figures are unconfirmed rather than showing you a zero.

## 4. What the buy screen shows you

Under the basket, the dashboard prints **what the exchange and the filings say** about those exact
names: any NSE caution or surveillance condition, and any high-concern event found in a real filing
in the last 30 days, with a link to the filing itself.

```
⚠️ What the exchange and the filings say

- JIOFIN — 🟡 exchange: Scrip PE is greater than 50 (4 trailing quarters)
- BLISSGVS — 🔴 exchange: trade-to-trade series BE; Long Term ASM stage 4

Clear: VBL, TCS, MARUTI.
```

**These are flags, not vetoes.** Nothing there removed a name from the basket. The screen chose it,
and whether to buy it is your call.

It tells you how old the exchange file is. If it says the names have **not** been checked, that is a
gap and not a clean bill — the daily job is not archiving, and that is worth a look.

## 5. What to ignore

**`reports/pretrade.md`.** A research surface. Anything from it that matters is already on the buy
screen.

**Any name the panel has not marked clear *and* has not flagged.** It will say "Filings NOT read"
for those. That is the honest state, not a warning about the company.

**The GO gate.** It reads NOT YET and will keep reading NOT YET. It was built to answer "has this
beaten a cheap index fund by more than luck", and the matched null showed that question needs
roughly 200 years of data at this effect size. It is not a countdown to anything.

## 6. What this system is, honestly

It buys large Indian companies that have fallen furthest below their one-year high, spreads them
across sectors, does the FIFO and capital-gains arithmetic properly, and keeps you invested rather
than waiting for certainty.

It is **not** proven to beat an index fund. The 18.2% backtest figure is in-sample: the winning
configuration was chosen by requiring it to beat the benchmark on the holdout, which spends the
holdout. Its edge over an equal-weight fund is 0.42% a year, which cannot be verified in a lifetime
at this concentration.

**Plan on the index's ~11–12%. Treat anything above that as unproven. Size the first year as
tuition.** That framing was true when the money went in and it is still true.

Two things it will not do, and no system can:

- **It will not find the next multibagger before it runs.** It ranks on how far a large-cap has
  fallen. That is a discipline, not a crystal ball.
- **It will not protect you in a crash.** Its worst backtested fall is **−47.5%**, against the
  index's −36.3%. You are paid extra return for taking extra risk, and nobody has yet watched this
  system live through a fall.

## 7. When to come back

Open the repo again when one of these happens:

| Trigger | Why |
|---|---|
| You sell something and the tax figure looks wrong | the engine has met exactly one real sale |
| A holding has a split, bonus, demerger or buyback | **no corporate action has ever been reconciled live** |
| A Telegram failure alert repeats for more than two days | the record is accruing holes |
| The market falls hard and you want to know what it did | nobody has watched this system fall |
| You want a flag to actually block a name | that is a veto, and flag-don't-veto is a rule with a reason |

Until one of those, the answer to "should I change something" is no. The strongest proven result in
this whole project is that **trading less beat trading more**, net of cost and tax, across every
sub-period tested. Leaving it alone is not neglect. It is the strategy.
