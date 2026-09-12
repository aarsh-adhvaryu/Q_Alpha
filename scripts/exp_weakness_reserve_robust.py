"""WC-2b — is the deep-only reserve an effect, or is it fitted to this history?

    uv run python scripts/exp_weakness_reserve_robust.py

**Read `reports/PREREGISTRATION_WEAKNESS_RESERVE.md` §8 first.** That section was registered after
WC-2's grid was seen and before this script was written, and it fixes the decision rule:

    beats the control in BOTH halves at BOTH r, and at ALL THREE thresholds  -> wire it
    wins overall but fails any half or any threshold                         -> stays disconnected
    COVID alone carries it                                                   -> do not wire it

WC-2 found the deep-only reserve worth +6.27% at r=0.25 and +12.23% at r=0.50 over fourteen years.
That is one path, and the eleven deep months come from about seven episodes with COVID supplying
four of them. Two attacks here: split the period, and move the threshold that defines "deep".

**A rule that works only at -12% is fitted to where this particular history's drawdowns happened to
fall.** That is the more dangerous of the two failures, because -12% was chosen by people who had
seen this history.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exp_weakness_reserve import (
    DEEP_AT,
    Result,
    _assert_classifier_agrees,
    run,
)

from qalpha.config import Config
from qalpha.live.console import use_utf8

REPORT = Path("reports/WEAKNESS_RESERVE_WC2B.md")

#: Fixed in §8 before this ran. Both halves contain deep episodes.
PERIODS = (
    ("full 2012-2026", "2012-01-01", "2026-09-11"),
    ("first half 2012-2019", "2012-01-01", "2019-06-30"),
    ("second half 2019-2026", "2019-07-01", "2026-09-11"),
)
HOLD_BACK = (Decimal("0.25"), Decimal("0.50"))
THRESHOLDS = (-0.10, DEEP_AT, -0.15)
DEEP_ONLY = ("deep",)


def main() -> int:
    use_utf8()
    cfg = Config()

    # HARNESS CHECK. The perturbation test reproduces `market_weakness`'s classification with the
    # threshold exposed; if that copy has drifted from the live function at the shipped -12%, every
    # row below is measuring a rule nobody runs.
    from typing import cast

    import pandas as pd
    from exp_weakness_reserve import PIT_PANEL
    from paper import _load_benchmark_series

    from qalpha.data.ingest import load_parquet

    bench = _load_benchmark_series()
    idx = cast(
        pd.DatetimeIndex,
        load_parquet(PIT_PANEL).adj_close.loc["2012-01-01":"2026-09-11"].index,
    )
    paydays = [
        stamp.date()
        for stamp in sorted(
            set(pd.DataFrame(index=idx).groupby([idx.year, idx.month]).apply(lambda g: g.index[0]))
        )
    ]
    _assert_classifier_agrees(bench, paydays)
    print(f"[wc2b] classifier agrees with market_weakness on all {len(paydays)} paydays")

    rows: list[tuple[str, float, float, float, float, int]] = []
    failures: list[str] = []
    for label, start, end in PERIODS:
        for deep_at in THRESHOLDS:
            control = Result(Decimal("0"), DEEP_ONLY)
            run(cfg, control, start=start, end=end, deep_at=deep_at)
            for hold in HOLD_BACK:
                cell = Result(hold, DEEP_ONLY)
                run(cfg, cell, start=start, end=end, deep_at=deep_at)
                edge = cell.terminal / control.terminal - 1.0
                rows.append((label, deep_at, float(hold), cell.terminal, edge, cell.releases))
                mark = "ok " if edge > 0 else "LOSS"
                if edge <= 0:
                    failures.append(f"{label} @ {deep_at:.0%}, r={float(hold):.0%}")
                print(
                    f"  {mark} {label:<22} deep<={deep_at:>6.0%}  r={float(hold):>4.0%}  "
                    f"Rs {cell.terminal:>14,.0f}  vs control {edge:>+7.2%}  "
                    f"releases {cell.releases}"
                )
                sys.stdout.flush()

    verdict = (
        "**WIRE IT.** Every cell beats its own control."
        if not failures
        else "**THE LEVER STAYS DISCONNECTED.** "
        f"{len(failures)} of {len(rows)} cells failed: " + "; ".join(failures) + "."
    )
    print(f"\n[wc2b] {verdict}")

    body = [
        "# WC-2b — is the deep-only reserve an effect, or fitted to this history?",
        "",
        f"_Run {datetime.now(UTC):%Y-%m-%d %H:%M UTC}. Registered in "
        "[PREREGISTRATION_WEAKNESS_RESERVE.md](PREREGISTRATION_WEAKNESS_RESERVE.md) §8, after "
        "WC-2's grid was seen and before this script was written._",
        "",
        "WC-2 found the deep-only reserve worth **+6.27%** at `r=0.25` and **+12.23%** at `r=0.50` "
        "over fourteen years. One path, eleven deep months, about seven episodes, COVID supplying "
        "four of them. Two attacks: split the period, and move the threshold that defines *deep*.",
        "",
        "Each row is measured against **its own control** — the same period and the same threshold, "
        "deploying everything on arrival. `r` is the fraction of an ordinary month's ₹50,000 held "
        "back; the whole reserve goes in on a deep month.",
        "",
        "| Period | `deep` at | `r` | Terminal | vs its control | Releases |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row_label, row_deep, row_hold, row_terminal, row_edge, row_releases in rows:
        body.append(
            f"| {row_label} | {row_deep:.0%} | {row_hold:.0%} | ₹{row_terminal:,.0f} | "
            f"**{row_edge:+.2%}** | {row_releases} |"
        )
    body += [
        "",
        f"## Verdict\n\n{verdict}",
        "",
        "**The classifier is checked, not assumed.** `market_weakness` hard-codes −12%, so this "
        "test reproduces its classification with the threshold exposed — and the run asserts that "
        "copy equals the live function on **every payday** at the shipped −12% before any row is "
        "computed. A silent drift there would mean measuring a rule nobody runs.",
        "",
        "> **The threshold perturbation is the sharper of the two attacks.** −12% was not chosen "
        "blind: it was set by people who had seen this history. A reserve that pays at −12% and not "
        "at −10% or −15% is a rule fitted to where this particular path's drawdowns happened to "
        "fall, and it would not survive contact with a different market.",
        "",
        "> **One path, either way.** Fourteen years of one market, and no 2008-style event in it. "
        "Passing every cell here makes the effect harder to dismiss. It does not make it proven, "
        "and nothing in this file authorizes anything.",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    from qalpha.live.atomic import write_text

    write_text(REPORT, "\n".join(body) + "\n")
    print(f"[wc2b] → {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
