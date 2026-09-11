"""Headlines as evidence — archived first, quoted verbatim, and never more than a flag.

Rules in ``reports/PREREGISTRATION_NEWS_V1.md``, frozen before the first feed was archived. What is
pinned here is what makes a snippet usable as evidence rather than as atmosphere: the bytes are kept
before anything reads them, an undated item is dropped rather than dated by us, a dead feed is a gap
rather than a quiet day, the alias table is the floor the model cannot widen, and a quote that is not
in the archived text is discarded however plausible it looked.

Fixtures are trimmed from the real responses of 2026-09-10. **No test here touches a network.**
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from qalpha.live import news
from qalpha.live.news import (
    NEWS_VERSION,
    Feed,
    NewsItem,
    batch_items,
    build_news_prompt,
    fetch_and_archive_feed,
    google_news_feed,
    load_aliases,
    map_items,
    map_tickers,
    news_rows,
    parse_feed,
    parse_news_lines,
    read_items,
    read_news,
    strip_html,
    write_items,
)

AS_OF = date(2026, 9, 10)

# Economic Times: CDATA title, a plain-text summary, +0530 dates.
ET = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
 <title>ET Markets</title>
 <item>
  <title><![CDATA[Sebi bars Torrent Pharmaceuticals promoter from the securities market]]></title>
  <link>https://economictimes.indiatimes.com/markets/stocks/news/x/articleshow/1.cms</link>
  <description><![CDATA[The regulator passed an interim order restraining the promoter, citing
  disclosure lapses over three years.]]></description>
  <pubDate>Thu, 10 Sep 2026 14:12:00 +0530</pubDate>
 </item>
 <item>
  <title><![CDATA[Tata Steel shares fall 5% on weak China demand]]></title>
  <link>https://economictimes.indiatimes.com/markets/stocks/news/y/articleshow/2.cms</link>
  <description><![CDATA[The stock was among the top Nifty losers.]]></description>
  <pubDate>Thu, 10 Sep 2026 11:00:00 +0530</pubDate>
 </item>
</channel></rss>
"""

# Google News: no description text, a " - Publisher" suffix, a redirect link.
GNEWS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
 <item>
  <title>Varun Beverages hit by excise notice in Rajasthan - Business Standard</title>
  <link>https://news.google.com/rss/articles/CBMiWkFVX3lxTE01</link>
  <guid>CBMiWkFVX3lxTE01</guid>
  <pubDate>Wed, 09 Sep 2026 06:30:00 GMT</pubDate>
  <source url="https://www.business-standard.com">Business Standard</source>
  <description>&lt;a href="https://news.google.com/x"&gt;Varun Beverages hit by excise notice&lt;/a&gt;
  &amp;nbsp;&lt;font color="#6f6f6f"&gt;Business Standard&lt;/font&gt;</description>
 </item>
</channel></rss>
"""

# Moneycontrol: answers 200, and its newest item is from 2024.
DEAD = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
 <item><title>Market close</title><link>http://x/1</link>
 <pubDate>Tue, 23 Apr 2024 16:00:00 +0530</pubDate></item>
</channel></rss>
"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <entry>
  <title>Cipla recalls a batch from the US market</title>
  <link href="https://example.com/cipla"/>
  <updated>2026-09-10T09:00:00Z</updated>
  <summary>The recall covers one lot, the company told the exchange.</summary>
 </entry>
</feed>
"""

UNDATED = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
 <item><title>Something happened to Infosys today</title><link>http://x/2</link></item>
