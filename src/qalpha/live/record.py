"""The page — the four books, what SYSTEM holds, and which filings were read.

**It reads. It does not compute.** Every figure comes from the file that produced it
(``data/twin/history.jsonl``, ``data/twin/books.json``, the price panels, the coverage log). A number
invented on a display surface is how every labelling defect in this repository started. Its
arithmetic is the brokerage-statement kind and is named on the page where it appears: quantity ×
mark, quantity × average price paid, their difference, and the change between the panel's last two
closes. Nothing it shows is an input to the investor, which never imports this module.

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
    #: The close of the panel's session before the mark's. ``None``: the name has no close on that
    #: session, so a day change would really be a change over more than one day.
    previous: float | None = None
    #: The session the mark is the close of.
    marked_on: str | None = None

    @property
    def value(self) -> float | None:
        return None if self.mark is None else self.mark * self.quantity

    @property
    def invested(self) -> float:
        return self.cost * self.quantity

    @property
    def pnl(self) -> float | None:
        v = self.value
        return None if v is None else v - self.invested

    @property
    def day_change(self) -> float | None:
        """Quantity × (last close − the close before). Unknown when either close is missing."""
        if self.mark is None or self.previous is None:
            return None
        return (self.mark - self.previous) * self.quantity


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
    closes = _closes()
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
        Holding(
            ticker=t,
            quantity=q,
            cost=(spent / q if q else 0.0),
            mark=closes[t][0] if t in closes else None,
            previous=closes[t][1] if t in closes else None,
            marked_on=closes[t][2] if t in closes else None,
        )
        for t, (q, spent) in sorted(merged.items())
    ]


def _last_closes() -> dict[str, float]:
    """The last close each panel holds, per ticker. See :func:`_closes`."""
    return {t: last for t, (last, _before, _on) in _closes().items()}


def _closes() -> dict[str, tuple[float, float | None, str]]:
    """``(last close, the close before it)`` per ticker, each from the panel that holds the name.

    **`data/twin/marks.json` is not this.** It is a book-level summary — four rows of Book / Value /
    Gain — and reading it for per-name prices silently returned nothing, so every holding rendered
    unpriced. The prices live in the panels `live/panels.py` names, which is where the twin and the
    screen read them from too.

    The page says *"marked at the last close in the panel"* rather than "current price", because on
    a Saturday that close is Friday's and the two are not the same claim.
    """
    from qalpha.live.panels import NIFTY50_PANEL, WATCHLIST_PANEL

    out: dict[str, tuple[float, float | None, str]] = {}
    for panel in (
        NIFTY50_PANEL,
        WATCHLIST_PANEL,
    ):  # watchlist second: it wins where both carry a name
        for ticker, pair in _panel_closes(panel).items():
            out[ticker] = pair
    return out


def _panel_closes(panel: Path) -> dict[str, tuple[float, float | None, str]]:
    """Per ticker: its last positive close, the close on the panel's session before that, and the date.

    The earlier close must be from the **panel's** previous session. A name missing a day would
    otherwise compare against a close two sessions back and call it a day's change.
    """
    if not panel.exists():
        return {}
    try:
        import pandas as pd

        frame = pd.read_parquet(panel, columns=["date", "ticker", "close"])
        frame["date"] = pd.to_datetime(frame["date"])
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        sessions = pd.Series(sorted(frame["date"].unique()))
        previous = dict(zip(sessions.iloc[1:], sessions.iloc[:-1], strict=True))
        good = frame[frame["close"] > 0]
        last = good.sort_values("date").groupby("ticker").tail(1).copy()
        # Vectorised, not a row loop: a panel is years of every name, and the page is drawn on
        # every request.
        last["before_on"] = last["date"].map(previous)
        joined = last.merge(
            good.rename(columns={"date": "before_on", "close": "before"}),
            on=["ticker", "before_on"],
            how="left",
        )
    except (OSError, ValueError, KeyError, ImportError, TypeError, AttributeError):
        return {}
    out: dict[str, tuple[float, float | None, str]] = {}
    for ticker, close, day, before in zip(
        joined["ticker"], joined["close"], joined["date"], joined["before"], strict=True
    ):
        prior = None if pd.isna(before) else float(str(before))
        out[str(ticker)] = (float(str(close)), prior, pd.Timestamp(str(day)).date().isoformat())
    return out


def _benchmark() -> dict[str, Any] | None:
    """NIFTYBEES's last two closes from the benchmark panel, with the last one's date."""
    from qalpha.live.panels import BENCHMARK_PANEL, BENCHMARK_TICKER

    if not BENCHMARK_PANEL.exists():
        return None
    try:
        import pandas as pd

        frame = pd.read_parquet(BENCHMARK_PANEL)
        frame = frame[pd.to_numeric(frame["close"], errors="coerce") > 0].sort_values("date")
        tail = frame.tail(2)
        if tail.empty:
            return None
        last = float(tail["close"].iloc[-1])
        before = float(tail["close"].iloc[0]) if len(tail) > 1 else None
        on = pd.Timestamp(tail["date"].iloc[-1]).date().isoformat()
    except (OSError, ValueError, KeyError, ImportError, TypeError, IndexError):
        return None
    return {
        "name": BENCHMARK_TICKER.removesuffix(".NS"),
        "close": last,
        "previous": before,
        "on": on,
    }


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
                "previous": h.previous,
                "marked_on": h.marked_on,
                "value": h.value,
                "invested": h.invested,
                "pnl": h.pnl,
                "day_change": h.day_change,
                "sector": sector_of.get(h.ticker, "?"),
            }
            for h in holdings
        ],
        "benchmark": _benchmark(),
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


def _short(n: float) -> str:
    """₹ in the way a brokerage page writes it: 2.01L, -11.28k. The exact figure sits beside it."""
    a = abs(n)
    sign = "-" if n < 0 else ""
    if a >= 1e7:
        return f"{sign}{a / 1e7:.2f}Cr"
    if a >= 1e5:
        return f"{sign}{a / 1e5:.2f}L"
    if a >= 1e3:
        return f"{sign}{a / 1e3:.2f}k"
    return f"{sign}{a:,.0f}"


def _signed(n: float, *, digits: int = 2) -> str:
    return f"{'+' if n >= 0 else '-'}₹{abs(n):,.{digits}f}"


def _tone(n: float | None) -> str:
    return "" if n is None else ("up" if n >= 0 else "down")


def _totals(data: dict[str, Any]) -> dict[str, Any]:
    """Sums over the holdings table. Any unpriced name makes the value-based sums unknown."""
    held = data["holdings"]
    invested = sum(h["invested"] for h in held)
    priced = all(h["value"] is not None for h in held)
    value = sum(h["value"] for h in held) if priced else None
    day_known = all(h["day_change"] is not None for h in held)
    day = sum(h["day_change"] for h in held) if day_known else None
    pnl = None if value is None else value - invested
    return {
        "invested": invested,
        "value": value,
        "pnl": pnl,
        "pnl_pct": None if pnl is None or not invested else pnl / invested * 100,
        "day": day,
        "day_pct": (
            None if day is None or value is None or not (value - day) else day / (value - day) * 100
        ),
    }


def _kpis(data: dict[str, Any]) -> str:
    """The four figures a holdings statement opens with, then the one that decides whether to bother."""
    t = _totals(data)
    books = {b["name"]: b for b in data["books"]}
    sysb, bar = books.get(SYSTEM), books.get(BASELINE_EW)

    def fig(label: str, value: str, tone: str = "", extra: str = "") -> str:
        return (
            f'<div class="fig"><div class="k">{_esc(label)}</div>'
            f'<div class="v {tone}">{value}{extra}</div></div>'
        )

    unknown = '<span class="dim">unknown</span>'
    cells = [
        fig("Total investment", f"₹{t['invested']:,.2f}"),
        fig("Current value", unknown if t["value"] is None else f"₹{t['value']:,.2f}"),
        fig(
            "Day's P&L",
            unknown if t["day"] is None else _signed(t["day"]),
            _tone(t["day"]),
            ""
            if t["day_pct"] is None
            else f'<span class="pill {_tone(t["day"])}">{t["day_pct"]:+.2f}%</span>',
        ),
        fig(
            "Total P&L",
            unknown if t["pnl"] is None else _signed(t["pnl"]),
            _tone(t["pnl"]),
            ""
            if t["pnl_pct"] is None
            else f'<span class="pill {_tone(t["pnl"])}">{t["pnl_pct"]:+.2f}%</span>',
        ),
    ]
    if sysb and bar:
        gap = sysb["value"] - bar["value"]
        cells.append(fig("vs the bar (EW fund)", _signed(gap, digits=0), _tone(gap)))
    read = sum(1 for c in data["coverage"] if c["complete"])
    cells.append(
        fig(
            "Filings read",
            f"{read} of {len(data['coverage'])}",
            "" if read == len(data["coverage"]) else "warn",
        )
    )
    return '<div class="figs">' + "".join(cells) + "</div>"


def _market_strip(data: dict[str, Any]) -> str:
    b = data.get("benchmark")
    if not b:
        return '<span class="dim">NIFTYBEES — no benchmark panel</span>'
    move = "" if b["previous"] is None else b["close"] - b["previous"]
    change = (
        '<span class="dim">no earlier close</span>'
        if move == ""
        else f'<span class="{_tone(float(move))}">{float(move):+.2f} '
        f"({float(move) / b['previous'] * 100:+.2f}%)</span>"
    )
    return (
        f'<b>{_esc(b["name"])}</b> <span class="{_tone(float(move) if move != "" else None)}">'
        f"{b['close']:,.2f}</span> {change} "
        f'<span class="dim">close of {_esc(b["on"])}</span>'
    )


def _marked_on(data: dict[str, Any]) -> str:
    """The close the holdings are marked at, in words. Two dates when the names disagree."""
    days = sorted({str(h["marked_on"]) for h in data["holdings"] if h.get("marked_on")})
    if not days:
        return "no close on record"
    return f"close of {days[0]}" if len(days) == 1 else f"closes of {days[0]} to {days[-1]}"


def _watchlist(data: dict[str, Any]) -> str:
    rows = []
    for h in sorted(data["holdings"], key=lambda x: x["ticker"]):
        if h["mark"] is None:
            rows.append(
                f'<div class="wl"><span class="nm">{_esc(h["ticker"])}</span>'
                f'<span class="dim">unpriced</span></div>'
            )
            continue
        move = None if h["previous"] is None else h["mark"] - h["previous"]
        pct = None if move is None or not h["previous"] else move / h["previous"] * 100
        tone = _tone(move)
        rows.append(
            f'<div class="wl"><span class="nm {tone}">{_esc(h["ticker"])}</span>'
            f'<span class="qty">{h["quantity"]:,.0f}</span>'
            f'<span class="dim">{"—" if move is None else f"{move:+.2f}"}</span>'
            f'<span class="{tone}">{"—" if pct is None else f"{pct:+.2f}%"}</span>'
            f'<span class="ltp {tone}">{h["mark"]:,.2f}</span></div>'
        )
    return (
        f'<div class="side-h">SYSTEM holdings ({len(data["holdings"])}) · '
        f"{_esc(_marked_on(data))}</div>"
        + ("".join(rows) or '<p class="dim pad">Nothing held.</p>')
        + '<p class="dim pad">Last close in the panel against the session before it. '
        "A paper book: nothing here places an order.</p>"
    )


def _allocation(data: dict[str, Any]) -> str:
    return (
        '<div class="alloc" data-alloc></div>'
        '<div class="alloc-foot"><span class="alloc-total" data-alloc-total></span>'
        '<span class="alloc-mode">'
        '<label><input type="radio" name="alloc-{id}" value="value" checked> Current value</label>'
        '<label><input type="radio" name="alloc-{id}" value="invested"> Invested</label>'
        "</span></div>"
    )


def _dashboard(data: dict[str, Any]) -> str:
    t = _totals(data)
    books = {b["name"]: b for b in data["books"]}
    sysb = books.get(SYSTEM)
    cash = None if not sysb or sysb.get("cash") is None else sysb["cash"]
    tiles = "".join(
        f'<div class="tile"><div class="k">{_esc(b["name"])}</div>'
        f'<div class="v">₹{_short(b["value"])}</div>'
        f'<div class="{_tone(b["value"] - b["invested"])}">'
        f"{_signed(b['value'] - b['invested'], digits=0)}</div>"
        f'<div class="dim small">{_esc(b["note"])}</div></div>'
        for b in data["books"]
    )
    decisions = data["investor"]["last_decisions"]
    tonight = (
        "".join(
            f'<div class="dec"><b>{_esc(str(r["ticker"]).removesuffix(".NS"))}</b>'
            f'<span class="tag">{_esc(r.get("action", ""))}</span>'
            f'<span class="dim">{_esc(r.get("status", ""))}</span></div>'
            for r in decisions
        )
        or '<p class="dim">No decision on record yet.</p>'
    )
    return f"""
