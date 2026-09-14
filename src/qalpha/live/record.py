"""The page — the four books, what SYSTEM holds, and which filings were read.

**It reads. It does not compute.** Every figure comes from the file that produced it
(``data/twin/history.jsonl``, ``data/twin/books.json``, the price panels, the coverage log). A number
invented on a display surface is how every labelling defect in this repository started. The one
arithmetic it performs is ``quantity × mark``, and it says so on the page.

**No chart library.** Served from ``127.0.0.1`` and meant to work unplugged: SVG drawn by vanilla
JavaScript over a JSON blob inlined into the page, so the data and the drawing stay separable.

**A sparse series is drawn as points, not a line**, with its observation count beside it. Two dots
joined read as a trend; they are two dots.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from qalpha.live.twin import BASELINE, BASELINE_EW, EVALUATION_START, REAL, SYSTEM, is_autonomous

HISTORY = Path("data/twin/history.jsonl")
BOOKS = Path("data/twin/books.json")
MARKS = Path("data/twin/marks.json")
WATCHLIST = Path("data/universes/nifty100_watchlist.csv")
MANAGER = Path("data/twin/manager")

#: Below this many distinct observations a series is drawn as points and labelled with its count.
#: Two dots joined by a line read as a trend; they are two dots.
MIN_FOR_A_LINE = 5

BOOK_ORDER = (SYSTEM, BASELINE_EW, BASELINE, REAL)
BOOK_NOTE = {
    SYSTEM: "the AI investor's paper book",
    BASELINE_EW: "the equal-weight index fund, charged 0.41%/yr — the bar",
    BASELINE: "NIFTYBEES bought and held — the do-nothing floor, never the bar",
    REAL: "your tradebook replayed — what you actually did",
}


@dataclass(frozen=True)
class Holding:
    ticker: str
    quantity: float
    cost: float
    mark: float | None

    @property
    def value(self) -> float | None:
        return None if self.mark is None else self.mark * self.quantity

    @property
    def pnl(self) -> float | None:
        v = self.value
        return None if v is None else v - self.cost * self.quantity


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _sectors() -> dict[str, str]:
    if not WATCHLIST.exists():
        return {}
    with WATCHLIST.open(encoding="utf-8-sig", newline="") as fh:
        return {
            str(r["ticker"]).strip(): str(r.get("sector", "?")).strip()
            for r in csv.DictReader(fh)
            if r.get("ticker")
        }


def _holdings() -> list[Holding]:
    """SYSTEM's lots, valued at the marks the twin step wrote. Never re-priced here."""
    if not BOOKS.exists():
        return []
    try:
        saved = json.loads(BOOKS.read_text(encoding="utf-8"))
        lots = saved["books"][SYSTEM]["portfolio"]["lots"]
    except (OSError, ValueError, KeyError):
        return []
    marks = _last_closes()
    merged: dict[str, tuple[float, float]] = {}
    for lot in lots:
        try:
            ticker = str(lot["ticker"])
            qty = float(Decimal(str(lot["quantity_remaining"])))
            px = float(Decimal(str(lot["buy_price"])))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
        if qty <= 0:
            continue
        held, spent = merged.get(ticker, (0.0, 0.0))
        merged[ticker] = (held + qty, spent + qty * px)
    return [
        Holding(ticker=t, quantity=q, cost=(spent / q if q else 0.0), mark=marks.get(t))
        for t, (q, spent) in sorted(merged.items())
    ]


def _last_closes() -> dict[str, float]:
    """The last close each panel holds, per ticker.

    **`data/twin/marks.json` is not this.** It is a book-level summary — four rows of Book / Value /
    Gain — and reading it for per-name prices silently returned nothing, so every holding rendered
    unpriced. The prices live in the panels `live/panels.py` names, which is where the twin and the
    screen read them from too.

    The page says *"marked at the last close in the panel"* rather than "current price", because on
    a Saturday that close is Friday's and the two are not the same claim.
    """
    from qalpha.live.panels import NIFTY50_PANEL, WATCHLIST_PANEL

    out: dict[str, float] = {}
    for panel in (
        NIFTY50_PANEL,
        WATCHLIST_PANEL,
    ):  # watchlist second: it wins where both carry a name
        if not panel.exists():
            continue
        try:
            import pandas as pd

            frame = pd.read_parquet(panel)
            last = frame.sort_values("date").groupby("ticker")["close"].last()
        except (OSError, ValueError, KeyError, ImportError):
            continue
        for ticker, close in last.items():
            try:
                value = float(close)
            except (TypeError, ValueError):
                continue
            if value > 0:
                out[str(ticker)] = value
    return out


