"""The reconciled account — track 1, and the base every other book is seeded from.

### Why this exists

The twin's ``REAL`` book holds **nothing**: ₹3,04,144 of cash and zero open lots, while the actual
Zerodha account holds eight names worth ₹2,93,197. The tradebook was never applied to it. The value
the dashboard printed for REAL came from a different code path entirely, which is why its holdings
chart said *"nothing priced yet"* directly beneath a valuation — one book, two answers.

So "start every book from a copy of my actual account" needs a copy of the actual account, and there
wasn't one. This is it.

### Reconciled means CHECKED, not assumed

A replay that disagrees with the broker is not a base for anything. The three ways they disagree are
different facts and are kept apart:

    mismatched          both know the name, quantities differ — a corporate action, or a missing
                        trade. The lots are wrong, so the tax is wrong.
    broker_only         you bought it somewhere this ledger cannot see. THIS IS THE "I added a stock
                        in Kite" case, and it is normal — it needs a tradebook export, not an alarm.
    tradebook_only      the ledger thinks you hold something the broker does not. A sale that never
                        reached the export, or a replay that consumed the wrong lots.

:attr:`ReconciledAccount.tallies` is true only when all three are empty. When it is false the
snapshot built from this account carries the reason in ``missing_critical``, so the run degrades to
"I could not check this" rather than deciding on a book that does not match reality.

### Dated lots are the whole point

The broker's holdings endpoint gives a **blended average cost** and no purchase dates. That is enough
to value a position and not nearly enough to tax one: FIFO needs to know which shares were bought
when. A portfolio built from holdings alone is marked ``dated=False`` and every tax figure derived
from it is an estimate — never presented as exact.

Pure: no network, no broker client, no clock. The caller fetches; this reconciles.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from qalpha.accounting.tax_lots import TaxLot
from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.live.tradebook import TradebookTrade, replay_tradebook


@dataclass(frozen=True)
class ReconciledAccount:
    """What you actually own, checked against the broker, with the disagreements named."""

    as_of: date
    portfolio: Portfolio
    cash: Decimal
    #: Do the lots carry real purchase dates? False ⇒ tax is an estimate, never exact.
    dated: bool
    #: Same name, different quantity. The lots are wrong, so the tax computed from them is wrong.
    mismatched: tuple[str, ...] = ()
    #: The broker holds it and the ledger cannot explain it — the "I bought it in Kite" case.
    broker_only: tuple[str, ...] = ()
    #: The ledger holds it and the broker does not.
    tradebook_only: tuple[str, ...] = ()
    #: Sells the replay could not match, verbatim from the engine.
    replay_warnings: tuple[str, ...] = ()
    realized_tax: Decimal = Decimal("0")
    #: Held names carried at the broker's average cost with no purchase date. Their VALUE is exact
    #: and their TAX is not — the two are tracked separately because they fail separately.
    undated_tickers: tuple[str, ...] = ()

    @property
    def tallies(self) -> bool:
        """True only when the replay reproduces the broker exactly. Anything else is not a base."""
        return not (self.mismatched or self.broker_only or self.tradebook_only)

    @property
    def blocking(self) -> tuple[str, ...]:
        """Why a decision cannot rest on this account, in the snapshot's words. Empty when it can.

        ``broker_only`` is deliberately NOT blocking on its own: a stock you bought in Kite yesterday
        is a normal event, and refusing to run until a CSV arrives would make the system useless on
        exactly the day something changed. It is a loud caveat, and it blocks anything TAX-exact.
        """
        out: list[str] = []
        if self.mismatched:
            out.append(f"quantities disagree with the broker: {', '.join(self.mismatched)}")
        if self.tradebook_only:
            out.append(
                f"held in the ledger but not at the broker: {', '.join(self.tradebook_only)}"
            )
        return tuple(out)

    @property
    def tax_exact(self) -> bool:
        """May a tax figure from this account be called exact?

        Three conditions, and the third was missing. A sale the replay could not match means part of
        the *history* is absent, and history is what FIFO consumes — yet the remaining quantities
        can still agree with the broker perfectly, so ``tallies`` says nothing about it. Found in
        review 2026-09-09: a skipped sale left ``tax_exact`` True.
        """
        return self.dated and self.tallies and not self.replay_warnings

    def report(self) -> str:
        """One paragraph a person can act on. Says what tallied, what did not, and what to do."""
        n = len(self.portfolio.positions())
        lines = [
            f"{n} holding{'s' if n != 1 else ''} · cash ₹{self.cash:,.0f} · "
            + ("dated FIFO lots" if self.dated else "undated lots (broker average cost)")
        ]
        if self.tallies:
            lines.append("✓ Reconstructed holdings match your broker account exactly.")
        if self.broker_only:
            names = ", ".join(t.removesuffix(".NS") for t in self.broker_only)
            lines.append(
                f"➕ **{names}** — held at the broker, not in the trade ledger. If you bought "
                "outside this system, upload a tradebook export so the purchase date and cost are "
                "known; until then its tax cannot be computed."
            )
        if self.tradebook_only:
            names = ", ".join(t.removesuffix(".NS") for t in self.tradebook_only)
            lines.append(
                f"➖ **{names}** — in the trade ledger, not at the broker. A sale that never reached "
                "the export, or a corporate action the replay did not apply."
            )
        if self.mismatched:
            lines.append(f"⚠️ Quantities disagree: {', '.join(self.mismatched)}.")
        if self.undated_tickers:
            names = ", ".join(t.removesuffix(".NS") for t in self.undated_tickers)
            lines.append(
                f"⚠️ **{names}** — carried at the broker's average cost with no purchase date. The "
                "value is exact; the tax is not, because FIFO needs to know which shares were "
                "bought when. Upload a tradebook covering these and it becomes exact."
            )
        elif not self.dated:
            lines.append(
                "⚠️ No dated lots — every tax figure here is an estimate. The broker's holdings "
                "give a blended average and no purchase dates, and FIFO needs the dates."
            )
        for w in self.replay_warnings:
            lines.append(f"⚠️ {w}")
        return "\n".join(lines)


def reconcile(
    trades: list[TradebookTrade],
    broker_quantities: dict[str, Decimal],
    cash: Decimal,
    cfg: Config,
    as_of: date,
    *,
    broker_costs: dict[str, Decimal] | None = None,
) -> ReconciledAccount:
    """Replay the ledger and check it against the broker. The result is track 1.

    ``broker_quantities`` is what Kite says you hold. An **empty** mapping means "the broker was not
    asked", not "you hold nothing" — with no trades either, that is an empty account; with trades, it
    is an unchecked replay, and every name reads as ``tradebook_only`` because nothing confirmed it.
    Callers that could not reach the broker should say so rather than passing ``{}``.
    """
    result = replay_tradebook(trades, cfg, cash=cash)
    replayed = result.portfolio.positions()

    mismatched: list[str] = []
    broker_only: list[str] = []
    tradebook_only: list[str] = []
    for ticker in sorted(set(replayed) | set(broker_quantities)):
        ours = replayed.get(ticker, Decimal("0"))
        theirs = broker_quantities.get(ticker, Decimal("0"))
        if ours == theirs:
            continue
        if ours == 0:
            broker_only.append(ticker)
        elif theirs == 0:
            tradebook_only.append(ticker)
        else:
            mismatched.append(f"{ticker.removesuffix('.NS')} ledger {ours} vs broker {theirs}")

    # A NAME THE LEDGER CANNOT EXPLAIN IS STILL A NAME YOU OWN. The first version left it out of
    # the portfolio entirely, so "if I buy a stock in Kite it appears" was false: the reconciler
    # named HDFCBANK as broker_only and then handed downstream a book containing only VBL. It could
    # not be valued, could not be monitored, and did not count toward concentration.
    #
    # It is added as an UNDATED lot at the broker's average cost — exact value, unknown tax — and
    # listed in `undated_tickers` so the tax gap is per-name rather than a blanket caveat.
    costs = broker_costs or {}
    for ticker in broker_only:
        result.portfolio.ledger.add_lot(
            TaxLot(
                ticker=ticker,
                acquisition_date=as_of,  # unknown; recorded as today and flagged, never guessed back
                quantity_original=broker_quantities[ticker],
                buy_price=costs.get(ticker, Decimal("0")),
            )
        )

    return ReconciledAccount(
        as_of=as_of,
        portfolio=result.portfolio,
        cash=cash,
        dated=bool(trades) and not broker_only,
        mismatched=tuple(mismatched),
        broker_only=tuple(broker_only),
        tradebook_only=tuple(tradebook_only),
        replay_warnings=tuple(result.warnings),
        realized_tax=result.realized_tax,
        undated_tickers=tuple(broker_only),
    )