</channel></rss>
"""


def _fetch(payload: bytes, status: int = 200):
    return lambda url: (status, payload)


# --- parsing the shapes that actually arrive --------------------------------------------------------
def test_an_et_item_parses_with_its_summary() -> None:
    items = parse_feed(ET, feed_id="et-stocks")
    assert len(items) == 2
    first = items[0]
    assert first.title.startswith("Sebi bars Torrent")
    assert "interim order" in first.description
    assert first.published_at.date() == date(2026, 9, 10)
    assert items[0].published_at > items[1].published_at, "newest first"


def test_an_atom_entry_parses_too() -> None:
    items = parse_feed(ATOM, feed_id="atom")
    assert len(items) == 1
    assert items[0].title.startswith("Cipla recalls")
    assert items[0].link == "https://example.com/cipla"
    assert "one lot" in items[0].description


def test_google_news_title_suffix_becomes_the_source() -> None:
    """Every Google title ends ' - Publisher'. Left on, the quote carries the publisher's name and
    the model is invited to treat it as part of the story."""
    item = parse_feed(GNEWS, feed_id="gnews-vbl")[0]
    assert item.title == "Varun Beverages hit by excise notice in Rajasthan"
    assert item.source == "Business Standard"


def test_markup_and_entities_are_stripped_before_anything_stores_them() -> None:
    """The quote a model returns is verified against what we stored, so both must see one string."""
    assert strip_html('<a href="x">Reliance &amp; Co</a>&nbsp;<font>BS</font>').startswith(
        "Reliance & Co"
    )
    assert "<" not in parse_feed(GNEWS, feed_id="g")[0].description


def test_a_description_that_is_the_headline_again_is_dropped() -> None:
    """Google sends the title back as a link followed by the publisher. Stored, the snippet reads
    "...excise notice Business Standard" — and a model can then quote a masthead as part of the
    event. What is kept has to be what the headline does not already say."""
    item = parse_feed(GNEWS, feed_id="g")[0]
    assert item.text == item.title
    assert "Business Standard" not in item.text


def test_a_description_that_adds_something_is_kept() -> None:
    item = parse_feed(ET, feed_id="et")[0]
    assert "interim order" in item.text and item.text != item.title


def test_an_undated_item_is_dropped_never_dated_by_us() -> None:
    """Stamping it with today would make three-year-old news look like this morning's."""
    assert parse_feed(UNDATED, feed_id="x") == []


def test_malformed_xml_is_no_items_rather_than_an_exception() -> None:
    assert parse_feed(b"<rss><channel><item>", feed_id="x") == []
    assert parse_feed(b"", feed_id="x") == []


def test_item_ids_are_stable_across_reparses() -> None:
    """A row keyed on the item has to point at the same item tomorrow."""
    assert [i.id for i in parse_feed(ET, feed_id="et")] == [
        i.id for i in parse_feed(ET, feed_id="et")
    ]
    assert parse_feed(ET, feed_id="et")[0].id != parse_feed(ET, feed_id="other")[0].id


# --- the archive ------------------------------------------------------------------------------------
def test_the_bytes_are_kept_before_anything_parses_them(tmp_path: Path) -> None:
    """Even when the parse yields nothing: the response is the evidence that we looked."""
    feed = Feed("et-stocks", "https://example.com/rss")
    archive = fetch_and_archive_feed(feed, AS_OF, fetch=_fetch(b"<not-xml"), directory=tmp_path)
    assert archive is not None and archive.items == ()
    xml, prov = news.feed_paths(feed, AS_OF, directory=tmp_path)
    assert xml.read_bytes() == b"<not-xml"
    assert prov.exists()


def test_the_sidecar_hash_matches_the_bytes(tmp_path: Path) -> None:
    import json

    from qalpha.live.evidence import sha256_of

    feed = Feed("et-stocks", "https://example.com/rss")
    fetch_and_archive_feed(feed, AS_OF, fetch=_fetch(ET), directory=tmp_path)
    _xml, prov = news.feed_paths(feed, AS_OF, directory=tmp_path)
    meta = json.loads(prov.read_text(encoding="utf-8"))
    assert meta["sha256"] == sha256_of(ET)
    assert meta["http_status"] == 200 and meta["feed"] == "et-stocks"


def test_a_403_is_a_failed_feed_not_an_empty_one(tmp_path: Path) -> None:
    """Business Standard 403s without a browser agent. 'We could not look' is not 'nothing filed'."""
    feed = Feed("bs-markets", "https://example.com/rss")
    assert fetch_and_archive_feed(feed, AS_OF, fetch=_fetch(b"", 403), directory=tmp_path) is None


