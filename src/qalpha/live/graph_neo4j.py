"""Neo4j: the knowledge graph as a database you can traverse and look at — rebuilt from the log.

**A projection, never the record.** :func:`sync` rebuilds the database from
``data/graph/assertions.jsonl``: every edge *version* becomes a relationship carrying its epistemic
class and both time axes, so Cypher can ask the same bitemporal questions the log answers. Node
identities are merged once with their current properties; a node's property history stays in the
log. Nothing writes to Neo4j except :func:`sync`, and the investor's tools only run the read-only
templates below.

**The model never writes Cypher.** It picks a template by name and supplies parameters; every value
travels as a ``$parameter``. Labels and relationship types appear in query text only from the
schema's own whitelist (:data:`qalpha.live.graph.NODE_LABELS`, :data:`~qalpha.live.graph.EDGE_TYPES`).

Run locally in Docker (Community Edition)::

    docker run -d --name qalpha-neo4j -p 7474:7474 -p 7687:7687 \\
        -e NEO4J_AUTH=neo4j/<password> -v qalpha-neo4j:/data neo4j:5-community

and set ``QALPHA_NEO4J_PASSWORD`` in ``.env``. When the container is down, the evening says so and
graph questions are answered from the log directly (:class:`qalpha.live.graph.GraphView`) — the same
answers, because they are the same assertions.
"""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from typing import Any

from qalpha.live import graph as g

URI_VAR, USER_VAR, PASSWORD_VAR = "QALPHA_NEO4J_URI", "QALPHA_NEO4J_USER", "QALPHA_NEO4J_PASSWORD"
DEFAULT_URI = "bolt://localhost:7687"
BATCH = 500

#: Bitemporal filter on one relationship variable ``r``. ISO strings compare correctly as text
#: because every time is written in UTC with the same format.
_WHEN = (
    "(r.valid_from IS NULL OR r.valid_from <= $valid_at) AND (r.valid_to IS NULL OR $valid_at < r.valid_to) "
    "AND r.known_from <= $known_at AND (r.known_to IS NULL OR $known_at < r.known_to) "
    "AND r.epistemic IN $classes"
)

TEMPLATES: dict[str, str] = {
    "neighbours_1": (
        "MATCH (a:Node {id: $node})-[r]-(b:Node) WHERE " + _WHEN + " "
        "RETURN b.id AS node, b.label AS label, type(r) AS relationship, r.id AS assertion, "
        "startNode(r).id AS from, r.passage AS passage ORDER BY node LIMIT 200"
    ),
    "paths_to": (
        "MATCH p = (a:Node {id: $start})-[rels*1..3]-(b:Node {id: $goal}) "
        "WHERE all(r IN rels WHERE " + _WHEN + ") "
        "RETURN [r IN rels | {assertion: r.id, relationship: type(r), from: startNode(r).id, "
        "to: endNode(r).id, passage: r.passage}] AS path ORDER BY length(p) LIMIT 50"
    ),
    "suppliers_of": (
        "MATCH (s:Node)-[r:SUPPLIER_TO]->(c:Node {id: $customer}) WHERE " + _WHEN + " "
        "RETURN s.id AS supplier, r.id AS assertion, r.passage AS passage, r.props AS props"
    ),
    "passages": (
        "MATCH ()-[r]->() WHERE r.id IN $assertions "
        "RETURN r.id AS assertion, r.passage AS passage, r.doc_sha256 AS doc_sha256, r.epistemic AS epistemic"
    ),
    "contradictions": (
        "MATCH (e:Node)-[r:CONTRADICTS]->(t:Node {id: $thesis}) WHERE " + _WHEN + " "
        "RETURN e.id AS evidence, r.id AS assertion, r.passage AS passage"
    ),
}


class Neo4jUnavailableError(RuntimeError):
    """The database is not reachable, or the driver is not installed. Said, never hidden."""


def _driver_module() -> Any:
    try:
        return importlib.import_module("neo4j")
    except ImportError as exc:
        raise Neo4jUnavailableError(
            "the neo4j driver is not installed: uv sync --extra dev --extra ai --extra graph"
        ) from exc


def connect() -> Any:
    """A driver for the configured database, verified reachable. Raises :class:`Neo4jUnavailableError`."""
    from qalpha.live.credentials import load_env

    load_env()
    password = os.environ.get(PASSWORD_VAR, "").strip()
    if not password:
        raise Neo4jUnavailableError(f"{PASSWORD_VAR} is not set in .env")
    module = _driver_module()
    uri = os.environ.get(URI_VAR, "").strip() or DEFAULT_URI
    user = os.environ.get(USER_VAR, "").strip() or "neo4j"
    driver = module.GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
    except Exception as exc:
        driver.close()
        raise Neo4jUnavailableError(f"Neo4j at {uri} is not reachable: {exc}") from exc
    return driver


