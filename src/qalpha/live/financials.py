"""Point-in-time company financials, from the XBRL the company filed with the exchange.

**What makes this point-in-time.** Every quarter carries the timestamp at which the exchange
disseminated it. A packet built for day D may only contain filings disseminated at or before D, so
the investor is never shown a number the market did not have. Restatements do not travel backwards
either: a later filing is a later row, and the row that was current on D stays what it was.

**Why not a vendor's table.** yfinance and its kind serve *today's* view of history — restated,
undated, and with no record of when anyone could have known it. A backtest fed from one is reading
tomorrow's newspaper. The source here is the company's own Ind-AS XBRL, fetched from the exchange's
archive, stored with its bytes' SHA-256 and its URL.

**What is checked before the investor sees a number.** The Ind-AS statement has internal identities
that must hold, and they are computed from separately tagged facts:

* ``Income == RevenueFromOperations + OtherIncome``
* ``ProfitBeforeExceptionalItemsAndTax == Income - Expenses``
* ``ProfitLossForPeriod == ProfitBeforeTax - TaxExpense`` (+ discontinued, + associates)

A filing whose own numbers do not add up is recorded as **unreconciled and not fed** — the fact that
it was filed is not the same as the fact that it parses. Rupee figures are exact; the tolerance is
for the paise-level rounding a filer's own spreadsheet introduces.

**Consolidated over standalone.** A holding company's standalone accounts describe a shell. Where
both are filed, consolidated is the one that describes the business, and which one a row came from
is recorded rather than assumed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

FACTS_PATH = Path("data/facts/financials.jsonl")
XBRL_DIR = Path("data/facts/xbrl")

#: The exchange's own index of filed quarterly results for one symbol — **up to the December 2024
#: quarter only.** From 2025 SEBI's "Integrated Filing" replaced the old results filing, and results
#: moved to :data:`INTEGRATED_URL`. Reading only this feed is why every name's latest quarter was
#: Dec-2024: the data was not missing, it had moved.
INDEX_URL = (
    "https://www.nseindia.com/api/corporates-financial-results"
    "?index=equities&symbol={symbol}&period=Quarterly"
)

#: Quarterly results from 2025 onward, under SEBI's Integrated Filing. Same Ind-AS tag names, filed
#: under an ``in-capmkt:`` prefix instead of ``in-bse-fin:``.
INTEGRATED_URL = (
    "https://www.nseindia.com/api/integrated-filing-results"
    "?index=equities&symbol={symbol}&type=Integrated%20Filing-%20Financials"
)

#: The fixed tag set. Fixed on purpose: a set that grows per company is a set that cannot be
#: compared across companies, and "the model can have whatever it finds" is how a packet stops being
#: reproducible. Names on the left are ours and stable; on the right, the taxonomy names that carry
#: them, **first match wins**. The second name, where there is one, is the banking taxonomy's: banks
#: report "interest earned" where a company reports "revenue from operations", and reading only the
#: company names is why every bank read "revenue unknown".
TAGS: dict[str, tuple[str, ...]] = {
    "revenue": ("RevenueFromOperations", "InterestEarned"),
    "other_income": ("OtherIncome",),
    "total_income": ("Income",),
    "employee_cost": ("EmployeeBenefitExpense", "EmployeesCost"),
    "finance_costs": ("FinanceCosts",),
    "depreciation": ("DepreciationDepletionAndAmortisationExpense",),
    "other_expenses": ("OtherExpenses", "OtherOperatingExpenses"),
    "total_expenses": ("Expenses", "ExpenditureExcludingProvisionsAndContingencies"),
    "profit_before_exceptional_and_tax": ("ProfitBeforeExceptionalItemsAndTax",),
    "exceptional_items": ("ExceptionalItemsBeforeTax", "ExceptionalItems"),
    "profit_before_tax": ("ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax"),
    "tax": ("TaxExpense",),
    "profit_after_tax": ("ProfitLossForPeriod", "ProfitLossForThePeriod"),
    "profit_to_owners": (
        "ProfitOrLossAttributableToOwnersOfParent",
        "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",
    ),
    "eps_basic": (
        "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        "BasicEarningsPerShareAfterExtraordinaryItems",
    ),
    "equity_capital": ("PaidUpValueOfEquityShareCapital",),
    "face_value": ("FaceValueOfEquityShareCapital",),
    # ---- banks only: what a bank's quarter is actually about ------------------------------------
    "interest_earned": ("InterestEarned",),
    "interest_expended": ("InterestExpended",),
    "operating_profit_before_provisions": ("OperatingProfitBeforeProvisionAndContingencies",),
    "provisions": ("ProvisionsOtherThanTaxAndContingencies",),
    "gross_npa_pct": ("PercentageOfGrossNpa",),
    "net_npa_pct": ("PercentageOfNpa",),
    "return_on_assets_pct": ("ReturnOnAssets",),
}

#: Ratios a bank's consolidated filing carries as a literal ``0`` because the regulator requires
#: them only in the standalone accounts. HDFC Bank's consolidated filing reports a gross NPA of 0.00%;
#: the bank does not have no bad loans. A zero here is a blank, and a blank is unknown.
ZERO_MEANS_NOT_REPORTED = frozenset({"gross_npa_pct", "net_npa_pct", "return_on_assets_pct"})

#: The longest period a "quarter" may span. A Q4 filing can carry the full year beside the quarter,
#: and a year stored as a quarter would report four quarters of revenue as one — and a year-on-year
#: "growth" of 300%.
MAX_QUARTER_DAYS = 100

#: Context metadata read alongside the numbers.
META_TAGS: dict[str, str] = {
    "period_start": "DateOfStartOfReportingPeriod",
    "period_end": "DateOfEndOfReportingPeriod",
    "basis": "NatureOfReportStandaloneConsolidated",
    "audited": "WhetherResultsAreAuditedOrUnaudited",
    "quarter": "ReportingQuarter",
    "board_meeting": "DateOfBoardMeetingWhenFinancialResultsWereApproved",
}

#: A filer's own rounding. The identities are exact arithmetic on figures reported in rupees; this
#: allows for the last digit, not for a number that is wrong.
TOLERANCE = Decimal("1000")


@dataclass(frozen=True)
class Quarter:
    """One quarter as one company filed it, with when the exchange published it."""

    ticker: str
    period_start: date
    period_end: date
    #: When the market could first have known this. **The packet's cut-off compares against it.**
    filed_at: datetime
    basis: str  # "Consolidated" or "Standalone"
    audited: str
    facts: dict[str, Decimal | None]
    source_url: str
    sha256: str
    #: Empty when every identity held. Each entry names an identity and by how much it failed.
    breaks: tuple[str, ...] = ()

    @property
    def reconciled(self) -> bool:
        """**Unreconciled quarters never reach a packet.** Filed is not the same as parsed."""
        return not self.breaks

    def get(self, name: str) -> Decimal | None:
        return self.facts.get(name)

    @property
    def is_bank(self) -> bool:
        """Filed under the banking taxonomy — interest income, provisions, NPAs."""
        return self.facts.get("interest_earned") is not None


def _decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.strip())
    except (InvalidOperation, AttributeError):
        return None


def _headline_context(xml: str) -> str | None:
    """The undimensioned context for the quarter being reported, preferring consolidated.

    A filing carries one context per basis (standalone and consolidated) plus dozens of dimensioned
    ones for segments and expense breakdowns. Only the undimensioned ones are the headline
    statement; taking a dimensioned one would report a single segment as the whole company.
    """
    plain: list[str] = []
    for match in re.finditer(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', xml, re.S):
        cid, inner = match.group(1), match.group(2)
        if "dimension=" in inner or "<xbrli:instant>" in inner:
            continue
        plain.append(cid)
    if not plain:
        return None
    for cid in plain:
        basis = _fact(xml, "NatureOfReportStandaloneConsolidated", cid)
        if basis and basis.strip().lower().startswith("consolidated"):
            return cid
    return plain[0]


def _fact(xml: str, tag: str, context: str) -> str | None:
    """One fact, under whichever taxonomy prefix the filing uses.

    The old results filing tags facts ``in-bse-fin:``; SEBI's Integrated Filing tags the same facts
    ``in-capmkt:``. Matching one prefix read the new filings as having no headline statement at all.
    """
    pattern = rf'<[A-Za-z][\w\-]*:{tag} contextRef="{re.escape(context)}"[^>]*>([^<]*)<'
    match = re.search(pattern, xml)
    return match.group(1) if match else None


def _identities(facts: dict[str, Decimal | None]) -> tuple[str, ...]:
    """Every internal identity that failed, named with the gap. Empty means the filing adds up."""
    breaks: list[str] = []

    def check(label: str, left: str, parts: list[str]) -> None:
        target = facts.get(left)
        values = [facts.get(p) for p in parts]
        if target is None or any(v is None for v in values):
            return  # a tag the filer did not use is unknown, not a failed identity
        total = sum((v for v in values if v is not None), Decimal("0"))
        if abs(total - target) > TOLERANCE:
            breaks.append(f"{label}: filed {target}, its own parts sum to {total}")

    check("total income", "total_income", ["revenue", "other_income"])
    pbe = facts.get("profit_before_exceptional_and_tax")
    income, expenses = facts.get("total_income"), facts.get("total_expenses")
    if (
        pbe is not None
        and income is not None
        and expenses is not None
        and abs((income - expenses) - pbe) > TOLERANCE
    ):
        breaks.append(
            f"profit before exceptional items: filed {pbe}, income less expenses is "
            f"{income - expenses}"
        )
    # A bank's statement adds up differently: income less expenditure (excluding provisions) is
    # operating profit, and operating profit less provisions and exceptional items is PBT.
    operating = facts.get("operating_profit_before_provisions")
    provisions = facts.get("provisions")
    if operating is not None and income is not None and expenses is not None:
        if abs((income - expenses) - operating) > TOLERANCE:
            breaks.append(
                f"operating profit before provisions: filed {operating}, income less expenditure "
                f"is {income - expenses}"
            )
        pbt_bank = facts.get("profit_before_tax")
        if pbt_bank is not None and provisions is not None:
            implied = operating - provisions - (facts.get("exceptional_items") or Decimal("0"))
            if abs(implied - pbt_bank) > TOLERANCE:
                breaks.append(
                    f"profit before tax: filed {pbt_bank}, operating profit less provisions is "
                    f"{implied}"
                )
    pbt, tax, pat = facts.get("profit_before_tax"), facts.get("tax"), facts.get("profit_after_tax")
    # Discontinued operations and equity-method associates sit between PBT and PAT, so this is a
    # bound rather than an equality for a group with either. A gap larger than half of PBT is not a
    # group structure; it is a parse that went wrong.
    if (
        pbt is not None
        and tax is not None
        and pat is not None
        and abs((pbt - tax) - pat) > max(TOLERANCE, abs(pbt) / 2)
    ):
        breaks.append(f"profit after tax: filed {pat}, PBT less tax is {pbt - tax}")
    return tuple(breaks)


def parse(xml: str, *, ticker: str, filed_at: datetime, url: str, sha256: str) -> Quarter | None:
    """One filing's XBRL into one :class:`Quarter`, or ``None`` when it is not a readable one."""
    context = _headline_context(xml)
    if context is None:
        return None
    meta = {name: _fact(xml, tag, context) for name, tag in META_TAGS.items()}
    if not meta.get("period_start") or not meta.get("period_end"):
        return None
    facts: dict[str, Decimal | None] = {}
    for name, tags in TAGS.items():
        value: Decimal | None = None
        for tag in tags:
            raw = _fact(xml, tag, context)
            if raw is not None:
                value = _decimal(raw)
                break
        if name in ZERO_MEANS_NOT_REPORTED and value == 0:
            value = None
        facts[name] = value
    try:
        start = date.fromisoformat(str(meta["period_start"])[:10])
        end = date.fromisoformat(str(meta["period_end"])[:10])
    except ValueError:
        return None
    if (end - start).days > MAX_QUARTER_DAYS:
        return None  # a year (or a half) is not a quarter, whatever the filing calls its context
    return Quarter(
        ticker=ticker,
        period_start=start,
        period_end=end,
        filed_at=filed_at,
        basis=str(meta.get("basis") or "unknown"),
        audited=str(meta.get("audited") or "unknown"),
        facts=facts,
        source_url=url,
        sha256=sha256,
        breaks=_identities(facts),
    )


