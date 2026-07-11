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

Three tabs = the whole final system on one screen: **📄 Paper book** (the validated optimizer +
advisor), **🔴 Live (Zerodha)** (the real account, read-only), and **🔬 Research** — the tax-free
hedge, the A/B/C forward study, and the daily AI brief, fetched read-only from the research repo's
committed reports (a data seam; the product never imports research). Only the product engine is ever
the calculator.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime
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
from qalpha.live.advisor import advise_raise_cash, advise_sell
from qalpha.live.dashboard import (
    _benchmark_return_pct,
    glossary_markdown,
    go_readiness_markdown,
    live_pm_brief_markdown,
    paper_freshness,
    performance_read,
    plain_summary_markdown,
    systemic_risk_markdown,
    today_brief_markdown,
    watchlist_is_stale,
)
from qalpha.live.go_scorecard import build_scorecard
from qalpha.live.holdings import LiveHoldings
from qalpha.live.paper import PaperBook, _prices_on
from qalpha.live.position_health import position_health
from qalpha.live.safety import SafetyReport, assess_advice_inputs, broker_session_guard

# The research repo's committed reports (public), fetched read-only over HTTP so the whole final
# system shows on one screen. This is a **data seam, not a code import** — the product NEVER imports
# research (iron rule); it just renders research's own committed markdown, exactly as research's
# mission-control fetches the product's paper_dashboard.md in reverse.
_RESEARCH_RAW = "https://raw.githubusercontent.com/aarsh-adhvaryu/Q_Alpha_Research/main/"
_RESEARCH_REPORTS = {
    "hedge": ("🛡 Tax-free hedge (paper overlay)", "reports/hedge_paper_dashboard.md"),
    "forward_study": (
        "🧪 Forward study — did it work, did the AI help?",
        "reports/forward_study_dashboard.md",
    ),
    "ai_brief": ("🧠 Daily AI market brief (context only, never a signal)", "reports/ai_brief.md"),
}


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


def _paper_status_panel(book: PaperBook) -> None:
    """Show whether the weekday paper-run pipeline actually marked the book (seen, not trusted)."""
    fresh = paper_freshness(book, date.today())
    (st.success if not fresh.is_stale else st.warning)(f"📊 Daily paper-run — {fresh.note}")


def _advisor_with_safety(
    portfolio: Portfolio,
    prices: PriceData,
    prices_dec: dict[str, Decimal],
    benchmark: pd.Series,
    as_of: date,
    *,
    live_session: bool | None = None,
    available_cash: Decimal | None = None,
) -> None:
    """Run the input-integrity guards, then either withhold advice (loud banner) or show the tabs.

    The system never auto-trades, so the only loss vector is acting on wrong displayed data — so the
    advisor is **gated** on the safety report: a stale feed / missing quote / dead session blocks the
    recommendation rather than quietly computing it on bad inputs. ``live_session`` is None for the
    paper book (no broker) and the live session's validity for the Zerodha view. ``available_cash``
    (live only) drives the zero-typing PM brief + prefills the Add-money field.
    """
    session = broker_session_guard(live_session) if live_session is not None else None
    report: SafetyReport = assess_advice_inputs(
        prices, prices_dec, sorted(portfolio.positions()), as_of, session=session
    )
    namespace = "live" if live_session is not None else "paper"
    st.subheader("Ask the advisor")
    if report.warnings:
        st.warning(report.render())
    if not report.safe_to_advise:
        st.error(report.render())
        st.caption(
            "Advice is withheld until the inputs are trustworthy — fix the above, then reload."
        )
        return
    # Auto "PM brief": on the live account, if there is meaningful idle cash, show the concrete
    # buy plan with zero typing (gated behind the same guards above — never bypassed). The
    # Add-money field is then prefilled with the available cash for a one-tap deeper dive.
    cfg = Config()
    floor = cfg.deploy_policy.idle_cash_floor
    default_add = 50000
    if available_cash is not None and available_cash >= floor:
        _auto_pm_brief(portfolio, benchmark, available_cash, as_of, cfg)
        default_add = int(available_cash)
    st.caption("Deterministic — every figure comes from the FIFO/cost/tax engine, no AI.")
    _advisor_tabs(
        portfolio, prices_dec, benchmark, as_of, default_add_amount=default_add, namespace=namespace
    )
    _satellite_section(portfolio, prices_dec, as_of)


