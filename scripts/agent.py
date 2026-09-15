"""AI-PM-3: see what tonight's attention would review, test decision models, run a shadow review.

    uv run python scripts/agent.py attention                 # tonight's triggers for SYSTEM ($0, no model)
    uv run python scripts/agent.py scenarios --model claude-sonnet-5 --budget-usd 2
    uv run python scripts/agent.py scenarios --model qwen3.5-9b-16k      # local: free
    uv run python scripts/agent.py agreement --candidate qwen3.5-9b-16k --reference claude-sonnet-5
    uv run python scripts/agent.py shadow-review             # one real AI-PM-3 review on a COPY of SYSTEM
    uv run python scripts/agent.py compare                   # live book vs the expanding shadow book

Nothing here changes the SYSTEM book. AI-PM-3 runs the evening only from the start date written in
``reports/PREREGISTRATION_AI_PM3.md`` and ``agent.Registration.start``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qalpha.config import Config
from qalpha.live import agent, manager, scenarios, spend
from qalpha.live.console import use_utf8
from qalpha.live.market import Market
from qalpha.live.progress import IST
from qalpha.live.twin import TwinBook


def _system() -> tuple[TwinBook, Market] | None:
    import twin

    from qalpha.live.twin import SYSTEM, load_books

    book = load_books(Config()).get(SYSTEM)
    market = twin._market(date.today())
    if book is None or market is None:
        print("[agent] no SYSTEM book or no market data", file=sys.stderr)
        return None
    return book, market


def cmd_attention(args: argparse.Namespace) -> int:
    from qalpha.live import graph as g

    loaded = _system()
    if loaded is None:
        return 2
    book, market = loaded
    copy = TwinBook(
        name="SYSTEM-attention",
        portfolio=book.portfolio.clone(),
        flows=list(book.flows),
        manager=dict(book.manager),
    )
    files = agent.Files(agent.AGENT_DIR / "preview")
    try:
        packet, attention, reviewed = agent.build(
            copy,
            market,
            store=manager.STORE,
            files=files,
            graph_log=g.GraphLog(),
            known_on=None,
            failed_steps=agent.failed_steps_today(datetime.now(IST).date()),
            registration=agent.REGISTRATION,
        )
    except manager.IncompleteReviewError as exc:
        print(f"[agent] cannot build tonight's packet: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(attention.as_dict(), indent=1))
    print(
        f"[agent] holdings under review: {reviewed or 'none'}; candidates: {[c['ticker'] for c in packet['candidates']]}"
    )
    return 0


def cmd_scenarios(args: argparse.Namespace) -> int:
    budget = None if args.budget_usd is None else Decimal(args.budget_usd)
    paid = args.model.startswith(("claude-", "deepseek-"))
    if paid and budget is None:
        print("[agent] a paid model needs --budget-usd", file=sys.stderr)
        return 2
    ledger = spend.Ledger(job=f"ai-pm3-scenarios-{args.model}", job_limit_usd=budget)
    try:
        mind = agent.brain_for(
            args.model, partition=spend.RESEARCH if paid else "decisions", ledger=ledger
        )
    except manager.IncompleteReviewError as exc:
        print(f"[agent] {exc}", file=sys.stderr)
        return 2
    results = scenarios.run_suite(mind.generate, args.model)
    path = scenarios.save(args.model, results)
    for r in results:
        print(f"  {'PASS' if r.passed else 'FAIL'}  {r.scenario:<26} {'; '.join(r.problems)}")
    passed = sum(r.passed for r in results)
    print(f"[agent] {args.model}: {passed}/{len(results)} scenarios passed → {path}")
    return 0 if passed == len(results) else 1


def cmd_agreement(args: argparse.Namespace) -> int:
    a, b = (
        scenarios.results_dir() / f"{args.candidate}.json",
        scenarios.results_dir() / f"{args.reference}.json",
    )
    for p in (a, b):
        if not p.exists():
            print(
                f"[agent] no saved run at {p}; run scenarios for that model first", file=sys.stderr
            )
            return 2
    print(json.dumps(scenarios.agreement(a, b), indent=1))
    return 0


def cmd_shadow_review(args: argparse.Namespace) -> int:
    loaded = _system()
    if loaded is None:
        return 2
    book, market = loaded
    root = agent.AGENT_DIR / "shadow-review"
    store = manager.Store(root / "records")
    store.root.mkdir(parents=True, exist_ok=True)
    for name in ("logbook.jsonl", "decisions.jsonl", "fills.jsonl"):
        live = manager.STORE.root / name
        if live.exists():
            shutil.copyfile(
                live, store.root / name
            )  # its memory, on a copy: nothing live is written
    copy = TwinBook(
        name="SYSTEM-shadow-v3",
        portfolio=book.portfolio.clone(),
        flows=list(book.flows),
        actions_through=book.actions_through or book.stepped_through or market.as_of,
    )
    now = datetime.now(IST)
    try:
        decisions = agent.review(
            copy,
            market,
            now=now,
            store=store,
            files=agent.Files(root),
            require_today=False,
            known_on=now.date(),
            failed_steps=agent.failed_steps_today(now.date()),
        )
    except manager.IncompleteReviewError as exc:
        print(f"[agent] INCOMPLETE: {exc}", file=sys.stderr)
        return 2
    for d in decisions:
        print(f"  {d.ticker:<14} {d.action:<14} {d.reason}")
    print(f"[agent] receipts and records in {root} — no book was changed.")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    loaded = _system()
    if loaded is None:
        return 2
    book, market = loaded
    if not agent.FILES.shadow.exists():
        print("[agent] no shadow book yet: it starts with AI-PM-3's first evening")
        return 0
    shadow = agent.load_shadow(agent.FILES, book, on=market.as_of, registration=agent.REGISTRATION)
    prices = {
        t: p
        for t in {*book.portfolio.positions(), *shadow.portfolio.positions()}
        if (p := manager.raw_close(market, market.as_of, t)) is not None
    }
    print(
        json.dumps(
            agent.compare_books(book, shadow, manager.STORE, prices, market.sector_of or {}),
            indent=1,
            default=str,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    use_utf8()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("attention", help="tonight's triggers, no model call").set_defaults(
        fn=cmd_attention
    )
    p = sub.add_parser("scenarios", help="run the scenario suite on one model")
    p.add_argument("--model", required=True)
    p.add_argument("--budget-usd")
    p.set_defaults(fn=cmd_scenarios)
    p = sub.add_parser("agreement", help="agreement between two saved scenario runs")
    p.add_argument("--candidate", required=True)
    p.add_argument("--reference", required=True)
    p.set_defaults(fn=cmd_agreement)
    sub.add_parser("shadow-review", help="one real AI-PM-3 review on a copy").set_defaults(
        fn=cmd_shadow_review
    )
    sub.add_parser("compare", help="live book vs shadow book").set_defaults(fn=cmd_compare)
    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