# ---- the store ------------------------------------------------------------------------------------


def _row(q: Quarter) -> dict[str, Any]:
    return {
        "ticker": q.ticker,
        "period_start": q.period_start.isoformat(),
        "period_end": q.period_end.isoformat(),
        "filed_at": q.filed_at.isoformat(),
        "basis": q.basis,
        "audited": q.audited,
        "facts": {k: (None if v is None else str(v)) for k, v in q.facts.items()},
        "source_url": q.source_url,
        "sha256": q.sha256,
        "breaks": list(q.breaks),
    }


def save(quarters: list[Quarter], path: Path | None = None) -> int:
    """Write every quarter, newest last. Returns how many rows are on file.

    Writes exactly the quarters it is given, sorted, so the same set always produces the same bytes.
    It does not decide what to keep: ``scripts/financials.py`` merges tonight's fetch INTO what is
    stored, because the exchange's index is not reliable about what it lists and a filing it omits
    one evening must not disappear from the record.
    """
    # Resolved at CALL time. A default bound at definition time is the module constant as it
    # was on import, so a test that redirects FACTS_PATH still wrote to the live file.
    path = FACTS_PATH if path is None else path
    from qalpha.live.atomic import write_text

    ordered = sorted(quarters, key=lambda q: (q.ticker, q.period_end, q.filed_at))
    write_text(path, "".join(json.dumps(_row(q)) + "\n" for q in ordered))
    return len(ordered)


