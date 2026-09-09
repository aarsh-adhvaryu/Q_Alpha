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

from qalpha.live import ui
from qalpha.live.account import ReconciledAccount
from qalpha.live.commitments import Allowance, Commitment, open_proposals, waiting


def _holdings_table(account: ReconciledAccount, prices: Mapping[str, Decimal]) -> str:
    columns = [
        ui.Column("Instrument"),
        ui.Column("Qty", "right"),
        ui.Column("Avg cost", "right"),
        ui.Column("Price", "right"),
        ui.Column("Value", "right"),
        ui.Column("P&L", "right"),
        ui.Column("% of equity", "right"),
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
    footer = ui.Row(
        cells=[
            ui.Cell(f"Total ({len(positions)} names)"),
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


def render(
    *,
    account: ReconciledAccount,
    prices: Mapping[str, Decimal],
    allowance: Allowance,
    commitments: Sequence[Commitment],
    generated_at: datetime,
    notes: Sequence[str] = (),
    proposal: Sequence[tuple[str, int, Decimal]] = (),
) -> str:
    """One self-contained page. No server, no network, no fonts to fetch — it opens from a file."""
    ist = generated_at.astimezone(ui.IST)
    positions = account.portfolio.positions()
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
                note=f"{len(positions)} name{'s' if len(positions) != 1 else ''}",
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
{ui.section("Today's basket", note="the screen, sized to this month's allowance")}
{_proposal_table(proposal, allowance)}
{ui.section("What the run decided")}
{_decisions(commitments, allowance, ist.date())}
<p style="margin-top:2rem;color:var(--qa-muted);font-size:.72rem">
Everything here is as of the run that wrote this file — {ist:%d %b %Y, %H:%M} IST. It does not
update on its own. Run again for a newer page.</p>
</div></body></html>
"""
