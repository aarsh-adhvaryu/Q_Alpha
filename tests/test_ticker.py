"""Realtime tick store + token resolution (the parts testable without a live socket).

The KiteTicker socket itself can only be verified on the box; here we pin the thread-safe store's
update/read semantics and the ltp()-based token resolution against a fake client.
"""

from __future__ import annotations

from typing import Any

from qalpha.live.ticker import TickStore, resolve_tokens


def test_tick_store_update_and_read() -> None:
    store = TickStore()
    assert store.snapshot() == {}
    store.update([{"instrument_token": 408065, "last_price": 1500.5}])
    assert store.last(408065) == 1500.5
    assert store.snapshot() == {408065: 1500.5}
    # a later tick overwrites the price
    store.update([{"instrument_token": 408065, "last_price": 1502.0}])
    assert store.last(408065) == 1502.0
    assert store.last_update() is not None


def test_tick_store_ignores_malformed_ticks() -> None:
    store = TickStore()
    store.update([{"instrument_token": 1}, {"last_price": 9.9}, {}])  # all missing a field
    assert store.snapshot() == {}
    assert store.last(1) is None


class _FakeKite:
    def ltp(self, keys: list[str]) -> dict[str, Any]:
        table = {"NSE:INFY": 408065, "NSE:TCS": 2953217}
        return {k: {"instrument_token": table[k], "last_price": 1.0} for k in keys if k in table}


def test_resolve_tokens_maps_symbols() -> None:
    tokens = resolve_tokens(_FakeKite(), ["INFY", "TCS", "UNKNOWN"])
    assert tokens == {"INFY": 408065, "TCS": 2953217}  # UNKNOWN silently dropped


def test_resolve_tokens_empty() -> None:
    assert resolve_tokens(_FakeKite(), []) == {}
