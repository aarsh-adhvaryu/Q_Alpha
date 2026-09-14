"""Phase 2 of the plan: measure every candidate reader on the same filings, before choosing one.

The question is not "which model is best" in general. It is: **on Indian exchange filings, under this
repository's extraction contract, which reader finds the events that should worry a shareholder,
without inventing any, at the lowest cost this laptop or budget can carry?** Benchmarks do not answer
that. The same documents, read by every candidate, scored against a validated reference, do.

This module owns the parts that do not involve the reference model:

* :func:`select_sample` — ~150 archived filings, stratified so the measurement can see the cases that
  matter: routine-looking filings (to test triage), long filings (to test chunking and context), and
  ordinary ones across sectors. Deterministic from a fixed seed, recorded in ``sample.jsonl``.
* :data:`READERS` — the candidates and how each is reached.
* :func:`run_reader` — one candidate over the sample, **resumable per document**, with its usage,
  wall time, and on this machine its peak GPU memory and RAM. Writes to ``runs/<reader>.json`` and
  nothing else: no coverage row, no event in the corpus, no receipt. A comparison is not a reading.

The reference set and its adjudication live in :mod:`qalpha.live.reference`; the scoring, the human
validation and the pre-registered selection rule in :mod:`qalpha.live.reader_scoring`.
"""

from __future__ import annotations

import ctypes
import json
import os
import random
import subprocess
import threading
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qalpha.live import triage

READERS_DIR = Path("data/readers")
SAMPLE_SEED = 20260914
SAMPLE_SIZE = 150

#: How the sample is split. Routine-looking filings are over-represented on purpose: triage can only
#: be trusted if the measurement contains enough of what it proposes to skip.
QUOTA_ROUTINE = 30
QUOTA_LONG = 25
LONG_CHARS = 30_000

#: The local context every local candidate runs at. Advertised maxima are not what this laptop can
#: hold with Neo4j and the evening pipeline beside it; raise only after measuring (plan, Phase 2).
LOCAL_CONTEXT = 16_384


def sample_path() -> Path:
    return READERS_DIR / "sample.jsonl"


def runs_dir() -> Path:
    return READERS_DIR / "runs"


# ---- the sample ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class SampleDoc:
    sha256: str
    symbol: str
    seq_id: str
    subject: str
    chars: int
    sector: str
    group: str  # "routine", "long" or "ordinary"
    triage_rule: str


def _sectors(watchlist: Path) -> dict[str, str]:
    import csv

    if not watchlist.exists():
        return {}
    with watchlist.open(encoding="utf-8", newline="") as fh:
        return {
            str(r["ticker"]).removesuffix(".NS"): str(r.get("sector") or "OTHER")
            for r in csv.DictReader(fh)
        }


def candidates_in_archive(archive: Path, watchlist: Path) -> list[SampleDoc]:
    """Every archived filing with a text layer, described well enough to stratify."""
    import gzip

    sectors = _sectors(watchlist)
    out: list[SampleDoc] = []
    for prov in sorted(archive.glob("*/*.provenance.json")):
        text_file = prov.with_name(prov.name.replace(".provenance.json", ".txt.gz"))
        if not text_file.exists():
            continue  # a scan with no text layer is not a fair test of a text reader
        try:
            meta = json.loads(prov.read_text(encoding="utf-8"))
            with gzip.open(text_file, "rt", encoding="utf-8", errors="replace") as fh:
                chars = len(fh.read())
        except (OSError, ValueError):
            continue
        symbol = str(meta.get("symbol") or prov.parent.name)
        subject = str(meta.get("subject") or "")
        verdict = triage.classify(subject, chars)
        group = "routine" if verdict.routine else ("long" if chars >= LONG_CHARS else "ordinary")
        out.append(
            SampleDoc(
                sha256=str(meta.get("sha256", "")),
                symbol=symbol,
                seq_id=str(meta.get("seq_id") or prov.name.split(".")[0]),
                subject=subject,
                chars=chars,
                sector=sectors.get(symbol, "OTHER"),
                group=group,
                triage_rule=verdict.rule,
            )
        )
    return [d for d in out if d.sha256]


