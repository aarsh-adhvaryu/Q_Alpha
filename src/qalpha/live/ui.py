"""The dashboard's visual layer — an instrument panel, not a report.

Everything here is **pure**: it takes numbers and labels and returns HTML or CSS strings. No
Streamlit import, no network, no I/O — so every piece is unit-testable and none of it can change a
figure. That separation is the point: this module decides how a number *looks*, never what it is.

The look is a trading terminal (Zerodha Kite is the reference): a dark instrument bar across the
top, dense hairline-ruled sections, small uppercase labels, and numbers in tabular figures so
columns align down the page. Colour is never the only carrier of meaning — every gain/loss cue
ships a ``▲``/``▼`` glyph and every status chip ships its own word, per the accessibility rule that
a colour-blind reader must lose nothing.

Palette (validated defaults, light surface):

    ink        #0b0b0b / #52514e / #898781      hairlines  #e1e0d9 / #c3c2b7
    accent     #2a78d6 (blue)                   bar        #16181d
    good       #0ca30c (mark) · #006300 (text)  bad        #d03b3b
    warning    #fab219                          serious    #ec835a

The status steps are reserved: they mean state, never "series 4". The one categorical pair on this
page (the equity curve vs the index) uses blue ``#2a78d6`` against muted ``#898781``, so the book is
the thing the eye lands on and the benchmark recedes behind it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from html import escape
from typing import Literal

Tone = Literal["neutral", "good", "warn", "serious", "bad", "info"]
"""What a chip / cell / delta *means*. Never decorative — `warn` and `bad` are reserved for state."""

Align = Literal["left", "right"]

IST = timezone(timedelta(hours=5, minutes=30))

# --- tokens -----------------------------------------------------------------------------------
# Kept as Python constants as well as CSS variables so callers (charts, Streamlit widgets that take
# an explicit colour) draw from exactly the same palette the stylesheet does.
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
LINE = "#e1e0d9"
LINE_2 = "#c3c2b7"
SURFACE = "#ffffff"
PLANE = "#f4f4f2"
BAR = "#16181d"
ACCENT = "#2a78d6"
GOOD = "#0ca30c"
GOOD_INK = "#006300"  # 4.5:1 on white — GOOD itself is a mark colour, not a text colour
WARN = "#fab219"
SERIOUS = "#ec835a"
BAD = "#d03b3b"

SERIES_BOOK = ACCENT  # the portfolio's own line
SERIES_BENCH = MUTED  # the index it is measured against — recessive by design

_TONE_INK: dict[str, str] = {
    "neutral": INK_2,
    "good": GOOD_INK,
    "warn": "#8a6100",  # the warning step is 1.79:1 on white; its text form is darkened
    "serious": "#9c4a24",
    "bad": BAD,
    "info": ACCENT,
}
_TONE_MARK: dict[str, str] = {
    "neutral": LINE_2,
    "good": GOOD,
    "warn": WARN,
    "serious": SERIOUS,
    "bad": BAD,
    "info": ACCENT,
}


# --- formatters -------------------------------------------------------------------------------
def inr(value: Decimal | float | int, *, decimals: int = 0) -> str:
    """Rupees, western grouping — the same grouping every existing figure on the page already uses.

    Deliberately *not* Indian lakh grouping: mixing ``₹5,00,000`` in a tile with ``₹500,000`` in the
    caption under it would be two spellings of one number on one screen, which is the exact class of
    confusion this page exists to avoid. Switching is a one-line change here, and then it changes
    everywhere at once.
    """
    return f"₹{float(value):,.{decimals}f}"


def signed_inr(value: Decimal | float | int, *, decimals: int = 0) -> str:
    """Rupees with an explicit sign, the minus **leading** the symbol (``-₹1,234``, not ``₹-1,234``).

    Streamlit decides a metric's arrow and colour by looking at the first character of the delta
    string, so ``₹-1,234`` was read as a *rise*: a losing day drew a green up-arrow. Sign first is
    also simply how a human scans a column — the eye should not have to find the minus inside.
    """
    amount = float(value)
    return f"{'-' if amount < 0 else '+'}₹{abs(amount):,.{decimals}f}"


def pct(value: float, *, decimals: int = 2, signed: bool = True) -> str:
    return f"{value:+.{decimals}f}%" if signed else f"{value:.{decimals}f}%"


def delta_glyph(value: Decimal | float | int) -> str:
    """``▲``/``▼``/``■`` — the shape that carries direction when colour cannot."""
    amount = float(value)
    if amount > 0:
        return "▲"
    if amount < 0:
        return "▼"
    return "■"


def change_delta(value: Decimal | float | int, *, suffix: str = "") -> tuple[str, Tone]:
    """The delta line for a rupee change — glyph, sign-first amount, tone — composed in one place.

    It lives here rather than inline in the dashboard because that is where it went wrong: the live
    tile built its own delta string, ``f"₹{change:,.0f} today"``, and Streamlit read the leading
    ``₹`` as "not a minus" and drew a green up-arrow over a losing day. A one-line format decision
    that no test could reach. Now the composition is a function, and the test below is its caller.
    """
    return f"{delta_glyph(value)} {signed_inr(value)}{suffix}", tone_for(value)


def tone_for(value: Decimal | float | int) -> Tone:
    amount = float(value)
    if amount > 0:
        return "good"
    if amount < 0:
        return "bad"
    return "neutral"


# --- market clock -----------------------------------------------------------------------------
@dataclass(frozen=True)
class MarketClock:
    """Where the IST wall clock sits relative to NSE's session — a clock fact, not a feed fact."""

    label: str
    tone: Tone
    note: str


