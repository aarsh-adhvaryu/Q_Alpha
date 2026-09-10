"""Q-Alpha, local. One command, one page. No server, no cloud, no browser tab left open.

    uv run python scripts/qalpha.py            # sync what it can, run, write the page, open it
    uv run python scripts/qalpha.py --no-open  # same, but do not launch a browser
    uv run python scripts/qalpha.py --login    # refresh the Kite session first (needs a browser)

### What clicking actually does

A page opened over ``file://`` cannot run Python, read your tradebook or call Kite — browsers block
all of it, correctly. So the clickable thing on the desktop is a launcher that runs *this*, and this
writes the page and opens it. **The HTML is the result, never the engine.**

### What it does when it cannot reach anything

Everything degrades to a named absence rather than a guess. No Kite session ⇒ the account is read
from the last saved snapshot and the page says how old it is. No tradebook ⇒ the lots are undated
and every tax figure is labelled an estimate. Nothing is silently carried forward as if fresh, which
is the one rule this whole repo is built on.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qalpha.config import Config
from qalpha.live.account import ReconciledAccount, reconcile
from qalpha.live.buygate import MAX_PRICE_AGE_DAYS, evaluate
from qalpha.live.commitments import Commitment, allowance, already_committed, confirm_fills
from qalpha.live.commitments import load as load_commitments
from qalpha.live.commitments import record as record_commitment
from qalpha.live.extraction import EXTRACTION_VERSION
from qalpha.live.mandate import Mandate, load_mandate
from qalpha.live.progress import LOG
from qalpha.live.report import render
from qalpha.live.session import load_snapshot, snapshot_from
from qalpha.live.tradebook import TradebookTrade, parse_tradebook

PAGE = Path("data/session/qalpha.html")
TRADEBOOK_DIR = Path("data/tradebooks")
#: Every file this run reads or writes, in one place and passed explicitly.
#:
#: They used to be default arguments bound at import time, which is a large part of why NO TEST
#: COULD REACH `main()` — and six defects survived a PR that claimed to fix them, because the gate
#: was tested with prepared inputs while nothing checked that `main` supplied them correctly.
SNAPSHOT = Path("data/session/snapshot.json")
SNAPSHOT_ARCHIVE = Path("data/session/snapshots")
COMMITMENTS = Path("data/session/commitments.jsonl")


def _trades() -> tuple[list[TradebookTrade], list[str]]:
    """Every Console export in ``data/tradebooks/``, de-duped on Zerodha trade ids.

    A folder rather than an upload widget: dropping a CSV in is the whole interaction, overlapping
    date ranges are safe because the ids de-dupe, and there is nothing to keep open.
    """
    notes: list[str] = []
    if not TRADEBOOK_DIR.exists():
        return [], [
            f"No tradebook yet. Drop a Zerodha Console export into {TRADEBOOK_DIR}/ — until then "
            "lots have no purchase dates and every tax figure is an estimate."
        ]
    seen: dict[str, TradebookTrade] = {}
    for csv in sorted(TRADEBOOK_DIR.glob("*.csv")):
        try:
            for t in parse_tradebook(str(csv)):
                # THE SIDE IS PART OF THE IDENTITY. Without it a same-day BUY and SELL of the
                # same quantity at the same price share a key and collapse into one row — one of
                # the two transactions simply disappears from the ledger, taking its tax with it.
                # Trade ids make this moot when the export has them; this is the fallback for when
                # it does not, and a fallback that loses a trade is worse than refusing to guess.
                key = t.trade_id or (
                    f"{t.trade_date}:{t.ticker}:{t.side.name}:{t.quantity}:{t.price}:{t.exec_time}"
                )
                seen[key] = t
        except Exception as exc:
            notes.append(f"{csv.name} could not be read ({exc}) — skipped, not guessed at.")
    if not seen:
        notes.append(f"No readable export in {TRADEBOOK_DIR}/ — tax figures are estimates.")
    return sorted(seen.values(), key=lambda t: (t.trade_date, t.exec_time)), notes


def _broker(
    cfg: Config,
) -> tuple[dict[str, Decimal], dict[str, Decimal], Decimal | None, list[str]]:
    """Holdings, average costs, cash — or a named absence. Never a stale value pretending to be new."""
    try:
        from qalpha.live.client import authenticated_kite
        from qalpha.live.holdings import fetch_available_cash, fetch_holdings

        kite = authenticated_kite()
        held = fetch_holdings(kite)
        return (
            {h.ticker: h.quantity for h in held},
            {h.ticker: h.average_price for h in held},
            fetch_available_cash(kite),
            [],
        )
    except Exception as exc:
        # `None`, NOT `Decimal("0")`. Returning zero replaced a recorded ₹2,01,117 balance with ₹0,
        # SAVED that to the snapshot, and still proposed purchases against it — a broker outage
        # rewritten as a confirmed empty account. "Unknown is never substituted" is the first iron
        # rule in this repo, and this broke it on the money path.
        return (
            {},
            {},
            None,
            [
                f"Kite was not reachable ({type(exc).__name__}). Holdings come from the trade "
                "ledger alone and the cash balance is UNKNOWN — not zero. Run with --login before "
                "buying against anything here."
            ],
        )


def _prices(tickers: list[str], costs: dict[str, Decimal]) -> tuple[dict[str, Decimal], list[str]]:
    """Marks for the page. The broker's last price where we have it; the panel otherwise."""
    out: dict[str, Decimal] = {}
    notes: list[str] = []
    try:
        from qalpha.data.ingest import load_parquet

        for path in (
            "data/historical/prices_watchlist.parquet",
            "data/historical/prices_pit_2026.parquet",
        ):
            if not Path(path).exists():
                continue
            adj = load_parquet(path).adj_close
            panel_end = adj.index[-1].date()
            for t in tickers:
                if t in out or t not in adj.columns:
                    continue
                series = adj[t].dropna()
                if not len(series):
                    continue
                # A NAME'S OWN LAST QUOTE, not the panel's last date. A panel dated 10 September can
                # carry a holding whose last print is 24 July — delisted, suspended, or simply not
                # trading — and marking it at that price says "worth this today" about a number
                # seven weeks old. The panel being fresh says nothing about the column.
                quoted_on = series.index[-1].date()
                if (panel_end - quoted_on).days > MAX_PRICE_AGE_DAYS:
                    notes.append(
                        f"{t.removesuffix('.NS')} last traded {quoted_on}, "
                        f"{(panel_end - quoted_on).days} days before the panel's own last day — "
                        "shown as unpriced rather than marked at a stale quote."
                    )
                    continue
                out[t] = Decimal(str(float(series.iloc[-1])))
    except Exception as exc:
        notes.append(f"price panel unavailable ({exc})")
    missing = [t for t in tickers if t not in out]
    if missing:
        # The broker's average cost is NOT a price. Falling back to it would show a 0% gain on a
        # name that moved, which is worse than saying nothing — so it is left unpriced and named.
        notes.append(
            "no price for "
            + ", ".join(t.removesuffix(".NS") for t in missing)
            + " — shown as unknown rather than marked at cost or at zero."
        )
    return out, notes


