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
from qalpha.live.commitments import Commitment, allowance, already_committed
from qalpha.live.commitments import load as load_commitments
from qalpha.live.commitments import record as record_commitment
from qalpha.live.extraction import EXTRACTION_VERSION
from qalpha.live.mandate import load_mandate
from qalpha.live.report import render
from qalpha.live.session import load_snapshot, snapshot_from
from qalpha.live.tradebook import TradebookTrade, parse_tradebook

PAGE = Path("data/session/qalpha.html")
TRADEBOOK_DIR = Path("data/tradebooks")


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
                seen[t.trade_id or f"{t.trade_date}:{t.ticker}:{t.quantity}:{t.price}"] = t
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
            for t in tickers:
                if t in out or t not in adj.columns:
                    continue
                series = adj[t].dropna()
                if len(series):
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
    account: ReconciledAccount, budget: Decimal, cfg: Config
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
            max_names=load_mandate().max_names,
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


def _prices_sha(prices: dict[str, Decimal], as_of: date | None) -> str:
    """A content hash of the marks this run used, and the day they are from.

    Without it two runs quoting different prices shared a digest, so a resumed run inherited work
    done against numbers that had since moved. A filename cannot prove this; an mtime is reset by a
    fresh checkout.
    """
    import hashlib

    payload = "|".join(f"{t}={prices[t]}" for t in sorted(prices)) + f"@{as_of}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _price_as_of() -> date | None:
    """The newest day in the panels the screen reads. ``None`` when there is no panel at all."""
    try:
        from qalpha.data.ingest import load_parquet

        newest: date | None = None
        for path in (
            "data/historical/prices_watchlist.parquet",
            "data/historical/prices_pit_2026.parquet",
        ):
            if not Path(path).exists():
                continue
            day = load_parquet(path).adj_close.index[-1].date()
            newest = day if newest is None else max(newest, day)
        return newest
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-open", action="store_true", help="write the page, do not open a browser")
    ap.add_argument("--login", action="store_true", help="refresh the Kite session first")
    args = ap.parse_args(argv)

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

    trades, tb_notes = _trades()
    notes += tb_notes
    quantities, costs, cash, broker_notes = _broker(cfg)
    notes += broker_notes

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
    prices, price_notes = _prices(sorted(account.portfolio.positions()), costs)
    notes += price_notes

    price_as_of = _price_as_of()
    mandate = load_mandate()
    commitments = load_commitments()
    left = allowance(mandate.monthly_budget, commitments, period=date.today())

    # The snapshot must identify the DATA, not only the account. It carried an empty price hash and
    # listed only the held names, so changing a holding's price from ₹80 to ₹88 left the digest
    # unchanged — and a decision that cannot be tied to the prices behind it cannot be replayed.
    stale: list[str] = []
    if price_as_of is not None and (date.today() - price_as_of).days > MAX_PRICE_AGE_DAYS:
        stale.append(f"prices are from {price_as_of}, {(date.today() - price_as_of).days} days old")
    if cash is None:
        stale.append("cash balance unconfirmed — the broker was not reachable")
    snapshot = snapshot_from(
        account,
        budget=left.remaining,
        universe=sorted(set(account.portfolio.positions()) | set(prices)),
        taken_at=datetime.now(UTC),
        prices_sha=_prices_sha(prices, price_as_of),
        stale=stale,
        extraction_version=EXTRACTION_VERSION,
    )
    previous = load_snapshot()
    changes = snapshot.changes_against(previous)
    if changes and previous is not None:
        notes.append("Changed since the last run: " + "; ".join(changes))
    snapshot.save()

    # THE GATE. Every check it makes already existed and was tested; NONE was in the buying path,
    # so a ₹100 account was offered a ₹49,658 basket and a book that did not reconcile got one
    # anyway. Nothing reaches the screen without passing here first.
    gate = evaluate(
        snapshot=snapshot,
        allowance=left,
        settled_cash=cash,
        cash_confirmed=cash is not None,
        price_as_of=price_as_of,
        today=date.today(),
        floor=mandate.idle_cash_floor,
    )
    notes += list(gate.reasons)
    orders: list[tuple[str, int, Decimal]] = []
    if gate.open:
        orders, screen_notes = _proposal(account, gate.budget, cfg)
        notes += screen_notes
        # WRITE WHAT WAS PROPOSED. The runner read the commitment ledger and never wrote to it, so
        # the allowance never moved: ₹49,766 of imported purchases still left ₹50,000 on offer, and
        # a second run proposed the same rupees again. A proposal RESERVES its money the moment it
        # is made — it is not spending until a broker trade confirms it, and `commitments.py` keeps
        # those two states apart.
        for ticker, qty, price in orders:
            amount = Decimal(qty) * price
            if already_committed(commitments, ticker) is not None:
                continue  # an open decision on this name already holds its allocation
            record_commitment(
                Commitment(
                    id=f"{date.today().isoformat()}:{ticker}",
                    ticker=ticker,
                    state="proposed",
                    amount=amount,
                    on=date.today(),
                    reason=f"screen basket, {qty} @ {price}",
                ),
            )

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
    print(f"Wrote {PAGE.resolve()}")
    for note in notes:
        print(f"  · {note}")
    if not args.no_open:
        webbrowser.open(PAGE.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