_PRE_OPEN = time(9, 0)
_OPEN = time(9, 15)
_CLOSE = time(15, 30)


def market_clock(now: datetime) -> MarketClock:
    """The session strip's clock chip.

    It says where the clock is, **not** that the exchange is trading: holidays are not checked, and
    inventing a holiday calendar to state "closed" would be substituting a guess for something this
    process does not know. So the label is ``MARKET HOURS``, the note says what it does not cover,
    and nothing downstream reads it.
    """
    ist = now.astimezone(IST)
    note = "IST clock only — trading holidays are not checked, so this is the session window, not a feed status."
    if ist.weekday() >= 5:
        return MarketClock("WEEKEND", "neutral", note)
    clock = ist.time()
    if clock < _PRE_OPEN:
        return MarketClock("PRE-MARKET", "neutral", note)
    if clock < _OPEN:
        return MarketClock("PRE-OPEN", "warn", note)
    if clock < _CLOSE:
        return MarketClock("MARKET HOURS", "good", note)
    return MarketClock("AFTER HOURS", "neutral", note)


# --- components -------------------------------------------------------------------------------
@dataclass(frozen=True)
class Chip:
    """A small state pill. The word carries the meaning; the colour only reinforces it."""

    label: str
    tone: Tone = "neutral"
    title: str | None = None
    dot: bool = True


@dataclass(frozen=True)
class Tile:
    """One figure in the instrument row: what it is, what it reads, and what it is measured against."""

    label: str
    value: str
    delta: str | None = None
    delta_tone: Tone = "neutral"
    note: str | None = None


@dataclass(frozen=True)
class Column:
    label: str
    align: Align = "left"


@dataclass(frozen=True)
class Cell:
    text: str
    tone: Tone = "neutral"
    strong: bool = False
    title: str | None = None


@dataclass(frozen=True)
class Row:
    cells: Sequence[Cell]
    muted: bool = False


def _attr(name: str, value: str | None) -> str:
    return f' {name}="{escape(value, quote=True)}"' if value else ""


def chip(item: Chip) -> str:
    dot = f'<i class="qa-dot" style="background:{_TONE_MARK[item.tone]}"></i>' if item.dot else ""
    return (
        f'<span class="qa-chip qa-{item.tone}"{_attr("title", item.title)}>'
        f"{dot}{escape(item.label)}</span>"
    )