def _coverage(as_of: date) -> list[dict[str, Any]]:
    """Which held names were read, how much of each, and what could not be read.

    ``as_of`` is the page's own date, not ``today``: a page drawn for a past day must not count a
    coverage row written after it.
    """
    from qalpha.live.evidence_log import coverage

    held = sorted({h.ticker for h in _holdings()})
    if not held:
        return []
    found = coverage(held, as_of=as_of)
    return [
        {
            "ticker": t.removesuffix(".NS"),
            "opened": found[t.removesuffix(".NS")].opened,
            "complete": found[t.removesuffix(".NS")].complete,
            "documents": found[t.removesuffix(".NS")].read,
            "filings": found[t.removesuffix(".NS")].filed,
            "unread": [
                {"on": u["on"], "subject": u["subject"]}
                for u in found[t.removesuffix(".NS")].unread
            ],
        }
        for t in held
    ]


def _investor() -> dict[str, Any]:
    """What the investor last did, read from its own records. Absent records say so."""
    state: dict[str, Any] = {}
    if BOOKS.exists():
        try:
            state = (
                json.loads(BOOKS.read_text(encoding="utf-8"))["books"][SYSTEM].get("manager") or {}
            )
        except (OSError, ValueError, KeyError):
            state = {}
    notes: dict[str, dict[str, str]] = {}
    for row in _rows(MANAGER / "logbook.jsonl"):
        notes[str(row.get("ticker", ""))] = {
            "on": str(row.get("as_of")),
            "note": str(row.get("note")),
        }
    decided = _rows(MANAGER / "decisions.jsonl")
    last_day = max((str(r.get("as_of")) for r in decided), default="")
    card: dict[str, Any] = {}
    if (MANAGER / "scorecard.json").exists():
        try:
            card = json.loads((MANAGER / "scorecard.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            card = {}
    return {
        "state": state,
        "notes": notes,
        "last_decisions": [r for r in decided if str(r.get("as_of")) == last_day],
        "scorecard": card.get("decisions", []),
    }


def dashboard_data(as_of: date | None = None) -> dict[str, Any]:
    """Everything the page draws, read from the files that produced it."""
    today = as_of or date.today()
    history = _rows(HISTORY)
    # Append-only, one row per run: later rows supersede earlier ones for the same day.
    by_day: dict[str, dict[str, Any]] = {}
    for row in history:
        day = str(row.get("as_of", ""))
        if day:
            by_day[day] = row

    series: dict[str, list[dict[str, float | str]]] = {}
    for day in sorted(by_day):
        books = by_day[day].get("books", {})
        if not isinstance(books, dict):
            continue
        for name, fields in books.items():
            try:
                value = float(str(fields.get("value", "nan")))
                invested = float(str(fields.get("net_invested", "nan")))
            except (TypeError, ValueError):
                continue
            if value != value:
                continue
            series.setdefault(str(name), []).append(
                {"date": day, "value": value, "invested": invested}
            )

    sector_of = _sectors()
    holdings = _holdings()
    sectors: dict[str, float] = {}
    for h in holdings:
        v = h.value
        if v is not None:
            sectors[sector_of.get(h.ticker, "?")] = (
                sectors.get(sector_of.get(h.ticker, "?"), 0.0) + v
            )

    latest_day = max(by_day) if by_day else ""
    latest_books = by_day.get(latest_day, {}).get("books", {}) if latest_day else {}
    books_now = []
    for name in BOOK_ORDER:
        fields = latest_books.get(name) if isinstance(latest_books, dict) else None
        if not isinstance(fields, dict):
            continue
        try:
            books_now.append(
                {
                    "name": name,
                    "value": float(str(fields.get("value", "nan"))),
                    "invested": float(str(fields.get("net_invested", "nan"))),
                    "xirr": float(str(fields.get("xirr", "nan"))),
                    # Absent on rows written before cash was recorded: unknown, not zero.
                    "cash": (
                        float(str(fields["cash"])) if fields.get("cash") is not None else None
                    ),
                    "note": BOOK_NOTE.get(name, ""),
                }
            )
        except (TypeError, ValueError):
            continue

    return {
        "as_of": today.isoformat(),
        "latest_day": latest_day,
        # None when no autonomous window is registered — never a countdown to a date that is not set.
        "evaluation_start": EVALUATION_START.isoformat() if EVALUATION_START else None,
        # **The session, not the calendar.** The twin steps SYSTEM on the day its prices come from,
        # so on a holiday that is the previous session. Asking `is_autonomous(today)` made the page
        # announce "deciding for itself" on the morning of a closed exchange while the book was
        # still mirroring REAL — the start date wearing the wrong date's label.
        "autonomous": is_autonomous(
            date.fromisoformat(latest_day) if latest_day else today,
        ),
        "days_to_start": (EVALUATION_START - today).days if EVALUATION_START else None,
        "books": books_now,
        "series": series,
        "holdings": [
            {
                "ticker": h.ticker.removesuffix(".NS"),
                "quantity": h.quantity,
                "cost": h.cost,
                "mark": h.mark,
                "value": h.value,
                "pnl": h.pnl,
                "sector": sector_of.get(h.ticker, "?"),
            }
            for h in holdings
        ],
        "sectors": [
            {"sector": k, "value": v} for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])
        ],
        "coverage": _coverage(today),
        "investor": _investor(),
        "min_for_a_line": MIN_FOR_A_LINE,
    }


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _kpis(data: dict[str, Any]) -> str:
    books = {b["name"]: b for b in data["books"]}
    sysb, bar = books.get(SYSTEM), books.get(BASELINE_EW)
    cells: list[tuple[str, str, str]] = []
    if sysb:
        gain = sysb["value"] - sysb["invested"]
        cells.append(("SYSTEM value", f"₹{sysb['value']:,.0f}", ""))
        cells.append(
            (
                "vs contributed",
                f"{'+' if gain >= 0 else '-'}₹{abs(gain):,.0f}",
                "up" if gain >= 0 else "down",
            )
        )
    if sysb and bar:
        gap = sysb["value"] - bar["value"]
        cells.append(
            (
                "vs the bar (EW fund)",
                f"{'+' if gap >= 0 else '-'}₹{abs(gap):,.0f}",
                "up" if gap >= 0 else "down",
            )
        )
    read = sum(1 for c in data["coverage"] if c["complete"])
    cells.append(
        (
            "filings read",
            f"{read} of {len(data['coverage'])}",
            "" if read == len(data["coverage"]) else "warn",
        )
    )
    return (
        '<div class="kpis">'
        + "".join(
            f'<div class="kpi"><div class="k">{_esc(k)}</div>'
            f'<div class="v {tone}">{_esc(v)}</div></div>'
            for k, v, tone in cells
        )
        + "</div>"
    )