def _utc(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def _day(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def node_rows(log: g.GraphLog) -> list[dict[str, Any]]:
    """One row per node identity, with the properties of its newest version."""
    newest: dict[str, g.Assertion] = {}
    for a in log.versions.values():
        if a.kind == g.NODE and (
            a.subject not in newest or a.known_from > newest[a.subject].known_from
        ):
            newest[a.subject] = a
    return [
        {
            "id": a.subject,
            "label": a.label,
            "epistemic": a.epistemic,
            "props": json.dumps(dict(a.props), sort_keys=True, default=str),
        }
        for a in newest.values()
    ]


def edge_rows(log: g.GraphLog) -> dict[str, list[dict[str, Any]]]:
    """Every edge version, grouped by relationship type."""
    out: dict[str, list[dict[str, Any]]] = {}
    for a in log.versions.values():
        if a.kind != g.EDGE:
            continue
        out.setdefault(a.label, []).append(
            {
                "id": a.id,
                "from": a.subject,
                "to": a.object,
                "epistemic": a.epistemic,
                "valid_from": _day(a.valid_from),
                "valid_to": _day(a.valid_to),
                "known_from": _utc(a.known_from),
                "known_to": _utc(a.known_to),
                "passage": a.source.get("passage"),
                "doc_sha256": a.source.get("doc_sha256"),
                "props": json.dumps(dict(a.props), sort_keys=True, default=str),
            }
        )
    return out


def sync_statements(log: g.GraphLog) -> list[tuple[str, dict[str, Any]]]:
    """The statements that rebuild the database. Relationship types come only from the schema."""
    statements: list[tuple[str, dict[str, Any]]] = [
        ("MATCH (n) DETACH DELETE n", {}),
        ("CREATE CONSTRAINT node_id IF NOT EXISTS FOR (n:Node) REQUIRE n.id IS UNIQUE", {}),
    ]
    nodes = node_rows(log)
    for i in range(0, len(nodes), BATCH):
        statements.append(
            (
                "UNWIND $rows AS row MERGE (n:Node {id: row.id}) "
                "SET n.label = row.label, n.epistemic = row.epistemic, n.props = row.props",
                {"rows": nodes[i : i + BATCH]},
            )
        )
    for rel, rows in sorted(edge_rows(log).items()):
        if rel not in g.EDGE_TYPES:
            raise g.GraphError(f"refusing to write unknown relationship {rel!r}")
        for i in range(0, len(rows), BATCH):
            statements.append(
                (
                    "UNWIND $rows AS row MERGE (a:Node {id: row.from}) MERGE (b:Node {id: row.to}) "
                    f"CREATE (a)-[r:{rel}]->(b) "
                    "SET r.id = row.id, r.epistemic = row.epistemic, r.valid_from = row.valid_from, "
                    "r.valid_to = row.valid_to, r.known_from = row.known_from, r.known_to = row.known_to, "
                    "r.passage = row.passage, r.doc_sha256 = row.doc_sha256, r.props = row.props",
                    {"rows": rows[i : i + BATCH]},
                )
            )
    return statements


def sync(log: g.GraphLog, driver: Any) -> dict[str, int]:
    """Rebuild the database from the log. Returns what was written."""
    statements = sync_statements(log)
    with driver.session() as session:
        for text, params in statements:
            session.run(text, params).consume()
    return {
        "nodes": len(node_rows(log)),
        "edges": sum(len(r) for r in edge_rows(log).values()),
        "statements": len(statements),
    }


def run(
    driver: Any,
    template: str,
    params: Mapping[str, Any],
    *,
    valid_at: date,
    known_at: datetime,
    classes: Iterable[str] = g.FACTS,
) -> list[dict[str, Any]]:
    """One read-only template, by name, with every value as a parameter."""
    if template not in TEMPLATES:
        raise KeyError(f"no such template {template!r}; choose from {sorted(TEMPLATES)}")
    bound = {
        **dict(params),
        "valid_at": valid_at.isoformat(),
        "known_at": _utc(known_at),
        "classes": list(classes),
    }
    with driver.session(default_access_mode="READ") as session:
        return [dict(record) for record in session.run(TEMPLATES[template], bound)]