def select_sample(
    pool: Sequence[SampleDoc], *, size: int = SAMPLE_SIZE, seed: int = SAMPLE_SEED
) -> list[SampleDoc]:
    """Stratified and deterministic: quotas per group, sectors taken in turn inside each group.

    Taking sectors in turn is what stops a sample of 150 being 40 filings from the one company that
    files the most.
    """
    rng = random.Random(seed)
    quotas = {"routine": QUOTA_ROUTINE, "long": QUOTA_LONG}
    quotas["ordinary"] = max(0, size - sum(quotas.values()))
    chosen: list[SampleDoc] = []
    for group, quota in quotas.items():
        by_sector: dict[str, list[SampleDoc]] = {}
        for doc in pool:
            if doc.group == group:
                by_sector.setdefault(doc.sector, []).append(doc)
        for docs in by_sector.values():
            docs.sort(key=lambda d: d.sha256)
            rng.shuffle(docs)
        sectors = sorted(by_sector)
        rng.shuffle(sectors)
        picked: list[SampleDoc] = []
        while len(picked) < quota and any(by_sector[s] for s in sectors):
            for sector in sectors:
                if by_sector[sector] and len(picked) < quota:
                    picked.append(by_sector[sector].pop())
        chosen.extend(picked)
    return chosen


def save_sample(docs: Sequence[SampleDoc], path: Path | None = None) -> None:
    from qalpha.live.atomic import write_text

    target = path or sample_path()
    write_text(target, "".join(json.dumps(asdict(d), sort_keys=True) + "\n" for d in docs))


def load_sample(path: Path | None = None) -> list[SampleDoc]:
    target = path or sample_path()
    if not target.exists():
        return []
    return [
        SampleDoc(**json.loads(line))
        for line in target.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_documents(sample: Sequence[SampleDoc]) -> tuple[list[Any], list[str]]:
    """The archived filings, **hash re-verified**. ``(documents, problems)``.

    A document whose bytes no longer match its provenance is left out and named: measuring readers
    on an edited primary source would measure the edit.
    """
    from qalpha.live.announcements import Announcement, SourceDocument, load_document

    docs: list[SourceDocument] = []
    problems: list[str] = []
    for item in sample:
        ann = Announcement(
            symbol=item.symbol,
            seq_id=item.seq_id,
            subject=item.subject,
            summary="",
            disseminated_at=datetime.now(UTC),
            attachment_url="",
        )
        text, prov = load_document(ann)
        if prov is None or not text:
            problems.append(f"{item.symbol}/{item.seq_id}: missing or failed its hash check")
            continue
        if prov.sha256 != item.sha256:
            problems.append(f"{item.symbol}/{item.seq_id}: bytes changed since sampling")
            continue
        docs.append(SourceDocument(announcement=ann, text=text, provenance=prov))
    return docs, problems


# ---- the candidates -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ReaderSpec:
    """One candidate: how it is reached and what it is called there."""

    slug: str
    kind: str  # "local", "anthropic", "deepseek" or "google"
    model: str
    note: str = ""


READERS: dict[str, ReaderSpec] = {
    spec.slug: spec
    for spec in (
        ReaderSpec("qwen3.5-9b-16k", "local", "qwen3.5-9b-16k", "default local candidate"),
        ReaderSpec("gemma4-12b-16k", "local", "gemma4-12b-16k", "closest local comparison"),
        ReaderSpec("qwen3.6-35b-16k", "local", "qwen3.6-35b-16k", "MoE, partly in RAM"),
        ReaderSpec("qwen3.8-27b-16k", "local", "qwen3.8-27b-16k", "partly in RAM, speed unknown"),
        ReaderSpec("qwen3-8b-32k", "local", "qwen3-8b-32k", "baseline already installed"),
        ReaderSpec("claude-haiku-4-5", "anthropic", "claude-haiku-4-5"),
        ReaderSpec("claude-sonnet-5", "anthropic", "claude-sonnet-5", "the EX-3 corpus reader"),
        ReaderSpec("deepseek-flash", "deepseek", "deepseek-flash"),
        ReaderSpec("gemini-3.1-flash-lite", "google", "gemini-3.1-flash-lite"),
    )
}

CLOUD_URLS = {
    "deepseek": "https://api.deepseek.com/chat/completions",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
}
CLOUD_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "google": "GEMINI_API_KEY",
}

