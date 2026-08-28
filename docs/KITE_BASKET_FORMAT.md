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

## ✅ VERIFIED: the round trip works (2026-08-28)

`kite_basket_roundtrip_test.json` — machine-written, `id` stripped, prices altered — **imported
cleanly into Kite web.** Both rows rendered correctly: BUY WIPRO NSE LIMIT ₹90 CNC (LTP ₹180.95) and
SELL JIOFIN NSE LIMIT ₹600 CNC (LTP ₹238.40), required margin ₹90.

Settled:

| Question | Answer |
|---|---|
| Is `id` required? | **No** — omitted, imported fine. Never generate it. |
| Does a machine-written file import? | **Yes** |
| Row limit? | **20 per basket** — the UI header reads `Instrument (2 / 20)` |

### ⚠️ 20 orders per basket is a hard cap

Any basket over 20 rows must be **split**, and the generator must do the splitting rather than emit a
file that silently truncates. The `max_names` slider defaults to 15 and the opening basket used 8, so
this does not bite today — but a harvest across a large book, or a deploy at a high slider setting,
can reach it. Encode as a constant with a test.

### Still open (low priority)

Whether the **full 23-key `instrument` object** is required, or a minimal subset suffices.
`kite_basket_minimal_test.json` keeps only `tradingsymbol`, `exchange`, `segment`,
`instrumentToken`, `exchangeToken`, `tickSize`, `lotSize`, `type`, `isEquity` and drops the 14
decorative UI fields (`company`, `fullName`, `niceName`, `niceNameHTML`, `stockWidget`, `precision`,
`scripCode`, `symbol`, `tradable`, `isin`, `related`, `underlying`, `auctionNumber`, `isWeekly`,
`isFound`). If it imports, the generator never has to synthesise them — Kite's public instruments dump
carries the nine that remain. Prices again unfillable (WIPRO ₹85, JIOFIN ₹650).

**Import is Kite web only** — Orders → Baskets → New Basket → Import basket icon. No basket import on
the mobile app, so any flow ending in a basket ends at a desktop.