<div class="duo">
  <div class="panel">
    <h3>Cash</h3>
    <div class="big">{"—" if cash is None else "₹" + _short(cash)}</div>
    <div class="dim">SYSTEM's uninvested cash{"" if cash is None else f" · ₹{cash:,.2f}"}</div>
    <div class="kv"><span>Money in</span><b>{"—" if not sysb else f"₹{sysb['invested']:,.0f}"}</b></div>
    <div class="kv"><span>In the market</span><b>{"unknown" if t["value"] is None else f"₹{t['value']:,.0f}"}</b></div>
  </div>
  <div class="panel">
    <h3>Holdings ({len(data["holdings"])})</h3>
    <div class="big {_tone(t["pnl"])}">{"unknown" if t["pnl"] is None else _short(t["pnl"])}
      <small>{"" if t["pnl_pct"] is None else f"{t['pnl_pct']:+.2f}%"}</small></div>
    <div class="dim">P&amp;L on the price paid, before charges · {_esc(_marked_on(data))}</div>
    <div class="kv"><span>Current value</span><b>{"unknown" if t["value"] is None else "₹" + _short(t["value"])}</b></div>
    <div class="kv"><span>Investment</span><b>₹{_short(t["invested"])}</b></div>
  </div>
</div>
<div class="panel">{_allocation(data).replace("{id}", "dash")}</div>
<h3 class="sec">Against the bar</h3>
<div class="tiles">{tiles or '<p class="dim">No book history yet.</p>'}</div>
<div class="duo">
  <div class="panel"><h3>The investor's last review</h3>{tonight}
    <p><a href="#investor">Reasons, notes and how its decisions went →</a></p></div>
  <div class="panel"><h3>Book values</h3>
    <p class="note">{sum(1 for _ in data["series"].get(SYSTEM, []))} observation(s) of SYSTEM; dots until
     there are {data["min_for_a_line"]}. <a href="#books">All four books →</a></p>
    <div id="overview-chart"></div></div>
