"""Tests for the dashboard's visual layer (``qalpha.live.ui``).

These assert **properties of what reaches the screen**, not the strings a particular version of the
CSS happens to contain: that a sign is never hidden behind a currency symbol, that direction is
carried by shape as well as by colour, that a company name can never inject markup into the page,
and that the market chip states a clock fact rather than a claim about the exchange.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from qalpha.live import ui


# --- the defect this module was extracted to fix -----------------------------------------------
def test_a_losing_day_is_never_spelled_with_the_minus_hidden_behind_the_rupee_sign() -> None:
    """``₹-1,234`` was rendered by Streamlit as a RISE, because it decides the arrow by looking at
    the first character of the delta string — and that character was ``₹``. A losing day drew a
    green up-arrow on the real-money tile. Sign first, always."""
    assert ui.signed_inr(Decimal("-1234")) == "-₹1,234"
    assert ui.signed_inr(Decimal("1234")) == "+₹1,234"
    assert ui.signed_inr(Decimal("-1234")).startswith("-"), "Streamlit reads character one"


def test_the_change_line_carries_direction_in_its_shape_not_only_its_colour() -> None:
    down, down_tone = ui.change_delta(Decimal("-4200"), suffix=" today")
    up, up_tone = ui.change_delta(Decimal("4200"), suffix=" today")
    flat, flat_tone = ui.change_delta(Decimal("0"))

    assert down.startswith("▼") and "-₹4,200" in down and down.endswith(" today")
    assert up.startswith("▲") and "+₹4,200" in up
    assert flat.startswith("■"), "zero is neither a rise nor a fall"
    assert (down_tone, up_tone, flat_tone) == ("bad", "good", "neutral")


def test_glyph_and_tone_always_agree() -> None:
    """A ▲ tinted red, or a ▼ tinted green, would be two answers to one question."""
    for value in (-1e9, -0.01, 0.0, 0.01, 1e9):
        glyph, tone = ui.delta_glyph(value), ui.tone_for(value)
        assert (glyph == "▲") == (tone == "good")
        assert (glyph == "▼") == (tone == "bad")


# --- escaping ----------------------------------------------------------------------------------
_HOSTILE = '<img src=x onerror="alert(1)">'


def test_no_caller_supplied_text_can_inject_markup() -> None:
    """Every one of these renders text that came from a filing, a broker or a ticker symbol. The
    page draws them with ``unsafe_allow_html``, so escaping is the only thing standing between a
    stray ``<`` in an exchange feed and a broken — or hostile — page."""
    rendered = [
        ui.chip(ui.Chip(_HOSTILE, title=_HOSTILE)),
        ui.app_bar(product=_HOSTILE, tagline=_HOSTILE, chips=[ui.Chip(_HOSTILE)]),
        ui.strip([(_HOSTILE, _HOSTILE)]),
        ui.tile_row([ui.Tile(label=_HOSTILE, value=_HOSTILE, delta=_HOSTILE, note=_HOSTILE)]),
        ui.section(_HOSTILE, note=_HOSTILE),
        ui.table([ui.Column(_HOSTILE)], [ui.Row([ui.Cell(_HOSTILE, title=_HOSTILE)])]),
        ui.legend([(_HOSTILE, "#2a78d6")]),
    ]
    for html in rendered:
        # The hostile string must never survive verbatim: no live tag, and no quote left able to
        # close an attribute early. Escaped, it is inert text — ``onerror=&quot;`` is not a handler.
        assert _HOSTILE not in html, html[:160]
        assert "<img" not in html
        assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html


# --- tables ------------------------------------------------------------------------------------
def test_money_columns_are_right_aligned_and_the_totals_row_renders() -> None:
    """Left-aligned money makes ₹9,900 and ₹99,000 the same length to the eye."""
    columns = [ui.Column("Instrument"), ui.Column("Value", "right")]
    rows = [ui.Row([ui.Cell("TCS"), ui.Cell("₹1,00,000")])]
    html = ui.table(columns, rows, footer=ui.Row([ui.Cell("Total"), ui.Cell("₹1,00,000")]))

    assert '<th class="qa-right">Value</th>' in html
    assert '<th class="qa-left">Instrument</th>' in html
    assert html.count('class="qa-right') >= 3, "header, body cell and footer cell"
    assert "<tfoot>" in html


def test_an_empty_table_says_so_instead_of_drawing_an_empty_grid() -> None:
    html = ui.table([ui.Column("Instrument")], [], empty="No holdings on this book yet.")
    assert "No holdings on this book yet." in html
    assert "<tbody>" not in html


def test_a_cells_tone_reaches_its_class_so_a_loss_is_never_inked_as_a_gain() -> None:
    html = ui.table([ui.Column("P&L", "right")], [ui.Row([ui.Cell("▼ -₹400", tone="bad")])])
    assert "qa-bad" in html
    assert "qa-good" not in html


# --- the market chip ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("ist_clock", "label"),
    [
        ("2026-09-08 08:30", "PRE-MARKET"),
        ("2026-09-08 09:00", "PRE-OPEN"),
        ("2026-09-08 09:14", "PRE-OPEN"),
        ("2026-09-08 09:15", "MARKET HOURS"),
        ("2026-09-08 15:29", "MARKET HOURS"),
        ("2026-09-08 15:30", "AFTER HOURS"),
        ("2026-09-08 23:59", "AFTER HOURS"),
        ("2026-09-11 11:00", "MARKET HOURS"),  # Friday
        ("2026-09-12 11:00", "WEEKEND"),  # Saturday
        ("2026-09-13 11:00", "WEEKEND"),  # Sunday
    ],
)
def test_the_market_chip_tracks_the_ist_session_window(ist_clock: str, label: str) -> None:
    ist = datetime.fromisoformat(ist_clock).replace(tzinfo=ui.IST)
    assert ui.market_clock(ist).label == label


def test_the_market_chip_is_read_from_ist_whatever_clock_the_host_runs_on() -> None:
    """Streamlit Cloud runs in UTC. 09:20 IST is 03:50 UTC — the same instant must read the same."""
    utc = datetime(2026, 9, 8, 3, 50, tzinfo=UTC)
    assert ui.market_clock(utc).label == "MARKET HOURS"


def test_the_market_chip_does_not_claim_the_exchange_is_open() -> None:
    """It knows the clock. It does not know the holiday calendar, and unknown is never substituted."""
    note = ui.market_clock(datetime(2026, 9, 8, 6, 0, tzinfo=UTC)).note
    assert "holidays are not checked" in note
    for hour in range(24):
        clock = ui.market_clock(datetime(2026, 9, 8, hour, tzinfo=UTC))
        assert "OPEN" not in clock.label or clock.label == "PRE-OPEN"
        assert "CLOSED" not in clock.label


# --- palette integrity -------------------------------------------------------------------------
def test_every_tone_has_both_an_ink_and_a_mark_colour() -> None:
    """A tone with no entry would raise at render time — on the page, not in a test."""
    tones = ("neutral", "good", "warn", "serious", "bad", "info")
    for tone in tones:
        assert tone in ui._TONE_INK and tone in ui._TONE_MARK
        # And every one must reach the stylesheet, or the class silently does nothing.
        assert f".qa-{tone}" in ui.stylesheet()


def test_the_stylesheet_is_one_style_block_carrying_the_palette() -> None:
    css = ui.stylesheet()
    assert css.startswith("<style>") and css.rstrip().endswith("</style>")
    assert css.count("<style>") == 1
    for token in (ui.ACCENT, ui.LINE, ui.BAR, ui.GOOD_INK, ui.BAD):
        assert token in css


def test_the_benchmark_series_recedes_behind_the_book() -> None:
    """One series is the point and the other is context — not two colours competing for the eye."""
    assert ui.SERIES_BOOK == ui.ACCENT
    assert ui.SERIES_BENCH == ui.MUTED
    assert ui.SERIES_BOOK != ui.SERIES_BENCH


def test_rupees_are_grouped_the_same_way_everywhere_on_the_page() -> None:
    """The rest of the dashboard formats with ``f"₹{x:,.0f}"``; a tile spelling the same number a
    second way would be the page's own defect family in miniature."""
    assert ui.inr(Decimal("500000")) == f"₹{500000:,.0f}"
    assert ui.inr(Decimal("1234.56"), decimals=2) == "₹1,234.56"