def _banner(data: dict[str, Any]) -> str:
    if data["autonomous"]:
        return (
            '<div class="banner"><b>SYSTEM is deciding for itself.</b> It was seeded as an exact '
            f"copy of your tradebook and has chosen alone since {_esc(data['evaluation_start'])}. "
            "It does not have to hold what you hold, and it is not advice — nothing here "
            "places an order.</div>"
        )
    days = data["days_to_start"]
    if days is None:
        return (
            '<div class="banner"><b>SYSTEM is not deciding.</b> No start date is registered, so it '
            "mirrors your tradebook exactly. It will start only when the AI investor's own "
            "registration sets a date.</div>"
        )
    when = "tomorrow" if days == 1 else f"in {days} days" if days > 0 else "today"
    return (
        f'<div class="banner"><b>SYSTEM starts deciding {_esc(when)}</b> '
        f"({_esc(data['evaluation_start'])}). Until then it mirrors your tradebook exactly, so "
        "every later difference is a decision rather than a different starting point.</div>"
    )


def _holdings_table(data: dict[str, Any]) -> str:
    rows = []
    for h in sorted(data["holdings"], key=lambda x: -(x["value"] or 0)):
        if h["value"] is None:
            rows.append(
                f"<tr><td>{_esc(h['ticker'])}</td><td>{h['quantity']:,.0f}</td>"
                f'<td>₹{h["cost"]:,.2f}</td><td class="dim" colspan="3">'
                "no price in any panel — unpriced, not zero</td></tr>"
            )
            continue
        tone = "up" if (h["pnl"] or 0) >= 0 else "down"
        sign = "+" if (h["pnl"] or 0) >= 0 else "-"
        rows.append(
            f"<tr><td>{_esc(h['ticker'])}</td><td>{h['quantity']:,.0f}</td>"
            f"<td>₹{h['cost']:,.2f}</td><td>₹{h['mark']:,.2f}</td>"
            f"<td>₹{h['value']:,.0f}</td>"
            f'<td class="{tone}">{sign}₹{abs(h["pnl"] or 0):,.0f}</td>'
            f"<td>{_esc(h['sector'])}</td></tr>"
        )
    return (
        '<div class="scroll"><table><thead><tr><th>Name</th><th>Qty</th><th>Avg cost</th>'
        "<th>Mark</th><th>Value</th><th>P&amp;L</th><th>Sector</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _books_table(data: dict[str, Any]) -> str:
    """The four books in rupees, with cash shown beside value.

    The chart plots value, and value alone cannot distinguish a book that chose well from a book
    that simply had not spent its money while the market fell. The baselines hold no cash by
    construction; the investor holds it for months, because it may spend only ₹50,000 a month.
    """
    rows = []
    for b in data["books"]:
        gain = b["value"] - b["invested"]
        tone = "up" if gain >= 0 else "down"
        cash = (
            f"₹{b['cash']:,.0f}"
            if b.get("cash") is not None
            else '<span class="dim">not recorded</span>'
        )
        market = (
            f"₹{b['value'] - b['cash']:,.0f}"
            if b.get("cash") is not None
            else '<span class="dim">unknown</span>'
        )
        rows.append(
            f"<tr><td>{_esc(b['name'])}</td><td>₹{b['invested']:,.0f}</td>"
            f"<td>{market}</td><td>{cash}</td><td>₹{b['value']:,.0f}</td>"
            f'<td class="{tone}">{"+" if gain >= 0 else "-"}₹{abs(gain):,.0f}</td>'
            f'<td class="dim">{_esc(b["note"])}</td></tr>'
        )
    return (
        '<div class="scroll"><table><thead><tr><th>Book</th><th>Money in</th>'
        "<th>In the market</th><th>Cash</th><th>Worth</th><th>Gain</th><th></th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _coverage_chips(data: dict[str, Any]) -> str:
    out = []
    for c in data["coverage"]:
        if not c["opened"]:
            colour, label = "var(--down)", "never read"
        elif c["complete"]:
            colour, label = "var(--up)", f"{c['documents']}/{c['filings']} read"
        else:
            gaps = c["unread"]
            subjects = ", ".join(sorted({str(u["subject"]) for u in gaps})[:2]) or "unknown"
            colour = "var(--warn)"
            label = (
                f"{c['documents']}/{c['filings']} read · {len(gaps)} could not be read ({subjects})"
            )
        out.append(
            f'<span class="chip"><span class="dot" style="background:{colour}"></span>'
            f'<b>{_esc(c["ticker"])}</b> <span class="dim">{_esc(label)}</span></span>'
        )
    return "".join(out) or '<p class="dim">Nothing held.</p>'


def _investor_card(data: dict[str, Any]) -> str:
    inv = data["investor"]
    state = inv["state"]
    if not state and not inv["last_decisions"]:
        return (
            '<div class="card wide"><h2>The investor</h2><p class="note">It has not reviewed this '
            "book yet. Until a start date is registered, SYSTEM mirrors your holdings.</p></div>"
        )
    pending = state.get("pending")
    waiting = (
        "<p><b>Waiting to fill</b> at the next session's close: "
        + ", ".join(
            f"{_esc(o['action'])} {o['quantity']} {_esc(str(o['ticker']).removesuffix('.NS'))}"
            for o in pending["orders"]
        )
        + (
            f' <span class="warn">— {_esc(pending["waiting"])}</span>'
            if pending.get("waiting")
            else ""
        )
        + "</p>"
        if pending
        else ""
    )
    last = state.get("last_review") or {}
    rows = "".join(
        f"<tr><td>{_esc(str(r['ticker']).removesuffix('.NS'))}</td><td>{_esc(r['action'])}</td>"
        f"<td>{_esc(str(r.get('accepted_quantity', '')))}</td><td>{_esc(r.get('status', ''))}</td>"
        f'<td style="white-space:normal;text-align:left">{_esc(r.get("reason", ""))}</td></tr>'
        for r in inv["last_decisions"]
    )
    notes = "".join(
        f'<li><b>{_esc(t.removesuffix(".NS"))}</b> <span class="dim">{_esc(n["on"])}</span> — '
        f"{_esc(n['note'])}</li>"
        for t, n in sorted(inv["notes"].items())
        if t != "PORTFOLIO"
    )
    portfolio_note = inv["notes"].get("PORTFOLIO")

    def change(value: object) -> str:
        return "—" if value is None else f"{float(str(value)):+.2f}%"

    card = "".join(
        f"<tr><td>{_esc(r['as_of'])}</td><td>{_esc(str(r['ticker']).removesuffix('.NS'))}</td>"
        f"<td>{_esc(r['action'])}</td><td>{change(r['change_pct'])}</td>"
        f"<td>{r['high_events_since']}</td></tr>"
        for r in inv["scorecard"]
    )
    return f"""<div class="card wide"><h2>The investor</h2>
    <p class="note">{_esc(str(state.get("version", "")))} · {_esc(str(state.get("model", "")))} · last
     review {_esc(str(last.get("as_of", "—")))}. Its notes are its own beliefs, not evidence.</p>
    {waiting}
    {f"<p><b>Portfolio note</b> — {_esc(portfolio_note['note'])}</p>" if portfolio_note else ""}
    <div class="scroll"><table><thead><tr><th>Name</th><th>Decision</th><th>Qty</th><th>Status</th>
    <th style="text-align:left">Reason</th></tr></thead><tbody>{rows}</tbody></table></div>
    <h2 style="margin-top:14px">Latest note per name</h2><ul>{notes}</ul>
    <h2 style="margin-top:14px">How its decisions went</h2>
    <p class="note">Change is the close now against the close it saw. High events since: verified,
     high-materiality events recorded for that name after the decision.</p>
    <div class="scroll"><table><thead><tr><th>Decided</th><th>Name</th><th>Decision</th>
    <th>Change since</th><th>High events since</th></tr></thead><tbody>{card}</tbody></table></div>
    </div>"""


def dashboard_html(as_of: date | None = None, *, top: str = "", bottom: str = "") -> str:
    """The whole page: the data inlined, the charts drawn from it in the browser.

    ``top`` and ``bottom`` are HTML the app places around the record — its controls and run feed
    above, the task trail below — so the app and the saved file are one page, not two.
    """
    from qalpha.live.record_assets import CSS, JS

    data = dashboard_data(as_of)
    # `</` inside a <script> ends the block even within a JSON string, so it is split. Without this
    # any ticker or note containing "</" would truncate the page's data and the charts would vanish.
    blob = json.dumps(data).replace("</", "<\\/")
    n_books = max((len(v) for v in data["series"].values()), default=0)
    sparse = (
        f' <span class="dim">— {n_books} observation'
        f"{'' if n_books == 1 else 's'}; drawn as points until there are "
        f"{data['min_for_a_line']}</span>"
        if n_books < data["min_for_a_line"]
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Q-Alpha</title><style>{CSS}</style></head>
<body><div class="wrap">
<h1>Q-Alpha</h1>
<p class="sub">An AI investor&rsquo;s paper book, read from the files that produced it, as of
 {_esc(data["latest_day"] or "—")}. Nothing on this page places an order.</p>
{top}
{_banner(data)}
{_kpis(data)}
<div class="grid">
  <div class="card wide"><h2>The four books</h2>
    <p class="note">Same cash flows, same days. <b>BASELINE_EW is the bar</b>; NIFTYBEES is the
     do-nothing floor and never the bar.{sparse}</p>
    <div id="books-chart"></div><div class="legend" id="books-legend"></div>
    {_books_table(data)}
    <p class="note">The baselines hold <b>no cash</b> &mdash; they buy the fund with every rupee on
     the day it arrives. SYSTEM may spend at most &#8377;50,000 a month, so it sits on cash for
     months: that helps it when the market falls and costs it when the market rises, for no
     decision it made. Read any gap with the cash column beside it.</p></div>

  <div class="card"><h2>What SYSTEM holds</h2>
    <p class="note">Green is above cost, red below. Marked at the last close in the panel —
     on a non-trading day that is the previous session, which is not the same as "now".</p>
    <div id="holdings-chart"></div></div>

  <div class="card"><h2>Sector mix</h2>
    <p class="note">By value of what is held. The 30% cap applies to the book, not to one basket.</p>
    <div id="sector-chart"></div><div id="sector-legend" style="margin-top:10px"></div></div>

  {_investor_card(data)}

  <div class="card wide"><h2>Positions</h2>
    <p class="note">Quantity and average cost from the lot ledger; value is quantity × mark,
     the only arithmetic this page performs.</p>
    {_holdings_table(data)}</div>

  <div class="card wide"><h2>Filings read</h2>
    <p class="note"><b>Unread is not clean.</b> A name nobody has read tells you nothing about that
     company. A filing that was fetched and could not be read — a scanned newspaper page — is named
     here and shown to the investor, rather than the company being quietly set aside.</p>
    {_coverage_chips(data)}</div>
</div>
{bottom}
</div>
<script>window.__QALPHA__ = {blob};</script>
<script>{JS}</script>
</body></html>"""
