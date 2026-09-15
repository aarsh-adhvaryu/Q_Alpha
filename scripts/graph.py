"""The knowledge graph: fill it, look at it, and read connections into it.

    uv run python scripts/graph.py ingest                  # everything on disk → the log ($0, no network)
    uv run python scripts/graph.py coverage --only INFY    # per connection type: known / MISSING / unknown
    uv run python scripts/graph.py ask connections --ticker INFY
    uv run python scripts/graph.py ask exposure --entity "Apple Inc"
    uv run python scripts/graph.py relations --reader qwen3.5-9b-16k --only INFY --limit 20
    uv run python scripts/graph.py neo4j status            # is the container up?
    uv run python scripts/graph.py neo4j sync              # rebuild Neo4j from the log

``relations`` reads filings with a model. A local reader costs nothing; an Anthropic reader is
charged to the reading partition of the monthly cap, reserved before each call.

``ask`` answers exactly as the investor's graph tools do: facts known by the end of ``--on``
(default today), valid on that date.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qalpha.live import graph as g
from qalpha.live import graph_ingest, graph_tools
from qalpha.live.console import use_utf8


def cmd_ingest(args: argparse.Namespace) -> int:
    log = g.GraphLog()
    report = graph_ingest.ingest_all(log)
    print(json.dumps(report, indent=1))
    print(f"[graph] {len(log.versions)} assertion versions on record → {log.path}")
    return 0


def _view(on: str | None) -> g.GraphView:
    day = date.fromisoformat(on) if on else datetime.now(UTC).date()
    return g.GraphLog().view(valid_at=day, known_at=graph_ingest.end_of_day(day))


def cmd_coverage(args: argparse.Namespace) -> int:
    view = _view(args.on)
    tickers = (
        [t.strip() for t in args.only.split(",")]
        if args.only
        else sorted(
            str(a.props.get("ticker"))
            for a in view.nodes.values()
            if a.label == "Company" and a.props.get("listed")
        )
    )
    for ticker in tickers:
        cov = view.coverage(g.company_id(ticker))
        print(f"{ticker:<16} " + "  ".join(f"{k}={v}" for k, v in cov.items()))
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    view = _view(args.on)
    request: dict[str, object] = {"tool": args.tool}
    for field in ("ticker", "entity", "metric"):
        if getattr(args, field):
            request[field] = getattr(args, field)
    if args.hops:
        request["hops"] = args.hops
    names = sorted(
        str(a.props.get("ticker"))
        for a in view.nodes.values()
        if a.label == "Company" and a.props.get("listed")
    )
    print(
        json.dumps(graph_tools.answer_one(request, view=view, names=names), indent=1, default=str)
    )
    return 0


def cmd_relations(args: argparse.Namespace) -> int:
    from qalpha.live import readers, relations, spend
    from qalpha.live.announcements import ARCHIVE_DIR, Announcement, SourceDocument, load_document
    from qalpha.live.credentials import load_env
    from qalpha.live.news import load_aliases

    spec = readers.READERS.get(args.reader)
    if spec is None:
        print(f"[graph] unknown reader; choose from {', '.join(readers.READERS)}", file=sys.stderr)
        return 2
    load_env()
    if spec.kind == "local":
        from qalpha.live import localmodel

        url = os.environ.get(localmodel.URL_VAR, "").strip() or localmodel.DEFAULT_URL
        why = localmodel.probe(url, model=spec.model)
        if why:
            print(f"[graph] {spec.model} cannot be used: {why}", file=sys.stderr)
            return 2
        generate = localmodel.local_generate(url)
        max_chars = localmodel.budget_for(readers.LOCAL_CONTEXT)
    elif spec.kind == "anthropic":
        from qalpha.live.extraction import PROMPT_CHAR_BUDGET, default_generate

        key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not key:
            print("[graph] ANTHROPIC_API_KEY is not set", file=sys.stderr)
            return 2
        generate = default_generate(key, partition=spend.READING)
        max_chars = PROMPT_CHAR_BUDGET
    else:
        print("[graph] relations supports local and Anthropic readers", file=sys.stderr)
        return 2

    done = relations.already_read(spec.model)
    resolver = relations.Resolver(load_aliases())
    log = g.GraphLog()
    read = 0
    for symbol in [t.strip().removesuffix(".NS") for t in args.only.split(",")]:
        for prov_path in sorted((ARCHIVE_DIR / symbol).glob("*.provenance.json"), reverse=True):
            if read >= args.limit:
                break
            meta = json.loads(prov_path.read_text(encoding="utf-8"))
            if str(meta.get("sha256")) in done:
                continue
            ann = Announcement(
                symbol=symbol,
                seq_id=str(meta.get("seq_id") or prov_path.name.split(".")[0]),
                subject=str(meta.get("subject") or ""),
                summary="",
                disseminated_at=datetime.fromisoformat(
                    str(meta.get("document_date") or "1970-01-01")
                ).replace(tzinfo=UTC),
                attachment_url=str(meta.get("source_url") or ""),
            )
            text, prov = load_document(ann)
            if prov is None or not text:
                continue
            try:
                row = relations.read_document(
                    SourceDocument(announcement=ann, text=text, provenance=prov),
                    generate=generate,
                    model=spec.model,
                    resolver=resolver,
                    log=log,
                    max_chars=max_chars,
                )
            except spend.SpendStopError as exc:
                print(f"[graph] stopped: {exc}", file=sys.stderr)
                log.flush()
                return 2
            log.flush()
            read += 1
            print(f"[graph] {symbol} {ann.seq_id}: kept {row['kept']}, dropped {row['dropped']}")
    print(f"[graph] {read} filing(s) read for connections")
    return 0


def cmd_neo4j(args: argparse.Namespace) -> int:
    from qalpha.live import graph_neo4j

    try:
        driver = graph_neo4j.connect()
    except graph_neo4j.Neo4jUnavailableError as exc:
        print(f"[graph] Neo4j: DOWN — {exc}")
        return 2
    try:
        if args.action == "status":
            print("[graph] Neo4j: up")
            return 0
        written = graph_neo4j.sync(g.GraphLog(), driver)
        print(f"[graph] Neo4j rebuilt from the log: {written}")
        return 0
    finally:
        driver.close()


def main(argv: list[str] | None = None) -> int:
    use_utf8()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest", help="everything on disk into the log").set_defaults(fn=cmd_ingest)

    p = sub.add_parser("coverage", help="known / MISSING / unknown per connection type")
    p.add_argument("--only", help="comma-separated tickers")
    p.add_argument("--on", help="YYYY-MM-DD; default today")
    p.set_defaults(fn=cmd_coverage)

    p = sub.add_parser("ask", help="one graph research question, as the investor would ask it")
    p.add_argument("tool", choices=sorted(graph_tools.TOOLS))
    p.add_argument("--ticker")
    p.add_argument("--entity")
    p.add_argument("--metric")
    p.add_argument("--hops", type=int)
    p.add_argument("--on")
    p.set_defaults(fn=cmd_ask)

    p = sub.add_parser("relations", help="read filings for company connections")
    p.add_argument("--reader", required=True)
    p.add_argument("--only", required=True, help="comma-separated tickers")
    p.add_argument("--limit", type=int, default=20, help="filings to read this run")
    p.set_defaults(fn=cmd_relations)

    p = sub.add_parser("neo4j", help="check or rebuild the Neo4j projection")
    p.add_argument("action", choices=("status", "sync"))
    p.set_defaults(fn=cmd_neo4j)

    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
