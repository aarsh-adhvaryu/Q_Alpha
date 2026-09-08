# Operating Q-Alpha

**The build is closed. This is the page you use it from.** Everything else in this repo is
background: how it was built, what was tried, what failed and why. You do not need any of it to run
the thing.

Nothing here places an order. Nothing ever will. You place every order yourself.

---

## 1. Once a month, when the ₹50,000 goes in

1. **Open the dashboard** and enter `APP_PASSWORD`.
2. **Log in to Kite.** One tap. It expires around 6am IST every day, so it will ask most times.
3. **Add money → type the amount.** Type `50000`. The number you type is a hard budget; the basket
   below it will add up to that and not more.
4. **Set the slider to 3–4.** (Slider 8 was for the opening ₹1,00,000. Monthly is 3–4.)
5. **Place the orders yourself in Kite.** CNC / delivery. **No stop-loss. No target.**
6. **Upload the tradebook afterwards.** Console → Reports → Tradebook. It de-duplicates on Zerodha
   trade IDs, so overlapping date ranges are safe — when in doubt, export wider.

Money for future instalments **stays in the broker account**. That is intended: the system counts it
and does not treat it as performance.

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

One scheduled job, weekdays at 12:23 UTC. It refreshes prices, marks the paper books, runs the twin
experiment, collects exchange filings, and commits the record. It is fail-soft everywhere and has a
postcondition that goes red if the day's record is missing or incomplete.

**If it fails you get a Telegram alert.** If you get one, nothing is on fire: no money moves on that
job. It means a day of evidence is missing.

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