def app_bar(*, product: str, tagline: str, chips: Sequence[Chip] = ()) -> str:
    """The dark instrument bar. One line of HTML — Streamlit's markdown must not reflow it."""
    right = "".join(chip(c) for c in chips)
    return (
        '<div class="qa-bar">'
        f'<div class="qa-bar-id"><span class="qa-mark">{escape(product)}</span>'
        f'<span class="qa-tagline">{escape(tagline)}</span></div>'
        f'<div class="qa-bar-chips">{right}</div>'
        "</div>"
    )


def strip(items: Sequence[tuple[str, str]]) -> str:
    """A hairline key/value strip — the row of small facts that sits under the bar."""
    cells = "".join(
        f'<div class="qa-strip-cell"><span class="qa-k">{escape(k)}</span>'
        f'<span class="qa-v">{escape(v)}</span></div>'
        for k, v in items
    )
    return f'<div class="qa-strip">{cells}</div>'


def tile_row(tiles: Sequence[Tile]) -> str:
    """The instrument row. Values use tabular figures so they stay aligned as prices tick."""
    out = []
    for t in tiles:
        delta = (
            f'<div class="qa-tile-delta qa-{t.delta_tone}">{escape(t.delta)}</div>'
            if t.delta
            else ""
        )
        note = f'<div class="qa-tile-note">{escape(t.note)}</div>' if t.note else ""
        out.append(
            f'<div class="qa-tile"><div class="qa-tile-label">{escape(t.label)}</div>'
            f'<div class="qa-tile-value">{escape(t.value)}</div>{delta}{note}</div>'
        )
    return f'<div class="qa-tiles">{"".join(out)}</div>'


def section(label: str, *, note: str | None = None) -> str:
    """A small uppercase heading with a hairline running to the right margin."""
    tail = f'<span class="qa-section-note">{escape(note)}</span>' if note else ""
    return (
        f'<div class="qa-section"><span class="qa-section-label">{escape(label)}</span>'
        f'{tail}<span class="qa-rule"></span></div>'
    )


def table(
    columns: Sequence[Column],
    rows: Sequence[Row],
    *,
    footer: Row | None = None,
    empty: str = "Nothing held.",
) -> str:
    """A dense HTML table: hairline rules, tabular figures, numbers right-aligned.

    Right-alignment is not decoration — a column of rupee amounts is compared by scanning the
    magnitudes, and left-aligned money makes ``₹9,900`` and ``₹99,000`` look the same length.
    """
    if not rows:
        return f'<div class="qa-empty">{escape(empty)}</div>'
    head = "".join(f'<th class="qa-{c.align}">{escape(c.label)}</th>' for c in columns)
    body = []
    for row in rows:
        tds = []
        for col, cell in zip(columns, row.cells, strict=False):
            cls = f"qa-{col.align} qa-{cell.tone}" + (" qa-strong" if cell.strong else "")
            tds.append(f'<td class="{cls}"{_attr("title", cell.title)}>{escape(cell.text)}</td>')
        cls = ' class="qa-muted-row"' if row.muted else ""
        body.append(f"<tr{cls}>{''.join(tds)}</tr>")
    foot = ""
    if footer is not None:
        foot_tds = "".join(
            f'<td class="qa-{col.align} qa-{cell.tone} qa-strong">{escape(cell.text)}</td>'
            for col, cell in zip(columns, footer.cells, strict=False)
        )
        foot = f"<tfoot><tr>{foot_tds}</tr></tfoot>"
    return (
        '<div class="qa-table-wrap"><table class="qa-table">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>{foot}</table></div>"
    )


@dataclass(frozen=True)
class Legend:
    """Series identity for a chart, spelled out — a legend is present whenever ≥2 series are drawn."""

    entries: Sequence[tuple[str, str]] = field(default_factory=tuple)


def legend(entries: Sequence[tuple[str, str]]) -> str:
    items = "".join(
        f'<span class="qa-legend-item"><i class="qa-swatch" style="background:{escape(colour, quote=True)}">'
        f"</i>{escape(name)}</span>"
        for name, colour in entries
    )
    return f'<div class="qa-legend">{items}</div>'


