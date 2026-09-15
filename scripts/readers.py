"""EX-5: measure which filing reader is good enough, and which triage rules are safe.

Every step is separate, resumable, and run by hand in this order. Nothing is switched on by it: the
evening pipeline keeps its registered reader until a selection is published and registered.

    uv run python scripts/readers.py sample                        # 150 archived filings, fixed seed
    uv run python scripts/readers.py read --reader qwen3.5-9b-16k  # a local candidate ($0)
    uv run python scripts/readers.py read --reader deepseek-flash --budget-usd 1
    uv run python scripts/readers.py reference submit --budget-usd 12   # Opus 5, Batch
    uv run python scripts/readers.py reference collect
    uv run python scripts/readers.py adjudicate submit --budget-usd 12  # after every reader has read
    uv run python scripts/readers.py adjudicate collect
    uv run python scripts/readers.py worksheet omissions           # 20 documents for you to read
    uv run python scripts/readers.py worksheet claims              # 25 adjudications for you to check
    uv run python scripts/readers.py score                         # reports/READER_COMPARISON_EX5.md
    uv run python scripts/readers.py status

**Money.** A paid step needs ``--budget-usd``: the total that job may ever commit, across months,
checked before each request by reserving its worst case in ``data/spend/ledger.jsonl``. Reader runs
share one job ceiling; the Opus reference and the adjudication share another. Neither draws on the
monthly operating cap, so neither can spend the evening review's money.

Rules are in ``reports/PREREGISTRATION_EX5_READERS.md``, written before any of this ran.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qalpha.live import reader_scoring, readers, reference, spend
from qalpha.live.announcements import ARCHIVE_DIR
from qalpha.live.console import use_utf8
from qalpha.live.panels import WATCHLIST_UNIVERSE

REPORT = Path("reports/READER_COMPARISON_EX5.md")


def _budget(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return value if value > 0 else None


def _documents() -> tuple[list[readers.SampleDoc], list[object]] | None:
    sample = readers.load_sample()
    if not sample:
        print("[readers] no sample yet — run: scripts/readers.py sample", file=sys.stderr)
        return None
    documents, problems = readers.load_documents(sample)
    for line in problems:
        print(f"[readers] left out: {line}", file=sys.stderr)
    return sample, documents


def cmd_sample(args: argparse.Namespace) -> int:
    if readers.load_sample() and not args.force:
        print(
            f"[readers] a sample already exists at {readers.sample_path()}. It is never redrawn: "
            "readers are measured on one fixed set. (--force only before anything has read it.)"
        )
        return 1
    if args.force and any(readers.runs_dir().glob("*.json")):
        print("[readers] refused: readers have already read this sample.", file=sys.stderr)
        return 2
    pool = readers.candidates_in_archive(ARCHIVE_DIR, WATCHLIST_UNIVERSE)
    chosen = readers.select_sample(pool)
    readers.save_sample(chosen)
    groups: dict[str, int] = {}
    for doc in chosen:
        groups[doc.group] = groups.get(doc.group, 0) + 1
    sectors = len({d.sector for d in chosen})
    print(
        f"[readers] sampled {len(chosen)} of {len(pool)} archived filings with a text layer — "
        f"{groups} — across {sectors} sectors → {readers.sample_path()}"
    )
    if len(chosen) < readers.SAMPLE_SIZE:
        print(
            f"[readers] WARNING: fewer than {readers.SAMPLE_SIZE}; a group had too few filings.",
            file=sys.stderr,
        )
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    spec = readers.READERS.get(args.reader)
    if spec is None:
        print(
            f"[readers] unknown reader; choose from: {', '.join(readers.READERS)}", file=sys.stderr
        )
        return 2
    budget = _budget(args.budget_usd)
    if spec.kind != "local" and budget is None:
        print(f"[readers] {spec.slug} is paid: give --budget-usd.", file=sys.stderr)
        return 2
    loaded = _documents()
    if loaded is None:
        return 2
    _, documents = loaded
    ledger = spend.Ledger(job=readers.READERS_JOB, job_limit_usd=budget)
    try:
        backend = readers.backend_for(spec, ledger=ledger)
    except RuntimeError as exc:
        print(f"[readers] {exc}", file=sys.stderr)
        return 2
    if spec.kind != "local":
        print(
            f"[readers] {readers.READERS_JOB}: ${ledger.job_committed(readers.READERS_JOB):.4f} "
            f"committed of ${budget}"
        )

    def progress(done: int, total: int, events: int) -> None:
        print(f"\r[readers] {spec.slug}: batch {done}/{total}, {events} events", end="", flush=True)

    run = readers.run_reader(
        spec, documents, backend=backend, workers=args.workers, progress=progress
    )
    print()
    last = run["segments"][-1] if run.get("segments") else {}
    print(
        f"[readers] {spec.slug}: {len(run['done'])}/{len(documents)} documents read, "
        f"{len(run['events'])} verified events; this segment {last.get('seconds', 0)}s, "
        f"${last.get('usd', '0')}, {last.get('tokens_per_second') or '—'} tok/s, "
        f"peak VRAM {last.get('peak_vram_mb') or '—'} MB, peak RAM {last.get('peak_ram_mb') or '—'} MB"
    )
    failed = int(last.get("usage", {}).get("failed_batches", 0)) if last else 0
    if failed or last.get("stopped"):
        print(
            f"[readers] {failed} failed batches; stopped: {last.get('stopped') or 'no'}. "
            "Run the same command again to read what is left.",
            file=sys.stderr,
        )
    return 0


def _anthropic_client() -> object | None:
    import os

    import anthropic

    from qalpha.live.credentials import load_env

    load_env()
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("[readers] ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return None
    return anthropic.Anthropic(api_key=key, max_retries=3, timeout=300.0)


def cmd_batch(args: argparse.Namespace) -> int:
    loaded = _documents()
    if loaded is None:
        return 2
    _, documents = loaded
    budget = _budget(getattr(args, "budget_usd", None))
    if args.action == "submit" and budget is None:
        print("[readers] submitting is paid: give --budget-usd.", file=sys.stderr)
        return 2
    client = _anthropic_client()
    if client is None:
        return 2
    ledger = spend.Ledger(job=reference.REFERENCE_JOB, job_limit_usd=budget)
    if args.action == "collect":
        lines = reference.collect(client=client, ledger=ledger, documents=documents)
        for line in lines or ["nothing in flight"]:
            print(f"[readers] {line}")
        return 0

    if args.kind == "reference":
        items = [
            (
                f"ref-{d.provenance.sha256[:48]}",
                reference.reference_prompt(d),
                {"doc_sha256": d.provenance.sha256},
            )
            for d in reference.pending_reference(documents)
        ]
    else:
        unread = [
            s
            for s in readers.READERS
            if len(readers.load_run(s).get("done", [])) < len(documents)
            and readers.run_path(s).exists()
        ]
        if reference.pending_reference(documents) and not args.partial:
            print(
                "[readers] refused: the Opus reference readings are not all collected, so their "
                "claims would go unjudged. Run 'reference collect' (or submit the rest) first.",
                file=sys.stderr,
            )
            return 2
        if unread and not args.partial:
            print(
                f"[readers] refused: {', '.join(unread)} have not finished reading. Claims added "
                "later would go unjudged. Finish them, or pass --partial.",
                file=sys.stderr,
            )
            return 2
        items = [
            (
                f"adj-{d.provenance.sha256[:48]}",
                reference.adjudication_prompt(d, claims),
                {"doc_sha256": d.provenance.sha256, "claims": claims},
            )
            for d, claims in reference.pending_adjudication(documents)
        ]
    if not items:
        print(f"[readers] nothing to submit for {args.kind}.")
        return 0
    try:
        record = reference.submit(
            args.kind,
            items,
            client=client,
            ledger=ledger,
            effort=args.effort,
            max_tokens=args.max_tokens,
        )
    except spend.SpendStopError as exc:
        print(f"[readers] not submitted: {exc}", file=sys.stderr)
        return 2
    if record is None:
        print(
            f"[readers] nothing submitted: the first request alone would pass the ${budget} budget "
            f"({reference.REFERENCE_JOB} has ${ledger.job_committed(reference.REFERENCE_JOB):.4f})."
        )
        return 2
    held = sum(
        (
            ledger.reservation(m["reservation_id"])
            or spend.Reservation("", "", "", Decimal("0"), "")
        ).usd
        for m in record["requests"].values()
    )
    print(
        f"[readers] {args.kind} batch {record['batch_id']}: {len(record['requests'])} of {len(items)} "
        f"requests, ${held:.4f} reserved (worst case). Batches finish within 24 h; then run "
        f"'{args.cmd} collect'."
    )
    if len(record["requests"]) < len(items):
        print("[readers] the rest did not fit the budget; submit again after collecting.")
    return 0


def cmd_worksheet(args: argparse.Namespace) -> int:
    loaded = _documents()
    if loaded is None:
        return 2
    sample, documents = loaded
    if args.which == "omissions":
        chosen = reader_scoring.choose_human_documents(sample)
        folder = reader_scoring.write_omission_worksheet(documents, chosen)
        print(
            f"[readers] {len(chosen)} documents to read end to end: {folder} (see HOW_TO_CHECK.md)"
        )
        return 0
    path = reader_scoring.write_claim_worksheet()
    if path is None:
        print("[readers] no adjudications yet — run adjudicate submit and collect first.")
        return 2
    print(f"[readers] fill the your_verdict column (agree / disagree): {path}")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    from qalpha.live.atomic import write_text

    loaded = _documents()
    if loaded is None:
        return 2
    sample, _ = loaded
    runs, model_ref, full_ref, adjudications = reader_scoring.load_everything(sample)
    read_docs = reader_scoring.read_human_documents()
    human = [e for e in reader_scoring.read_human_events() if e["doc_sha256"] in read_docs]
    validation = reader_scoring.validate(
        model_ref, human, read_docs, reader_scoring.read_claim_checks()
    )
    scores = [reader_scoring.score_reader(run, full_ref, adjudications) for run in runs]
    selection = reader_scoring.select(scores, validation, readers.unique_documents(sample))
    triage_result = reader_scoring.triage_check(sample, full_ref)
    text = reader_scoring.render_report(
        scores,
        selection,
        validation,
        triage_result,
        sample_size=readers.unique_documents(sample),
        reference_events=len(full_ref),
    )
    write_text(REPORT, text)
    print(text)
    print(f"[readers] written: {REPORT}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    sample = readers.load_sample()
    print(f"sample: {len(sample)} filings, {readers.unique_documents(sample)} distinct documents")
    for slug in readers.READERS:
        if readers.run_path(slug).exists():
            run = readers.load_run(slug)
            print(
                f"  {slug:<24} {len(run.get('done', []))}/{readers.unique_documents(sample)} read"
            )
        else:
            print(f"  {slug:<24} not started")
    for record in reference.load_batches():
        state = "collected" if record.get("collected") else "in flight"
        print(
            f"  {record['kind']} batch {record['batch_id']}: {len(record['requests'])} requests, {state}"
        )
    book = spend.Ledger()
    for job in (readers.READERS_JOB, reference.REFERENCE_JOB):
        print(f"  {job}: ${book.job_committed(job):.4f} committed")
    return 0


def main(argv: list[str] | None = None) -> int:
    use_utf8()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sample", help="draw the fixed sample from the archive")
    p.add_argument(
        "--force", action="store_true", help="redraw, only before any reader has read it"
    )
    p.set_defaults(fn=cmd_sample)

    p = sub.add_parser("read", help="one candidate reads the sample (resumes)")
    p.add_argument("--reader", required=True, choices=sorted(readers.READERS))
    p.add_argument("--budget-usd", help="total ceiling for all paid reader runs")
    p.add_argument(
        "--workers", type=int, default=1, help="1 for local models: one request at a time"
    )
    p.set_defaults(fn=cmd_read)

    for kind in ("reference", "adjudicate"):
        p = sub.add_parser(kind, help=f"Opus 5 {kind} batches")
        p.add_argument("action", choices=("submit", "collect"))
        p.add_argument("--budget-usd", help="total ceiling for reference + adjudication")
        p.add_argument("--effort", default=reference.DEFAULT_EFFORT, choices=("high", "max"))
        p.add_argument(
            "--max-tokens",
            type=int,
            default=reference.REFERENCE_MAX_TOKENS,
            help="output room, thinking included; raise it to resubmit a reading cut off",
        )
        p.add_argument(
            "--partial", action="store_true", help="adjudicate before every run finished"
        )
        p.set_defaults(fn=cmd_batch, kind="reference" if kind == "reference" else "adjudication")

    p = sub.add_parser("worksheet", help="the checks only you can do")
    p.add_argument("which", choices=("omissions", "claims"))
    p.set_defaults(fn=cmd_worksheet)

    sub.add_parser("score", help="apply the registered rule").set_defaults(fn=cmd_score)
    sub.add_parser("status", help="what has been done").set_defaults(fn=cmd_status)

    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
