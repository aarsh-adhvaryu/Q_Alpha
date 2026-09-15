"""Replay the investor over past sessions — its own book, its own records, its own spend ceiling.

    uv run python scripts/replay.py coverage --start 2026-09-01 --end 2026-09-11
    uv run python scripts/replay.py run pilot-1 --start 2026-09-01 --end 2026-09-11 --ceiling 5
    uv run python scripts/replay.py run pilot-1          # resume where it stopped
    uv run python scripts/replay.py status pilot-1
    uv run python scripts/replay.py report pilot-1 --out reports/REPLAY_pilot-1.md

``coverage`` makes **no model call and writes nothing**: for every session it builds the packet the
investor would get for the starting book and counts what is in it and what is missing. Run it before
choosing a window.

``run`` is the one command. The first call registers the run in ``data/replay/<run>/run.json`` — the
window, the model, a digest of the mandate and prompt, the code commit, the corpus date and the spend
ceiling — then replays. Every later call resumes, and refuses if the code, model, mandate or prompt
is no longer the registered one: a change is a new run. **It spends money**, charged to its own job
in ``data/spend/ledger.jsonl`` and stopped at the ceiling. The evening run's records are hashed before
and after, and any change is printed and kept in ``integrity.jsonl``.

``report`` writes the consolidated evaluation: operation, decisions, what the investor was shown,
accounting, descriptive figures beside both baselines, and whether the real records were touched.

**What a replay cannot show.** The model may already know how these sessions went. It tests that the
investor runs correctly; its returns are not evidence of skill.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import evaluate
import twin as twin_script

from qalpha.config import Config
from qalpha.live import atomic, manager, replay, spend
from qalpha.live.console import use_utf8
from qalpha.live.evidence_log import corpus_as_of
from qalpha.live.flows import Flow
from qalpha.live.market import Market
from qalpha.live.news import NEWS_DIR
from qalpha.live.progress import IST
from qalpha.live.twin import flows_with_off_market, load_off_market

#: Files whose change makes a run's code a different investor. Data and tests are not the investor.
CODE = ("src", "scripts", "pyproject.toml", "uv.lock")

ABORTED = 2


def _commit() -> tuple[str, bool]:
    """The code commit, and whether the investor's code differs from it on disk."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", *CODE],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True
    return head, bool(dirty)


def _inputs() -> tuple[Market, list[Any], list[Flow], list[Any], list[Any]] | None:
    """The evening run's own readers: the price panels, the tradebook, the ledger's flows, the actions."""
    full = twin_script._market(date.today())
    if full is None:
        return None
    trades, notes = twin_script._tradebook()
    if notes or not trades:
        print(f"[replay] tradebook unusable: {'; '.join(notes) or 'it is empty'}", file=sys.stderr)
        return None
    credits = load_off_market()
    flows = twin_script._flows(trades, credits)
    return (
        full,
        trades,
        flows_with_off_market(trades, credits) if flows is None else flows,
        (twin_script._actions()),
        credits,
    )


