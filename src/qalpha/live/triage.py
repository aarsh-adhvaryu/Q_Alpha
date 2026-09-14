"""Which filings a model need not read — proposed here, measured before it is ever used.

About a third of what the exchange publishes is administration: the dates of an analyst call, a copy
of a newspaper advertisement, a trading-window closure, a depositories certificate, an ESOP
allotment. Reading them costs the same as reading a results filing and almost never produces an
event that should worry a shareholder.

**"Routine, not read" is a status of its own.** It is never "read", never "verified", and never
counts toward a name being fully covered. A document the triage skips is a document nobody looked
at, and every surface that counts coverage must say so.

**Nothing here is switched on.** The rules below are a proposal. Phase 2 of the plan measures them
against the reference set: if any high-materiality event, or more than the pre-registered number of
medium ones, sits inside a document these rules call routine, the rule that caught it is removed
before the evening run ever uses triage. Once in use, a weekly audit reads a random share of
skipped documents and escalates any subject pattern that turns out to carry material events.

Two guards are structural rather than statistical:

* **Ambiguous subjects are always read.** "Updates", "General Updates", "Press Release" and
  "Investor Presentation" carry everything from a board resignation to a festival greeting.
* **A routine subject over its length ceiling is read.** An analyst-meet *intimation* is a
  paragraph; a call *transcript* filed under the same subject is thirty pages of management
  commentary. Length is what tells them apart.
"""

from __future__ import annotations

from dataclasses import dataclass

READ = "read"
ROUTINE = "routine, not read"

#: Triage rule set version. A changed rule is a changed corpus: rows record which rules skipped them.
TRIAGE_VERSION = "TRIAGE-1"


@dataclass(frozen=True)
class Rule:
    """A subject prefix that is routine when the document is no longer than ``max_chars``."""

    name: str
    subject_prefix: str
    max_chars: int


#: The proposal. Each ceiling is set where the administrative form of the filing ends and the
#: substantive form begins; the measurement decides whether each rule survives.
RULES: tuple[Rule, ...] = (
    Rule("trading-window", "Trading Window", 6_000),
    Rule("newspaper-copy", "Copy of Newspaper Publication", 8_000),
    Rule("depositories-certificate", "Certificate under SEBI (Depositories", 6_000),
    Rule("analyst-meet-intimation", "Analysts/Institutional Investor Meet", 4_000),
    Rule("esop-allotment", "ESOP/ESOS/ESPS", 6_000),
    Rule("shareholders-meeting-notice", "Shareholders meeting", 5_000),
)

#: Always read, whatever their length: their subject says nothing about their content.
ALWAYS_READ = ("Updates", "General Updates", "Press Release", "Investor Presentation")


@dataclass(frozen=True)
class Verdict:
    status: str  # READ or ROUTINE
    rule: str  # the rule that decided, or why it was read
    version: str = TRIAGE_VERSION

    @property
    def routine(self) -> bool:
        return self.status == ROUTINE


def classify(subject: str, chars: int, *, rules: tuple[Rule, ...] = RULES) -> Verdict:
    """Read, or routine-not-read — with the rule that decided, so the audit can trace it."""
    clean = (subject or "").strip()
    if not clean:
        return Verdict(READ, "no subject — unknown is read")
    if any(clean == name for name in ALWAYS_READ):
        return Verdict(READ, "ambiguous subject — always read")
    for rule in rules:
        if clean.startswith(rule.subject_prefix):
            if chars <= rule.max_chars:
                return Verdict(ROUTINE, rule.name)
            return Verdict(
                READ, f"{rule.name}: {chars:,} chars is over its {rule.max_chars:,} ceiling"
            )
    return Verdict(READ, "no routine rule matches")


def without(rule_names: set[str], rules: tuple[Rule, ...] = RULES) -> tuple[Rule, ...]:
    """The rule set with named rules removed — what a failed measurement or audit produces."""
    return tuple(r for r in rules if r.name not in rule_names)