def load(path: Path | None = None) -> list[Quarter]:
    """Every stored quarter. A missing file is no financials, never an empty company."""
    # Resolved at CALL time. A default bound at definition time is the module constant as it
    # was on import, so a test that redirects FACTS_PATH still wrote to the live file.
    path = FACTS_PATH if path is None else path
    if not path.exists():
        return []
    out: list[Quarter] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            out.append(
                Quarter(
                    ticker=str(raw["ticker"]),
                    period_start=date.fromisoformat(raw["period_start"]),
                    period_end=date.fromisoformat(raw["period_end"]),
                    filed_at=datetime.fromisoformat(raw["filed_at"]),
                    basis=str(raw.get("basis", "unknown")),
                    audited=str(raw.get("audited", "unknown")),
                    facts={
                        k: (None if v is None else Decimal(str(v)))
                        for k, v in (raw.get("facts") or {}).items()
                    },
                    source_url=str(raw.get("source_url", "")),
                    sha256=str(raw.get("sha256", "")),
                    breaks=tuple(raw.get("breaks") or ()),
                )
            )
        except (ValueError, KeyError, TypeError):
            continue
    return out


def known_on(quarters: list[Quarter], ticker: str, when: date, *, limit: int = 4) -> list[Quarter]:
    """The last ``limit`` reconciled quarters for ``ticker`` that were **public on** ``when``.

    The whole point of the store. A filing disseminated on the evening of the review is included
    (the market had it); one disseminated the next morning is not, however much it would have
    helped. Newest first.
    """
    name = ticker.removesuffix(".NS")
    rows = [
        q
        for q in quarters
        if q.ticker.removesuffix(".NS") == name and q.reconciled and q.filed_at.date() <= when
    ]
    # One row per period: the latest filing known on that date wins, so a restatement supersedes
    # the original only from the day it was actually filed.
    latest: dict[date, Quarter] = {}
    for q in sorted(rows, key=lambda q: q.filed_at):
        latest[q.period_end] = q
    return sorted(latest.values(), key=lambda q: q.period_end, reverse=True)[:limit]


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return round(float(numerator / denominator) * 100, 1)


