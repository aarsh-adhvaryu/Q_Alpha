"""Headlines as evidence: archived first, read locally, and never more than a flag (`NEWS-1`).

Rules frozen in ``reports/PREREGISTRATION_NEWS_V1.md`` **before the first feed was archived**.

### Why a system that reads filings needs headlines at all

Filings are the primary record and they arrive late. A regulator's order, a rating action or a
governance failure is usually *reported* before the company discloses it — and the screen this
system runs buys names that have already fallen, which is exactly the population where the reason
for the fall is the thing worth knowing. `announcements.py` reads what the company said; this reads
what was said about the company, one step further from the source and labelled that way everywhere.

### What makes a headline usable as evidence rather than as noise

The same machinery that made filings usable, and for the same reason: **the bytes are kept before
anything reads them, and every claim carries a quote that is checked against those bytes.** A
headline the model paraphrased, attributed to the wrong company, or invented is discarded
mechanically — :func:`~qalpha.live.extraction.verify_passage` does not care how plausible it looked.

Three things this module refuses to do, each a decision recorded in the pre-registration:

**It does not read the article.** Only the headline and the feed's own summary. Google News carries
no description at all, so a passage from there can only be its title. A snippet is thin evidence,
which is why it can only ever flag.

**It does not compute a sentiment number.** The surface says *3 negative / 1 positive
high-materiality items in 7 days*. A score in [0, 1] would invite being ranked and optimised
against, and an 8B model labelling headlines has earned none of that.

**It cannot exclude a name.** Only NSE's published lists do that, asserted in
:func:`qalpha.live.pretrade.assess_candidate`. A model's reading of a headline is the weakest
evidence here and gets the weakest power.
"""

from __future__ import annotations

import csv
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

from qalpha.live.announcements import USER_AGENT, FetchFn
from qalpha.live.evidence import Provenance, sha256_of
from qalpha.live.extraction import (
    EVENT_TYPES,
    MATERIALITY,
    MATERIALITY_RUBRIC,
    GenerateFn,
    normalise,
    parse_fields,
    verify_passage,
)

#: Bump on any change to the feed list, the prompt, the parser, the mapping rule or the policy that
#: acts on these rows. One label spanning two rules makes every row under it unusable — that has
#: already cost this project the first four days of a forward run.
NEWS_VERSION = "NEWS-1"

NEWS_DIR = Path("data/evidence/news")
NEWS_EVENTS = Path("data/evidence/news_events.jsonl")
NEWS_RECEIPTS = Path("data/evidence/news_extracted.jsonl")
ALIASES = Path("data/universes/nifty100_aliases.csv")

#: A feed whose newest item is older than this is **stale**, which is UNKNOWN for the day rather
#: than a quiet news day. Moneycontrol's feeds answer 200 and are three years dead.
STALE_AFTER_DAYS = 30

#: How far back an item still counts as something to show beside a name. The archive keeps the rest.
LOOKBACK_DAYS = 7

#: Snippet characters per model call. Far smaller than a filing batch: these are one or two
#: sentences each, and a batch of twenty is still a short prompt.
PROMPT_CHAR_BUDGET = 12_000

#: Headlines per call, **and this is the binding constraint, not the character budget.**
#:
#: A filing batch is limited by what fits the model's context; a headline batch is limited by what
#: the REPLY can hold. Twenty snippets is a short prompt and a long answer — one line per item, and
#: the first archived run cut two names off at ``max_tokens`` with 60 and 72 items in a call, which
#: counts as a failed read and covered neither name. Twenty lines fits 3,000 tokens with room over.
MAX_ITEMS_PER_CALL = 20

#: The stance vocabulary. Anything else is coerced to ``neutral``, which never flags.
STANCE = ("negative", "neutral", "positive")

_NEWS_PREFIX = "NEWS:"


@dataclass(frozen=True)
class Feed:
    """One source: an id that names its archive file, a URL, and what it covers."""

    id: str
    url: str
    #: ``market`` — the day's market news. ``name`` — one company, from a search.
    kind: str = "market"
    ticker: str = ""


