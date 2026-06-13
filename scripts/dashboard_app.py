"""Live web dashboard — the consumer-facing view + interactive tax-smart advisor (plan items #2/#3).

A Streamlit app over the portfolio: equity vs Nifty 50 TRI, holdings, today's recommendation, and an
**interactive advisor** (sell / raise cash / add money) calling the same deterministic engine as
``scripts/advisor.py``. A sidebar toggle switches the **data source** between the notional paper book
and the **live Zerodha account** (``kite.holdings()`` + ``ltp()``) — same advisor, same page.

    uv run --extra dashboard streamlit run scripts/dashboard_app.py

Read-only: the page never places or commits a trade — it shows what the system *recommends*; the user
acts in his own broker. Live holdings carry no purchase dates, so live tax is approximate until a
tradebook is imported (criterion 4); the page shows that caveat.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
from paper import BOOK_PATH, _load_benchmark_series, _load_market

from qalpha.backtest.portfolio import Portfolio
from qalpha.config import Config
from qalpha.data.prices import PriceData
from qalpha.data.universe import Universe
from qalpha.live.advisor import advise_deploy, advise_raise_cash, advise_sell
from qalpha.live.dashboard import _benchmark_return_pct
from qalpha.live.holdings import LiveHoldings
from qalpha.live.paper import PaperBook, _prices_on


@st.cache_resource
def _load() -> tuple[PaperBook, PriceData, Universe, dict[str, str], pd.Series]:
    """Load the book + market once per session (cached; press 'Reload data' to refresh)."""
    cfg = Config()
    prices, universe, sector_of = _load_market()
    book = PaperBook.load(BOOK_PATH, cfg)
    return book, prices, universe, sector_of, _load_benchmark_series()


def _load_live(cfg: Config, as_of: date) -> LiveHoldings | None:
    """Fetch the live Zerodha account as a Portfolio (not cached — it changes). None if unavailable."""
    try:
        from qalpha.live.client import authenticated_kite
        from qalpha.live.holdings import (
            fetch_available_cash,
            fetch_holdings,
            portfolio_from_holdings,
        )

        kite = authenticated_kite()
        holdings = fetch_holdings(kite)
        if not holdings:
            st.info("Live Zerodha account holds no equity yet — fund it and trade to see it here.")
            return None
        return portfolio_from_holdings(holdings, cfg, as_of=as_of, cash=fetch_available_cash(kite))
    except Exception as exc:  # surface any broker/auth error to the user, don't crash the page
        st.error(
            f"Could not read the live account: {exc}\n\n"
            "Re-login with `uv run python -m qalpha.live.auth --manual`."
        )
        return None


def _current_target(
    book: PaperBook, prices: PriceData, universe: Universe, sector_of: dict[str, str], as_of: date
) -> pd.Series | None:
    plan = book.plan(prices, universe, sector_of, as_of)
    if plan.decision.target is not None and not plan.decision.target.empty:
        return plan.decision.target
    return book.last_target


def main() -> None:
    st.set_page_config(page_title="Q-Alpha", page_icon="📈", layout="wide")
    if not BOOK_PATH.exists():
        st.error(f"No paper book at {BOOK_PATH}. Run `uv run python scripts/paper.py init` first.")
        return

    if st.sidebar.button("🔄 Reload data"):
        st.cache_resource.clear()
    source = st.sidebar.radio("Data source", ["Paper book", "Live Zerodha"])
    book, prices, universe, sector_of, benchmark = _load()
    cfg = Config()
    as_of = prices.dates[-1].date()
    target = _current_target(book, prices, universe, sector_of, as_of)

    st.title("Q-Alpha — Tax-Smart Portfolio Advisor")

    if source == "Paper book":
        st.caption(
            f"Notional paper book (no real money) · as of **{as_of}** · "
            "decisions from the validated engine — this page never trades."
        )
        portfolio: Portfolio | None = book.portfolio
        prices_dec = _prices_on(prices, as_of)
        _paper_overview(book, prices, benchmark, universe, sector_of, as_of)
    else:
        st.caption("Live Zerodha account · read-only — this page never trades.")
        live = _load_live(cfg, as_of)
        if live is None:
            return
        portfolio = live.portfolio
        prices_dec = live.prices
        _live_overview(live)

    st.divider()
    st.subheader("Ask the advisor")
    st.caption("Deterministic — every figure comes from the FIFO/cost/tax engine, no AI.")
    _advisor_tabs(portfolio, prices_dec, target, as_of)


def _paper_overview(
    book: PaperBook,
    prices: PriceData,
    benchmark: pd.Series,
    universe: Universe,
    sector_of: dict[str, str],
    as_of: date,
) -> None:
    prices_dec = _prices_on(prices, as_of)
    equity = book.portfolio.market_value(prices_dec)
    ret = book.total_return_pct(prices, as_of)
    bench = _benchmark_return_pct(benchmark, book.start_date, as_of)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Equity", f"₹{equity:,.0f}", f"{ret:+.2f}%")
    c2.metric("Nifty 50 TRI", f"{bench:+.2f}%" if bench is not None else "—")
    c3.metric("Cash", f"₹{book.portfolio.cash:,.0f}")
    c4.metric("Realized tax to date", f"₹{book.realized_tax():,.0f}")

    plan = book.plan(prices, universe, sector_of, as_of)
    if plan.has_orders:
        st.warning(f"**Action suggested — {plan.decision.reason}**")
        st.table(
            pd.DataFrame(
                [
                    {"Side": o.side.name, "Ticker": o.ticker, "Qty": str(o.quantity)}
                    for o in plan.proposed_orders
                ]
            )
        )
    else:
        st.success(f"Hold — {plan.decision.reason}.")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Equity vs Nifty 50 TRI")
        _equity_chart(book, benchmark)
    with right:
        st.subheader("Holdings")
        st.dataframe(_holdings_frame(book.portfolio, prices_dec), hide_index=True, width="stretch")


def _live_overview(live: LiveHoldings) -> None:
    equity = live.portfolio.market_value(live.prices)
    c1, c2, c3 = st.columns(3)
    c1.metric("Equity", f"₹{equity:,.0f}")
    c2.metric("Cash", f"₹{live.portfolio.cash:,.0f}")
    c3.metric("Holdings", str(len(live.portfolio.positions())))
    if live.tax_caveat:
        st.warning(live.tax_caveat)
    st.subheader("Holdings")
    st.dataframe(_holdings_frame(live.portfolio, live.prices), hide_index=True, width="stretch")


def _advisor_tabs(
    portfolio: Portfolio, prices_dec: dict[str, Decimal], target: pd.Series | None, as_of: date
) -> None:
    sell_tab, raise_tab, add_tab = st.tabs(["Sell a holding", "Raise cash", "Add money"])
    positions = sorted(portfolio.positions())

    with sell_tab:
        if not positions:
            st.info("No holdings to sell yet.")
        else:
            ticker = st.selectbox("Holding", positions)
            held = int(portfolio.ledger.quantity_held(ticker))
            qty = st.number_input("Shares to sell", min_value=1, max_value=held, value=held, step=1)
            if st.button("Advise sell") and ticker in prices_dec:
                st.markdown(
                    advise_sell(
                        portfolio,
                        ticker,
                        prices_dec[ticker],
                        as_of,
                        Config(),
                        quantity=Decimal(qty),
                    ).render()
                )

    with raise_tab:
        amount = st.number_input(
            "Cash needed (₹)", min_value=1000, value=50000, step=1000, key="raise_amt"
        )
        if st.button("Advise raise-cash"):
            st.markdown(advise_raise_cash(portfolio, Decimal(amount), prices_dec, as_of).render())

    with add_tab:
        amount = st.number_input(
            "New money to invest (₹)", min_value=1000, value=50000, step=1000, key="add_amt"
        )
        if st.button("Advise deploy"):
            if target is None:
                st.error("No target weights available — cannot route new money.")
            else:
                st.markdown(
                    advise_deploy(portfolio, Decimal(amount), target, prices_dec, as_of).render()
                )


def _holdings_frame(portfolio: Portfolio, prices_dec: dict[str, Decimal]) -> pd.DataFrame:
    weights = portfolio.current_weights(prices_dec)
    rows = []
    for t, q in sorted(portfolio.positions().items()):
        px = prices_dec.get(t, Decimal("0"))
        rows.append(
            {
                "Ticker": t,
                "Qty": str(q),
                "Price": f"₹{px:,.2f}",
                "Value": f"₹{q * px:,.0f}",
                "Weight": f"{weights.get(t, 0.0) * 100:.1f}%",
            }
        )
    return pd.DataFrame(rows)


def _equity_chart(book: PaperBook, benchmark: pd.Series) -> None:
    curve = book.equity_curve
    if len(curve) < 2:
        st.info("Track record begins — not enough daily marks to chart yet.")
        return
    eq = pd.Series(
        {pd.Timestamp(p["date"]): float(p["equity"]) for p in curve}, name="Q-Alpha"
    ).sort_index()
    # Rebase the TRI to the book's starting equity so the two lines are comparable.
    window = benchmark[(benchmark.index >= eq.index[0]) & (benchmark.index <= eq.index[-1])]
    chart = pd.DataFrame({"Q-Alpha": eq})
    if len(window) >= 2:
        rebased = window / float(window.iloc[0]) * float(eq.iloc[0])
        chart["Nifty 50 TRI"] = rebased.reindex(eq.index, method="ffill")
    st.line_chart(chart)


if __name__ == "__main__":
    main()
