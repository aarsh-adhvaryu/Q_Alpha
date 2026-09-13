"""The world on one evening, gathered once and handed to whatever decides.

Passed in rather than fetched, so a review is replayable: the same market and the same book give
the same packet. A book whose past decisions cannot be reproduced cannot be audited when it turns
out to have been wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from qalpha.data.prices import PriceData


@dataclass(frozen=True)
class Market:
    as_of: date
    #: Last adjusted close per ticker, on or before ``as_of``. A name absent here is unpriced, never 0.
    prices: dict[str, Decimal]
    #: NIFTYBEES adjusted close — the ETF, not the index level.
    index_close: pd.Series
    adj_close: pd.DataFrame
    #: A name whose price series has an unexplained gap is measured only from after the gap.
    rebase_from: dict[str, date] | None = None
    #: Names with too little comparable history since a gap to read a pullback from.
    exclude: set[str] | None = None
    watchlist: list[str] | None = None
    sector_of: dict[str, str] | None = None
    #: The watchlist panel, with raw close and volume as well as adjusted close.
    wl_prices: PriceData | None = None