def test_a_feed_whose_newest_item_is_years_old_is_stale_not_quiet(tmp_path: Path) -> None:
    """Moneycontrol answers 200 with items from April 2024, and is excluded for exactly this."""
    archive = fetch_and_archive_feed(
        Feed("moneycontrol", "https://example.com/rss"),
        AS_OF,
        fetch=_fetch(DEAD),
        directory=tmp_path,
    )
    assert archive is not None and archive.stale(AS_OF)


def test_a_feed_that_returned_nothing_is_stale_too(tmp_path: Path) -> None:
    archive = fetch_and_archive_feed(
        Feed("empty", "https://example.com/rss"),
        AS_OF,
        fetch=_fetch(b"<rss><channel></channel></rss>"),
        directory=tmp_path,
    )
    assert archive is not None and archive.stale(AS_OF)


def test_the_fetch_sends_a_browser_user_agent() -> None:
    import inspect

    from qalpha.live.announcements import USER_AGENT

    assert USER_AGENT in inspect.getsource(
        news._urlopen_fetch
    ) or "USER_AGENT" in inspect.getsource(news._urlopen_fetch)


def test_items_round_trip_through_the_archive(tmp_path: Path) -> None:
    items = parse_feed(ET, feed_id="et-stocks", feed_sha256="abc")
    write_items(items, AS_OF, directory=tmp_path)
    back = read_items(AS_OF, directory=tmp_path)
    assert [i.id for i in back] == [i.id for i in items]
    assert back[0].feed_sha256 == "abc"
    assert back[0].published_at.tzinfo is not None


def test_a_missing_items_file_is_empty_rather_than_an_error(tmp_path: Path) -> None:
    assert read_items(AS_OF, directory=tmp_path) == []


# --- which company is this about ---------------------------------------------------------------------
def test_every_watchlist_name_has_an_alias() -> None:
    """A name with no alias can never be searched for or matched, and its coverage row would then
    say 'no news' for a reason that has nothing to do with the news."""
    import csv

    with open("data/universes/nifty100_watchlist.csv", encoding="utf-8") as handle:
        tickers = {row["ticker"] for row in csv.DictReader(handle)}
    assert tickers - set(load_aliases()) == set()


def test_family_names_alone_map_to_nothing() -> None:
    """'Adani' is eight listed companies and 'Tata' is a dozen. A flag on the wrong one is worse
    than a missed item — and a missed item is a gap the coverage row reports."""
    aliases = load_aliases()
    for family in ("Adani", "Tata", "Bajaj", "HDFC", "ICICI", "Godrej", "Mahindra"):
        assert map_tickers(f"{family} group in talks over a stake sale", aliases) == ()


def test_a_full_name_maps_and_nothing_else_does() -> None:
    aliases = load_aliases()
    assert map_tickers("Tata Steel shares fall on China demand", aliases) == ("TATASTEEL.NS",)
    assert map_tickers("Sebi bars Torrent Pharmaceuticals promoter", aliases) == ("TORNTPHARM.NS",)


def test_aliases_match_whole_words_only() -> None:
    """'HAL' must not match 'halted' and 'Trent' must not match 'current'."""
    aliases = load_aliases()
    assert map_tickers("trading was halted after a technical fault", aliases) == ()
    assert map_tickers("the current account deficit widened", aliases) == ()


def test_mapping_is_case_insensitive() -> None:
    assert map_tickers("INFOSYS wins a deal", load_aliases()) == ("INFY.NS",)


def test_one_item_can_be_about_two_companies() -> None:
    found = map_tickers("Tata Steel and JSW Steel both raised prices", load_aliases())
    assert set(found) == {"TATASTEEL.NS", "JSWSTEEL.NS"}


# --- what the model may say ---------------------------------------------------------------------------
def _item(title: str, tickers: tuple[str, ...] = ("TORNTPHARM.NS",), **kw) -> NewsItem:
    base = {
        "id": "abc123def456",
        "feed_id": "et-stocks",
        "feed_sha256": "f" * 64,
        "title": title,
        "link": "https://example.com/x",
        "published_at": datetime(2026, 9, 10, 8, 0, tzinfo=UTC),
        "source": "ET",
        "description": "",
        "tickers": tickers,
    }
    base.update(kw)
    return NewsItem(**base)  # type: ignore[arg-type]


