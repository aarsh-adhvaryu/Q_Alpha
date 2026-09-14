"""A headline is read once.

The feeds keep a week of items. Before this, every evening re-sent the whole week to the model, so
one headline was paid for up to seven times and six of those readings could only repeat the first.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from qalpha.config import Config
from qalpha.live.news import NewsItem

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import news as news_script


def _item(n: int, day: int) -> NewsItem:
    return NewsItem(
        id=f"item{n}",
        feed_id="feed",
        feed_sha256="s",
        title=f"Headline number {n} about Test Co",
        link=f"https://example.invalid/{n}",
        published_at=datetime(2026, 9, day, 9, 0, tzinfo=UTC),
        tickers=("TEST.NS",),
    )


@pytest.fixture
def evening(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    sent: list[str] = []

    def generate(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        sent.append(prompt)
        return "", {"input": 10, "output": 1}

    world: dict[str, object] = {"items": [], "sent": sent}
    monkeypatch.setattr(news_script, "NEWS_READ", tmp_path / "news_read.jsonl")
    monkeypatch.setattr(news_script, "NEWS_COVERAGE", tmp_path / "news_coverage.jsonl")
    monkeypatch.setattr(news_script, "NEWS_EVENTS", tmp_path / "news_events.jsonl")
    monkeypatch.setattr(news_script, "_scope", lambda cfg, as_of: ["TEST.NS"])
    monkeypatch.setattr(
        news_script,
        "_archive",
        lambda scope, as_of: ([SimpleNamespace(items=list(world["items"]))], [], 1),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(news_script, "load_aliases", lambda path: {})
    monkeypatch.setattr(news_script, "map_items", lambda items, aliases: list(items))
    monkeypatch.setattr(news_script, "write_items", lambda items, as_of: None)
    monkeypatch.setattr(
        news_script,
        "choose_backend",
        lambda **_: SimpleNamespace(
            generate=generate, model="reader-x", note="test reader", batch_chars=12_000
        ),
    )
    return world


def test_an_evening_reads_only_the_headlines_it_has_not_read(evening: dict[str, object]) -> None:
    sent = evening["sent"]
    assert isinstance(sent, list)

    evening["items"] = [_item(1, 13), _item(2, 13)]
    assert news_script.cmd_daily(Config(), date(2026, 9, 13)) == 0
    first = "".join(sent)
    assert "Headline number 1" in first and "Headline number 2" in first

    sent.clear()
    evening["items"] = [_item(1, 13), _item(2, 13), _item(3, 14)]
    assert news_script.cmd_daily(Config(), date(2026, 9, 14)) == 0
    second = "".join(sent)
    assert "Headline number 3" in second, "the new headline is read"
    assert "Headline number 1" not in second and "Headline number 2" not in second, (
        "a headline read on an earlier evening must not be sent to the model again"
    )


def test_nothing_new_sends_nothing(evening: dict[str, object]) -> None:
    sent = evening["sent"]
    assert isinstance(sent, list)
    evening["items"] = [_item(1, 13)]
    news_script.cmd_daily(Config(), date(2026, 9, 13))
    sent.clear()
    news_script.cmd_daily(Config(), date(2026, 9, 14))
    assert sent == [], "an evening with no new headlines costs nothing"


def test_a_different_reader_reads_again(
    evening: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A different reader is a different reading — the rule the corpus label applies to filings."""
    sent = evening["sent"]
    assert isinstance(sent, list)
    evening["items"] = [_item(1, 13)]
    news_script.cmd_daily(Config(), date(2026, 9, 13))
    sent.clear()
    reader = news_script.choose_backend()
    monkeypatch.setattr(
        news_script,
        "choose_backend",
        lambda **_: SimpleNamespace(
            generate=reader.generate, model="reader-y", note="another", batch_chars=12_000
        ),
    )
    news_script.cmd_daily(Config(), date(2026, 9, 14))
    assert any("Headline number 1" in p for p in sent)


def test_a_failed_reading_is_not_marked_read(
    evening: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Marking a failed batch read would leave its headlines unread for ever."""
    sent = evening["sent"]
    assert isinstance(sent, list)

    def broken(model: str, prompt: str) -> tuple[str, dict[str, int]]:
        raise RuntimeError("the API was down")

    monkeypatch.setattr(
        news_script,
        "choose_backend",
        lambda **_: SimpleNamespace(
            generate=broken, model="reader-x", note="down", batch_chars=12_000
        ),
    )
    evening["items"] = [_item(1, 13)]
    news_script.cmd_daily(Config(), date(2026, 9, 13))
    assert news_script._read_before("reader-x") == set()