def _auto_pm_brief(
    portfolio: Portfolio,
    benchmark: pd.Series,
    available_cash: Decimal,
    as_of: date,
    cfg: Config,
) -> None:
    """Render the zero-typing idle-cash buy brief on the Live tab (cached per (cash, as_of))."""
    cache_key = f"pm_brief::{available_cash}::{as_of}"
    brief = st.session_state.get(cache_key)
    if brief is None:
        wl = _watchlist()
        if wl is None:
            return  # watchlist not ready — silently skip the auto-brief (tabs still work)
        from qalpha.live.deploy import advise_deploy_into_weakness

        tickers, sector_of, wl_prices = wl
        advice = advise_deploy_into_weakness(
            portfolio,
            available_cash,
            tickers,
            sector_of,
            wl_prices,
            benchmark,
            as_of,
            max_names=cfg.deploy_policy.max_names_default,
        )
        brief = live_pm_brief_markdown(
            available_cash, advice, floor=cfg.deploy_policy.idle_cash_floor
        )
        st.session_state[cache_key] = brief
    if brief:
        st.success(brief)


def _satellite_section(portfolio: Portfolio, prices_dec: dict[str, Decimal], as_of: date) -> None:
    """Show the discretionary (satellite / IPO) sleeve — flagged, non-optimized — if any is registered.

    No-op unless ``data/satellite.json`` lists a holding the book actually holds, so the paper view and
    a satellite-free account are unaffected. The optimizer already excludes these (registry gate); this
    panel surfaces their exact exit tax, graduation countdown, and concentration alerts.
    """
    from qalpha.live.satellite import SatelliteRegistry, satellite_report

    registry = SatelliteRegistry.load()
    if not registry.tickers:
        return
    report = satellite_report(portfolio, registry, prices_dec, as_of, Config())
    if report.holdings or report.alerts:
        st.divider()
        st.markdown(report.render())


def _systemic_risk_view(benchmark: pd.Series, as_of: date) -> None:
    """Read-only systemic-risk watch — like the paper book, a record you watch; it never acts."""
    st.markdown(systemic_risk_markdown(benchmark, as_of))


def _logs_view(book: PaperBook, as_of: date) -> None:
    """Autonomous run log + freshness — proof the headless pipeline works when nobody's watching.

    The daily weekday cron marks the book and commits the track record with no human or Streamlit
    open; this view just reads the audit trail it leaves behind (``data/paper/run_log.jsonl``).
    """
    from qalpha.live.runlog import health_markdown, load_runs

    st.header("🧾 System health & autonomous run log")
    st.caption(
        "The strategy pipeline runs headless on a weekday cron — it does the work and persists it "
        "whether or not this page is open. This is its audit trail; the live Zerodha view is the only "
        "on-demand part (Kite needs your daily login)."
    )
    fresh = paper_freshness(book, as_of)
    (st.success if not fresh.is_stale else st.warning)(fresh.note)
    runs = load_runs()
    if not runs:
        st.info("No autonomous runs logged yet — the cron hasn't recorded one (or fresh checkout).")
        return
    st.markdown(health_markdown(runs, tail=30))


def _go_readiness_view(book: PaperBook, benchmark: pd.Series, as_of: date) -> None:
    """The autonomous GO verdict — counts down on real criteria, flips to GO when the evidence clears."""
    sc = build_scorecard(book.equity_curve, benchmark, as_of)
    badge = {"GO": "🟢", "READY": "🟢", "NO-GO": "🔴", "NOT YET": "🟡"}[sc.verdict]
    st.header(f"{badge} Real-money readiness: {sc.verdict}")
    st.caption(
        "Deterministic — no AI, no human judgement. GO appears the moment every criterion clears "
        "(earlier than 6 months if it does); a blocking failure shows NO-GO."
    )
    for c in sc.criteria:
        st.markdown(f"{c.icon} **{c.name}** — {c.detail}")
    st.divider()
    st.markdown(go_readiness_markdown(book, benchmark, as_of))


def _position_health_view(book: PaperBook, prices: PriceData, as_of: date) -> None:
    """Mid-cycle watch — flags a holding breaking down between the slow rebalances. Advisory only."""
    st.header("🩺 Position health (between rebalances)")
    st.caption(
        "The core rebalances slowly (annual) — this watches your holdings in between and flags any "
        "name in a sustained, *idiosyncratic* breakdown (not a market-wide dip). It never sells."
    )
    held = list(book.portfolio.positions())
    if not held:
        st.info("No holdings yet — nothing to watch.")
        return
    rep = position_health(prices.adj_close, held, as_of)
    for h in sorted(rep.holdings, key=lambda x: x.trailing_return):
        st.markdown(f"{h.icon} {h.note}")
    st.divider()
    st.markdown(rep.render())