# --- stylesheet -------------------------------------------------------------------------------
def stylesheet() -> str:
    """The whole page's CSS, including the overrides that make Streamlit's own chrome read as dense.

    Every selector is defensive: if Streamlit renames a test id the rule simply stops matching and
    the page degrades to Streamlit's own styling rather than breaking. Nothing here is load-bearing
    for a number.
    """
    return f"""<style>
:root {{
  --qa-ink:{INK}; --qa-ink-2:{INK_2}; --qa-muted:{MUTED};
  --qa-line:{LINE}; --qa-line-2:{LINE_2};
  --qa-surface:{SURFACE}; --qa-plane:{PLANE}; --qa-bar:{BAR};
  --qa-accent:{ACCENT}; --qa-good:{GOOD}; --qa-good-ink:{GOOD_INK};
  --qa-warn:{WARN}; --qa-serious:{SERIOUS}; --qa-bad:{BAD};
  --qa-sans: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
  --qa-num: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
}}

/* ---- page plane: tighter than Streamlit's default, wider, and flat ---- */
html, body, [data-testid="stAppViewContainer"] {{ background: var(--qa-plane); }}
[data-testid="stHeader"] {{ background: transparent; height: 2.25rem; }}
[data-testid="stMainBlockContainer"], .block-container {{
  padding: 0.6rem 1.6rem 4rem; max-width: 1480px;
}}
[data-testid="stAppViewContainer"] * {{ font-family: var(--qa-sans); }}
[data-testid="stSidebar"] {{ background: var(--qa-surface); border-right: 1px solid var(--qa-line); }}
[data-testid="stVerticalBlock"] {{ gap: 0.55rem; }}
[data-testid="stHorizontalBlock"] {{ gap: 0.75rem; }}
hr, [data-testid="stDivider"] hr {{ border-color: var(--qa-line); margin: 0.85rem 0; }}

/* ---- the instrument bar ---- */
.qa-bar {{
  display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:.5rem;
  background: var(--qa-bar); color:#fff; padding:.55rem .9rem; border-radius:3px;
  margin: 0 0 .55rem;
}}
.qa-bar-id {{ display:flex; align-items:baseline; gap:.6rem; min-width:0; }}
.qa-mark {{ font-size:1.02rem; font-weight:700; letter-spacing:.09em; text-transform:uppercase; }}
.qa-tagline {{ font-size:.72rem; color:#b8b7b1; letter-spacing:.02em; }}
.qa-bar-chips {{ display:flex; align-items:center; gap:.4rem; flex-wrap:wrap; }}
.qa-bar .qa-chip {{ background:rgba(255,255,255,.07); border-color:rgba(255,255,255,.16); color:#e9e8e3; }}
.qa-bar .qa-chip.qa-good {{ color:#7ee08a; }}
.qa-bar .qa-chip.qa-warn {{ color:#f4c65e; }}
.qa-bar .qa-chip.qa-bad {{ color:#ff9a97; }}

/* ---- chips ---- */
.qa-chip {{
  display:inline-flex; align-items:center; gap:.34rem; padding:.16rem .45rem; border-radius:2px;
  border:1px solid var(--qa-line); background:var(--qa-surface); color:var(--qa-ink-2);
  font-size:.68rem; font-weight:600; letter-spacing:.07em; text-transform:uppercase;
  white-space:nowrap;
}}
.qa-dot {{ width:6px; height:6px; border-radius:50%; display:inline-block; flex:0 0 auto; }}

/* ---- key/value strip ---- */
.qa-strip {{
  display:flex; flex-wrap:wrap; gap:0; border:1px solid var(--qa-line); border-radius:3px;
  background:var(--qa-surface); margin-bottom:.6rem; overflow:hidden;
}}
.qa-strip-cell {{
  display:flex; flex-direction:column; gap:.1rem; padding:.4rem .8rem; min-width:0;
  border-right:1px solid var(--qa-line); flex:1 1 auto;
}}
.qa-strip-cell:last-child {{ border-right:0; }}
.qa-k {{ font-size:.62rem; letter-spacing:.09em; text-transform:uppercase; color:var(--qa-muted); }}
.qa-v {{ font-size:.8rem; color:var(--qa-ink); font-variant-numeric: tabular-nums; }}

/* ---- instrument tiles ---- */
.qa-tiles {{ display:flex; flex-wrap:wrap; gap:0; border:1px solid var(--qa-line);
  border-radius:3px; background:var(--qa-surface); overflow:hidden; margin-bottom:.55rem; }}
.qa-tile {{ flex:1 1 160px; min-width:0; padding:.6rem .9rem .65rem;
  border-right:1px solid var(--qa-line); }}
.qa-tile:last-child {{ border-right:0; }}
.qa-tile-label {{ font-size:.63rem; letter-spacing:.1em; text-transform:uppercase;
  color:var(--qa-muted); margin-bottom:.2rem; }}
.qa-tile-value {{ font-size:1.35rem; line-height:1.15; font-weight:650; color:var(--qa-ink);
  font-variant-numeric: tabular-nums; }}
.qa-tile-delta {{ font-size:.76rem; font-weight:600; margin-top:.12rem;
  font-variant-numeric: tabular-nums; }}
.qa-tile-note {{ font-size:.68rem; color:var(--qa-muted); margin-top:.18rem; line-height:1.35; }}

/* ---- semantic ink ---- */
.qa-good {{ color:var(--qa-good-ink); }}
.qa-bad {{ color:var(--qa-bad); }}
.qa-warn {{ color:{_TONE_INK["warn"]}; }}
.qa-serious {{ color:{_TONE_INK["serious"]}; }}
.qa-info {{ color:var(--qa-accent); }}
.qa-neutral {{ color:var(--qa-ink-2); }}

/* ---- section rules ---- */
.qa-section {{ display:flex; align-items:center; gap:.55rem; margin:.9rem 0 .45rem; }}
.qa-section-label {{ font-size:.7rem; font-weight:700; letter-spacing:.13em;
  text-transform:uppercase; color:var(--qa-ink); white-space:nowrap; }}
.qa-section-note {{ font-size:.7rem; color:var(--qa-muted); white-space:nowrap; }}
.qa-rule {{ flex:1 1 auto; height:1px; background:var(--qa-line); }}

/* ---- tables ---- */
.qa-table-wrap {{ border:1px solid var(--qa-line); border-radius:3px; overflow-x:auto;
  background:var(--qa-surface); }}
.qa-table {{ width:100%; border-collapse:collapse; font-size:.78rem; }}
.qa-table thead th {{ background:#fafaf8; color:var(--qa-muted); font-weight:600;
  font-size:.63rem; letter-spacing:.09em; text-transform:uppercase; padding:.42rem .7rem;
  border-bottom:1px solid var(--qa-line); white-space:nowrap; }}
.qa-table tbody td {{ padding:.4rem .7rem; border-bottom:1px solid var(--qa-line);
  color:var(--qa-ink); white-space:nowrap; font-variant-numeric: tabular-nums; }}
.qa-table tbody tr:last-child td {{ border-bottom:0; }}
.qa-table tbody tr:hover td {{ background:#f7f9fc; }}
.qa-table tfoot td {{ padding:.42rem .7rem; border-top:1px solid var(--qa-line-2);
  background:#fafaf8; font-variant-numeric: tabular-nums; }}
.qa-table .qa-right {{ text-align:right; }}
.qa-table .qa-left {{ text-align:left; }}
.qa-table .qa-strong {{ font-weight:650; }}
.qa-table .qa-muted-row td {{ color:var(--qa-muted); }}
.qa-empty {{ border:1px dashed var(--qa-line-2); border-radius:3px; padding:.75rem;
  color:var(--qa-muted); font-size:.78rem; background:var(--qa-surface); }}

/* ---- legend ---- */
.qa-legend {{ display:flex; gap:.9rem; flex-wrap:wrap; font-size:.72rem; color:var(--qa-ink-2);
  margin:.15rem 0 .1rem; }}
.qa-legend-item {{ display:inline-flex; align-items:center; gap:.35rem; }}
.qa-swatch {{ width:11px; height:3px; border-radius:1px; display:inline-block; }}

/* ---- Streamlit chrome, made dense ---- */
[data-testid="stMetric"] {{
  background: var(--qa-surface); border:1px solid var(--qa-line); border-radius:3px;
  padding:.55rem .8rem .6rem;
}}
[data-testid="stMetricLabel"] p {{ font-size:.63rem !important; letter-spacing:.1em;
  text-transform:uppercase; color:var(--qa-muted) !important; }}
[data-testid="stMetricValue"] {{ font-size:1.35rem !important; font-weight:650;
  font-variant-numeric: tabular-nums; color:var(--qa-ink); }}
[data-testid="stMetricDelta"] {{ font-size:.76rem !important; font-weight:600;
  font-variant-numeric: tabular-nums; }}

.stTabs [data-baseweb="tab-list"] {{ gap:0; border-bottom:1px solid var(--qa-line);
  background:transparent; }}
.stTabs [data-baseweb="tab"] {{ padding:.5rem .95rem; font-size:.75rem; font-weight:650;
  letter-spacing:.08em; text-transform:uppercase; color:var(--qa-muted); }}
.stTabs [aria-selected="true"] {{ color:var(--qa-ink); }}
.stTabs [data-baseweb="tab-highlight"] {{ background-color: var(--qa-accent); height:2px; }}
.stTabs [data-baseweb="tab-border"] {{ display:none; }}

[data-testid="stAlert"] {{ border-radius:2px; border-left:3px solid var(--qa-line-2);
  font-size:.8rem; padding:.5rem .75rem; }}
[data-testid="stAlertContentSuccess"] {{ border-left-color: var(--qa-good); }}
[data-testid="stAlertContentWarning"] {{ border-left-color: var(--qa-warn); }}
[data-testid="stAlertContentError"] {{ border-left-color: var(--qa-bad); }}
[data-testid="stAlertContentInfo"] {{ border-left-color: var(--qa-accent); }}

[data-testid="stExpander"] details {{ border:1px solid var(--qa-line); border-radius:3px;
  background: var(--qa-surface); }}
[data-testid="stExpander"] summary {{ font-size:.78rem; font-weight:600; }}

.stButton > button, .stDownloadButton > button {{ border-radius:2px; font-size:.78rem;
  font-weight:600; border:1px solid var(--qa-line-2); }}
.stButton > button[kind="primary"] {{ background: var(--qa-accent); border-color: var(--qa-accent); }}

[data-testid="stDataFrame"] {{ border-radius:3px; }}
[data-testid="stDataFrame"] > div {{
  --gdg-border-color: {LINE}; --gdg-horizontal-border-color: {LINE};
  --gdg-bg-header: #fafaf8; --gdg-bg-header-hovered: #f2f2ef;
  --gdg-text-header: {MUTED}; --gdg-text-dark: {INK}; --gdg-accent-color: {ACCENT};
  --gdg-font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --gdg-cell-horizontal-padding: 10;
}}

[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{
  font-size:.72rem; color:var(--qa-muted); line-height:1.45;
}}
[data-testid="stMarkdownContainer"] p {{ font-size:.84rem; }}
[data-testid="stMarkdownContainer"] h1 {{ font-size:1.25rem; letter-spacing:-.01em; }}
[data-testid="stMarkdownContainer"] h2 {{ font-size:1.02rem; }}
[data-testid="stMarkdownContainer"] h3 {{ font-size:.92rem; }}
[data-testid="stMarkdownContainer"] h4 {{ font-size:.82rem; letter-spacing:.06em;
  text-transform:uppercase; color:var(--qa-ink-2); }}
[data-testid="stMarkdownContainer"] table {{ font-size:.78rem; }}
[data-testid="stMarkdownContainer"] code {{ font-family: var(--qa-num); font-size:.76rem; }}
</style>"""
