# Kite basket import format (verified from an exported basket, 2026-08-28)

Source: a two-order basket created by hand in Kite web and exported —
`data/fixtures/kite_basket_sample.json`. **Zerodha publishes no spec for this**; every field below
comes from a file Kite itself produced. Do not extend this from guesswork.

## It is JSON, not CSV

A top-level **array**, one object per order. (The plan originally assumed CSV — wrong.)

```jsonc
[
  {
    "id": 327546830,          // Kite-assigned per row. Unknown whether import requires it.
    "weight": 0,              // row index / ordering
    "instrument": { ... },    // see below
    "params": {
      "transactionType": "BUY",   // "BUY" | "SELL"  ← the field that could not be guessed
      "product": "CNC",
      "orderType": "LIMIT",
      "validity": "DAY",
      "validityTTL": 1,
      "quantity": 1,              // integer
      "price": 100,               // number, NOT a string
      "triggerPrice": 0,
      "disclosedQuantity": 0,
      "variety": "regular",
      "gtt": null,
      "tags": []
    }
  }
]
```

`instrument` carries 23 keys; the load-bearing ones are `tradingsymbol`, `exchange`, `segment`,
`instrumentToken`, `exchangeToken`, `tickSize`, `lotSize`, `type`, `isEquity`. A `related` array holds
the same name's BSE listing — the system's `canonical_ticker` always resolves to NSE, so generated
rows use the NSE entry.

## ⚠️ Tick size is per instrument, and a bad price is rejected

| Name | Exchange | tickSize |
|---|---|---|
| WIPRO | NSE | **0.01** |
| JIOFIN | NSE | **0.05** |
| WIPRO | BSE | 0.05 |

**Every generated price must be rounded to that instrument's tick.** A harvest order at ₹238.03 on
JIOFIN (tick 0.05) is rejected at the exchange. This is not inferable from the price panel — it comes
from the instrument record — so the generator must read `tickSize` and round, and a test must assert
it. Note tick size also differs **by exchange** for the same name.

## `instrumentToken` must come from the instruments master

Tokens are Kite-internal (WIPRO 969473, JIOFIN 4644609) and cannot be derived from a ticker. Generating
a basket for arbitrary names needs Kite's instruments dump; the tradebook/holdings path already deals
in `tradingsymbol`, so the mapping has to be built and cached.

## ⚠️ UNVERIFIED: the round trip

This file proves what Kite **exports**. It does **not** prove what Kite **imports**. Open questions:

1. Is `id` required, optional, or ignored on a generated file?
2. Is the full 23-key `instrument` object required, or is `tradingsymbol` + `exchange` enough?
3. Is there a row limit?

**These are settled by importing a machine-written file, not by reading.** `data/fixtures/
kite_basket_roundtrip_test.json` is the first probe: identical instruments, `id` removed, prices
changed. Both prices are deliberately unfillable (WIPRO buy ₹90 vs ~₹180 market; JIOFIN sell ₹600 vs
~₹238), so even an accidental execute rests unfilled and is cancelled.

**Import is Kite web only** — Orders → Baskets → New Basket → Import basket icon. No basket import on
the mobile app, so any flow ending in a basket ends at a desktop.