def _plain_summary(
    book: PaperBook,
    prices: PriceData,
    benchmark: pd.Series,
    universe: Universe,
    sector_of: dict[str, str],
    as_of: date,
) -> str:
    """Compute the plain-English summary inputs from the engines and render the everyday-words panel."""
    from qalpha.live.deploy import market_weakness

    ret = book.total_return_pct(prices, as_of)
    bench = _benchmark_return_pct(benchmark, book.start_date, as_of)
    plan = book.plan(prices, universe, sector_of, as_of)
    verdict = build_scorecard(book.equity_curve, benchmark, as_of).verdict
    return plain_summary_markdown(
        book_return_pct=ret,
        benchmark_return_pct=bench,
        market_level=market_weakness(benchmark, as_of).level,
        go_verdict=verdict,
        action_needed=plan.has_orders,
    )


def _today_brief(
    book: PaperBook,
    prices: PriceData,
    benchmark: pd.Series,
    universe: Universe,
    sector_of: dict[str, str],
    as_of: date,
) -> str:
    """Assemble the one-screen 'what to do today' brief from the engines (no Kite, never trades)."""
    from qalpha.live.deploy import market_weakness

    plan = book.plan(prices, universe, sector_of, as_of)
    if plan.has_orders:
        core_action = f"⚠️ Rebalance due — {len(plan.proposed_orders)} order(s) to approve below."
    else:
        core_action = plan.decision.reason
    w = market_weakness(benchmark, as_of)
    hedge_note = (
        "no systemic stress — no hedge indicated."
        if w.level == "normal"
        else "stress elevated — consider the research-proven tax-free futures hedge (informational)."
    )
    held = list(book.portfolio.positions())
    if held:
        rep = position_health(prices.adj_close, held, as_of)
        flagged = [h for h in rep.holdings if h.level != "healthy"]
        health_note = (
            "all holdings healthy — nothing to sell."
            if not flagged
            else f"{len(flagged)} holding(s) flagged — see 🩺 Position health below."
        )
    else:
        health_note = "no holdings yet."
    go = build_scorecard(book.equity_curve, benchmark, as_of).verdict
    return today_brief_markdown(
        as_of,
        core_action=core_action,
        market_level=w.level,
        market_drawdown=w.drawdown,
        market_note=w.note,
        hedge_note=hedge_note,
        health_note=health_note,
        go_verdict=go,
    )


@st.cache_data(ttl=1800)
def _fetch_research(path: str) -> str | None:
    """Fetch one of the research repo's committed reports (data seam, not a code import). Fail-soft:
    any error (offline, 404 before a branch is merged) → ``None`` so the tab degrades gracefully."""
    import urllib.request

    try:
        with urllib.request.urlopen(_RESEARCH_RAW + path, timeout=10) as resp:
            return resp.read().decode("utf-8")  # type: ignore[no-any-return]
    except Exception:
        return None


