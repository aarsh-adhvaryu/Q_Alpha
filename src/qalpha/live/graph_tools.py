"""Graph research the investor may ask for: read-only, point in time, bounded, with the quotes.

The same rules as :mod:`qalpha.live.tools`, applied to connections instead of documents:

* **Read-only.** Answers come from a :class:`~qalpha.live.graph.GraphView` — a snapshot valid on the
  review's date and known by the end of it. Nothing here writes to the graph or to Neo4j.
* **Facts by default.** ``DISCLOSED`` and ``COMPUTED`` only. A model's inference is returned only by
  ``inferred``, and says so on every row.
* **Every connection comes with its passage and assertion id**, so a decision can cite the
  company's own words, and a citation can be checked.
* **Unknown is said.** A company with no disclosed supplier is "no SUPPLIER_TO known" together with
  its coverage row — never "has no suppliers".
"""

from __future__ import annotations

from typing import Any

from qalpha.live import graph as g

MAX_HOPS = 3
MAX_ROWS = 40

TOOLS: dict[str, str] = {
    "connections": (
        "connections(ticker, hops=1) — the company's disclosed business connections (suppliers, "
        "customers, owners, subsidiaries, competitors, related parties), each with its quote. hops ≤ 2."
    ),
    "exposure": (
        "exposure(entity) — which names in this review connect to an organisation (a ticker or a "
        "name), through up to three disclosed connections, with the path and quotes."
    ),
    "gaps": "gaps(ticker) — for each connection type: known, MISSING (a recorded gap) or unknown.",
    "periods": (
        "periods(ticker, metric) — one metric across every filed period on record, newest first. "
        "metric: revenue, profit_after_tax, eps_basic, interest_earned, provisions."
    ),
    "thesis_history": (
        "thesis_history(ticker) — your own earlier theses for the name, how they were revised, and "
        "any evidence recorded as contradicting them. Your beliefs, not evidence."
    ),
    "inferred": (
        "inferred(ticker) — connections a model INFERRED but no document states. Labelled; never "
        "evidence on their own."
    ),
}

METRICS = {"revenue", "profit_after_tax", "eps_basic", "interest_earned", "provisions"}


def describe() -> str:
    return "\n".join(f"  - {text}" for text in TOOLS.values())


def _resolve(entity: str, view: g.GraphView) -> str | None:
    text = entity.strip()
    if not text:
        return None
    for candidate in (g.company_id(text), f"org:{g.slug(text)}", text):
        if candidate in view.nodes or any(candidate in (e.subject, e.object) for e in view.edges):
            return candidate
    return None


def answer_one(request: dict[str, Any], *, view: g.GraphView, names: list[str]) -> dict[str, Any]:
    tool = str(request.get("tool", ""))
    ticker = str(request.get("ticker", ""))
    if (
        tool in ("connections", "gaps", "periods", "thesis_history", "inferred")
        and ticker not in names
    ):
        return {"request": request, "error": f"{ticker!r} is not held or shown in this review"}
    cid = g.company_id(ticker) if ticker else ""
    if tool == "connections":
        hops = max(1, min(int(request.get("hops", 1) or 1), 2))
        rows = view.neighbourhood(cid, hops=hops, types=[*g.CONNECTION_TYPES])[:MAX_ROWS]
        return {
            "request": request,
            "result": {
                "ticker": ticker,
                "connections": rows,
                "coverage": view.coverage(cid),
                "note": (
                    "Disclosed or computed connections only, as known on this date. A connection "
                    "type marked unknown or MISSING is not evidence that none exists."
                ),
            },
        }
    if tool == "exposure":
        entity = _resolve(str(request.get("entity", "")), view)
        if entity is None:
            return {
                "request": request,
                "result": {
                    "entity": request.get("entity"),
                    "paths": {},
                    "note": "no organisation by that name is in the graph on this date",
                },
            }
        paths = view.exposure(names, entity, max_hops=MAX_HOPS)
        return {
            "request": request,
            "result": {
                "entity": entity,
                "paths": paths,
                "note": (
                    "Names in this review connected to the entity through disclosed or computed "
                    "facts. A name absent here may still be exposed through a connection nobody "
                    "has disclosed or read — check its gaps."
                ),
            },
        }
    if tool == "gaps":
        return {"request": request, "result": {"ticker": ticker, "coverage": view.coverage(cid)}}
    if tool == "periods":
        metric = str(request.get("metric", ""))
        if metric not in METRICS:
            return {"request": request, "error": f"metric must be one of {sorted(METRICS)}"}
        return {
            "request": request,
            "result": {"ticker": ticker, "metric": metric, "periods": view.periods(cid, metric)},
        }
    if tool == "thesis_history":
        theses = [
            e.subject
            for e in view.facts()
            if e.label == "ABOUT" and e.object == cid and view.label(e.subject) == "Thesis"
        ]
        rows = []
        for tid in sorted(theses):
            node = view.nodes.get(tid)
            rows.append(
                {
                    "thesis": tid,
                    "text": None if node is None else node.props.get("text"),
                    "invalidate_if": None if node is None else node.props.get("invalidate_if"),
                    "revised_to": [
                        e.object
                        for e in view.facts()
                        if e.label == "REVISED_TO" and e.subject == tid
                    ],
                    "contradicted_by": [
                        {
                            "evidence": e.subject,
                            "assertion": e.id,
                            "passage": e.source.get("passage"),
                        }
                        for e in view.contradictions(tid)
                    ],
                }
            )
        return {
            "request": request,
            "result": {
                "ticker": ticker,
                "theses": rows,
                "note": "Your own earlier beliefs, not evidence.",
            },
        }
    if tool == "inferred":
        return {
            "request": request,
            "result": {
                "ticker": ticker,
                "inferred": [
                    {
                        "assertion": e.id,
                        "relationship": e.label,
                        "from": e.subject,
                        "to": e.object,
                        "model": e.source.get("model"),
                        "confidence": e.source.get("confidence"),
                        "epistemic": g.INFERRED,
                    }
                    for e in view.inferred(cid)
                ][:MAX_ROWS],
                "note": "INFERRED by a model. No document states these. Not evidence on their own.",
            },
        }
    return {"request": request, "error": f"no such graph tool; choose from {sorted(TOOLS)}"}


def answer(
    requests: list[Any], *, view: g.GraphView, names: list[str], limit: int
) -> list[dict[str, Any]]:
    """Answer up to ``limit`` requests in order; a refusal is an answer, with its reason."""
    out: list[dict[str, Any]] = []
    for raw in requests[:limit]:
        if not isinstance(raw, dict):
            out.append({"request": str(raw), "error": "not a request object"})
            continue
        try:
            out.append(answer_one(raw, view=view, names=names))
        except Exception as exc:  # a broken request must not end the review
            out.append({"request": raw, "error": f"{type(exc).__name__}: {exc}"})
    if len(requests) > limit:
        out.append(
            {"error": f"{len(requests)} requests were made; only the first {limit} were answered."}
        )
    return out


def cited_assertions(answers: list[dict[str, Any]]) -> set[str]:
    """Assertion ids research put in front of the investor — citable, and checkable."""
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("assertion"), str):
                found.add(value["assertion"])
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    for entry in answers:
        walk(entry.get("result"))
    return found
