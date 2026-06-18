"""Live web dashboard — the consumer-facing view + interactive tax-smart advisor (plan items #2/#3).

A Streamlit app over the portfolio: equity vs Nifty 50 TRI, holdings, today's recommendation, and an
**interactive advisor** (sell / raise cash / add money) calling the same deterministic engine as
``scripts/advisor.py``. A sidebar toggle switches the **data source** between the notional paper book
and the **live Zerodha account** (``kite.holdings()`` + ``ltp()``) — same advisor, same page.

    uv run --extra dashboard streamlit run scripts/dashboard_app.py

Read-only: the page never places or commits a trade — it shows what the system *recommends*; the user
acts in his own broker. Live holdings carry no purchase dates, so live tax is approximate until you
**upload a Zerodha Console tradebook CSV** in the Live view — that replays exact dated FIFO lots
(criterion 4) and switches the page to exact-tax mode; otherwise it shows the short-term caveat.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime
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
from qalpha.live.dashboard import _benchmark_return_pct, paper_freshness
from qalpha.live.holdings import LiveHoldings
from qalpha.live.paper import PaperBook, _prices_on


def _bridge_secrets() -> None:
    """Copy Streamlit Cloud secrets into the environment so the env-based credential/password code
    works unchanged (Streamlit Cloud exposes secrets via ``st.secrets``, not ``os.environ``)."""
    try:
        for k in ("KITE_API_KEY", "KITE_API_SECRET", "APP_PASSWORD"):
            if k in st.secrets:  # raises if no secrets configured → caught below
                os.environ.setdefault(k, str(st.secrets[k]))
    except Exception:
        pass  # no secrets file (local dev) — env vars / .env already cover it


@st.cache_resource(show_spinner=False)
def _ensure_data() -> None:
    """First run on a fresh host (e.g. Streamlit Cloud): the gitignored price panels are absent —
    download them once (cached for the container's life). The paper view needs **both** the strategy
    panel *and* the Nifty-50-TRI benchmark; ``paper.py daily`` fetches both (``refresh`` is prices
    only). Guard on both files so a partial first run still self-heals."""
    prices = Path("data/historical/prices_pit_2026.parquet")
    benchmark = Path("data/historical/benchmark_NIFTYBEESNS_2026.parquet")
    if prices.exists() and benchmark.exists():
        return
    import subprocess

    with st.spinner("First run — downloading market data (~1–2 min). This happens once."):
        subprocess.run([sys.executable, "scripts/paper.py", "daily"], check=False, cwd=Path.cwd())


def _check_password() -> bool:
    """Gate the dashboard behind ``APP_PASSWORD`` (set when hosted). Empty env = open (local dev)."""
    pw = os.environ.get("APP_PASSWORD", "").strip()
    if not pw or st.session_state.get("authed"):
        return True
    entered = st.text_input("🔒 Password", type="password")
    if entered and entered == pw:
        st.session_state["authed"] = True
        st.rerun()
    elif entered:
        st.error("Wrong password.")
    return bool(st.session_state.get("authed"))


def _ensure_kite_credentials() -> bool:
    """Make the Kite app key+secret available — from secrets/env, or an **in-app form** so everything
    can be done from the dashboard (no `.env` needed). Held for the session; returns True when set."""
    # Restore from this session, then check env (Streamlit secrets bridged here, or .env, or entered).
    for k in ("KITE_API_KEY", "KITE_API_SECRET"):
        if not os.environ.get(k, "").strip() and st.session_state.get(k):
            os.environ[k] = str(st.session_state[k])
    if os.environ.get("KITE_API_KEY", "").strip() and os.environ.get("KITE_API_SECRET", "").strip():
        return True

    st.info(
        "Enter your **Kite Connect** app key + secret once to enable the live view — from "
        "https://developers.kite.trade → **My apps** → your app (regenerate the secret if forgotten). "
        "Held only for this session; never written to the repo."
    )
    with st.form("kite_creds"):
        api_key = st.text_input("Kite API key", type="password")
        api_secret = st.text_input("Kite API secret", type="password")
        if st.form_submit_button("Save credentials") and api_key and api_secret:
            st.session_state["KITE_API_KEY"] = os.environ["KITE_API_KEY"] = api_key.strip()
            st.session_state["KITE_API_SECRET"] = os.environ["KITE_API_SECRET"] = api_secret.strip()
            st.rerun()
    return False


def _kite_login_gate() -> bool:
    """Ensure a fresh Kite session for live data; render a phone-friendly login if not.

    Captures the ``request_token`` Kite appends when it redirects back to this page (so logging in is
    one tap), with a paste fallback. Returns True only when a usable token is in place.
    """
    from qalpha.live.auth import exchange, login_url, parse_request_token, persist_session
    from qalpha.live.credentials import load_credentials

    qp = st.query_params
    if "request_token" in qp:
        try:
            sess = exchange(load_credentials(), parse_request_token(qp["request_token"]))
            persist_session(sess)
            st.query_params.clear()
            st.success("✅ Logged in to Zerodha for today.")
            return True
        except Exception as exc:
            st.error(f"Login failed: {exc}")

    try:
        from qalpha.live.auth import get_access_token

        get_access_token()  # raises if missing/stale
        return True
    except Exception:
        pass

    st.warning("Kite session expired — log in to Zerodha to see live data (once a day).")
    try:
        api_key = load_credentials(require_secret=False).api_key
        st.link_button("🔑 Login to Zerodha", login_url(api_key))
    except Exception as exc:
        st.error(f"Kite credentials not configured: {exc}")
        return False
    pasted = st.text_input("…or paste the redirect URL / request_token", key="rt_paste")
    if pasted:
        try:
            persist_session(exchange(load_credentials(), parse_request_token(pasted)))
            st.success("✅ Logged in.")
            return True
        except Exception as exc:
            st.error(f"Could not log in: {exc}")
    return False


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


def _paper_status_panel(book: PaperBook) -> None:
    """Show whether the weekday paper-run pipeline actually marked the book (seen, not trusted)."""
    fresh = paper_freshness(book, date.today())
    (st.success if not fresh.is_stale else st.warning)(f"📊 Daily paper-run — {fresh.note}")


def main() -> None:
    st.set_page_config(page_title="Q-Alpha", page_icon="📈", layout="wide")
    _bridge_secrets()
    if not _check_password():
        st.stop()
    _ensure_data()  # download the price panels on a fresh host (no-op once cached/present)
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
    _paper_status_panel(book)

    if source == "Paper book":
        st.caption(
            f"Notional paper book (no real money) · as of **{as_of}** · "
            "decisions from the validated engine — this page never trades."
        )
        _paper_overview(book, prices, benchmark, universe, sector_of, as_of)
        st.divider()
        st.subheader("Ask the advisor")
        st.caption("Deterministic — every figure comes from the FIFO/cost/tax engine, no AI.")
        _advisor_tabs(book.portfolio, _prices_on(prices, as_of), target, as_of)
        return

    # Live source: enter Kite credentials in-app (if not set), then a one-tap login, then the live
    # view auto-refreshes (near-realtime). Creds + login stay OUTSIDE the auto-refresh so typing
    # isn't interrupted.
    if not _ensure_kite_credentials():
        return
    if not _kite_login_gate():
        return

    auto = st.sidebar.toggle("⏱ Auto-refresh live (30s)", value=True)

    @st.fragment(run_every=30 if auto else None)
    def _live_view() -> None:
        live = _load_live(cfg, as_of)
        if live is None:
            return
        st.caption(
            f"Live Zerodha · refreshed {datetime.now():%H:%M:%S} · read-only — this page never trades."
        )
        portfolio, prices_dec = _live_section(live, cfg)
        st.divider()
        st.subheader("Ask the advisor")
        st.caption("Deterministic — every figure comes from the FIFO/cost/tax engine, no AI.")
        _advisor_tabs(portfolio, prices_dec, target, as_of)

    _live_view()


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


def _live_section(live: LiveHoldings, cfg: Config) -> tuple[Portfolio, dict[str, Decimal]]:
    """Render the live overview, with an optional tradebook upload that makes the tax exact.

    Returns the portfolio + marking prices the advisor tabs should use: the dated tradebook replay
    when a CSV is uploaded (exact holding periods), else the holdings snapshot (short-term assumed).
    """
    st.caption(
        "Upload your Zerodha **Console → Reports → Tradebook** CSV for *exact* holding-period tax. "
        "Without it, tax assumes short-term (holdings carry no purchase dates)."
    )
    uploaded = st.file_uploader("Tradebook CSV", type=["csv"], key="tradebook")

    if uploaded is not None:
        from qalpha.live.tradebook import parse_tradebook, reconcile_positions, replay_tradebook

        try:
            trades = parse_tradebook(uploaded)
            result = replay_tradebook(trades, cfg, cash=live.portfolio.cash)
        except Exception as exc:  # malformed CSV → fall back to the holdings snapshot
            st.error(f"Could not read the tradebook: {exc}")
        else:
            st.success(
                f"Loaded {result.n_trades} trades → dated FIFO lots. "
                f"Realized capital-gains tax to date: ₹{result.realized_tax:,.2f}."
            )
            for w in result.warnings:
                st.warning(w)
            issues = reconcile_positions(result.portfolio, live.portfolio.positions())
            if issues:
                st.warning(
                    "Reconstructed holdings differ from the broker:\n- " + "\n- ".join(issues)
                )
            else:
                st.caption("✓ Reconstructed holdings match your broker account exactly.")
            _live_overview(result.portfolio, live.prices, caveat=None)
            return result.portfolio, live.prices

    _live_overview(live.portfolio, live.prices, caveat=live.tax_caveat)
    return live.portfolio, live.prices


def _live_overview(portfolio: Portfolio, prices: dict[str, Decimal], *, caveat: str | None) -> None:
    equity = portfolio.market_value(prices)
    c1, c2, c3 = st.columns(3)
    c1.metric("Equity", f"₹{equity:,.0f}")
    c2.metric("Cash", f"₹{portfolio.cash:,.0f}")
    c3.metric("Holdings", str(len(portfolio.positions())))
    if caveat:
        st.warning(caveat)
    else:
        st.success("Exact tax mode — holding periods dated from your tradebook.")
    st.subheader("Holdings")
    st.dataframe(_holdings_frame(portfolio, prices), hide_index=True, width="stretch")


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