def _research_tab() -> None:
    """The research side of the final system, read-only: the tax-free hedge overlay, the A/B/C forward
    study, and the daily AI brief — each fetched from the research repo's own committed report. Nothing
    here trades or feeds the product engine; it is the 'watch the whole system before the GO' pane."""
    st.caption(
        "The **research half** of the final system — fetched read-only from the public research repo "
        "(the product never imports research). **All paper / fake-money · nothing here ever trades.**"
    )
    if st.button("🔄 Refresh research feeds"):
        _fetch_research.clear()
    for _key, (title, path) in _RESEARCH_REPORTS.items():
        st.divider()
        st.subheader(title)
        text = _fetch_research(path)
        if text and "No brief generated yet" not in text:
            st.markdown(text)
        else:
            st.info(
                f"Not published yet — the research cron writes `{path}` (the forward study lands once "
                "its branch merges to research `main`). This pane fills in automatically once it does."
            )


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
    book, prices, universe, sector_of, benchmark = _load()
    cfg = Config()
    as_of = prices.dates[-1].date()

    st.title("Q-Alpha — Tax-Smart Portfolio Advisor")
    _paper_status_panel(book)

    paper_tab, live_tab, research_tab = st.tabs(
        ["📄 Paper book", "🔴 Live (Zerodha)", "🔬 Research (hedge · forward study · AI)"]
    )

    with paper_tab:
        # Plain-English summary first — how you're doing / market / readiness / to-dos, in everyday
        # words — then the detailed "what to do" brief and the numbers.
        st.info(_plain_summary(book, prices, benchmark, universe, sector_of, as_of))
        st.markdown(_today_brief(book, prices, benchmark, universe, sector_of, as_of))
        st.divider()
        st.caption(
            f"Notional paper book (no real money) · as of **{as_of}** · decisions from the validated "
            "engine — this page never trades."
        )
        _paper_overview(book, prices, benchmark, universe, sector_of, as_of)
        with st.expander("🎯 GO readiness — the real-money verdict"):
            _go_readiness_view(book, benchmark, as_of)
        with st.expander("🩺 Position health — between-rebalance watch"):
            _position_health_view(book, prices, as_of)
        with st.expander("🛡 Systemic risk — hedge watch"):
            _systemic_risk_view(benchmark, as_of)
        with st.expander("🧾 Logs & system health — autonomous run trail"):
            _logs_view(book, as_of)
        with st.expander("📖 Jargon, in plain English — look anything up"):
            st.markdown(glossary_markdown())
        st.divider()
        _advisor_with_safety(book.portfolio, prices, _prices_on(prices, as_of), benchmark, as_of)

    with live_tab:
        # Act on the REAL Zerodha account: login → live holdings + advisor (sell / raise / add money).
        auto = st.sidebar.toggle("⏱ Auto-refresh live (30s)", value=True)

        @st.fragment(run_every=30 if auto else None)
        def _live_view() -> None:
            if not _kite_login_gate():
                return
            live = _load_live(cfg, as_of)
            if live is None:
                return
            portfolio, prices_dec = _live_section(live, cfg)
            # Session-scoped realtime ticks (true KiteTicker push while open); 30s polling is fallback.
            prices_dec, stream_label = _streamed_prices(prices_dec, sorted(portfolio.positions()))
            st.caption(
                f"Live Zerodha · {stream_label} · page rendered {datetime.now():%H:%M:%S} · "
                "read-only — this page never trades."
            )
            if auto:
                st.caption(
                    "↻ Auto-refreshes every 30 s **while this tab is open and focused**. If the "
                    "rendered time stops advancing, the tab paused — tap the page or reload."
                )
            st.divider()
            _advisor_with_safety(
                portfolio,
                prices,
                prices_dec,
                benchmark,
                as_of,
                live_session=True,
                available_cash=portfolio.cash,
            )

        _live_view()

    with research_tab:
        _research_tab()


def _streamed_prices(
    prices_dec: dict[str, Decimal], symbols_ns: list[str]
) -> tuple[dict[str, Decimal], str]:
    """Overlay session-scoped realtime LTPs onto the polled prices; fall back silently if the socket
    isn't up. The ``RealtimeTicker`` is parked in ``st.session_state`` so it lives exactly as long as
    the browser session (started once, torn down when the session ends)."""
    from qalpha.backtest.portfolio import to_decimal_price
    from qalpha.live.ticker import RealtimeTicker, resolve_tokens, stream_status

    try:
        if "rt_ticker" not in st.session_state:
            from qalpha.live.auth import get_access_token
            from qalpha.live.client import authenticated_kite
            from qalpha.live.credentials import load_credentials

            bare_to_ns = {s.split(".")[0]: s for s in symbols_ns}
            tokens = resolve_tokens(authenticated_kite(), list(bare_to_ns))
            api_key = load_credentials(require_secret=False).api_key
            rt = RealtimeTicker(api_key, get_access_token(), list(tokens.values()))
            rt.start()
            st.session_state["rt_ticker"] = rt
            st.session_state["rt_token_to_ns"] = {t: bare_to_ns[b] for b, t in tokens.items()}

        rt = st.session_state["rt_ticker"]
        token_to_ns = st.session_state["rt_token_to_ns"]
        merged = dict(prices_dec)
        for token, px in rt.store.snapshot().items():
            ns = token_to_ns.get(token)
            if ns and px > 0:
                merged[ns] = to_decimal_price(px)
        label, _live = stream_status(rt.store.connected, rt.store.last_update(), datetime.now(UTC))
        return merged, label
    except Exception:
        return prices_dec, "⏱ polling"


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
    st.caption(performance_read(ret, bench))  # plain good/bad read so the numbers aren't bare

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