#: The four that answered from this machine on 2026-09-10, in the shape the pre-registration records.
#: Moneycontrol is excluded: both its feeds answer 200 with items from April 2024.
MARKET_FEEDS: tuple[Feed, ...] = (
    Feed("et-stocks", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
    Feed("et-markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    Feed("mint-markets", "https://www.livemint.com/rss/markets"),
    Feed("bs-markets", "https://www.business-standard.com/rss/markets-106.rss"),
)


def google_news_feed(ticker: str, alias: str, *, days: int = LOOKBACK_DAYS) -> Feed:
    """A search feed for one name. **In-scope names only** — never the whole watchlist.

    Google News answers with titles and a source, and no article text, so what it contributes is a
    headline and a link. The link is a ``news.google.com`` redirect to a JavaScript page: it is
    recorded so a reader can follow it, and it is never fetched.
    """
    from urllib.parse import quote_plus

    query = quote_plus(f'"{alias}" when:{days}d')
    bare = ticker.removesuffix(".NS").lower()
    return Feed(
        id=f"gnews-{bare}",
        url=f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en",
        kind="name",
        ticker=ticker,
    )


# --- the items -------------------------------------------------------------------------------------


class _Stripper(HTMLParser):
    """Feed descriptions carry markup — an ``<img>`` tag, a list of ``<a>`` links, escaped entities.

    The quote a model returns has to verify against the text we stored, so the stripping happens
    **once, before archiving the parsed item**, and both sides then see the same characters.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.parts)).strip()


def strip_html(raw: str) -> str:
    """Plain text from a feed's description. Never raises — a malformed fragment is still text."""
    stripper = _Stripper()
    try:
        stripper.feed(unescape(raw))
        stripper.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", unescape(raw)).strip()
    return stripper.text()


@dataclass(frozen=True)
class NewsItem:
    """One headline, its provenance, and the names it was mapped to. Snippet only, never an article."""

    id: str
    feed_id: str
    feed_sha256: str
    title: str
    link: str
    published_at: datetime
    source: str = ""
    description: str = ""
    tickers: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        """What the model is shown and what a quote is verified against — the same string."""
        return f"{self.title} — {self.description}" if self.description else self.title

    def render(self) -> str:
        return f"{self.published_at:%Y-%m-%d} · {self.source or self.feed_id} · {self.title}"


def _item_id(feed_id: str, link: str, title: str) -> str:
    return sha256_of(f"{feed_id}|{link}|{title}".encode())[:16]


def _parse_when(raw: str) -> datetime | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def _text_of(node: ET.Element | None) -> str:
    return "".join(node.itertext()).strip() if node is not None else ""


def parse_feed(payload: bytes, *, feed_id: str, feed_sha256: str = "") -> list[NewsItem]:
    """Items from an RSS 2.0 or Atom body, newest first. Malformed XML yields ``[]``, never raises.

    **An item the feed did not date is dropped, never dated by us** — the rule
    :func:`qalpha.live.announcements.parse_index` follows, for the same reason: something that cannot
    be ordered against a price cannot support a claim about what was knowable when, and stamping it
    with today would make three-year-old news look current.
    """
    try:
        root = ET.fromstring(payload.decode("utf-8", errors="replace"))
    except ET.ParseError:
        return []

    nodes = root.findall(".//item")
    atom = "{http://www.w3.org/2005/Atom}"
    if not nodes:
        nodes = root.findall(f".//{atom}entry")

    out: list[NewsItem] = []
    for node in nodes:
        title = _text_of(node.find("title")) or _text_of(node.find(f"{atom}title"))
        link = _text_of(node.find("link")) or _text_of(node.find("guid"))
        if not link:
            anchor = node.find(f"{atom}link")
            link = anchor.get("href", "") if anchor is not None else ""
        when = _parse_when(
            _text_of(node.find("pubDate"))
            or _text_of(node.find(f"{atom}updated"))
            or _text_of(node.find(f"{atom}published"))
        )
        if when is None or not title:
            continue
        source = _text_of(node.find("source"))
        # GOOGLE NEWS APPENDS " - Publisher" TO EVERY TITLE, and also supplies <source>. Left on,
        # the publisher's name is inside the verbatim quote an event row carries — so the archived
        # snippet reads "Sebi bars X - Business Standard" and the flag quotes a masthead as if it
        # were part of the story. Split it off; keep the publisher, because who reported it is part
        # of what a later reader needs to weigh the item.
        if " - " in title:
            head, _, tail = title.rpartition(" - ")
            if head and (tail == source or (not source and len(tail) < 40)):
                title, source = head, source or tail
        description = strip_html(
            _text_of(node.find("description")) or _text_of(node.find(f"{atom}summary"))
        )
        # A DESCRIPTION THAT IS THE HEADLINE AGAIN ADDS NOTHING AND COSTS SOMETHING. Google News
        # sends the title back as an <a> link followed by the publisher, so the stored snippet would
        # read "Varun Beverages hit by excise notice Business Standard" — and a model could then
        # quote a masthead as part of the event. Dropped when, publisher aside, one contains the
        # other; kept whenever it says something the headline does not.
        trimmed = normalise(description)
        if source:
            trimmed = trimmed.replace(normalise(source), "").strip()
        if trimmed and (trimmed in normalise(title) or normalise(title) in trimmed):
            description = ""
        out.append(
            NewsItem(
                id=_item_id(feed_id, link, title),
                feed_id=feed_id,
                feed_sha256=feed_sha256,
                title=title,
                link=link,
                published_at=when,
                source=source,
                description=description,
            )
        )
    out.sort(key=lambda i: i.published_at, reverse=True)
    return out


# --- the archive -------------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedArchive:
    """One feed's response, kept, plus what was in it."""

    feed: Feed
    provenance: Provenance
    items: tuple[NewsItem, ...]

    def stale(self, as_of: date, *, days: int = STALE_AFTER_DAYS) -> bool:
        """Is the newest item too old for this feed to speak for today?

        An empty feed is stale by this test, which is correct: a source that returns nothing is a
        source that told us nothing, and that is not the same as a quiet day.
        """
        if not self.items:
            return True
        return (as_of - self.items[0].published_at.date()).days > days


def feed_paths(feed: Feed, as_of: date, *, directory: Path = NEWS_DIR) -> tuple[Path, Path]:
    base = directory / as_of.isoformat()
    return base / f"{feed.id}.xml", base / f"{feed.id}.provenance.json"


def write_feed(
    payload: bytes,
    feed: Feed,
    as_of: date,
    *,
    http_status: int,
    retrieved_at_utc: datetime | None = None,
    directory: Path = NEWS_DIR,
) -> Provenance:
    """Persist the response exactly as served, plus provenance, **before anything parses it**."""
    xml_path, prov_path = feed_paths(feed, as_of, directory=directory)
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.write_bytes(payload)
    prov = Provenance(
        source_url=feed.url,
        retrieved_at_utc=retrieved_at_utc or datetime.now(UTC),
        http_status=http_status,
        sha256=sha256_of(payload),
        byte_length=len(payload),
        document_date=as_of,
    )
    prov_path.write_text(
        json.dumps(
            {
                "source_url": prov.source_url,
                "retrieved_at_utc": prov.retrieved_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "http_status": prov.http_status,
                "bytes": prov.byte_length,
                "sha256": prov.sha256,
                "document_date": prov.document_date.isoformat(),
                "feed": feed.id,
                "kind": feed.kind,
                "ticker": feed.ticker,
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    return prov


def _urlopen_fetch(url: str, *, timeout: float = 20.0) -> tuple[int, bytes]:
    """``(status, body)``. Business Standard 403s without a browser agent; the rest do not care."""
    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, */*"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), bytes(response.read())
    except urllib.error.HTTPError as exc:
        return int(exc.code), b""
    except Exception:
        return 0, b""


def fetch_and_archive_feed(
    feed: Feed,
    as_of: date,
    *,
    fetch: FetchFn | None = None,
    directory: Path = NEWS_DIR,
) -> FeedArchive | None:
    """Fetch one feed and keep the bytes. ``None`` means the fetch failed — never an empty feed.

    A failed fetch and an empty feed are different facts, and collapsing them is how "we could not
    look" becomes "there was nothing to find".
    """
    status, body = (fetch or _urlopen_fetch)(feed.url)
    if status != 200 or not body:
        return None
    prov = write_feed(body, feed, as_of, http_status=status, directory=directory)
    items = parse_feed(body, feed_id=feed.id, feed_sha256=prov.sha256)
    return FeedArchive(feed=feed, provenance=prov, items=tuple(items))


def items_path(as_of: date, *, directory: Path = NEWS_DIR) -> Path:
    return directory / as_of.isoformat() / "items.jsonl"


def write_items(items: Sequence[NewsItem], as_of: date, *, directory: Path = NEWS_DIR) -> Path:
    """Keep the snippets, not only the feed bytes.

    The XML is gitignored: it is large, it is a day's whole feed, and most of it is about companies
    nobody here holds. **The item text is what a later reader needs** — an event row quotes it, and a
    quote that cannot be checked against anything is not evidence. Small, and tracked.
    """
    path = items_path(as_of, directory=directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(
                {
                    "id": i.id,
                    "feed_id": i.feed_id,
                    "feed_sha256": i.feed_sha256,
                    "title": i.title,
                    "link": i.link,
                    "published_at": i.published_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "source": i.source,
                    "description": i.description,
                    "tickers": list(i.tickers),
                },
                ensure_ascii=False,
            )
            + "\n"
            for i in items
        ),
        encoding="utf-8",
    )
    return path


def read_items(as_of: date, *, directory: Path = NEWS_DIR) -> list[NewsItem]:
    """The day's archived snippets. Missing file → ``[]``, never an exception."""
    path = items_path(as_of, directory=directory)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[NewsItem] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            when = datetime.strptime(str(row["published_at"]), "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=UTC
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        out.append(
            NewsItem(
                id=str(row.get("id", "")),
                feed_id=str(row.get("feed_id", "")),
                feed_sha256=str(row.get("feed_sha256", "")),
                title=str(row.get("title", "")),
                link=str(row.get("link", "")),
                published_at=when,
                source=str(row.get("source", "")),
                description=str(row.get("description", "")),
                tickers=tuple(str(t) for t in row.get("tickers", ())),
            )
        )
    return out


# --- which company is this about ------------------------------------------------------------------


def load_aliases(path: Path = ALIASES) -> dict[str, tuple[str, ...]]:
    """``{ticker: (alias, ...)}``. Missing file → ``{}``, and then nothing maps and coverage says so."""
    if not path.exists():
        return {}
    out: dict[str, tuple[str, ...]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            ticker = (row.get("ticker") or "").strip()
            aliases = [a.strip() for a in (row.get("aliases") or "").split("|") if a.strip()]
            if ticker and aliases:
                out[ticker] = tuple(aliases)
    return out


def map_tickers(text: str, aliases: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    """Which names this snippet is about, by whole-word alias match.

    **Family names map to nothing, deliberately.** "Adani" is eight listed companies and "Tata" is a
    dozen; a flag on the wrong company is worse than a missed item, and a missed item is a gap the
    coverage row reports. The alias table carries only full names and unambiguous short ones.

    Whole-word, so ``Trent Ltd`` does not match "current" and ``HAL`` does not match "halted".
    """
    hay = text.lower()
    found: list[str] = []
    for ticker, names in aliases.items():
        for alias in names:
            needle = alias.lower()
            if needle in hay and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", hay):
                found.append(ticker)
                break
    return tuple(sorted(found))


def map_items(items: Iterable[NewsItem], aliases: dict[str, tuple[str, ...]]) -> list[NewsItem]:
    """Attach the names to each item. The mapper is the floor: the model cannot widen this."""
    from dataclasses import replace

    return [replace(i, tickers=map_tickers(i.text, aliases)) for i in items]


# --- what the model is asked, and what survives ----------------------------------------------------


@dataclass(frozen=True)
class NewsEvent:
    """One thing a headline says about one company, with the quote that says it."""

    ticker: str
    item_id: str
    event_type: str
    stance: str
    materiality: str
    passage: str
    summary: str
    link: str
    source: str
    published_at: datetime
    feed_id: str
    feed_sha256: str
    model: str
    news_version: str = NEWS_VERSION
    verified: bool = False

    @property
    def flags(self) -> bool:
        """Only a high-materiality NEGATIVE item is worth putting in front of a buy decision."""
        return self.verified and self.materiality == "high" and self.stance == "negative"


def build_news_prompt(items: Sequence[NewsItem]) -> str:
    """Ask what each headline says about the company it is about. Same rubric as the filing reader."""
    header = (
        "You are reading news headlines about Indian listed companies (NSE).\n\n"
        "Report what each headline says. DO NOT recommend, rank, rate, or advise, and do not say "
        "whether a stock should be bought, held or sold — that decision is made elsewhere by rules, "
        "and an opinion here would be discarded.\n\n"
        + MATERIALITY_RUBRIC
        + "STANCE is the direction of the item FOR SOMEONE WHO OWNS THE SHARES, as the headline "
        "states it — not your forecast of the price:\n"
        "  negative — the item describes something bad for the company\n"
        "  neutral  — descriptive, procedural, or about the market rather than this company\n"
        "  positive — the item describes something good for the company\n\n"
        "**A PRICE MOVE IS NOT AN EVENT.** 'Shares fall 5%', 'stock hits 52-week low', 'rallies on "
        "volumes' — the system already measures prices, and it selected these names BECAUSE they "
        "fell. Rate any headline that is only about the share price 'low' materiality.\n\n"
        "For every headline that says something material, emit one line in EXACTLY this format:\n\n"
        "NEWS: ticker=<SYMBOL>; item=<ID>; type=<TYPE>; stance=<negative|neutral|positive>; "
        'materiality=<high|medium|low>; passage="<VERBATIM QUOTE FROM THE HEADLINE>"; '
        "summary=<one clause>\n\n"
        f"TYPE must be one of: {', '.join(EVENT_TYPES)}\n\n"
        "RULES, which are the part that matters:\n"
        "- Use the ID and the SYMBOL exactly as given for that headline. A headline is listed with "
        "the companies it is about; you cannot report it against any other company, and a line "
        "naming one is discarded.\n"
        "- The quote must be copied VERBATIM from that headline's text below. It is checked against "
        "the stored text automatically; an invented or paraphrased quote is discarded.\n"
        "- At least 20 characters.\n"
        "- If a headline says nothing material about the company, emit no line for it. Silence is a "
        "valid answer and is preferred over a weak event.\n\n"
    )
    body = []
    for item in items:
        body.append(
            f"--- HEADLINE {item.id} ---\n"
            f"companies: {', '.join(t.removesuffix('.NS') for t in item.tickers)}\n"
            f"published: {item.published_at:%Y-%m-%d %H:%M}\n"
            f"source: {item.source or item.feed_id}\n"
            f"text:\n{item.text}\n"
        )
    return header + "\n".join(body)


def batch_items(
    items: Sequence[NewsItem],
    *,
    budget: int = PROMPT_CHAR_BUDGET,
    max_items: int = MAX_ITEMS_PER_CALL,
) -> list[list[NewsItem]]:
    """Pack snippets into calls. One item never spans two calls; a giant one gets its own.

    **Two limits, and the count is usually the binding one.** The prompt has to fit the context and
    the reply has to fit ``max_tokens`` — one line per item — so a call carrying seventy headlines
    is a short prompt that cannot be answered inside the cap.
    """
    batches: list[list[NewsItem]] = []
    current: list[NewsItem] = []
    used = 0
    for item in items:
        size = len(item.text)
        if current and (used + size > budget or len(current) >= max_items):
            batches.append(current)
            current, used = [], 0
        current.append(item)
        used += size
    if current:
        batches.append(current)
    return batches


def parse_news_lines(
    text: str, items: Sequence[NewsItem], *, model: str
) -> tuple[list[NewsEvent], int]:
    """Parse ``NEWS:`` lines into events, verifying every one. Returns ``(kept, discarded)``.

    Three guards, and a line has to pass all of them:

    1. **the item must have been in this batch** — the model cannot report on something it was not
       shown, and cannot invent an id;
    2. **the ticker must be one the MAPPER assigned to that item** — the deterministic alias table
       is the floor, so a headline about one company can never be filed against another;
    3. **the quote must be in that item's archived text** — checked by the same verifier the filing
       reader uses, against the same stored characters the prompt was built from.
    """
    by_id = {i.id: i for i in items}
    kept: list[NewsEvent] = []
    discarded = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(_NEWS_PREFIX):
            continue
        f = parse_fields(stripped, prefix=_NEWS_PREFIX)
        item = by_id.get(f.get("item", "").strip())
        if item is None:
            discarded += 1
            continue
        ticker = f.get("ticker", "").upper().removesuffix(".NS")
        match = next((t for t in item.tickers if t.removesuffix(".NS") == ticker), None)
        if match is None:
            discarded += 1  # the mapper did not put this name on this headline
            continue
        passage = f.get("passage", "")
        if not verify_passage(passage, item.text):
            discarded += 1
            continue
        event_type = f.get("type", "").lower()
        stance = f.get("stance", "").lower()
        materiality = f.get("materiality", "").lower()
        kept.append(
            NewsEvent(
                ticker=match,
                item_id=item.id,
                event_type=event_type if event_type in EVENT_TYPES else "other",
                stance=stance if stance in STANCE else "neutral",
                materiality=materiality if materiality in MATERIALITY else "low",
                passage=passage.strip()[:1000],
                summary=f.get("summary", "")[:300],
                link=item.link,
                source=item.source,
                published_at=item.published_at,
                feed_id=item.feed_id,
                feed_sha256=item.feed_sha256,
                model=model,
                verified=True,
            )
        )
    return kept, discarded


def read_news(
    items: Sequence[NewsItem],
    *,
    generate: GenerateFn,
    model: str,
    batch_chars: int = PROMPT_CHAR_BUDGET,
) -> tuple[list[NewsEvent], int, str, dict[str, int]]:
    """Read every mapped snippet. ``(events, discarded, raw, usage)``.

    Fail-soft per batch, and **truncation counts as failure** — exactly as in
    :func:`qalpha.live.extraction.extract`, because a reply cut off at the token cap has items after
    the cut that were sent and never reported on, while coverage would count them read.
    """
    usage: dict[str, int] = {
        "input": 0,
        "output": 0,
        "calls": 0,
        "failed_batches": 0,
        "truncated_batches": 0,
    }
    mapped = [i for i in items if i.tickers]
    if not mapped:
        return [], 0, "", usage
    events: list[NewsEvent] = []
    discarded = 0
    raws: list[str] = []
    for batch in batch_items(mapped, budget=batch_chars):
        try:
            raw, call_usage = generate(model, build_news_prompt(batch))
        except Exception as exc:
            raws.append(f"news extraction failed: {exc}")
            usage["failed_batches"] += 1
            continue
        raws.append(raw)
        usage["calls"] += 1
        for field in ("input", "output"):
            usage[field] += int(call_usage.get(field, 0))
        if call_usage.get("truncated"):
            usage["truncated_batches"] += 1
            usage["failed_batches"] += 1
        found, dropped = parse_news_lines(raw, batch, model=model)
        events.extend(found)
        discarded += dropped
    seen: set[tuple[str, str, str]] = set()
    unique: list[NewsEvent] = []
    for event in events:
        key = (event.ticker, event.item_id, normalise(event.passage))
        if key not in seen:
            seen.add(key)
            unique.append(event)
    return unique, discarded, "\n\n".join(raws), usage


def news_rows(events: Sequence[NewsEvent], *, as_of: date) -> list[dict[str, object]]:
    """Append-only rows, keyed so a re-run corrects rather than duplicates."""
    import hashlib

    return [
        {
            "as_of": as_of.isoformat(),
            "ticker": e.ticker,
            "item_id": e.item_id,
            "event_type": e.event_type,
            "stance": e.stance,
            "materiality": e.materiality,
            "passage": e.passage,
            "summary": e.summary,
            "link": e.link,
            "source": e.source,
            "published_at": e.published_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "feed_id": e.feed_id,
            "feed_sha256": e.feed_sha256,
            "model": e.model,
            "news_version": e.news_version,
            "verified": e.verified,
            "kind": "news",
            "_key": (
                f"{e.item_id}:{e.ticker}:{e.event_type}:"
                f"{hashlib.sha256(normalise(e.passage).encode()).hexdigest()[:8]}"
            ),
        }
        for e in events
    ]


def market_headlines(as_of: date, *, limit: int = 60, directory: Path = NEWS_DIR) -> list[NewsItem]:
    """The day's market-level snippets, newest first — what the local brief is written from.

    Market feeds only: a per-name search returns the same story from six outlets and would crowd the
    prompt with one company's coverage.
    """
    market = {f.id for f in MARKET_FEEDS}
    items = [i for i in read_items(as_of, directory=directory) if i.feed_id in market]
    return items[:limit]