#: The one-time research job every paid reader run is charged to, with a ceiling set on the command
#: line. See :mod:`qalpha.live.spend`.
READERS_JOB = "ex5-reader-runs"


@dataclass
class Backend:
    generate: Any
    batch_chars: int
    identity: dict[str, str]


def backend_for(spec: ReaderSpec, *, ledger: Any = None) -> Backend:
    """Build the reader, or raise ``RuntimeError`` saying exactly why it cannot be built.

    Local readers are **not** required to be pinned here — pinning follows measurement — but the
    digest served during the run is recorded, so the result names the exact weights measured.
    """
    from qalpha.live import localmodel, spend
    from qalpha.live.credentials import load_env
    from qalpha.live.extraction import PROMPT_CHAR_BUDGET

    load_env()
    if spec.kind == "local":
        from qalpha.live.model_identity import ollama_digests

        url = os.environ.get(localmodel.URL_VAR, "").strip() or localmodel.DEFAULT_URL
        why = localmodel.probe(url, model=spec.model)
        if why:
            raise RuntimeError(f"{spec.model} cannot be used: {why}")
        digest = ollama_digests(url).get(spec.model) or ollama_digests(url).get(
            f"{spec.model}:latest", ""
        )
        return Backend(
            localmodel.local_generate(url),
            min(localmodel.budget_for(LOCAL_CONTEXT), PROMPT_CHAR_BUDGET),
            {"url": url, "digest": digest, "context": str(LOCAL_CONTEXT)},
        )
    key_var = CLOUD_KEYS[spec.kind]
    key = os.environ.get(key_var, "").strip()
    if not key:
        raise RuntimeError(f"{key_var} is not set, so {spec.slug} cannot be read")
    if spec.kind == "anthropic":
        from qalpha.live.extraction import default_generate

        return Backend(
            default_generate(key, partition=spend.RESEARCH, ledger=ledger),
            PROMPT_CHAR_BUDGET,
            {"provider": "anthropic"},
        )
    return Backend(
        localmodel.cloud_generate(
            CLOUD_URLS[spec.kind], api_key=key, partition=spend.RESEARCH, ledger=ledger
        ),
        PROMPT_CHAR_BUDGET,
        {"provider": spec.kind, "url": CLOUD_URLS[spec.kind]},
    )