def _download_watchlist_panel() -> None:
    import subprocess

    with st.spinner("Loading the Nifty-100 watchlist (one-time price download, ~1–2 min)…"):
        subprocess.run(
            [sys.executable, "scripts/build_nifty100_watchlist.py", "--prices"],
            check=False,
            cwd=Path.cwd(),
        )


@st.cache_resource(ttl=6 * 3600, show_spinner=False)
def _watchlist() -> tuple[list[str], dict[str, str], PriceData] | None:
    """The Nifty-100 watchlist + its price panel — the buy-suggestion universe.

    The panel is downloaded once and persists on disk, so a bare forever-cache would serve week-old
    prices to the deploy advisor. Two guards: a 6-hour ``ttl`` on the cache, and a
    :func:`watchlist_is_stale` check that re-downloads the panel when its last price date has aged out.
    """
    from qalpha.data.ingest import load_parquet

    csv = Path("data/universes/nifty100_watchlist.csv")
    panel = Path("data/historical/prices_watchlist.parquet")
    if not csv.exists():
        return None
    if not panel.exists():
        _download_watchlist_panel()
    elif watchlist_is_stale(load_parquet(str(panel)).dates[-1].date(), date.today()):
        _download_watchlist_panel()  # refresh a stale on-disk panel
    if not panel.exists():
        return None

    wl = pd.read_csv(csv)
    tickers = [str(t) for t in wl["ticker"]]
    sector_of = {str(t): str(s) for t, s in zip(wl["ticker"], wl["sector"], strict=True)}
    return tickers, sector_of, load_parquet(str(panel))


def _advisor_tabs(
    portfolio: Portfolio,
    prices_dec: dict[str, Decimal],
    benchmark: pd.Series,
    as_of: date,
    *,
    default_add_amount: int = 50000,
    namespace: str = "paper",
) -> None:
    """Interactive sell / raise-cash / add-money tabs.

    ``benchmark`` is the **real Nifty 50 TRI** series — the deploy-into-weakness advisor's market
    signal must come from the index, not the watchlist mean (a prior bug). ``namespace`` keeps widget
    keys unique so the paper and live advisors can both render in one run without a key collision;
    ``default_add_amount`` prefills the Add-money field (live view seeds it with available cash).
    """
    sell_tab, raise_tab, add_tab = st.tabs(["Sell a holding", "Raise cash", "Add money"])
    positions = sorted(portfolio.positions())

    with sell_tab:
        if not positions:
            st.info("No holdings to sell yet.")
        else:
            ticker = st.selectbox("Holding", positions, key=f"sell_pick_{namespace}")
            held = int(portfolio.ledger.quantity_held(ticker))
            qty = st.number_input(
                "Shares to sell",
                min_value=1,
                max_value=held,
                value=held,
                step=1,
                key=f"sell_qty_{namespace}",
            )
            if st.button("Advise sell", key=f"sell_btn_{namespace}") and ticker in prices_dec:
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
            "Cash needed (₹)", min_value=1000, value=50000, step=1000, key=f"raise_amt_{namespace}"
        )
        if st.button("Advise raise-cash", key=f"raise_btn_{namespace}"):
            st.markdown(advise_raise_cash(portfolio, Decimal(amount), prices_dec, as_of).render())

    with add_tab:
        st.caption(
            "Suggests **what to buy** with new money — a diversified, **tax-free (buys-only)** spread "
            "across Nifty 100, tilted toward out-of-favour names + market weakness. Not stock tips."
        )
        amount = st.number_input(
            "New money to invest (₹)",
            min_value=1000,
            value=max(1000, default_add_amount),
            step=1000,
            key=f"add_amt_{namespace}",
        )
        n_stocks = st.slider(
            "Spread across how many stocks?",
            min_value=5,
            max_value=40,
            value=15,
            help="Fewer = bigger, more concentrated positions (more risk, fewer orders). "
            "More = broader & thinner. ~12–25 is the usual sweet spot.",
            key=f"add_names_{namespace}",
        )
        if st.button("Suggest what to buy", key=f"add_btn_{namespace}"):
            wl = _watchlist()
            if wl is None:
                st.error("Watchlist prices not ready yet — try again in a minute.")
            else:
                from qalpha.live.deploy import advise_deploy_into_weakness

                tickers, sector_of, wl_prices = wl
                st.markdown(
                    advise_deploy_into_weakness(
                        portfolio,
                        Decimal(amount),
                        tickers,
                        sector_of,
                        wl_prices,
                        benchmark,  # the REAL Nifty TRI, not the watchlist mean
                        as_of,
                        max_names=n_stocks,
                    ).render()
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
