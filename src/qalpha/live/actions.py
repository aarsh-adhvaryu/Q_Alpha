"""Corporate actions on the books: dividends as dated cash, splits and bonuses on the lots.

**Why the book was losing money it had actually earned.** The baselines are marked on NIFTYBEES'
*adjusted* close, which is a total-return series: their dividends are already reinvested in it. The
twin's holdings are marked on raw closes and were credited no dividend at all, so every rupee the
eight holdings paid out simply vanished from the comparison. That is a bias against the investor, of
roughly a thousand rupees a quarter on this book, and it grows with the book.

**What counts as a document here.** The vendor's dividend and split series, cross-checked against the
vendor's *own* price adjustment: a dividend of ``D`` on ex-date ``T`` must move the panel's
``adj_close / close`` ratio by exactly ``1 - D / close(T-1)``. Two independently computed fields have
to agree to the paise, and one that does not is recorded as unreconciled and **not applied**. That is
weaker than the company's filing and is labelled as what it is -- a vendor record that reconciles --
never as the company's own announcement.

**Entitlement is holding on the ex-date.** Buying on the ex-date does not earn the dividend, so an
action applies before that day's trades. :func:`qalpha.live.tradebook.replay_tradebook` already
orders a day as action -> buys -> sells, which is that rule, so dividends go through the replay
rather than being credited afterwards: the cash falls out of the same arithmetic that produced the
lots, and re-running the replay can never credit one twice.

A dividend is **income**, not capital gains: it credits cash and never touches a lot. Indian slab tax
and the 10% TDS above the annual threshold per company are the user's own tax position, not the
book's capital-gains model, so the book credits the gross amount and says so.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from qalpha.accounting.corporate_actions import CorporateAction, CorporateActionType
from qalpha.live.atomic import write_text

ACTIONS_PATH = Path("data/twin/corporate_actions.json")

#: How far a dividend implied by the panel's own adjustment may sit from the recorded amount before
#: the record is refused. Adjustment factors are stored as floats and the implied figure is a
#: difference of ratios, so a few paise of float noise is expected; a wrong amount or a wrong date is
#: off by rupees, not paise.
TOLERANCE = Decimal("0.05")


@dataclass(frozen=True)
class Recorded:
    """One corporate action, with the arithmetic that was used to check it."""

    action: CorporateAction
    #: What the panel's own price adjustment implies the dividend was. ``None`` for splits and
    #: bonuses (checked by the share count reconciling against the broker) and when the panel has no
    #: window around the ex-date.
    implied: Decimal | None
    #: Why it was or was not accepted -- carried onto every surface that shows the action.
    note: str

    @property
    def reconciled(self) -> bool:
        """Accepted for application. **Unreconciled actions are never applied.**"""
        if self.action.action_type is not CorporateActionType.DIVIDEND:
            return True
        if self.implied is None:
            return False
        return abs(self.implied - self.action.amount_per_share) <= TOLERANCE


@dataclass(frozen=True)
class Record:
    """Everything known about corporate actions on the names this book has ever held."""

    actions: tuple[Recorded, ...]
    source: str
    fetched_at: str

    def for_replay(self) -> list[CorporateAction]:
        """The actions the replay may apply -- reconciled only, oldest first."""
        return [r.action for r in sorted(self.actions, key=_key) if r.reconciled]

    @property
    def unreconciled(self) -> tuple[Recorded, ...]:
        """Named rather than dropped: a dividend that does not check out is a thing to look at."""
        return tuple(r for r in self.actions if not r.reconciled)


def _key(r: Recorded) -> tuple[date, str, str]:
    return (r.action.ex_date, r.action.ticker, str(r.action.action_type))


def implied_dividend(panel: pd.DataFrame, ticker: str, ex_date: date) -> Decimal | None:
    """What the panel's own ``adj_close / close`` says the dividend on ``ex_date`` was.

    yfinance back-adjusts history: every close before an ex-date is scaled by
    ``1 - D / close(T-1)``. So the ratio's step across the ex-date recovers ``D`` from prices alone,
    without consulting the dividend series that is being checked.

    ``None`` when the panel has no session on either side of the ex-date -- unknown, never zero, and
    an action whose amount cannot be checked is not applied.
    """
    rows = panel[panel["ticker"] == ticker].sort_values("date")
    if rows.empty:
        return None
    stamp = pd.Timestamp(ex_date)
    before = rows[rows["date"] < stamp]
    after = rows[rows["date"] >= stamp]
    if before.empty or after.empty:
        return None
    prev_close = Decimal(str(float(before["close"].iloc[-1])))
    ratio_before = float(before["adj_close"].iloc[-1]) / float(before["close"].iloc[-1])
    ratio_after = float(after["adj_close"].iloc[0]) / float(after["close"].iloc[0])
    if ratio_after == 0 or prev_close <= 0:
        return None
    implied = (Decimal("1") - Decimal(str(ratio_before / ratio_after))) * prev_close
    return implied.quantize(Decimal("0.0001"))


def check(action: CorporateAction, panel: pd.DataFrame) -> Recorded:
    """Cross-check one action against the panel and say, in words, what was found."""
    if action.action_type is not CorporateActionType.DIVIDEND:
        return Recorded(
            action=action,
            implied=None,
            note=(
                f"{action.action_type} x{action.ratio} - checked by the share count: after it is "
                "applied the replay must still reproduce the broker's holdings exactly."
            ),
        )
    implied = implied_dividend(panel, action.ticker, action.ex_date)
    if implied is None:
        return Recorded(
            action=action,
            implied=None,
            note=(
                "no session either side of the ex-date in the panel, so the amount could not be "
                "checked - NOT applied."
            ),
        )
    gap = abs(implied - action.amount_per_share)
    if gap <= TOLERANCE:
        return Recorded(
            action=action,
            implied=implied,
            note=(
                f"₹{action.amount_per_share}/share; the panel's own price adjustment implies "
                f"₹{implied} - they agree to ₹{gap}."
            ),
        )
    return Recorded(
        action=action,
        implied=implied,
        note=(
            f"₹{action.amount_per_share}/share recorded but the panel's price adjustment "
            f"implies ₹{implied} - off by ₹{gap}, more than ₹{TOLERANCE}. NOT applied; "
            "the amount or the ex-date is wrong."
        ),
    )


def save(record: Record, path: Path | None = None) -> None:
    # Resolved at CALL time. A default bound at definition time is the module constant as it
    # was on import, so a test that redirects ACTIONS_PATH still wrote to the live file.
    path = ACTIONS_PATH if path is None else path
    write_text(
        path,
        json.dumps(
            {
                "source": record.source,
                "fetched_at": record.fetched_at,
                "actions": [
                    {
                        "ticker": r.action.ticker,
                        "ex_date": r.action.ex_date.isoformat(),
                        "kind": str(r.action.action_type),
                        "ratio": str(r.action.ratio),
                        "amount_per_share": str(r.action.amount_per_share),
                        "implied": None if r.implied is None else str(r.implied),
                        "reconciled": r.reconciled,
                        "note": r.note,
                    }
                    for r in sorted(record.actions, key=_key)
                ],
            },
            indent=2,
        )
        + "\n",
    )


def load(path: Path | None = None) -> Record | None:
    """The recorded actions, or ``None`` when none have been imported. Never a guess."""
    # Resolved at CALL time. A default bound at definition time is the module constant as it
    # was on import, so a test that redirects ACTIONS_PATH still wrote to the live file.
    path = ACTIONS_PATH if path is None else path
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        actions = tuple(
            Recorded(
                action=CorporateAction(
                    ticker=str(a["ticker"]),
                    ex_date=date.fromisoformat(str(a["ex_date"])),
                    action_type=CorporateActionType(str(a["kind"])),
                    ratio=Decimal(str(a.get("ratio", "0"))),
                    amount_per_share=Decimal(str(a.get("amount_per_share", "0"))),
                ),
                implied=(None if a.get("implied") is None else Decimal(str(a["implied"]))),
                note=str(a.get("note", "")),
            )
            for a in raw["actions"]
        )
        return Record(
            actions=actions,
            source=str(raw.get("source", "")),
            fetched_at=str(raw.get("fetched_at", "")),
        )
    except (OSError, ValueError, KeyError):
        print(f"[actions] {path} is unreadable -- treating corporate actions as not imported")
        return None