# ---- measuring this machine ---------------------------------------------------------------------


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def ram_used_mb() -> int | None:
    """System RAM in use, from Windows itself. ``None`` elsewhere — unknown, not zero."""
    if os.name != "nt":
        return None
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(_MemoryStatus)
    # Looked up at run time: ``ctypes.windll`` exists only on Windows, and CI type-checks on Linux.
    kernel32 = getattr(ctypes, "windll").kernel32  # noqa: B009
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int((status.ullTotalPhys - status.ullAvailPhys) // (1024 * 1024))


def vram_used_mb() -> int | None:
    """GPU memory in use, from ``nvidia-smi``. ``None`` when there is no NVIDIA driver to ask."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
        return int(out.splitlines()[0]) if out else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


@dataclass
class ResourceSampler:
    """Samples GPU memory and RAM every ``interval`` seconds while a run is in progress.

    The baseline is taken before the first call, so the report can say what the reader added on top
    of everything else running — Neo4j, the browser, the pipeline — which is the figure that decides
    whether it fits beside them.
    """

    interval: float = 2.0
    baseline_vram: int | None = None
    baseline_ram: int | None = None
    peak_vram: int | None = None
    peak_ram: int | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def __enter__(self) -> ResourceSampler:
        self.baseline_vram, self.baseline_ram = vram_used_mb(), ram_used_mb()
        self.peak_vram, self.peak_ram = self.baseline_vram, self.baseline_ram
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            v, r = vram_used_mb(), ram_used_mb()
            if v is not None:
                self.peak_vram = max(self.peak_vram or 0, v)
            if r is not None:
                self.peak_ram = max(self.peak_ram or 0, r)

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval * 3)

    def summary(self) -> dict[str, int | None]:
        return {
            "baseline_vram_mb": self.baseline_vram,
            "peak_vram_mb": self.peak_vram,
            "baseline_ram_mb": self.baseline_ram,
            "peak_ram_mb": self.peak_ram,
        }


# ---- one reader over the sample -----------------------------------------------------------------


def run_path(slug: str) -> Path:
    return runs_dir() / f"{slug}.json"


def load_run(slug: str) -> dict[str, Any]:
    path = run_path(slug)
    if not path.exists():
        return {"reader": slug, "events": [], "done": [], "segments": []}
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _save_run(run: dict[str, Any]) -> None:
    from qalpha.live.atomic import write_text

    write_text(run_path(str(run["reader"])), json.dumps(run, indent=1, sort_keys=True) + "\n")


def event_row(event: Any) -> dict[str, Any]:
    return {
        "doc_sha256": event.doc_sha256,
        "ticker": event.ticker,
        "event_type": event.event_type,
        "materiality": event.materiality,
        "passage": event.passage,
        "summary": event.summary,
        "verified": bool(event.verified),
    }


def run_reader(
    spec: ReaderSpec,
    documents: Sequence[Any],
    *,
    backend: Backend,
    workers: int = 1,
    progress: Any = None,
) -> dict[str, Any]:
    """Read every not-yet-read sample document with one candidate. Resumes where it stopped.

    Each finished document is written the moment its last batch lands, so an interruption — a spent
    budget, a closed laptop — loses at most the documents in flight, and a rerun reads only the rest.
    """
    from qalpha.live import spend
    from qalpha.live.extraction import extract

    run = load_run(spec.slug)
    run.update({"reader": spec.slug, "kind": spec.kind, "model": spec.model})
    done = set(run.get("done", []))
    todo = [d for d in documents if d.provenance.sha256 not in done]
    if not todo:
        return run

    def checkpoint(fresh: Sequence[Any], finished: frozenset[str]) -> None:
        run["events"].extend(event_row(e) for e in fresh)
        run["done"] = sorted(set(run["done"]) | set(finished))
        _save_run(run)

    started = datetime.now(UTC)
    wall = time.monotonic()
    stop: str | None = None
    with ResourceSampler() as sampler:
        try:
            result = extract(
                todo,
                generate=backend.generate,
                model=spec.model,
                batch_chars=backend.batch_chars,
                workers=workers,
                progress=progress,
                checkpoint=checkpoint,
            )
            usage = dict(result.usage)
            discarded = result.discarded
            unread = sorted(result.unread)
        except spend.SpendStopError as exc:  # pragma: no cover - extract is fail-soft per batch
            usage, discarded, unread, stop = {}, 0, [], str(exc)
    seconds = time.monotonic() - wall
    output = int(usage.get("output", 0))
    usd = "0"
    if spec.kind != "local" and usage:
        try:
            usd = str(
                spend.cost(spec.model, int(usage.get("input", 0)), output, at=datetime.now(UTC))
            )
        except spend.SpendStopError:
            usd = "unknown"
    run.setdefault("segments", []).append(
        {
            "started": started.isoformat(timespec="seconds"),
            "seconds": round(seconds, 1),
            "documents": len(todo),
            "usage": usage,
            "discarded": discarded,
            "unread": unread,
            "usd": usd,
            "stopped": stop,
            "identity": backend.identity,
            "batch_chars": backend.batch_chars,
            "tokens_per_second": round(output / seconds, 2) if seconds > 0 else None,
            **sampler.summary(),
        }
    )
    _save_run(run)
    return run