def summarise(quarters: list[Quarter], *, as_of: date | None = None) -> dict[str, Any] | None:
    """What code computes from the filings, so the model is never asked to do arithmetic.

    Growth is quarter against the **same quarter a year earlier**, which is the only comparison that
    is not dominated by seasonality. It is reported only when that quarter is actually on file —
    a year-on-year figure computed against the nearest available quarter is a different statistic
    wearing the same name.
    """
    if not quarters:
        return None
    latest = quarters[0]
    # How old this is, said out loud. The exchange's results archive can run a long way behind the
    # price panel, and a quarter presented without its age reads as current when it is not. A
    # statement about a company two years ago is evidence about a company two years ago.
    stale_days = None if as_of is None else (as_of - latest.filed_at.date()).days
    year_ago = next(
        (
            q
            for q in quarters
            if 330 <= (latest.period_end - q.period_end).days <= 400  # the same quarter, last year
        ),
        None,
    )

    def growth(field: str) -> float | None:
        if year_ago is None:
            return None
        now, before = latest.get(field), year_ago.get(field)
        if now is None or before is None or before <= 0:
            return None
        return round(float(now / before - 1) * 100, 1)

    def text(field: str) -> str | None:
        value = latest.get(field)
        return None if value is None else str(value)  # absent is absent, never the string "None"

    out: dict[str, Any] = {
        "quarter_ending": latest.period_end.isoformat(),
        "filed_at": latest.filed_at.isoformat(),
        "basis": latest.basis,
        "audited": latest.audited,
        "revenue": text("revenue"),
        "profit_after_tax": text("profit_after_tax"),
        "eps_basic": text("eps_basic"),
        "net_margin_pct": _ratio(latest.get("profit_after_tax"), latest.get("revenue")),
        "revenue_growth_yoy_pct": growth("revenue"),
        "profit_growth_yoy_pct": growth("profit_after_tax"),
        "year_ago_quarter": None if year_ago is None else year_ago.period_end.isoformat(),
        "quarters_on_file": len(quarters),
        "days_since_filed": stale_days,
        "how_current": (
            None
            if stale_days is None
            # Results arrive about six weeks after a quarter ends and the next set about three
            # months after that, so a filing up to ~140 days old is still the newest one due.
            else (
                "the newest quarter the company has filed"
                if stale_days <= 140
                else f"THIS IS {stale_days // 30} MONTHS OLD — the exchange has published no "
                "newer quarter for this company, so it describes the company as it was, not as it "
                "is. Weigh it against the price history and the filings, which are current."
            )
        ),
        "note": (
            "Filed with the exchange and public at or before this review's date. Growth is against "
            "the same quarter a year earlier, and is absent when that quarter is not on file. "
            "Figures are as filed, in rupees; they are not restated."
        ),
    }
    if latest.is_bank:
        earned, expended = latest.get("interest_earned"), latest.get("interest_expended")
        nii = None if earned is None or expended is None else earned - expended
        out["bank"] = {
            "revenue_means": "interest earned — a bank's equivalent of revenue from operations",
            "net_interest_income": None if nii is None else str(nii),
            "operating_profit_before_provisions": text("operating_profit_before_provisions"),
            "provisions": text("provisions"),
            "provisions_pct_of_operating_profit": _ratio(
                latest.get("provisions"), latest.get("operating_profit_before_provisions")
            ),
            "gross_npa_pct": text("gross_npa_pct"),
            "net_npa_pct": text("net_npa_pct"),
            "note": (
                "NPA ratios are required only in a bank's standalone accounts; the consolidated "
                "filing leaves them blank. Null here means NOT REPORTED IN THIS FILING, not zero bad "
                "loans."
            ),
        }
    return out
