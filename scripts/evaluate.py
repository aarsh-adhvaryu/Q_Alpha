"""The evaluation harness: three separate tests, and an honest account of what is not measurable.

    uv run python scripts/evaluate.py                    # the report
    uv run python scripts/evaluate.py --out reports/evaluation.md

**One command, immutable inputs, no code change for a negative result.** It reads the records the
system already wrote — receipts, decisions, fills, the book history — and computes the same three
things whatever they say. There is no gate here and nothing to tune: a bad answer is an answer.

The three tests are kept apart because they fail for different reasons and conflating them is how a
system gets credit for luck:

1. **Operation** — did the machine do what was registered? Reviews attempted and completed, reviews
   that did not happen and why, orders queued and filled, the monthly budget, the caps. This is
   pass/fail and it is the only one that can be judged from a short record.
2. **Decision quality** — were the decisions *made properly*, independent of whether they paid?
   Every decision cites verified evidence, reviews every holding, states what would make it wrong.
   A decision can be well made and lose money; a decision can be badly made and win.
3. **Outcome** — did it beat the bar? Unitized NAV against ``BASELINE_EW``, which is blind to when
   money arrived. **This is the one that needs years**, and the report says how far it is from
   meaning anything rather than printing a number that invites over-reading.

What it cannot measure is printed too, by name. A harness that reports only what it can compute
teaches its reader that nothing else matters.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qalpha.config import Config
from qalpha.live import manager
from qalpha.live.console import use_utf8
from qalpha.live.twin import (
    BASELINE_EW,
    EVALUATION_START,
    SYSTEM,
    load_history,
    navs_from_history,
)

#: Below this many trading days of overlap, an outcome comparison is not reported as a figure. It is
#: not a threshold for significance — there is no such threshold at this sample size — it is the
#: point below which even the arithmetic is dominated by which day the window started.
MIN_OBSERVATIONS = 60

#: What the registration claims the outcome test needs before it can mean anything.
YEARS_FOR_AN_OUTCOME = 3


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _operation(store: manager.Store) -> tuple[list[str], int]:
    """Did the machine run as registered? Pass/fail, from its own records."""
    lines: list[str] = []
    problems = 0
    receipts = sorted(store.receipts.glob("*.json")) if store.receipts.exists() else []
    decisions = _rows(store.decisions)
    fills = _rows(store.fills)

    versions = Counter(str(r.get("version", "?")) for r in decisions)
    models = Counter(str(r.get("model", "?")) for r in decisions)
    lines.append(f"- Reviews with a saved receipt: **{len(receipts)}**")
    lines.append(f"- Decisions recorded: **{len(decisions)}**, fills recorded: **{len(fills)}**")
    lines.append(
        f"- Versions in the record: {dict(versions) or 'none'} · models: {dict(models) or 'none'}"
    )
    if len(versions) > 1:
        lines.append(
            "  - **More than one version is present.** Their records are not comparable and must "
            "not be pooled; each is its own experiment."
        )

    # Every decision must carry the model that made it: a record that cannot name its model cannot
    # be reproduced or attributed.
    unattributed = [r for r in decisions if not r.get("model") or not r.get("version")]
    if unattributed:
        problems += 1
        lines.append(f"- **{len(unattributed)} decision(s) name no model or version.** FAIL")

    # The monthly budget, counted from fills, which is what actually happened.
    spent: dict[str, Decimal] = {}
    for f in fills:
        if str(f.get("side", "")).upper() != "BUY":
            continue
        month = str(f.get("on", ""))[:7]
        cost = Decimal(str(f.get("cash", f.get("cost", "0")) or "0"))
        spent[month] = spent.get(month, Decimal("0")) + abs(cost)
    over = {m: v for m, v in spent.items() if v > manager.MONTHLY_BUDGET}
    if spent:
        worst = max(spent.values())
        lines.append(
            f"- Monthly purchases: {len(spent)} month(s), largest ₹{worst:,.0f} against a "
            f"₹{manager.MONTHLY_BUDGET:,.0f} limit — {'**OVER**' if over else 'within'}"
        )
    else:
        lines.append("- Monthly purchases: nothing has filled yet, so the budget is untested")
    if over:
        problems += 1
        lines.append(f"  - **Months over the limit: {sorted(over)}.** FAIL")

    # Code cutting an order is the system working, not a fault. It is counted so that a version
    # which constantly proposes the impossible is visible.
    cut = [r for r in decisions if r.get("requested_quantity") != r.get("accepted_quantity")]
    if decisions:
        lines.append(
            f"- Orders code reduced or cancelled: **{len(cut)} of {len(decisions)}** "
            f"({len(cut) / len(decisions):.0%}) — the limits binding is the design, not a fault"
        )
    return lines, problems


def _decision_quality(store: manager.Store) -> tuple[list[str], int]:
    """Were the decisions made properly — regardless of whether they paid?"""
    lines: list[str] = []
    problems = 0
    decisions = _rows(store.decisions)
    if not decisions:
        return ["- No decisions yet. Nothing to judge, and no credit either."], 0

    actions = Counter(str(r.get("action", "?")) for r in decisions)
    lines.append(f"- Action mix: {dict(actions)}")
    no_cite = [r for r in decisions if not r.get("evidence_ids")]
    no_invalidate = [r for r in decisions if not str(r.get("invalidate_if", "")).strip()]
    no_thesis = [r for r in decisions if not str(r.get("thesis", "")).strip()]
    for label, rows in (
        ("cite no evidence", no_cite),
        ("state nothing that would make them wrong", no_invalidate),
        ("carry no thesis", no_thesis),
    ):
        if rows:
            problems += 1
            lines.append(f"- **{len(rows)} decision(s) {label}.** FAIL")
    if not (no_cite or no_invalidate or no_thesis):
        lines.append(
            f"- All {len(decisions)} decisions cite verified evidence, carry a thesis, and state "
            "what would falsify them. Enforced at parse time, so this is a check that the "
            "enforcement is still on, not a compliment to the model."
        )

    # A thesis repeated unchanged for months is not conviction; it may be a model not reading. This
    # counts rather than judges.
    per_name: dict[str, set[str]] = {}
    for r in decisions:
        per_name.setdefault(str(r.get("ticker")), set()).add(str(r.get("thesis", "")).strip())
    repeated = {k for k, v in per_name.items() if len(v) == 1}
    reviewed_twice = {k for k, v in per_name.items() if len(v) >= 1 and _count(decisions, k) > 1}
    if reviewed_twice:
        lines.append(
            f"- Names reviewed more than once: {len(reviewed_twice)}; of those, "
            f"{len(repeated & reviewed_twice)} have never had their thesis reworded. Counted, not "
            "judged: an unchanged thesis can be conviction or inattention, and only reading the "
            "logbook distinguishes them."
        )
    return lines, problems


def _count(rows: list[dict[str, Any]], ticker: str) -> int:
    return sum(1 for r in rows if str(r.get("ticker")) == ticker)


def _outcome() -> tuple[list[str], int]:
    """Did it beat the bar — and is the record long enough for that question to mean anything?

    The unitized NAV comes from :func:`qalpha.live.twin.navs_from_history`, which derives each day's
    contribution from the day-on-day change in ``net_invested`` already on file. One source, so the
    flows behind the statistic cannot disagree with the flows behind the books.
    """
    lines: list[str] = []
    history = load_history()
    counted = [
        r
        for r in history
        if str(r.get("as_of", "")) >= (start.isoformat() if (start := EVALUATION_START) else "9999")
    ]
    n = len(counted)
    lines.append(
        f"- Registered start: **{EVALUATION_START or 'none'}** · observations inside the window: "
        f"**{n}**"
    )
    if EVALUATION_START is None:
        lines.append("- **NOT MEASURABLE.** No autonomous window is registered, so there is none.")
        return lines, 0
    if n < MIN_OBSERVATIONS:
        need = YEARS_FOR_AN_OUTCOME * 250
        lines.append(
            f"- **NOT MEASURABLE.** {n} observation(s) is far below the {MIN_OBSERVATIONS} at which "
            "even the arithmetic stops depending on which day the window opened, and much further "
            f"below the ~{need} sessions (~{YEARS_FOR_AN_OUTCOME} years) at which a difference in "
            "skill could be told from a difference in luck. No figure is printed here, because a "
            "figure printed here would be read as one."
        )
        return lines, 0

    navs = navs_from_history(history)
    system, bar = navs.get(SYSTEM), navs.get(BASELINE_EW)
    if system is None or bar is None or bar <= 0:
        lines.append("- Unitized NAV is unavailable for one of the books — unmeasured, not zero.")
        return lines, 0
    lines.append(
        f"- Unitized NAV: SYSTEM {system:.4f} against BASELINE_EW {bar:.4f} — "
        f"**{(system / bar - 1) * 100:+.1f}%**, over {n} observations. Unitized, so when money "
        "arrived neither flatters nor punishes it. Descriptive: at this length it separates nothing."
    )
    return lines, 0


def _not_measurable() -> list[str]:
    """Named limits. A harness that lists only what it computes teaches that nothing else matters."""
    out = [
        "- **Skill against luck.** Nothing in a record this short can separate them. Every number "
        "above is descriptive.",
        "- **A broader universe, point in time.** `NEXT_50_CHANGES` in "
        "`scripts/build_nifty100_pit.py` is still empty, so there is no point-in-time Nifty-100 "
        "membership. Candidate selection is therefore judged only against the Nifty-50 universe, "
        "which IS point-in-time. Filling it with today's constituents would look complete and "
        "reintroduce ~3.8%/yr of survivorship bias, so it stays empty until it is sourced.",
        "- **Whether the financials helped.** The exchange's results archive runs well behind the "
        "price panel for these names, so the investor is reading quarters that are months old and "
        "is told so. Any effect of financials on decisions is confounded with their staleness.",
        "- **Counterfactual decisions.** The record shows what it did, never what the alternative "
        "would have returned. There is no way to ask this system what it would have done with a "
        "different packet without running a different version.",
    ]
    return out


def main(argv: list[str] | None = None) -> int:
    use_utf8()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="", help="also write the report to this path")
    ap.add_argument("--store", default="", help="a different manager store (e.g. a shadow run)")
    args = ap.parse_args(argv)
    Config()
    store = manager.Store(Path(args.store)) if args.store else manager.STORE

    operation, op_fail = _operation(store)
    quality, q_fail = _decision_quality(store)
    outcome, _ = _outcome()

    parts = [
        f"# Evaluation — {manager.VERSION} on {manager.MODEL}",
        "",
        f"Generated {date.today().isoformat()} from the records in `{store.root}` and the book "
        "history. Immutable inputs; one command; no gate.",
        "",
        "## 1. Operation — did the machine run as registered?",
        *operation,
        "",
        "## 2. Decision quality — were the decisions made properly?",
        *quality,
        "",
        "## 3. Outcome — did it beat the bar?",
        *outcome,
        "",
        "## What this cannot measure",
        *_not_measurable(),
        "",
        "---",
        (
            f"**Verdict on operation:** {'FAIL' if op_fail else 'pass'} "
            f"({op_fail} problem(s)). "
            f"**Decision quality:** {'FAIL' if q_fail else 'pass'} ({q_fail} problem(s)). "
            "**Outcome:** not a verdict — see above."
        ),
    ]
    report = "\n".join(parts) + "\n"
    print(report)
    if args.out:
        from qalpha.live.atomic import write_text

        write_text(Path(args.out), report)
        print(f"[evaluate] written to {args.out}")
    return 1 if (op_fail or q_fail) else 0


if __name__ == "__main__":
    raise SystemExit(main())
