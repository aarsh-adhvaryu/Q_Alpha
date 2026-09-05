"""Evidence adapter v1 — the fixtures frozen in reports/PREREGISTRATION_EVIDENCE_V1.md §5.

**Fixture 1 failed its prediction and the test records the failure rather than hiding it.** The
pre-registration expected VBL to read ``WATCH`` on the real-money purchase date. It reads ``PASS``:
NSE's own file carries no active indicator for VBL on 2026-08-27. That is a negative, it is
published, and the rule was not widened afterwards to make VBL appear.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from qalpha.live.evidence import (
    BLOCK,
    COL_PE_50,
    NOT_COVERED_DIMENSIONS,
    PASS,
    STALENESS_TOLERANCE_DAYS,
    UNKNOWN,
    WATCH,
    Provenance,
    active_indicators,
    assess,
    assess_basket,
    load_archive,
    parse_reg_ind,
    reg_ind_url,
    sha256_of,
    write_archive,
)

PURCHASE_DATE = date(2026, 8, 27)

_HEADER = (
    "ScripCode,Symbol,Nse Exclusive,Status,Series,GSM,"
    "Long_Term_Additional_Surveillance_Measure (Long Term ASM),Unsolicited_SMS,"
    "Insolvency_Resolution_Process(IRP),"
    "Short_Term_Additional_Surveillance_Measure (Short Term ASM),Default,Under BZ/SZ Series,"
    "Scrip PE is greater than 50 (4 trailing quarters),Filler12"
)


def _row(symbol: str, **over: str) -> str:
    cells = {
        "status": "A",
        "series": "EQ",
        "gsm": "100",
        "lt_asm": "100",
        "sms": "100",
        "irp": "100",
        "st_asm": "100",
        "default": "100",
        "bzsz": "100",
        "pe": "100",
    }
    cells.update(over)
    return (
        f"NA,{symbol},N,{cells['status']},{cells['series']},{cells['gsm']},{cells['lt_asm']},"
        f"{cells['sms']},{cells['irp']},{cells['st_asm']},{cells['default']},{cells['bzsz']},"
        f"{cells['pe']},"
    )


def _synthetic(*rows: str) -> dict[str, dict[str, str]]:
    return parse_reg_ind("\n".join((_HEADER, *rows)) + "\n")


def _prov(trading_date: date = PURCHASE_DATE) -> Provenance:
    return Provenance(
        source_url=reg_ind_url(trading_date),
        retrieved_at_utc=datetime(2026, 9, 5, tzinfo=UTC),
        http_status=200,
        sha256="0" * 64,
        byte_length=1234,
        document_date=trading_date,
    )


# --- the real archived documents ---------------------------------------------------------------


def _archive() -> tuple[dict[str, dict[str, str]], Provenance]:
    rows, prov = load_archive(PURCHASE_DATE)
    if prov is None:  # pragma: no cover - the archive is committed alongside this test
        pytest.skip("archived REG1_IND270826 not present")
    return rows, prov


def test_fixture_1_vbl_reads_pass_not_the_predicted_watch() -> None:
    """PRE-REGISTERED: WATCH. ACTUAL: PASS. The prediction failed and this is the record.

    VBL carried the P/E-above-50 caution from at least 2025-07 to 2025-12 and again in 2026-05/06,
    but it had lapsed by 2026-07 and was still clear on the purchase date. The adapter does cover
    VBL; the caution simply was not live when the money went in.
    """
    rows, prov = _archive()
    a = assess("VBL.NS", rows, prov, as_of=PURCHASE_DATE)
    assert a.state == PASS
    assert a.indicators == ()
    assert a.provenance is not None and a.provenance.document_date == PURCHASE_DATE


def test_the_pe_caution_does_fire_on_names_this_system_buys() -> None:
    """The adapter is not blind to the VBL *class* of problem — only to VBL on that date.

    JIOFIN sits in the basket the live screen recommends today, and NSE cautions on it.
    """
    rows, prov = _archive()
    a = assess("JIOFIN.NS", rows, prov, as_of=PURCHASE_DATE)
    assert a.state == WATCH
    assert any(i.column == COL_PE_50 for i in a.indicators)
    assert a.needs_human and not a.blocking


def test_fixture_2_hard_condition_blocks() -> None:
    """Chosen by applying the §4 rule to the file, not by picking a name that made it pass."""
    rows, prov = _archive()
    a = assess("BLISSGVS", rows, prov, as_of=PURCHASE_DATE)
    assert a.state == BLOCK
    assert a.blocking


def test_fixture_3_clean_security_passes() -> None:
    rows, prov = _archive()
    assert assess("20MICRONS", rows, prov, as_of=PURCHASE_DATE).state == PASS


def test_archive_round_trips_and_hash_is_verified(tmp_path: Path) -> None:
    payload = ("\n".join((_HEADER, _row("ACME"))) + "\n").encode()
    prov = write_archive(payload, PURCHASE_DATE, http_status=200, directory=tmp_path)
    assert prov.sha256 == sha256_of(payload)
    rows, back = load_archive(PURCHASE_DATE, directory=tmp_path)
    assert back is not None and back.sha256 == prov.sha256 and "ACME" in rows


def test_a_tampered_archive_is_treated_as_missing(tmp_path: Path) -> None:
    """A silently edited primary document is worse than an absent one."""
    payload = ("\n".join((_HEADER, _row("ACME"))) + "\n").encode()
    write_archive(payload, PURCHASE_DATE, http_status=200, directory=tmp_path)
    csv_path = tmp_path / "REG1_IND270826.csv"
    csv_path.write_bytes(payload.replace(b"ACME", b"OTHR"))
    rows, back = load_archive(PURCHASE_DATE, directory=tmp_path)
    assert (rows, back) == ({}, None)


# --- the four states that are not PASS -----------------------------------------------------------


def test_fixture_4_no_file_is_unknown_never_approval() -> None:
    a = assess("VBL.NS", {}, None, as_of=PURCHASE_DATE)
    assert a.state == UNKNOWN and a.needs_human


def test_fixture_4_stale_file_is_unknown() -> None:
    rows = _synthetic(_row("VBL"))
    stale = PURCHASE_DATE.toordinal() + STALENESS_TOLERANCE_DAYS + 1
    a = assess("VBL", rows, _prov(), as_of=date.fromordinal(stale))
    assert a.state == UNKNOWN
    assert "stale" in a.detail or "old" in a.detail


def test_a_file_inside_tolerance_still_decides() -> None:
    rows = _synthetic(_row("VBL"))
    fresh = date.fromordinal(PURCHASE_DATE.toordinal() + STALENESS_TOLERANCE_DAYS)
    assert assess("VBL", rows, _prov(), as_of=fresh).state == PASS


def test_absent_symbol_is_unknown_not_pass() -> None:
    """Absence from the file is not a clean bill of health."""
    a = assess("NOTLISTED", _synthetic(_row("VBL")), _prov(), as_of=PURCHASE_DATE)
    assert a.state == UNKNOWN


def test_fixture_5_not_covered_is_always_reported_and_never_blocks() -> None:
    """Every unbuilt dimension is named, so silence is not read as approval."""
    for state_rows in (_synthetic(_row("VBL")), {}):
        a = assess("VBL", state_rows, _prov() if state_rows else None, as_of=PURCHASE_DATE)
        assert a.not_covered == NOT_COVERED_DIMENSIONS
        assert "fundamentals" in a.render()
    assert "corporate announcements" in NOT_COVERED_DIMENSIONS


# --- the BLOCK rules, one at a time --------------------------------------------------------------


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({"status": "S"}, "suspended"),
        ({"series": "BZ"}, "trade-to-trade"),
        ({"series": "BE"}, "trade-to-trade"),
        ({"lt_asm": "2"}, "ASM stage 2"),
        ({"st_asm": "3"}, "short-term ASM stage 3"),
        ({"gsm": "4"}, "GSM stage 4"),
        ({"irp": "1"}, "insolvency"),
        ({"bzsz": "0"}, "BZ/SZ flag"),
    ],
)
def test_hard_conditions_block(over: dict[str, str], why: str) -> None:
    assert (
        assess("X", _synthetic(_row("X", **over)), _prov(), as_of=PURCHASE_DATE).state == BLOCK
    ), why


@pytest.mark.parametrize("over", [{"lt_asm": "1"}, {"gsm": "1"}, {"st_asm": "1"}, {"pe": "0"}])
def test_advisory_indicators_watch_but_do_not_block(over: dict[str, str]) -> None:
    """Stage 1 and the P/E caution are warnings. The exchange mandates a pop-up, not a prohibition."""
    a = assess("X", _synthetic(_row("X", **over)), _prov(), as_of=PURCHASE_DATE)
    assert a.state == WATCH and not a.blocking and a.needs_human


def test_clear_value_100_is_not_an_active_flag() -> None:
    assert active_indicators(_synthetic(_row("X"))["X"]) == ()


def test_indicator_keeps_the_raw_published_value() -> None:
    inds = active_indicators(_synthetic(_row("X", lt_asm="4"))["X"])
    assert [(i.raw_value, i.stage) for i in inds] == [("4", 4)]


def test_assess_basket_covers_every_candidate() -> None:
    rows = _synthetic(_row("A"), _row("B", pe="0"), _row("C", lt_asm="2"))
    out = assess_basket(["A", "B", "C", "D"], rows, _prov(), as_of=PURCHASE_DATE)
    assert [out[t].state for t in "ABCD"] == [PASS, WATCH, BLOCK, UNKNOWN]


def test_url_matches_the_exchange_naming() -> None:
    assert reg_ind_url(PURCHASE_DATE).endswith("/REG1_IND270826.csv")
