"""Opportunity-scan decision logic — the pure, fully-testable brain behind the daily alerts (PR-1).

The paper cron computes everything analytical already (market weakness, the GO scorecard, freshness),
but only *renders* it — nothing decides "is this worth interrupting the user for?". That judgement is
this module: given today's :class:`ScanFacts` and the persisted :class:`AlertState`, :func:`evaluate`
returns the alerts to send **and** the next state. It is deliberately free of I/O, Telegram, prices,
and Streamlit — the composition script (:mod:`scripts.scan_alerts`) gathers the facts and does the
sending; every dedupe/hysteresis rule lives here so it can be unit-tested without a network.

The contract (the alert taxonomy) is documented on :func:`evaluate`. Two ideas drive the design:

* **Edge-triggered, not level-triggered** — an alert fires on a *change* (weakness rises, GO flips,
  a rebalance comes due), never on every scan, so a persistent condition is announced once.
* **Hysteresis on de-escalation** — weakness *easing* must hold for several consecutive scans before
  it's announced, so a benchmark oscillating around a −5%/−12% threshold doesn't ping-pong the user.

State persists as JSON at ``data/paper/alert_state.json`` (a tracked dir, no secrets), round-tripping
exactly like :mod:`qalpha.live.runlog`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ALERT_STATE_PATH = Path("data/paper/alert_state.json")

# Weakness severity ordering (from qalpha.live.deploy.market_weakness).
_LEVELS = {"normal": 0, "elevated": 1, "deep": 2}
# A lower weakness level must hold this many consecutive scans before "easing" is announced — the
# hysteresis that stops a benchmark hovering near a −5%/−12% threshold from ping-ponging alerts.
_EASE_CONFIRM_SCANS = 3


def _rank(level: str) -> int:
    return _LEVELS.get(level, 0)


def _iso_week(day: date) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


@dataclass(frozen=True)
class AlertState:
    """What we've already told the user — the memory that makes alerts edge-triggered, not spammy.

    Round-trips to/from JSON like :class:`qalpha.live.runlog.RunLogEntry`. Persisted between cron
    runs at ``data/paper/alert_state.json`` (tracked, no secrets).
    """

    weakness_level: str = "normal"  # the last *notified/confirmed* weakness level
    weakness_pending: str = ""  # a lower level currently being confirmed for an easing alert
    weakness_pending_count: int = 0  # consecutive scans the pending lower level has held
    go_verdict: str = (
        ""  # last GO verdict seen ("" = never recorded → first obs is silent baseline)
    )
    was_stale: bool = False  # freshness-stale on the previous scan (for the False→True edge)
    last_rebalance_alert: str = ""  # as_of of the rebalance we last alerted (once-per-event dedupe)
    last_digest_week: str = ""  # ISO week ("YYYY-Www") the Monday digest last went out

    def to_dict(self) -> dict[str, object]:
        return {
            "weakness_level": self.weakness_level,
            "weakness_pending": self.weakness_pending,
            "weakness_pending_count": self.weakness_pending_count,
            "go_verdict": self.go_verdict,
            "was_stale": self.was_stale,
            "last_rebalance_alert": self.last_rebalance_alert,
            "last_digest_week": self.last_digest_week,
        }

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> AlertState:
        return cls(
            weakness_level=str(d.get("weakness_level", "normal")),
            weakness_pending=str(d.get("weakness_pending", "")),
            weakness_pending_count=int(str(d.get("weakness_pending_count", 0) or 0)),
            go_verdict=str(d.get("go_verdict", "")),
            was_stale=bool(d.get("was_stale", False)),
            last_rebalance_alert=str(d.get("last_rebalance_alert", "")),
            last_digest_week=str(d.get("last_digest_week", "")),
        )


@dataclass(frozen=True)
class ScanFacts:
    """Today's already-computed state — everything :func:`evaluate` needs, all gathered by the script.

    Text bodies that require prices/holdings (the tranche + out-of-favour lines, the rebalance order
    summary, the digest) are *pre-rendered* by the composition script so this module stays pure and
    the wrapping/framing/dedupe is all that lives here.
    """

    as_of: date
    weakness_level: str  # "normal" | "elevated" | "deep"
    weakness_note: str  # the market_weakness drawdown-from-1y-high description
    deploy_lines: str  # pre-rendered tranche policy + top out-of-favour names
    go_verdict: str  # GO / NO-GO / READY / NOT YET (from build_scorecard)
    rebalance_applied: bool  # the cron auto-applied scheduled orders this run
    rebalance_pending: bool  # a plan has orders awaiting human approval
    rebalance_date: str  # as_of identifying the rebalance event (for once-per-event dedupe)
    rebalance_summary: str  # pre-rendered order lines
    freshness_stale: bool  # paper_freshness flagged the book stale
    freshness_note: str  # the freshness detail line
    digest_body: str  # pre-rendered Monday-digest heartbeat body
    pipeline_failed: str | None = None  # non-None ⇒ a GH Actions job failed (message = the detail)


@dataclass(frozen=True)
class Alert:
    """One message to send: ``kind`` (for the job log) + the ready-to-send HTML ``text``."""

    kind: str
    text: str


def _weakness_alert(facts: ScanFacts, *, rising: bool) -> Alert:
    if rising:
        head = f"⚠️ <b>Market weakness rose to {facts.weakness_level.upper()}</b>"
    else:
        head = f"🟢 <b>Market weakness eased to {facts.weakness_level.upper()}</b>"
    body = f"{head}\n{facts.weakness_note}"
    if facts.deploy_lines:
        body += f"\n\n{facts.deploy_lines}"
    return Alert("weakness-escalation" if rising else "weakness-easing", body)


def _go_alert(facts: ScanFacts, prev: str) -> Alert:
    flag = "🔴 " if facts.go_verdict == "NO-GO" else "🎯 "
    text = (
        f"{flag}<b>GO verdict changed: {prev} → {facts.go_verdict}</b>\n"
        f"The forward paper-run scorecard flipped as of {facts.as_of.isoformat()}."
    )
    return Alert("go-flip", text)


def _rebalance_alert(facts: ScanFacts) -> Alert:
    if facts.rebalance_applied:
        head = "🔁 <b>Scheduled rebalance auto-applied</b> (notional paper book)"
    else:
        head = "🔁 <b>Rebalance due — orders await your approval</b>"
    body = f"{head}\nEvent date {facts.rebalance_date}."
    if facts.rebalance_summary:
        body += f"\n\n{facts.rebalance_summary}"
    return Alert("rebalance", body)


def _guard_alert(facts: ScanFacts) -> Alert:
    return Alert(
        "guard-failure",
        f"🚧 <b>Data-freshness guard tripped</b>\n{facts.freshness_note}\n"
        "The daily pipeline may have missed a run — check the Actions tab.",
    )


def _pipeline_alert(message: str) -> Alert:
    return Alert("pipeline-failed", f"🚨 <b>Paper pipeline failed</b>\n{message}")


def _digest_alert(facts: ScanFacts) -> Alert:
    return Alert("weekly-digest", f"🗓 <b>Q-Alpha weekly digest</b>\n\n{facts.digest_body}")


def evaluate(
    facts: ScanFacts, state: AlertState, today: date, *, force_digest: bool = False
) -> tuple[list[Alert], AlertState]:
    """Decide which alerts fire today and return them with the updated :class:`AlertState`.

    The alert taxonomy (the contract, all dedupe rules enforced here):

    * **weakness-escalation** — the weakness level rose vs the last notified level → fires immediately
      (even if the intermediate level was never announced: a normal→deep jump fires as *deep*).
    * **weakness-easing** — the level fell → announced only after the lower level holds
      :data:`_EASE_CONFIRM_SCANS` consecutive scans (hysteresis vs −5%/−12% oscillation noise).
    * **rebalance** — the cron auto-applied orders OR a plan has orders pending → once per event date.
    * **go-flip** — ``build_scorecard`` verdict changed → any change (the first-ever observation is a
      silent baseline so a fresh deployment doesn't ping); NO-GO is flagged 🔴.
    * **guard-failure** — freshness stale → once per stale streak (the ``False→True`` edge only).
    * **pipeline-failed** — a GH Actions job failed → every failure (no dedupe; runs in ``if:
      failure()``).
    * **weekly-digest** — Monday, once per ISO week: the liveness heartbeat. ``force_digest`` emits it
      on demand (for verification) without consuming the week's slot.

    Pure: no I/O, no side effects — same inputs, same ``(alerts, state)``.
    """
    alerts: list[Alert] = []

    # --- weakness escalation / easing (with de-escalation hysteresis) ---
    weakness_level = state.weakness_level
    weakness_pending = state.weakness_pending
    weakness_pending_count = state.weakness_pending_count
    cur, prev = _rank(facts.weakness_level), _rank(state.weakness_level)
    if cur > prev:
        alerts.append(_weakness_alert(facts, rising=True))
        weakness_level = facts.weakness_level
        weakness_pending, weakness_pending_count = "", 0
    elif cur < prev:
        if weakness_pending == facts.weakness_level:
            weakness_pending_count += 1
        else:
            weakness_pending, weakness_pending_count = facts.weakness_level, 1
        if weakness_pending_count >= _EASE_CONFIRM_SCANS:
            alerts.append(_weakness_alert(facts, rising=False))
            weakness_level = facts.weakness_level
            weakness_pending, weakness_pending_count = "", 0
    else:  # back at the notified level → any pending easing is void
        weakness_pending, weakness_pending_count = "", 0

    # --- GO verdict flip (first observation is a silent baseline) ---
    go_verdict = state.go_verdict
    if facts.go_verdict != state.go_verdict:
        if state.go_verdict:
            alerts.append(_go_alert(facts, state.go_verdict))
        go_verdict = facts.go_verdict

    # --- rebalance due / applied (once per event date) ---
    last_rebalance_alert = state.last_rebalance_alert
    if (
        (facts.rebalance_applied or facts.rebalance_pending)
        and facts.rebalance_date
        and facts.rebalance_date != state.last_rebalance_alert
    ):
        alerts.append(_rebalance_alert(facts))
        last_rebalance_alert = facts.rebalance_date

    # --- guard failure (once per stale streak, on the False→True edge) ---
    if facts.freshness_stale and not state.was_stale:
        alerts.append(_guard_alert(facts))
    was_stale = facts.freshness_stale

    # --- pipeline failure (every failure) ---
    if facts.pipeline_failed:
        alerts.append(_pipeline_alert(facts.pipeline_failed))

    # --- weekly digest (Monday, once per ISO week; or forced for verification) ---
    last_digest_week = state.last_digest_week
    if force_digest:
        alerts.append(_digest_alert(facts))
    elif today.weekday() == 0 and _iso_week(today) != state.last_digest_week:
        alerts.append(_digest_alert(facts))
        last_digest_week = _iso_week(today)

    new_state = AlertState(
        weakness_level=weakness_level,
        weakness_pending=weakness_pending,
        weakness_pending_count=weakness_pending_count,
        go_verdict=go_verdict,
        was_stale=was_stale,
        last_rebalance_alert=last_rebalance_alert,
        last_digest_week=last_digest_week,
    )
    return alerts, new_state


def load_state(path: Path = ALERT_STATE_PATH) -> AlertState:
    """Load the persisted alert state; a missing/empty file yields the default (first-run) state."""
    if not path.exists():
        return AlertState()
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return AlertState()
    return AlertState.from_dict(json.loads(text))


def save_state(state: AlertState, path: Path = ALERT_STATE_PATH) -> None:
    """Persist the alert state as pretty JSON (tracked, committed by the cron; no secrets)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2) + "\n", encoding="utf-8")


__all__ = [
    "ALERT_STATE_PATH",
    "Alert",
    "AlertState",
    "ScanFacts",
    "evaluate",
    "load_state",
    "save_state",
]