TITLE = "Sebi bars Torrent Pharmaceuticals promoter from the securities market"


def _line(**over: str) -> str:
    f = {
        "ticker": "TORNTPHARM",
        "item": "abc123def456",
        "type": "regulatory_action",
        "stance": "negative",
        "materiality": "high",
        "passage": TITLE,
        "summary": "regulator restrained the promoter",
    }
    f.update(over)
    return (
        f"NEWS: ticker={f['ticker']}; item={f['item']}; type={f['type']}; stance={f['stance']}; "
        f'materiality={f["materiality"]}; passage="{f["passage"]}"; summary={f["summary"]}'
    )


def test_a_verified_line_becomes_an_event() -> None:
    item = _item(TITLE)
    kept, discarded = parse_news_lines(_line(), [item], model="m")
    assert discarded == 0 and len(kept) == 1
    assert kept[0].ticker == "TORNTPHARM.NS" and kept[0].verified and kept[0].flags


def test_a_quote_that_is_not_in_the_snippet_is_discarded() -> None:
    """The whole guard. A plausible paraphrase is exactly what this catches."""
    kept, discarded = parse_news_lines(
        _line(passage="Sebi barred the promoter of Torrent for three years"),
        [_item(TITLE)],
        model="m",
    )
    assert kept == [] and discarded == 1


def test_the_model_cannot_report_an_item_it_was_not_shown() -> None:
    kept, discarded = parse_news_lines(_line(item="999999999999"), [_item(TITLE)], model="m")
    assert kept == [] and discarded == 1


def test_the_model_cannot_move_a_headline_to_another_company() -> None:
    """The alias table is the floor. A headline about one company cannot be filed against another,
    however confidently the line names it."""
    kept, discarded = parse_news_lines(_line(ticker="CIPLA"), [_item(TITLE)], model="m")
    assert kept == [] and discarded == 1


def test_an_unreadable_stance_falls_back_to_neutral_which_never_flags() -> None:
    kept, _ = parse_news_lines(_line(stance="bearish"), [_item(TITLE)], model="m")
    assert kept[0].stance == "neutral" and not kept[0].flags


def test_an_unknown_type_falls_back_rather_than_inventing_a_category() -> None:
    kept, _ = parse_news_lines(_line(type="scandal"), [_item(TITLE)], model="m")
    assert kept[0].event_type == "other"


def test_only_high_and_negative_flags() -> None:
    for over, flags in (
        ({}, True),
        ({"materiality": "medium"}, False),
        ({"stance": "positive"}, False),
        ({"stance": "neutral"}, False),
    ):
        kept, _ = parse_news_lines(_line(**over), [_item(TITLE)], model="m")
        assert kept[0].flags is flags, over


def test_the_prompt_shares_the_materiality_rubric_with_the_filing_reader() -> None:
    """One rubric, one string. EX-1 rated routine results `high` because the instruction never said
    material to whom; a second copy of that text is a second chance to make the mistake once."""
    from qalpha.live.extraction import MATERIALITY_RUBRIC

    assert MATERIALITY_RUBRIC in build_news_prompt([_item(TITLE)])


def test_the_prompt_says_a_price_move_is_not_an_event() -> None:
    """The screen selected these names BECAUSE they fell. Rating the fall is double-counting."""
    prompt = build_news_prompt([_item(TITLE)])
    assert "A PRICE MOVE IS NOT AN EVENT" in prompt
    assert "shares fall 5%" in prompt.lower()


def test_the_prompt_forbids_advice() -> None:
    assert "DO NOT recommend" in build_news_prompt([_item(TITLE)])


def test_the_prompt_lists_only_the_companies_the_mapper_assigned() -> None:
    prompt = build_news_prompt([_item(TITLE, tickers=("TORNTPHARM.NS",))])
    assert "companies: TORNTPHARM" in prompt


