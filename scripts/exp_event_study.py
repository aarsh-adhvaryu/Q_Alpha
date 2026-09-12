"""ES-1 — do verified filing events predict anything? Registered before it was written.

    uv run python scripts/exp_event_study.py

**Read `reports/PREREGISTRATION_EVENT_STUDY.md` first.** The question, the statistic, the horizons,
the unit of observation and the decision rule were all fixed there before any return was computed.
This file only executes them.

**What it cannot settle, restated here so nobody reads the output without it.** All 15 corpus names
are in today's basket or holdings — selected because they are here now. Survivorship on the live
universe is worth ~3.8 points a year, more than the effect being looked for, and it biases *toward*
making names look good after bad news because the ones that never recovered are not in the sample.
ES-1 is a first read on method and direction. It is not evidence, and it cannot license ``AI-V2`` to
go on dropping names.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from qalpha.data.ingest import load_parquet
from qalpha.live.console import use_utf8
from qalpha.live.extraction import EVENT_LOG, EXTRACTION_VERSION, corpus_reader
from qalpha.live.verdicts import VETO_TYPES

PANEL = "data/historical/prices_watchlist.parquet"
REPORT = Path("reports/EVENT_STUDY_ES1.md")

#: Fixed in the registration. All three are reported; picking the flattering one afterwards is the
#: failure this study is organised to avoid.
HORIZONS = (5, 20, 60)

#: NSE closes at 15:30 IST = 10:00 UTC. A filing disseminated after that is only actionable on the
#: next trading day. Crediting the strategy with a move it could not have traded is look-ahead.
CLOSE_UTC_HOUR = 10


def _occurred_utc(row: dict[str, object]) -> datetime | None:
    raw = str(row.get("disseminated_at", "") or "")
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def actionable_day(when: datetime) -> date:
    """The first day this information could be traded on. After the close means tomorrow."""
    day = when.date()
    if when.hour >= CLOSE_UTC_HOUR:
        day = day + timedelta(days=1)
    return day


def load_events() -> list[dict[str, object]]:
    """Verified, current-version, current-reader events carrying a dissemination timestamp."""
    out: list[dict[str, object]] = []
    for line in EVENT_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("kind") != "event" or not row.get("verified"):
            continue
        if row.get("extraction_version") != EXTRACTION_VERSION:
            continue
        if row.get("model") != corpus_reader():
            continue
        out.append(row)
    return out


def abnormal_returns(
    events: list[dict[str, object]], prices: pd.DataFrame, benchmark: pd.Series
) -> pd.DataFrame:
    """One row per (name, actionable day) — the unit the registration fixed, not per event."""
    index = prices.index
    seen: dict[tuple[str, date], dict[str, Any]] = {}
    for row in events:
        when = _occurred_utc(row)
        if when is None:
            continue
        ticker = str(row["ticker"])
        col = ticker if ticker in prices.columns else f"{ticker}.NS"
        if col not in prices.columns:
            continue
        t0 = actionable_day(when)
        key = (col, t0)
        # Collapse to one observation. Keep the strongest materiality and whether ANY event on the
        # day was veto-shaped — that is the signal AI-V2 acts on.
        rank = {"high": 3, "medium": 2, "low": 1}
        prior = seen.get(key)
        mat = str(row.get("materiality", "")).lower()
        veto = str(row.get("event_type", "")) in VETO_TYPES
        if prior is None:
            seen[key] = {"materiality": mat, "veto": veto, "n_events": 1}
        else:
            if rank.get(mat, 0) > rank.get(str(prior["materiality"]), 0):
                prior["materiality"] = mat
            prior["veto"] = bool(prior["veto"]) or veto
            prior["n_events"] = int(prior["n_events"]) + 1

    rows: list[dict[str, object]] = []
    for (col, t0), meta in sorted(seen.items()):
        pos = index.searchsorted(pd.Timestamp(t0))
        if pos >= len(index):
            continue  # the event is more recent than the panel; no forward window exists
        rec: dict[str, object] = {
            "ticker": col,
            "t0": index[int(pos)].date(),
            "materiality": meta["materiality"],
            "veto": meta["veto"],
            "n_events": meta["n_events"],
        }
        usable = False
        for h in HORIZONS:
            end = pos + h
            if end >= len(index):
                rec[f"ar{h}"] = np.nan
                continue
            p0, p1 = prices[col].iloc[pos], prices[col].iloc[end]
            b0, b1 = benchmark.iloc[pos], benchmark.iloc[end]
            if not all(np.isfinite([p0, p1, b0, b1])) or p0 <= 0 or b0 <= 0:
                rec[f"ar{h}"] = np.nan
                continue
            rec[f"ar{h}"] = float(np.log(p1 / p0) - np.log(b1 / b0))
            usable = True
        if usable:
            rows.append(rec)
    return pd.DataFrame(rows)


def clustered_t(values: pd.Series, clusters: pd.Series) -> tuple[float, float, int]:
    """Mean, t-statistic with standard errors clustered by name, and the cluster count.

    Pooling 4,776 events as though independent overstates significance by roughly the square root
    of the clustering — the classic way an event study manufactures a result. One filing yields
    several events, one day carries several filings, and VEDL alone accounts for 269 of them.
    """
    v = values.dropna()
    if len(v) < 3:
        return float("nan"), float("nan"), 0
    g = clusters.loc[v.index]
    mean = float(v.mean())
    groups = list(g.unique())
    if len(groups) < 2:
        return mean, float("nan"), len(groups)
    # CRVE: sum of squared within-cluster deviation sums, over n^2.
    total = 0.0
    for name in groups:
        dev = (v[g == name] - mean).sum()
        total += float(dev) ** 2
    n = len(v)
    se = float(np.sqrt(total)) / n if total > 0 else float("nan")
    t = mean / se if se and np.isfinite(se) and se > 0 else float("nan")
    return mean, t, len(groups)


def per_name_test(frame: pd.DataFrame, column: str) -> tuple[float, float, int]:
    """Average within each name first, then test across names. 14 df, and honest about it."""
    by_name = frame.groupby("ticker")[column].mean().dropna()
    if len(by_name) < 3:
        return float("nan"), float("nan"), len(by_name)
    mean = float(by_name.mean())
    se = float(by_name.std(ddof=1) / np.sqrt(len(by_name)))
    t = mean / se if se > 0 else float("nan")
    return mean, t, len(by_name)


def _block(frame: pd.DataFrame, label: str) -> list[str]:
    lines = [f"### {label}", ""]
    if frame.empty:
        return [*lines, "_No observations._", ""]
    lines += [
        f"**{len(frame)} name-days · {frame['ticker'].nunique()} names · "
        f"{int(frame['n_events'].sum())} underlying events**",
        "",
        "| Horizon | Mean AR | t (clustered by name) | names | t (per-name, 14 df) |",
        "|---|---:|---:|---:|---:|",
    ]
    for h in HORIZONS:
        col = f"ar{h}"
        mean, t, groups = clustered_t(frame[col], frame["ticker"])
        pn_mean, pn_t, _pn_n = per_name_test(frame, col)
        lines.append(
            f"| {h}d | {mean * 100:+.2f}% | {t:+.2f} | {groups} | {pn_t:+.2f} (mean {pn_mean * 100:+.2f}%) |"
        )
    return [*lines, ""]


def main() -> int:
    use_utf8()
    events = load_events()
    print(f"[es1] {len(events)} verified {EXTRACTION_VERSION} events by {corpus_reader()}")
    panel = load_parquet(PANEL)
    prices = panel.adj_close
    corpus_cols = sorted(
        {
            c
            for c in prices.columns
            if c in {f"{e['ticker']}.NS" for e in events} | {str(e["ticker"]) for e in events}
        }
    )
    # THE BENCHMARK IS THE EQUAL-WEIGHT CORPUS, not the index — see the registration. Daily
    # rebalanced: the mean of each day's simple returns, compounded.
    rets = prices[corpus_cols].pct_change()
    benchmark = (1.0 + rets.mean(axis=1).fillna(0.0)).cumprod()
    print(f"[es1] benchmark: equal-weight over {len(corpus_cols)} corpus names, daily rebalanced")

    frame = abnormal_returns(events, prices, benchmark)
    if frame.empty:
        print("[es1] no usable observations — nothing written.", file=sys.stderr)
        return 2
    print(f"[es1] {len(frame)} name-day observations from {frame['ticker'].nunique()} names")

    veto_high = frame[(frame["veto"]) & (frame["materiality"] == "high")]
    body = [
        "# ES-1 — do verified filing events predict anything?",
        "",
        f"_Run {datetime.now(UTC):%Y-%m-%d %H:%M UTC}. Registered in "
        "[PREREGISTRATION_EVENT_STUDY.md](PREREGISTRATION_EVENT_STUDY.md) before any return was "
        "computed._",
        "",
        "> **This is not evidence.** All 15 corpus names are in today's basket or holdings, "
        "selected because they are here now. Survivorship on the live universe is worth ~3.8 "
        "points a year — more than the effect being looked for — and it biases *toward* making "
        "names look good after bad news, because the ones that never recovered are not in the "
        "sample. A clean answer needs a point-in-time universe, which is open-work item 1 and "
        "still an empty list.",
        "",
        "`AR` is log return of the name minus log return of the equal-weight corpus over the same "
        "days. `t0` is the first trading day the filing was actionable: after a 15:30 IST "
        "dissemination, that is the next day.",
        "",
    ]
    body += _block(veto_high, "PRIMARY — high materiality, veto-shaped (what AI-V2 acts on)")
    body += [
        "**Read the two t columns together.** The pooled column treats every name-day as "
        "independent; the per-name column averages within a name first and then tests across the "
        "names. Where they disagree, the per-name column is the one to believe — the gap between "
        "them IS the clustering, and on the 60-day horizon it is the whole of the effect.",
        "",
    ]
    body += _block(frame[frame["materiality"] == "high"], "All high materiality")
    body += _block(frame[frame["materiality"] == "medium"], "Medium materiality")
    body += _block(frame[frame["materiality"] == "low"], "Low materiality")
    body += _block(frame, "Every event day (the unconditional base rate)")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    from qalpha.live.atomic import write_text

    write_text(REPORT, "\n".join(body) + "\n")
    print(f"[es1] → {REPORT}")
    print()
    for line in _block(veto_high, "PRIMARY"):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