</div>"""


def _holdings_tab(data: dict[str, Any]) -> str:
    t = _totals(data)
    unknown = '<span class="dim">unknown</span>'
    value = unknown if t["value"] is None else f"{t['value']:,.2f}"
    pnl = unknown if t["pnl"] is None else f"{t['pnl']:+,.2f}"
    pnl_pct = "" if t["pnl_pct"] is None else f"{t['pnl_pct']:+.2f}%"
    day = unknown if t["day"] is None else f"{t['day']:+,.2f}"
    total_row = (
        '<tr class="total"><td colspan="4">Total</td>'
        f"<td>{t['invested']:,.2f}</td><td>{value}</td>"
        f'<td class="{_tone(t["pnl"])}">{pnl}</td>'
        f'<td class="{_tone(t["pnl"])}">{pnl_pct}</td>'
        f'<td class="{_tone(t["day"])}">{day}</td>'
        "<td></td></tr>"
    )
    return f"""
{_kpis(data)}
<div class="panel"><h2>Positions</h2>
  <p class="note">Quantity and average price paid from the lot ledger (before charges). Current value
   is quantity × the last close in the panel ({_esc(_marked_on(data))}); day change is against the
   panel's session before it. Refresh prices for today's close.</p>
  {_holdings_table(data, total_row)}
  {_allocation(data).replace("{id}", "hold")}
