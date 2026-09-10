"""The page — one self-contained HTML file, written by the local run and opened from the desktop.

### What replaced what

The dashboard was a Streamlit app: a server, a browser tab pointed at localhost, a session that had
to stay open, and a hosted redeploy for anything to change. This is a file. The run writes it and
the run is over; opening it needs nothing but a browser, and it is still readable in a year when
none of this code runs any more.

`live/ui.py` was written pure — no Streamlit import, HTML and CSS strings out — so the entire visual
layer moves across unchanged. That was not foresight; it was the rule that a module which decides
how a number *looks* must never be able to change what it *is*. It happens to be exactly what makes
the page portable.

### What a file cannot do, stated so nobody expects it

A page opened over ``file://`` cannot run Python, read your tradebook or call Kite — browsers block
all of it, and that is the correct behaviour. So the click that starts things is a small launcher
that runs the pipeline and then opens what it produced. **The HTML is the result, never the engine.**

Everything on it is therefore *as of* the run that wrote it. The page says when that was, in IST,
because a stale page that does not announce its age is worse than no page.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from html import escape

from qalpha.live import evidence, ui
from qalpha.live.account import ReconciledAccount
from qalpha.live.commitments import Allowance, Commitment, open_proposals, waiting
from qalpha.live.desk import UNREADABLE, Desk, NameView


def _holdings_table(account: ReconciledAccount, prices: Mapping[str, Decimal]) -> str:
    columns = [
        ui.Column("Instrument"),
        ui.Column("Qty", "right"),
        ui.Column("Avg cost", "right"),
        ui.Column("Price", "right"),
        ui.Column("Value", "right"),
        ui.Column("P&L", "right"),
        ui.Column("% of priced", "right"),
        ui.Column("Tax basis"),
    ]
    positions = account.portfolio.positions()
    equity = sum((q * prices[t] for t, q in positions.items() if t in prices), Decimal("0"))
    rows: list[ui.Row] = []
    total_value = total_pnl = Decimal("0")
    for ticker, qty in sorted(positions.items()):
        lots = account.portfolio.ledger.open_lots(ticker)
        cost = sum(
            (lot.cost_basis_per_share * lot.quantity_remaining for lot in lots), Decimal("0")
        )
        held = sum((lot.quantity_remaining for lot in lots), Decimal("0"))
        avg = cost / held if held > 0 else Decimal("0")
        priced = ticker in prices
        # An unpriced holding is shown as unknown, never marked at zero: a ₹0 row understates the
        # account and reads as a wipeout rather than as a missing quote.
        value = qty * prices[ticker] if priced else Decimal("0")
        pnl = value - cost if priced else Decimal("0")
        if priced:
            total_value += value
            total_pnl += pnl
        undated = ticker in account.undated_tickers
        rows.append(
            ui.Row(
                cells=[
                    ui.Cell(ticker.removesuffix(".NS"), strong=True),
                    ui.Cell(str(int(qty))),
                    ui.Cell(ui.inr(avg, decimals=2)),
                    ui.Cell(
                        ui.inr(prices[ticker], decimals=2) if priced else "no quote",
                        tone="neutral" if priced else "warn",
                    ),
                    ui.Cell(ui.inr(value) if priced else "—"),
                    ui.Cell(
                        f"{ui.delta_glyph(pnl)} {ui.signed_inr(pnl)}" if priced else "—",
                        tone=ui.tone_for(pnl) if priced else "neutral",
                    ),
                    # "% of equity" where equity omits unpriced names would read 100% for a book
                    # that is half unvalued. It says "of priced" instead, which is true.
                    ui.Cell(
                        f"{float(value / equity * 100):.1f}%" if priced and equity > 0 else "—"
                    ),
                    ui.Cell(
                        "estimated — no purchase date" if undated else "dated (FIFO)",
                        tone="warn" if undated else "neutral",
                    ),
                ],
                muted=not priced,
            )
        )
    unpriced = [t for t in positions if t not in prices]
    # A PARTIAL VALUATION IS NOT A TOTAL. With two holdings and one quoted, the page showed the
    # quoted holding's ₹1,000 as total equity and called it 100% of equity — the missing row said
    # "no quote" while every aggregate beside it treated the book as fully valued. The label now
    # carries the gap; a number that cannot be complete must not be spelled like one.
    label = (
        f"Total ({len(positions)} names)"
        if not unpriced
        else f"Partial — {len(positions) - len(unpriced)} of {len(positions)} priced"
    )
    footer = ui.Row(
        cells=[
            ui.Cell(label, tone="neutral" if not unpriced else "warn"),
            ui.Cell(""),
            ui.Cell(""),
            ui.Cell(""),
            ui.Cell(ui.inr(total_value)),
            ui.Cell(
                f"{ui.delta_glyph(total_pnl)} {ui.signed_inr(total_pnl)}",
                tone=ui.tone_for(total_pnl),
            ),
            ui.Cell(""),
            ui.Cell(""),
        ]
    )
    return ui.table(columns, rows, footer=footer, empty="No holdings.")


def _decisions(commitments: Sequence[Commitment], allowance: Allowance, today: object) -> str:
    """What the run is waiting on and what it has proposed — the part that is not a number."""
    body = [f"<p>{escape(allowance.explain())}</p>"]
    proposals = open_proposals(commitments)
    holds = waiting(commitments)
    if not proposals and not holds:
        body.append(
            "<p>Nothing proposed and nothing on watch. That is a decision, not an absence — "
            "the run examined the account and found nothing that cleared its bar.</p>"
        )
    for c in sorted(proposals, key=lambda c: c.on):
        body.append(
            f"<p><b>{escape(c.ticker.removesuffix('.NS'))}</b> — proposed {c.on}, "
            f"{escape(ui.inr(c.amount))} reserved, <b>not yet confirmed as bought</b>. "
            f"{escape(c.reason)}</p>"
        )
    for c in sorted(holds, key=lambda c: c.ticker):
        body.append(
            f"<p><b>{escape(c.ticker.removesuffix('.NS'))}</b> — waiting. "
            f"{escape(c.trigger or 'no trigger recorded')}</p>"
        )
    return "".join(body)


def _proposal_table(orders: Sequence[tuple[str, int, Decimal]], allowance: Allowance) -> str:
    """What the screen proposed, and what it would cost. **You place every one of these in Kite.**

    An empty basket is rendered as a sentence rather than an empty grid, because "nothing proposed"
    and "the screen did not run" look identical as a blank table and are completely different facts.
    """
    if not orders:
        return (
            '<div class="qa-empty">No basket this run. If the screen ran and found nothing, the '
            "note above says so; if it could not run, that note says so too — a blank table cannot "
            "tell you which.</div>"
        )
    total = sum((Decimal(q) * price for _, q, price in orders), Decimal("0"))
    rows = [
        ui.Row(
            cells=[
                ui.Cell(t.removesuffix(".NS"), strong=True),
                ui.Cell(str(q)),
                ui.Cell(ui.inr(price, decimals=2)),
                ui.Cell(ui.inr(Decimal(q) * price)),
            ]
        )
        for t, q, price in orders
    ]
    footer = ui.Row(
        cells=[
            ui.Cell(f"Total ({len(orders)} names)"),
            ui.Cell(""),
            ui.Cell(""),
            ui.Cell(ui.inr(total), strong=True),
        ]
    )
    table = ui.table(
        [
            ui.Column("Instrument"),
            ui.Column("Qty", "right"),
            ui.Column("Price", "right"),
            ui.Column("Cost", "right"),
        ],
        rows,
        footer=footer,
    )
    return (
        table
        + "<p><b>You place these yourself, in Kite — CNC/delivery, no stop-loss, no target.</b> "
        f"Sized against {escape(ui.inr(allowance.remaining))} of allowance, at the run's prices; "
        "the fill you get will differ. Nothing here has been ordered.</p>"
    )


# --- the research desk ---------------------------------------------------------------------------
#
# The columns a person actually reads a name on, side by side, with the third state visible in every
# one of them. A blank cell here would read as "fine"; none of them is ever blank.
_HEALTH_TONE: dict[str, ui.Tone] = {
    "breaking": "bad",
    "watch": "warn",
    "healthy": "good",
    UNREADABLE: "warn",
}
# IMPORTED, NOT RETYPED. The first version of this map spelled the passing state ``"CLEAR"``,
# which is not one of evidence.py's states — the real one is ``PASS``, and ``CLEAR`` is a column
# code meaning something else entirely. Every clean name therefore fell through to the warn tone
# and was rendered amber. A string constant copied by hand onto a display surface is this repo's
# oldest defect wearing a stylesheet.
_EXCHANGE_TONE: dict[str, ui.Tone] = {
    evidence.PASS: "good",
    evidence.WATCH: "warn",
    evidence.BLOCK: "bad",
    evidence.UNKNOWN: "warn",
    evidence.NOT_COVERED: "warn",
}


def _trend_cell(value: float | None, *, invert: bool = False) -> ui.Cell:
    """A percentage, or the word for not knowing. **Never a zero standing in for absence.**"""
    if value is None:
        return ui.Cell("—", tone="warn", title="Not enough price history to measure this.")
    shown = value * 100.0
    tone = ui.tone_for(-shown if invert else shown)
    return ui.Cell(ui.pct(shown), tone=tone)


def _desk_row(view: NameView) -> ui.Row:
    mark = ui.inr(view.mark) if view.mark is not None else "unpriced"
    pnl = view.unrealised
    return ui.Row(
        cells=[
            ui.Cell(view.ticker.removesuffix(".NS"), strong=True),
            # THE THIRD STATE AGAIN, IN THE ONE COLUMN THAT COULD READ AS AN INSTRUCTION. A blank
            # or a dash beside a research row invites it to be read as a position of zero, or
            # worse, as something to open. It says which of the three this row is.
            ui.Cell(
                f"{view.quantity:,}"
                if view.held
                else ("in basket" if view.proposed else "watching"),
                tone="neutral" if view.held else "info",
                title=(
                    None
                    if view.held
                    else (
                        "proposed in today's basket"
                        if view.proposed
                        else "on the desk for research only — not held, not proposed"
                    )
                ),
            ),
            ui.Cell(mark, tone="neutral" if view.mark is not None else "warn"),
            ui.Cell(
                ui.signed_inr(pnl) if pnl is not None else "—",
                tone=ui.tone_for(pnl) if pnl is not None else "warn",
            ),
            _trend_cell(view.trailing_return),
            _trend_cell(view.drawdown),
            _trend_cell(view.excess),
            ui.Cell(
                view.health,
                tone=_HEALTH_TONE.get(view.health, "warn"),
                title=view.health_note or None,
            ),
            ui.Cell(
                view.exchange,
                tone=_EXCHANGE_TONE.get(view.exchange, "warn"),
                title="; ".join(view.indicators) if view.indicators else None,
            ),
            ui.Cell(
                view.evidence_state,
                tone=("bad" if view.concerns else ("good" if view.filings_read else "warn")),
                title="\n".join(view.concerns) if view.concerns else None,
            ),
        ]
    )


def _desk_panel(desk: Desk | None) -> str:
    """Everything known about every name in scope. Absent is a sentence, never an empty table."""
    if desk is None:
        return (
            ui.section("The desk")
            + '<div class="qa-empty">The research layer did not run this time, so there is '
            "nothing here. That is not the same as nothing being wrong.</div>"
        )
    columns = [
        ui.Column("Name"),
        ui.Column("Qty", "right"),
        ui.Column("Mark", "right"),
        ui.Column("P&L", "right"),
        ui.Column("6m", "right"),
        ui.Column("From high", "right"),
        ui.Column("vs median", "right"),
        ui.Column("Trend"),
        ui.Column("Exchange"),
        ui.Column("Filings"),
    ]
    ordered = sorted(desk.rows, key=lambda r: (not r.attention, not r.held, r.ticker))
    age = desk.exchange_file_age
    note = (
        f"surveillance file {age} day{'s' if age != 1 else ''} old"
        if age is not None
        else "no surveillance file found — every Exchange cell reads UNKNOWN"
    )
    body = ui.section("The desk", note=note) + ui.table(
        columns, [_desk_row(r) for r in ordered], empty="No names in scope."
    )
    body += f'<p class="qa-foot">{escape(desk.coverage_line())}</p>'
    if desk.notes:
        body += (
            '<div class="qa-note">' + "".join(f"<p>{escape(n)}</p>" for n in desk.notes) + "</div>"
        )
    body += (
        '<p class="qa-foot">'
        "<b>6m</b> is the return over the health window · <b>From high</b> is the fall from this "
        "name&#8217;s own trailing high · <b>vs median</b> is that return minus the cross-sectional "
        "median, which is the part that is about the company rather than the market. "
        "A dash means there was not enough history to measure — it does not mean flat. "
        "<b>UNKNOWN</b> on Exchange means the surveillance file could not be read for this name; "
        "it is not CLEAR. <b>filings not read</b> means nobody opened this company&#8217;s "
        "announcements, so the absence of a concern below is not evidence of one&#8217;s absence. "
        "<b>watching</b> in the quantity column means the row is here so the market is visible "
        "when the gate is shut &#8212; it is neither held nor proposed, and it is not a suggestion "
        "to buy. The only thing this system ever proposes is in <i>Today&#8217;s basket</i> below."
        "</p>"
    )
    return body


def _concerns_panel(desk: Desk | None) -> str:
    """What the filings actually said, quoted, for the names where anything was found."""
    if desk is None:
        return ""
    flagged = [r for r in desk.rows if r.concerns]
    if not flagged:
        return ""
    items = []
    for view in flagged:
        lines = "".join(f"<li>{escape(c)}</li>" for c in view.concerns)
        items.append(f"<p><b>{escape(view.ticker.removesuffix('.NS'))}</b></p><ul>{lines}</ul>")
    return (
        ui.section("What the filings said", note="verified quotes, current extractor only")
        + '<div class="qa-note">'
        + "".join(items)
        + "</div>"
    )


def render(
    *,
    account: ReconciledAccount,
    prices: Mapping[str, Decimal],
    allowance: Allowance,
    commitments: Sequence[Commitment],
    generated_at: datetime,
    notes: Sequence[str] = (),
    proposal: Sequence[tuple[str, int, Decimal]] = (),
    desk: Desk | None = None,
) -> str:
    """One self-contained page. No server, no network, no fonts to fetch — it opens from a file."""
    ist = generated_at.astimezone(ui.IST)
    positions = account.portfolio.positions()
    unpriced_names = sorted(t for t in positions if t not in prices)
    equity = sum((q * prices[t] for t, q in positions.items() if t in prices), Decimal("0"))
    cost = sum(
        (
            lot.cost_basis_per_share * lot.quantity_remaining
            for t in positions
            for lot in account.portfolio.ledger.open_lots(t)
            if t in prices
        ),
        Decimal("0"),
    )
    unrealised = equity - cost

    tiles = ui.tile_row(
        [
            ui.Tile(
                label="Equity (shares only)",
                value=ui.inr(equity),
                note=(
                    f"{len(positions)} name{'s' if len(positions) != 1 else ''}"
                    if not unpriced_names
                    else f"{len(positions) - len(unpriced_names)} of {len(positions)} priced — "
                    f"{', '.join(t.removesuffix('.NS') for t in unpriced_names)} not valued, so "
                    "the account is worth MORE than this"
                ),
                delta=None if not unpriced_names else "incomplete",
                delta_tone="neutral" if not unpriced_names else "warn",
            ),
            ui.Tile(
                label="Cash",
                value=ui.inr(account.cash),
                note="uninvested — not part of Equity",
            ),
            ui.Tile(
                label="Unrealised P&L",
                value=ui.signed_inr(unrealised),
                delta=(
                    f"{ui.delta_glyph(unrealised)} {ui.pct(float(unrealised / cost * 100))}"
                    if cost > 0
                    else None
                ),
                delta_tone=ui.tone_for(unrealised),
                note=f"on {ui.inr(cost)} of cost basis",
            ),
            ui.Tile(
                label="This month's allowance",
                value=ui.inr(allowance.remaining),
                note=f"of {ui.inr(allowance.authorised)} — the rest is committed or spent",
            ),
        ]
    )

    strip = ui.strip(
        [
            ("Generated", f"{ist:%d %b %Y, %H:%M} IST"),
            ("Account", "reconciled ✓" if account.tallies else "does NOT tally — see below"),
            ("Tax", "exact (dated FIFO lots)" if account.tax_exact else "estimated"),
            ("Orders", "you place every one, in Kite — nothing here trades"),
        ]
    )

    warnings = ""
    report_lines = account.report().splitlines()[1:]  # the first line is the tile row's content
    if report_lines or notes:
        items = "".join(f"<p>{escape(line)}</p>" for line in [*report_lines, *notes])
        warnings = f'<div class="qa-note">{items}</div>'

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Q-Alpha — {ist:%d %b %Y}</title>
{ui.stylesheet()}
<style>
  body {{ margin:0; padding:18px 22px 60px; background:var(--qa-plane); }}
  .qa-wrap {{ max-width:1180px; margin:0 auto; }}
  .qa-note {{ border:1px solid var(--qa-line); border-left:3px solid var(--qa-warn);
    background:var(--qa-surface); border-radius:3px; padding:.6rem .85rem; margin:.6rem 0;
    font-size:.8rem; color:var(--qa-ink-2); }}
  .qa-note p {{ margin:.25rem 0; }}
  p {{ font-size:.84rem; color:var(--qa-ink-2); line-height:1.5; }}
  .qa-foot {{ font-size:.74rem; color:var(--qa-muted); line-height:1.55; margin:.35rem 0 1rem; }}
  .qa-note ul {{ margin:.2rem 0 .5rem 1.1rem; padding:0; }}
  .qa-note li {{ margin:.15rem 0; }}
</style>
</head><body><div class="qa-wrap">
{
        ui.app_bar(
            product="Q-Alpha",
            tagline="local run · read-only",
            chips=[
                ui.Chip(f"{ist:%d %b %H:%M} IST", tone="neutral", dot=False),
                ui.Chip(
                    "reconciled" if account.tallies else "not reconciled",
                    tone="good" if account.tallies else "warn",
                ),
                ui.Chip(
                    "read-only",
                    tone="info",
                    title="This page is a file. It cannot trade, and nothing that produced it can.",
                ),
            ],
        )
    }
{strip}
{tiles}
{warnings}
{ui.section("Holdings", note="marked at the run's prices")}
{_holdings_table(account, prices)}
{_desk_panel(desk)}
{_concerns_panel(desk)}
{ui.section("Today's basket", note="the screen, sized to this month's allowance")}
{_proposal_table(proposal, allowance)}
{ui.section("What the run decided")}
{_decisions(commitments, allowance, ist.date())}
<p style="margin-top:2rem;color:var(--qa-muted);font-size:.72rem">
Everything here is as of the run that wrote this file — {ist:%d %b %Y, %H:%M} IST. It does not
update on its own. Run again for a newer page.</p>
</div></body></html>
"""