def _proposal(
    account: ReconciledAccount, budget: Decimal, cfg: Config, mandate: Mandate
) -> tuple[list[tuple[str, int, Decimal]], list[str]]:
    """The day's basket from the deterministic screen — the one thing that would have been lost.

    This is the same ``advise_deploy_into_weakness`` the dashboard called; it never needed Streamlit,
    only the wiring around it. Returns ``(orders, notes)`` and NEVER raises: a screen that cannot run
    is a named absence on the page, not a missing section and not an empty basket, because an empty
    basket reads as "nothing worth buying" when the truth is "nothing was looked at".
    """
    notes: list[str] = []
    if budget <= 0:
        return [], ["This month's allowance is committed, so nothing was screened."]
    try:
        import pandas as pd
        from paper import _load_benchmark_series

        from qalpha.data.ingest import load_parquet
        from qalpha.live.deploy import advise_deploy_into_weakness

        wl = pd.read_csv("data/universes/nifty100_watchlist.csv")
        tickers = [str(t) for t in wl["ticker"]]
        sector_of = {str(t): str(sec) for t, sec in zip(wl["ticker"], wl["sector"], strict=True)}
        panel = load_parquet("data/historical/prices_watchlist.parquet")
        as_of = min(date.today(), panel.adj_close.index[-1].date())
        advice = advise_deploy_into_weakness(
            account.portfolio,
            budget,
            tickers,
            sector_of,
            panel,
            _load_benchmark_series(),
            as_of,
            max_names=mandate.max_names,
            max_sector_weight=mandate.max_sector_weight,
            max_name_fraction=mandate.max_name_fraction,
            spend_idle_cash=False,  # the budget IS the allowance; never the whole balance
        )
        if as_of != date.today():
            notes.append(
                f"The screen ran on {as_of}, the newest day in the price panel — not today. "
                "Refresh the panel for a current basket."
            )
        orders = [(o.ticker, int(o.quantity), o.price) for o in advice.deploy.buy_orders]
        if not orders:
            notes.append("The screen ran and proposed nothing that fits the allowance cleanly.")
        return orders, notes
    except Exception as exc:
        return [], [
            f"The screen could not run ({type(exc).__name__}: {exc}). No basket below means it was "
            "not looked at — not that nothing was worth buying."
        ]