def cmd_coverage(start: date, end: date, recorded_by: date) -> int:
    """What the investor would be shown on each session, for the starting book. No model, no writes."""
    loaded = _inputs()
    if loaded is None:
        return ABORTED
    full, trades, flows, actions, credits = loaded
    cfg = Config()
    book = replay.reconstruct(
        start, trades=trades, flows=flows, actions=actions, off_market=credits, cfg=cfg
    )
    headlines_from = replay.archive_starts(NEWS_DIR)
    days = replay.sessions(full, start, end)
    corpus = corpus_as_of(recorded_by)
    print(
        f"# Coverage — {start} to {end}, {len(days)} session(s), corpus as of {recorded_by}\n\n"
        f"Starting book: {len(book.portfolio.positions())} name(s), cash ₹{book.portfolio.cash:,.2f}. "
        f"Headlines archived from: {headlines_from or 'never'}. The book is held fixed here, so the "
        "candidates are what this book would be shown; a real run's book changes as it decides.\n"
    )
    print(
        "| session | reviewable | held filings filed/read/unread | events (held · shown) | "
        "candidates shown | not shown | exchange file | financials unknown | gaps |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    with tempfile.TemporaryDirectory() as tmp:
        store = manager.Store(Path(tmp))
        for day in days:
            market = replay.world_on(full, day)
            if market is None:
                print(f"| {day} | **no closes in the watchlist panel** | | | | | | | |")
                continue
            try:
                packet = manager.build_packet(
                    book,
                    market,
                    store,
                    known_on=day,
                    corpus=corpus,
                    gaps=replay.gaps_on(day, headlines_from=headlines_from),
                )
            except manager.IncompleteReviewError as exc:
                print(f"| {day} | **INCOMPLETE — {exc}** | | | | | | | |")
                continue
            s = replay.packet_summary(packet)
            held = [h["ticker"] for h in packet["portfolio"]["holdings"]]
            filed = sum(s["filings"][t]["filed"] for t in held)
            read = sum(s["filings"][t]["read"] for t in held)
            unread = sum(s["filings"][t]["unread"] for t in held)
            events_held = sum(s["events"].get(t.removesuffix(".NS"), 0) for t in held)
            events_shown = sum(
                s["events"].get(t.removesuffix(".NS"), 0) for t in s["candidates_shown"]
            )
            reasons = Counter(s["not_shown"].values())
            print(
                f"| {day} | yes | {filed}/{read}/{unread} | {events_held} · {events_shown} | "
                f"{len(s['candidates_shown'])} | "
                f"{', '.join(f'{n} {r}' for r, n in reasons.items()) or '—'} | "
                f"{'UNKNOWN' if len(s['exchange_unknown']) == len(held) + len(s['candidates_shown']) else 'on file'} | "
                f"{len(s['financials_unknown'])} | {', '.join(s['data_gaps']) or '—'} |"
            )
    return 0


def _log_integrity(paths: replay.Paths, entry: dict[str, Any]) -> None:
    existing = (
        (paths.root / "integrity.jsonl").read_text(encoding="utf-8")
        if (paths.root / "integrity.jsonl").exists()
        else ""
    )
    atomic.write_text(
        paths.root / "integrity.jsonl", existing + json.dumps(entry, sort_keys=True) + "\n"
    )


def cmd_run(
    run_id: str,
    *,
    start: date | None,
    end: date | None,
    ceiling: Decimal | None,
    recorded_by: date | None,
) -> int:
    paths = replay.paths_for(run_id)
    commit, dirty = _commit()
    if dirty:
        print(
            f"[replay] the investor's code ({', '.join(CODE)}) has uncommitted changes, so no commit "
            "names what would run. Commit or discard them first.",
            file=sys.stderr,
        )
        return ABORTED
    plan = replay.load_plan(paths)
    if plan is not None:
        given = {"start": start, "end": end, "ceiling_usd": ceiling, "recorded_by": recorded_by}
        registered = plan.to_dict()
        clash = [k for k, v in given.items() if v is not None and str(v) != registered[k]]
        if clash:
            print(
                f"[replay] {run_id} is registered with "
                f"{', '.join(f'{k}={registered[k]}' for k in clash)}; a registered run is never "
                "changed. Omit the flags to resume, or start a new run.",
                file=sys.stderr,
            )
            return ABORTED
    elif start is None or end is None or ceiling is None:
        print("[replay] a new run needs --start, --end and --ceiling", file=sys.stderr)
        return ABORTED

    loaded = _inputs()
    if loaded is None:
        return ABORTED
    full, trades, flows, actions, credits = loaded
    if plan is None:
        assert start is not None and end is not None and ceiling is not None
        try:
            plan = replay.new_plan(
                run_id,
                start=start,
                end=end,
                recorded_by=recorded_by or date.today(),
                ceiling_usd=ceiling,
                commit=commit,
                inputs=replay.inputs_digest(
                    full, end, trades=trades, flows=flows, actions=actions, off_market=credits
                ),
            )
        except ValueError as exc:
            print(f"[replay] {exc}", file=sys.stderr)
            return ABORTED
        replay.save_plan(paths, plan, corpus_as_of(plan.recorded_by))
        print(f"[replay] registered {paths.plan}")
    moved = replay.changed_since(
        plan,
        commit=commit,
        inputs=replay.inputs_digest(
            full, plan.end, trades=trades, flows=flows, actions=actions, off_market=credits
        ),
    )
    if moved:
        print(
            f"[replay] {run_id} was registered with different code or inputs: {'; '.join(moved)}. "
            "A change is a new run.",
            file=sys.stderr,
        )
        return ABORTED

    ledger = spend.Ledger(job=plan.spend_job, job_limit_usd=plan.ceiling_usd)
    try:
        mind = manager.brain(ledger=ledger, partition=spend.RESEARCH)
    except manager.IncompleteReviewError as exc:
        print(f"[replay] {exc}", file=sys.stderr)
        return ABORTED

    before = replay.fingerprint()
    started = datetime.now(UTC).isoformat(timespec="seconds")
    status = 0
    try:
        state = replay.run(
            plan,
            paths,
            full=full,
            now=datetime.now(IST),
            make_brain=lambda: mind,
            trades=trades,
            flows=flows,
            actions=actions,
            off_market=credits,
            cfg=Config(),
            headlines_from=replay.archive_starts(NEWS_DIR),
        )
        print(f"[replay] checkpointed through {state.through} — {len(state.sessions)} session(s)")
    except replay.ReplayStoppedError as exc:
        print(f"[replay] STOPPED — {exc}. Nothing was recorded for that session.", file=sys.stderr)
        status = ABORTED
    finally:
        touched = replay.changed(before, replay.fingerprint())
        _log_integrity(
            paths,
            {
                "started": started,
                "ended": datetime.now(UTC).isoformat(timespec="seconds"),
                "commit": commit,
                "live_records_changed": touched,
            },
        )
        print(
            f"[replay] spent on this run so far: ${ledger.job_committed(plan.spend_job):.4f} of "
            f"${plan.ceiling_usd}"
        )
        if touched:
            print(f"[replay] **THE EVENING RUN'S RECORDS CHANGED**: {touched}", file=sys.stderr)
            status = ABORTED
    return status


def cmd_status(run_id: str) -> int:
    paths = replay.paths_for(run_id)
    plan = replay.load_plan(paths)
    if plan is None:
        print(f"[replay] no run {run_id}")
        return ABORTED
    state = replay.load_state(paths, Config())
    done = len(state.sessions) if state else 0
    print(
        f"{run_id}: {plan.start} → {plan.end}, {plan.model} ({plan.version}), commit {plan.commit[:12]}\n"
        f"  sessions checkpointed: {done}, through {state.through if state else 'none'}\n"
        f"  spend: ${spend.Ledger().job_committed(plan.spend_job):.4f} of ${plan.ceiling_usd}"
    )
    return 0


def _money(value: object) -> str:
    return "unknown" if value is None else f"₹{Decimal(str(value)):,.2f}"


def report(run_id: str) -> str | None:
    """The consolidated evaluation of one run, as markdown."""
    paths = replay.paths_for(run_id)
    plan = replay.load_plan(paths)
    state = replay.load_state(paths, Config()) if plan else None
    if plan is None or state is None:
        return None
    store = paths.store
    rows = state.sessions
    reviewed = [r for r in rows if r.get("status") == "reviewed"]
    incomplete = [r for r in rows if r.get("status") == "incomplete"]
    spent = spend.Ledger().job_committed(plan.spend_job)
    integrity = evaluate._rows(paths.root / "integrity.jsonl")
    fills = evaluate._rows(store.fills)
    decisions = evaluate._rows(store.decisions)
    operation, _ = evaluate._operation(store)
    quality, _ = evaluate._decision_quality(store)
    b = state.boundary
    out: list[str] = [
        f"# Replay {run_id} — {plan.version} over {plan.start} to {plan.end}",
        "",
        "**A plumbing test, not a performance record.** The model may already know how these "
        "sessions turned out, so nothing below is evidence of skill. What it can show is whether the "
        "investor researches, decides, fills, remembers and resumes correctly, and what it was shown.",
        "",
        f"- Model `{plan.model}`, investor digest `{plan.investor}`, code commit `{plan.commit}`",
        f"- Filings and headlines: documents public by each session, from the corpus recorded by "
        f"{plan.recorded_by} (read later, published then)",
        f"- Spend: **${spent:.4f}** of a ${plan.ceiling_usd} ceiling, job `{plan.spend_job}`",
        f"- Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC from `{paths.root}`",
        "",
        "## 1. Starting book — the origin",
        f"- The close of **{b['as_of']}**, rebuilt from the tradebook and the broker's ledger through "
        "that day.",
        f"- Value {_money(b.get('value'))} · cash {_money(b.get('cash'))} · net invested "
        f"{_money(b.get('net_invested'))}",
        f"- Holdings: {', '.join(f'{t} {q}' for t, q in b['holdings'].items()) or 'none'}",
        "",
        "## 2. Operation",
        f"- Sessions in the window checkpointed: **{len(rows)}** · reviewed **{len(reviewed)}** · "
        f"incomplete **{len(incomplete)}**",
    ]
    for reason, n in Counter(str(r.get("reason")) for r in incomplete).most_common():
        out.append(f"  - {n}× {reason}")
    waiting = [r for r in rows if r.get("waiting")]
    research = sum(int((r.get("packet") or {}).get("research_requests", 0)) for r in reviewed)
    out += [
        f"- Orders waiting on a missing close: {len(waiting)} session(s)"
        + (f" — {waiting[-1]['waiting']}" if waiting else ""),
        f"- Research rounds used: {sum(1 for r in reviewed if (r.get('packet') or {}).get('research_requests'))} "
        f"({research} look-up(s))",
        f"- Later reviews that carried its own earlier notes: "
        f"{sum(1 for r in reviewed if (r.get('packet') or {}).get('memory_notes'))} of {len(reviewed)}",
        f"- Resumed: {len(integrity)} invocation(s) of `run`",
        *operation,
        "",
        "## 3. Decisions",
        *quality,
    ]
    for r in reviewed:
        queued = ", ".join(
            f"{o['action']} {o['quantity']} {o['ticker']}" for o in r.get("queued") or []
        )
        out.append(
            f"- {r['as_of']}: {r.get('decisions')}" + (f" · queued {queued}" if queued else "")
        )
    cut = [d for d in decisions if d.get("status") not in ("hold", "filled")]
    for d in cut:
        out.append(f"  - code: {d['as_of']} {d['action']} {d['ticker']} — {d['status']}")
    out += [
        "",
        "## 4. What it was shown",
        "| session | held filings filed/read/unread | events on held | candidates shown | not shown | "
        "exchange unknown | financials unknown | gaps |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in reviewed:
        s = r.get("packet") or {}
        fil = s.get("filings", {})
        held = [t for t in fil if t not in set(s.get("candidates_shown", []))]
        out.append(
            f"| {r['as_of']} | {sum(fil[t]['filed'] for t in held)}/"
            f"{sum(fil[t]['read'] for t in held)}/{sum(fil[t]['unread'] for t in held)} | "
            f"{sum(s.get('events', {}).get(t.removesuffix('.NS'), 0) for t in held)} | "
            f"{len(s.get('candidates_shown', []))} | "
            f"{', '.join(f'{n} {k}' for k, n in Counter(s.get('not_shown', {}).values()).items()) or '—'} | "
            f"{len(s.get('exchange_unknown', []))} | {len(s.get('financials_unknown', []))} | "
            f"{', '.join(s.get('data_gaps', [])) or '—'} |"
        )
    cash_path = [Decimal(str(r["cash"])) for r in rows if r.get("cash") is not None]
    credited = [f for r in rows for f in r.get("flows") or []]
    actions = [a for r in rows for a in r.get("corporate_actions") or []]
    out += [
        "",
        "## 5. Accounting",
        f"- Money credited during the run: {len(credited)} movement(s)"
        + (
            f" — {', '.join(f'{f["on"]} ₹{Decimal(f["amount"]):,.2f}' for f in credited)}"
            if credited
            else ""
        ),
        f"- Corporate actions credited: {len(actions)}"
        + (f" — {'; '.join(actions)}" if actions else ""),
        f"- Fills: {len(fills)} row(s), "
        f"{sum(1 for f in fills if int(f.get('filled', 0) or 0))} with shares; statuses "
        f"{dict(Counter(str(f.get('status')) for f in fills)) or 'none'}",
        f"- Lowest cash after a session: {_money(min(cash_path)) if cash_path else 'unknown'}"
        + (" — **NEGATIVE**" if cash_path and min(cash_path) < 0 else ""),
        f"- End: value {_money(rows[-1].get('value')) if rows else 'unknown'}, cash "
        f"{_money(rows[-1].get('cash')) if rows else 'unknown'}",
    ]
    ew = twin_script._ew_fund_series()
    figures = replay.outcome(
        state, store, index_close=twin_script._benchmark_series(), ew_series=ew
    )
    out += [
        "",
        "## 6. Descriptive figures — not evidence of skill",
        f"Unitized, so deposits are not returns. {figures['sessions']} session(s); a figure over this "
        "few sessions separates nothing, and the model may know the outcome.",
    ]
    if figures.get("value_unknown_on"):
        out.append(
            f"- Value unknown (a holding had no close) on: {', '.join(figures['value_unknown_on'])}"
        )
    for label, key in (
        ("The replayed investor", "system"),
        ("Equal-weight fund, same money same days", "baseline_equal_weight_fund"),
        ("NIFTYBEES, same money same days", "baseline_niftybees"),
    ):
        f = figures.get(key)
        out.append(
            f"- {label}: "
            + (
                f"return {f['return_pct']:+.2f}%, worst drawdown {f['max_drawdown_pct']:.2f}%"
                if f
                else "unavailable — not zero"
            )
        )
    if figures.get("traded_value") is not None:
        out.append(
            f"- Turnover {figures['turnover_pct_of_average_value']}% of average value · traded "
            f"{_money(figures['traded_value'])} · costs {_money(figures['costs'])} · tax "
            f"{_money(figures['tax'])}"
        )
    touched = sorted({f for e in integrity for f in e.get("live_records_changed", [])})
    out += [
        "",
        "## 7. The evening run's records",
        f"- Hashed before and after every one of {len(integrity)} invocation(s): "
        + (f"**CHANGED — {', '.join(touched)}**" if touched else "unchanged."),
        "- The spend ledger is not among them: it is the record of real money, and this run's "
        "calls are in it under its own job.",
        "",
        "## 8. Named limits",
        "- **Hindsight.** The model's training may include these sessions' outcomes.",
        "- **Candidates** come from today's Nifty-100 watchlist, not the membership on each date.",
        "- **Filings were read after the fact**, by the registered reader, from documents public by "
        "each session. An event the reader dated after the session is not shown.",
        "- **Headlines** before the archive began are UNKNOWN, and the packet says so.",
        "- **Prices** are the vendor's; a split after a session would make earlier closes differ from "
        "the prints of the day.",
    ]
    return "\n".join(out) + "\n"


def cmd_report(run_id: str, out: str) -> int:
    text = report(run_id)
    if text is None:
        print(f"[replay] {run_id} has no registration or no checkpoint yet", file=sys.stderr)
        return ABORTED
    print(text)
    if out:
        atomic.write_text(Path(out), text)
        print(f"[replay] written to {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    use_utf8()  # first: Windows pipes fall back to cp1252 and die on a rupee sign
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    cov = sub.add_parser("coverage", help="what each session would show; no model, no writes")
    cov.add_argument("--start", required=True, type=date.fromisoformat)
    cov.add_argument("--end", required=True, type=date.fromisoformat)
    cov.add_argument("--recorded-by", type=date.fromisoformat, default=None)
    go = sub.add_parser("run", help="register (first call) and replay; resumes; SPENDS MONEY")
    go.add_argument("run_id")
    go.add_argument("--start", type=date.fromisoformat, default=None)
    go.add_argument("--end", type=date.fromisoformat, default=None)
    go.add_argument("--ceiling", type=Decimal, default=None, help="USD, for the whole run")
    go.add_argument("--recorded-by", type=date.fromisoformat, default=None)
    st = sub.add_parser("status")
    st.add_argument("run_id")
    rep = sub.add_parser("report")
    rep.add_argument("run_id")
    rep.add_argument("--out", default="")
    args = ap.parse_args(argv)
    if args.cmd == "coverage":
        return cmd_coverage(args.start, args.end, args.recorded_by or date.today())
    if args.cmd == "run":
        return cmd_run(
            args.run_id,
            start=args.start,
            end=args.end,
            ceiling=args.ceiling,
            recorded_by=args.recorded_by,
        )
    if args.cmd == "status":
        return cmd_status(args.run_id)
    return cmd_report(args.run_id, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