# --- reading a day ------------------------------------------------------------------------------------
def test_unmapped_items_are_never_sent_to_the_model() -> None:
    calls: list[str] = []

    def _generate(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        calls.append(prompt)
        return "", {}

    events, _d, _raw, usage = read_news(
        [_item("Nifty ends flat", tickers=())], generate=_generate, model="m"
    )
    assert calls == [] and events == [] and usage["calls"] == 0


def test_a_failed_call_is_counted_so_coverage_can_refuse() -> None:
    def _boom(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        raise RuntimeError("the model was not there")

    _events, _d, raw, usage = read_news([_item(TITLE)], generate=_boom, model="m")
    assert usage["failed_batches"] == 1 and "not there" in raw


def test_a_truncated_reply_is_not_a_reading() -> None:
    _events, _d, _raw, usage = read_news(
        [_item(TITLE)], generate=lambda m, p: (_line(), {"truncated": 1}), model="m"
    )
    assert usage["truncated_batches"] == 1 and usage["failed_batches"] == 1


def test_the_same_event_is_recorded_once() -> None:
    events, _d, _raw, _u = read_news(
        [_item(TITLE)], generate=lambda m, p: (_line() + "\n" + _line(), {}), model="m"
    )
    assert len(events) == 1


def test_batches_never_split_an_item() -> None:
    items = [_item(TITLE, id=f"{n:012d}") for n in range(10)]
    batches = batch_items(items, budget=len(TITLE) * 2)
    assert sum(len(b) for b in batches) == 10
    assert all(b for b in batches)


def test_rows_carry_the_version_the_model_and_the_feed_hash() -> None:
    events, _d, _raw, _u = read_news(
        [_item(TITLE)], generate=lambda m, p: (_line(), {}), model="qwen"
    )
    row = news_rows(events, as_of=AS_OF)[0]
    assert row["news_version"] == NEWS_VERSION
    assert row["model"] == "qwen"
    assert row["feed_sha256"] == "f" * 64
    assert row["kind"] == "news" and row["verified"] is True
    assert row["_key"].startswith("abc123def456:TORNTPHARM.NS")


def test_the_search_feed_is_built_per_name_and_quotes_the_alias() -> None:
    feed = google_news_feed("VBL.NS", "Varun Beverages")
    assert feed.kind == "name" and feed.ticker == "VBL.NS" and feed.id == "gnews-vbl"
    assert "Varun+Beverages" in feed.url and "when%3A7d" in feed.url


def test_mapping_a_batch_attaches_the_names(tmp_path: Path) -> None:
    items = map_items(parse_feed(ET, feed_id="et"), load_aliases())
    assert items[0].tickers == ("TORNTPHARM.NS",)
    assert items[1].tickers == ("TATASTEEL.NS",)


@pytest.mark.parametrize("feed", news.MARKET_FEEDS)
def test_every_market_feed_is_named_in_the_pre_registration(feed: Feed) -> None:
    """The feed list is part of the frozen specification, not a thing that drifts."""
    text = Path("reports/PREREGISTRATION_NEWS_V1.md").read_text(encoding="utf-8")
    assert feed.url.rstrip("/").rsplit("/", 1)[-1] in text, feed.id


def test_a_call_never_carries_more_headlines_than_its_reply_can_hold() -> None:
    """FOUND ON THE FIRST ARCHIVED RUN. Two names came back cut off at `max_tokens` with 60 and 72
    items in one call — a short prompt whose ANSWER could not fit, which counts as a failed read and
    covered neither name. The character budget was never the binding limit here."""
    items = [_item(TITLE, id=f"{n:012d}") for n in range(72)]
    batches = batch_items(items)
    assert max(len(b) for b in batches) <= news.MAX_ITEMS_PER_CALL
    assert sum(len(b) for b in batches) == 72


def test_the_count_is_labelled_as_reports_rather_than_events() -> None:
    """Nine flagged items on SHREECEM were nine outlets carrying one Meghalaya High Court order.
    The count is right; read as nine problems it is not. Clustering them would mean inventing a
    similarity score, which this layer is not allowed to have — so the surfaces say what they count."""
    import inspect

    from qalpha.live import desk, flags

    assert "reports, not events" in inspect.getsource(flags.flags_markdown).replace(
        "\n", " "
    ).replace("  ", " ") or "reports, not events" in inspect.getsource(flags.flags_markdown)
    assert "reports rather than events" in inspect.getsource(desk.Desk.news_line)