def _panel_sha() -> str:
    """A fingerprint of the SCREENING data, not just the held names' marks.

    The snapshot hashed only the prices of things already owned, so changing an unheld candidate's
    price changed its recommended quantity and left the digest identical — two different decisions
    sharing one identity, which defeats the entire point of having one. The screen reads the whole
    watchlist panel and the benchmark, so both belong in the fingerprint.

    Shape and last row rather than every cell: enough to change when the data changes, cheap enough
    to compute on every run.
    """
    import hashlib

    h = hashlib.sha256()
    try:
        # THE WHOLE FILE. Hashing shape plus the last row missed the history the strategy actually
        # reads: `cheapness_scores` ranks on the fall from a rolling 1-YEAR high, so changing a
        # candidate's older prices changed the basket while the digest stayed identical. A content
        # hash of the bytes covers every row, and costs one read of a file already on disk.
        for panel in (SCREEN_PANEL, BENCHMARK_PANEL):
            if panel.exists():
                h.update(panel.name.encode())
                h.update(panel.read_bytes())
    except Exception:
        h.update(b"screening panel unreadable")
    return h.hexdigest()[:16]


def _prices_sha(prices: dict[str, Decimal], as_of: date | None) -> str:
    """A content hash of the marks this run used, and the day they are from.

    Without it two runs quoting different prices shared a digest, so a resumed run inherited work
    done against numbers that had since moved. A filename cannot prove this; an mtime is reset by a
    fresh checkout.
    """
    import hashlib

    payload = "|".join(f"{t}={prices[t]}" for t in sorted(prices)) + f"@{as_of}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


#: The panel `_proposal` screens from. Freshness must follow THIS file and no other.
SCREEN_PANEL = Path("data/historical/prices_watchlist.parquet")
BENCHMARK_PANEL = Path("data/historical/benchmark_NIFTYBEESNS_2026.parquet")