</div>"""


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


def _holdings_table(data: dict[str, Any], total_row: str = "") -> str:
    rows = []
    for h in sorted(data["holdings"], key=lambda x: x["ticker"]):
        if h["value"] is None:
            rows.append(
                f"<tr><td>{_esc(h['ticker'])}</td><td>{h['quantity']:,.0f}</td>"
                f'<td>{h["cost"]:,.2f}</td><td class="dim" colspan="7">'
                "no price in any panel — unpriced, not zero</td></tr>"
            )
            continue
        net = h["pnl"] / h["invested"] * 100 if h["invested"] else None
        day_pct = (
            None
            if h["previous"] in (None, 0)
            else (h["mark"] - h["previous"]) / h["previous"] * 100
        )
        rows.append(
            f"<tr><td>{_esc(h['ticker'])}</td><td>{h['quantity']:,.0f}</td>"
            f"<td>{h['cost']:,.2f}</td><td>{h['mark']:,.2f}</td>"
            f"<td>{h['invested']:,.2f}</td><td>{h['value']:,.2f}</td>"
            f'<td class="{_tone(h["pnl"])}">{h["pnl"]:+,.2f}</td>'
            f'<td class="{_tone(net)}">{"—" if net is None else f"{net:+.2f}%"}</td>'
            f'<td class="{_tone(day_pct)}">{"—" if day_pct is None else f"{day_pct:+.2f}%"}</td>'
            f'<td class="dim">{_esc(h["sector"])}</td></tr>'
        )
    return (
        '<div class="scroll"><table class="hold"><thead><tr><th>Instrument</th><th>Qty.</th>'
        "<th>Avg. cost</th><th>Last close</th><th>Invested</th><th>Cur. val</th><th>P&amp;L</th>"
        "<th>Net chg.</th><th>Day chg.</th><th>Sector</th></tr></thead><tbody>"
        + "".join(rows)
        + total_row
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
        when = (
            f"It first reviews on the evening of {_esc(data['evaluation_start'])}; until then "
            "SYSTEM mirrors your holdings."
            if data["evaluation_start"]
            else "No start date is registered, so SYSTEM mirrors your holdings."
        )
        return (
            '<div class="card wide"><h2>The investor</h2><p class="note">It has not reviewed this '
            f"book yet. {when}</p></div>"
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

    ``top`` and ``bottom`` are HTML the app places around the record — its controls and run feed,
    and the task trail — shown under the Run tab, so the app and the saved file are one page.
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
    state = (
        '<span class="state on">Deciding</span>'
        if data["autonomous"]
        else '<span class="state">Mirroring your book</span>'
    )
    run = (
        top + bottom
        if top or bottom
        else '<p class="dim">This is a saved copy of the page. Open the Q-Alpha app to run an evening.</p>'
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Q-Alpha</title><style>{CSS}</style></head>
<body>
<header class="top">
  <div class="strip">{_market_strip(data)}</div>
  <div class="brand"><span class="mark" aria-hidden="true"></span>Q-Alpha</div>
  <nav class="tabs" aria-label="Sections">
    <a href="#dashboard">Dashboard</a><a href="#holdings">Holdings</a><a href="#investor">Investor</a>
    <a href="#books">Books</a><a href="#filings">Filings</a><a href="#run">Run</a>
  </nav>
  <div class="who">{state}<span class="dim">as of {_esc(data["latest_day"] or "—")}</span></div>
</header>
<div class="shell">
<aside class="side">{_watchlist(data)}</aside>
<main class="main">
<h1 class="sr">Q-Alpha</h1>
<p class="sub">An AI investor&rsquo;s paper book, read from the files that produced it, as of
 {_esc(data["latest_day"] or "—")}. Nothing on this page places an order.</p>
{_banner(data)}

<section class="tab" id="tab-dashboard">{_dashboard(data)}</section>

<section class="tab" id="tab-holdings">{_holdings_tab(data)}
  <div class="duo">
    <div class="panel"><h2>What SYSTEM holds</h2>
      <p class="note">Green is above the price paid, red below. Marked at the last close in the panel —
       on a non-trading day that is the previous session, which is not the same as "now".</p>
      <div id="holdings-chart"></div></div>
    <div class="panel"><h2>Sector mix</h2>
      <p class="note">By value of what is held. The 30% cap applies to the book, not to one basket.</p>
      <div id="sector-chart"></div><div id="sector-legend" style="margin-top:10px"></div></div>
  </div>
</section>

<section class="tab" id="tab-investor">{_investor_card(data)}</section>

<section class="tab" id="tab-books"><div class="panel"><h2>The four books</h2>
    <p class="note">Same cash flows, same days. <b>BASELINE_EW is the bar</b>; NIFTYBEES is the
     do-nothing floor and never the bar.{sparse}</p>
    <div id="books-chart"></div><div class="legend" id="books-legend"></div>
    {_books_table(data)}
    <p class="note">The baselines hold <b>no cash</b> &mdash; they buy the fund with every rupee on
     the day it arrives. SYSTEM may spend at most &#8377;50,000 a month, so it sits on cash for
     months: that helps it when the market falls and costs it when the market rises, for no
     decision it made. Read any gap with the cash column beside it.</p></div>
</section>

<section class="tab" id="tab-filings"><div class="panel"><h2>Filings read</h2>
    <p class="note"><b>Unread is not clean.</b> A name nobody has read tells you nothing about that
     company. A filing that was fetched and could not be read — a scanned newspaper page — is named
     here and shown to the investor, rather than the company being quietly set aside.</p>
    {_coverage_chips(data)}</div>
</section>

<section class="tab" id="tab-run">{run}</section>
</main>
</div>
<script>window.__QALPHA__ = {blob};</script>
<script>{JS}</script>
</body></html>"""