def _price_as_of() -> date | None:
    """The newest day in the panel the screen ACTUALLY READS, and in the benchmark beside it.

    It used to take the newest date across two panels while ``_proposal`` read one specific file —
    so a fresh secondary panel licensed a 90-day-old screening panel to produce ₹49,766 of
    recommendations. Freshness has to follow the data the decision is made from, and when two inputs
    are both required the OLDER one governs: a current price list against a stale benchmark still
    paces the deploy tranche off a stale market.
    """
    try:
        import pandas as pd

        from qalpha.data.ingest import load_parquet

        if not SCREEN_PANEL.exists():
            return None
        oldest = load_parquet(str(SCREEN_PANEL)).adj_close.index[-1].date()
        if BENCHMARK_PANEL.exists():
            raw = pd.read_parquet(BENCHMARK_PANEL)
            column = raw["date"] if "date" in raw.columns else raw.index
            bench = pd.to_datetime(pd.Series(list(column))).max().date()
            oldest = min(oldest, bench)
        return oldest
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-open", action="store_true", help="write the page, do not open a browser")
    ap.add_argument("--login", action="store_true", help="refresh the Kite session first")
    ap.add_argument(
        "--app",
        action="store_true",
        help="open the local app instead: buttons, live progress, the Kite login, token status",
    )
    ap.add_argument("--port", type=int, default=8787, help="port for --app (loopback only)")
    args = ap.parse_args(argv)

    if args.app:
        # The interactive half: a page you press buttons on, watching the run narrate itself. The
        # file this script writes is still the record; the app is a way to make it and read it.
        from qalpha.live.server import serve

        serve(args.port, open_browser=not args.no_open)
        return 0

    cfg = Config()
    notes: list[str] = []

    if args.login:
        from qalpha.live.auth import capture_request_token, exchange, login_url
        from qalpha.live.credentials import load_credentials

        creds = load_credentials()
        print(f"Opening Kite login…\n  {login_url(creds.api_key)}")
        webbrowser.open(login_url(creds.api_key))
        token = capture_request_token()
        exchange(creds, token)
        print("Session refreshed.")

    LOG.say(f"Reading tradebook exports from {TRADEBOOK_DIR}/", "step")
    trades, tb_notes = _trades()
    notes += tb_notes
    LOG.say(f"{len(trades)} dated trade(s) on file.", "detail" if trades else "warn")
    LOG.say("Asking Kite for holdings, average cost and cash…", "step")
    quantities, costs, cash, broker_notes = _broker(cfg)
    notes += broker_notes
    LOG.say(
        f"Broker returned {len(quantities)} holding(s)."
        if quantities
        else "Broker not reachable — working from the ledger alone.",
        "detail" if quantities else "warn",
    )

    # AN OUTAGE IS NOT A CONFIRMED EMPTY ACCOUNT. Buying already stopped correctly, but the account,
    # the saved snapshot and the displayed cash all became ₹0 — a known ₹2,01,117 overwritten by a
    # network failure. The last figure on file is carried forward FOR DISPLAY ONLY; `cash_confirmed`
    # stays False, so the gate still refuses to spend against it.
    last = load_snapshot(SNAPSHOT)
    cash_confirmed = cash is not None
    if cash is None and last is not None:
        cash = last.cash
        notes.append(
            f"Showing the last known balance, ₹{cash:,.0f} from {last.as_of} — not confirmed with "
            "the broker just now, and nothing will be bought against it."
        )

    # The ledger replay needs a number to set the balance to; the GATE gets the honest `None`.
    # Keeping the two apart is the point: the page may display a last-known figure, and nothing may
    # be bought against one.
    account = reconcile(
        trades,
        quantities,
        cash if cash is not None else Decimal("0"),
        cfg,
        date.today(),
        broker_costs=costs,
    )
    LOG.say("Marking holdings from the price panel…", "step")
    prices, price_notes = _prices(sorted(account.portfolio.positions()), costs)
    notes += price_notes
    LOG.say(f"{len(prices)} name(s) priced.", "detail")

    price_as_of = _price_as_of()
    LOG.say(
        f"Newest usable market data: {price_as_of}." if price_as_of else "No price panel at all.",
        "detail" if price_as_of else "error",
    )
    mandate = load_mandate()
    commitments = load_commitments(COMMITMENTS)

    # CONFIRM WHAT THE BROKER ACTUALLY EXECUTED, before deciding anything new. Recording a proposal
    # was only half the lifecycle: importing its purchases left it marked `proposed` with spending
    # still ₹0, so ₹49,766 of real buys still showed a full ₹50,000 allowance.
    for done in confirm_fills(commitments, trades, today=date.today()):
        record_commitment(done, COMMITMENTS)
        notes.append(
            f"{done.ticker.removesuffix('.NS')}: proposal confirmed as bought for "
            f"₹{done.amount:,.0f} — the allowance is debited, not just reserved."
        )
    commitments = load_commitments(COMMITMENTS)
    left = allowance(mandate.monthly_budget, commitments, period=date.today(), trades=trades)

    # The snapshot must identify the DATA, not only the account. It carried an empty price hash and
    # listed only the held names, so changing a holding's price from ₹80 to ₹88 left the digest
    # unchanged — and a decision that cannot be tied to the prices behind it cannot be replayed.
    stale: list[str] = []
    if price_as_of is not None and (date.today() - price_as_of).days > MAX_PRICE_AGE_DAYS:
        stale.append(f"prices are from {price_as_of}, {(date.today() - price_as_of).days} days old")
    if not cash_confirmed:
        stale.append("cash balance unconfirmed — the broker was not reachable")
    snapshot = snapshot_from(
        account,
        budget=left.remaining,
        universe=sorted(set(account.portfolio.positions()) | set(prices)),
        taken_at=datetime.now(UTC),
        # Held marks AND the screening panel: a decision depends on both, so its identity must too.
        prices_sha=f"{_prices_sha(prices, price_as_of)}:{_panel_sha()}",
        stale=stale,
        extraction_version=EXTRACTION_VERSION,
    )
    previous = last
    changes = snapshot.changes_against(previous)
    if changes and previous is not None:
        notes.append("Changed since the last run: " + "; ".join(changes))
    snapshot.save(SNAPSHOT, archive=SNAPSHOT_ARCHIVE)

    # THE GATE. Every check it makes already existed and was tested; NONE was in the buying path,
    # so a ₹100 account was offered a ₹49,658 basket and a book that did not reconcile got one
    # anyway. Nothing reaches the screen without passing here first.
    gate = evaluate(
        snapshot=snapshot,
        allowance=left,
        settled_cash=cash,
        cash_confirmed=cash_confirmed,
        price_as_of=price_as_of,
        today=date.today(),
        floor=mandate.idle_cash_floor,
    )
    notes += list(gate.reasons)
    LOG.say(
        f"Budget for this run: ₹{gate.budget:,.0f}."
        if gate.open
        else "No basket: " + " ".join(gate.reasons),
        "step" if gate.open else "warn",
    )
    orders: list[tuple[str, int, Decimal]] = []
    if gate.open:
        orders, screen_notes = _proposal(account, gate.budget, cfg, mandate)
        notes += screen_notes
        # WRITE WHAT WAS PROPOSED. The runner read the commitment ledger and never wrote to it, so
        # the allowance never moved: ₹49,766 of imported purchases still left ₹50,000 on offer, and
        # a second run proposed the same rupees again. A proposal RESERVES its money the moment it
        # is made — it is not spending until a broker trade confirms it, and `commitments.py` keeps
        # those two states apart.
        kept: list[tuple[str, int, Decimal]] = []
        for ticker, qty, price in orders:
            amount = Decimal(qty) * price
            open_already = already_committed(commitments, ticker)
            if open_already is not None:
                # SUPPRESSING THE RESERVATION IS NOT ENOUGH. The order stayed on the page, so the
                # basket showed something the run had deliberately declined to allocate for — an
                # instruction to buy money it had not set aside. Drop it and say why.
                notes.append(
                    f"{ticker.removesuffix('.NS')} is not in today's basket: it already has an "
                    f"open {open_already.state} decision from {open_already.on}."
                )
                continue
            kept.append((ticker, qty, price))
            record_commitment(
                Commitment(
                    id=f"{date.today().isoformat()}:{ticker}",
                    ticker=ticker,
                    state="proposed",
                    amount=amount,
                    on=date.today(),
                    reason=f"screen basket, {qty} @ {price}",
                ),
                COMMITMENTS,
            )
        orders = kept
        LOG.say(f"Screen proposed {len(orders)} name(s).", "detail")
        # RE-READ. The page must show the allowance AFTER this run's reservations, not before —
        # the first page said "₹50,000 available" and "nothing cleared the screen" on the very run
        # that had just reserved ₹49,766 and printed a basket. Three statements, one screen, two of
        # them false.
        commitments = load_commitments(COMMITMENTS)
        left = allowance(mandate.monthly_budget, commitments, period=date.today(), trades=trades)

    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(
        render(
            account=account,
            prices=prices,
            allowance=left,
            commitments=commitments,
            generated_at=datetime.now(UTC),
            notes=notes,
            proposal=orders,
        ),
        encoding="utf-8",
    )
    # "matches the broker" is false when the broker was never asked — with both sides empty,
    # `tallies` is trivially true and would have printed a reassurance nobody earned.
    if not cash_confirmed:
        LOG.say("Account NOT checked against the broker — no session this run.", "warn")
    else:
        LOG.say(
            f"Account reconciled: {'matches the broker' if account.tallies else 'does NOT match'}.",
            "detail" if account.tallies else "warn",
        )
    print(f"Wrote {PAGE.resolve()}")
    for note in notes:
        print(f"  · {note}")
    if not args.no_open:
        webbrowser.open(PAGE.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
