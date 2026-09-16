# tr-payout-reconciliation

[![tests](https://github.com/eliftb/tr-payout-reconciliation/actions/workflows/tests.yml/badge.svg)](https://github.com/eliftb/tr-payout-reconciliation/actions/workflows/tests.yml)

*English · [Türkçe](README.tr.md)*

A local reconciliation panel for restaurants selling through Turkish food
delivery platforms (Yemeksepeti, Trendyol Yemek, Getir Yemek). It computes
what the platform **should** have paid from your own POS records and your
contract terms, compares that with what the platform's payout statement
**actually** paid, and attributes every missing lira to a specific cause.

Runs entirely on your machine: Python standard library plus `openpyxl`,
SQLite, a server bound to `127.0.0.1`. No platform API, no cloud, no data
leaves the computer.

> The user interface, code comments and error messages are in Turkish — the
> tool is built for Turkish restaurant owners and reads Turkish-formatted
> files. This README and the repository metadata are in English.

## Why

Platforms send a monthly payout statement and a bank transfer. Checking them
by hand is impractical, and a claim like "you underpaid us" goes nowhere.
A claim like "order YS-480003: contract rate is 18%, you charged 21% on a
207.06 TL base" does.

Two design decisions follow from that:

- **The POS is the source of truth.** The platform statement is what gets
  audited, never the reference. Platform API integration was deliberately
  avoided — it requires a commercial agreement and approval.
- **Every result is a breakdown, not a number.** Each order opens into a
  line-by-line calculation (order amount → discounts → commission base →
  commission → VAT → processing fee → expected net) that can be pasted into
  a dispute.

## What it detects

| Code | Meaning |
|---|---|
| `MISSING_FROM_PAYOUT` | Delivered order never appears on the payout statement |
| `RATE_MISMATCH` | Commission rate higher than the contract rate |
| `COMMISSION_OVERCHARGE` | Rate is right, commission amount is still too high |
| `CHARGED_ON_CANCELLED` | Commission taken on a cancelled or refunded order |
| `PLATFORM_DISCOUNT_CHARGED` | A platform-funded campaign was deducted from your revenue |
| `UNKNOWN_DEDUCTION` | Deduction with no stated reason |
| `DUPLICATE_LINE` | Same order listed more than once |
| `PERIOD_TOTAL_MISMATCH` | Sum of statement lines ≠ money that actually reached the bank |
| `UNDERPAID` | Underpaid, cause could not be determined |
| `NOT_IN_POS` | Paid by the platform but not in your records (in your favour) |
| `OVERPAID` | Paid more than owed (in your favour; may be clawed back) |
| `NO_RULE` | No commission rule covers this order's date |

Each underpaid amount is attributed to **exactly one** cause, so the dispute
total is never double-counted. The results screen reports how much of the
shortfall is explained; when the unexplained remainder is zero, the dispute
list is defensible.

Commission rules are **date-ranged**: an order from March is checked against
the rate that was valid in March, not today's rate. A rule covers the
commission rate and base (before/after restaurant discount, including
delivery, or gross), a fixed per-order fee, online payment
processing rate, commission VAT (20% by default) and who keeps the
delivery fee.

## Results on the benchmark month

The only data the tool has been run on so far is the generated sample month
in `sample/` — no real platform statement yet. On that month:

| | |
|---|---|
| POS orders / statement lines | 220 / 216 |
| Errors planted by the generator | 30, across 7 discrepancy types |
| Found by the tool | 30, each with the exact amount |
| False positives | 0 |
| Expected payout per contract | 66,755.11 TL |
| Actually reached the bank | 63,155.16 TL |
| Underpayment found | **3,599.95 TL (5.4%)** — 1,749.95 TL across order-level findings, fully attributed to a cause, plus a 1,850.00 TL lump-sum deduction |

These numbers are asserted by the test suite, so a change that breaks
detection or attribution fails CI.

## Engineering notes

Problems that were not obvious up front and shaped the code:

- **One lira, one cause.** A commission overcharge on a rate mismatch is
  reported as `RATE_MISMATCH` only, not also as `COMMISSION_OVERCHARGE` or
  `UNDERPAID`. Double-counting inflates the dispute total and gives the
  platform a reason to reject the whole list. The rate is checked before the
  amount because "you applied 21% instead of 18%" is a stronger claim than
  "the deduction is too high".
- **Don't invent a cause.** When an order appears on the statement more than
  once, commission is not compared against a single order's rate — an exact
  duplicate would look like a 36% rate. Such orders are flagged as
  `DUPLICATE_LINE` and the difference is left for review.
- **VAT is part of the loss.** Excess commission is invoiced with 20% VAT,
  so the restaurant loses the excess *plus* its VAT.
- **Cash on delivery flips the sign.** The restaurant collected the money,
  so the expected payout is negative: the platform is owed its commission.
- **Bank ≠ statement.** Money can disappear between the statement's line
  total and the bank transfer without touching any order. That check uses
  every statement line, including orders the engine could not evaluate.
- **Turkish text traps.** In Python `"İ".lower()` yields `i` plus a
  combining dot (U+0307); a naive match would silently read `İptal Edildi`
  (cancelled) as a delivered order. The column guesser matches whole words so `tip`
  does not capture `Ödeme Tipi` (payment type), and assigns columns globally
  by score rather than field by field, so a weak early match cannot steal a
  later exact one.

## Quick start

Requires Python 3 (tested on 3.10).

```bash
pip install openpyxl        # only needed for .xlsx files; CSV works without it
python3 app.py
```

Open **http://127.0.0.1:8770**. The database is created on first run under
`data/`.

On Ubuntu, `baslat.sh` starts the server in the background (if it isn't
already running) and opens the browser — suitable as the target of a
desktop launcher. `durdur.sh` stops it, `sifirla.sh` wipes all data.

### Try it with the sample data

`sample/` holds a generated month (August 2026, Yemeksepeti, 220 orders)
with errors planted on purpose. `sample/beklenen_hatalar.csv` lists the 30
findings the tool is expected to produce.

1. **Ayarlar** (Settings) → add a rule: platform `yemeksepeti`, rate 18%,
   valid from any date before August 2026. Under *Gelişmiş ayarlar*
   (advanced): commission base *after restaurant discount*, online payment
   processing fee 1.79%.
2. **Dosya Yükle** (Upload) → upload `pos_siparisler_2026-08.csv` as the POS
   file and `yemeksepeti_hakedis_2026-08.csv` as the payout statement.
   Column mapping is guessed automatically; confirm it. Enter `63155,16`
   as the amount that reached the bank.
3. **Sonuç** (Results) → select August 2026.

All 30 planted errors should appear with nothing extra, and the whole
shortfall should be explained. `make_sample.py` regenerates the files
(fixed seed, same output).

## Tests

```bash
python3 -m unittest discover -s tests
```

58 tests, standard library only (the XLSX test is skipped without
`openpyxl`). CI runs them on Python 3.10–3.14 and once without `openpyxl`.

- `test_rules.py` — rule selection by date, every commission base, expected
  payout computed by hand for online, cash, cancelled and fixed-fee orders
- `test_importers.py` — number and date formats, Turkish normalisation,
  column guessing, cp1254 CSV, XLSX
- `test_reconcile.py` — one scenario per discrepancy type, attribution,
  tolerances
- `test_sample_regression.py` — the benchmark table above, and that
  `make_sample.py` reproduces the committed files byte for byte
- `test_app.py` — upload → reconcile → export over HTTP against a temporary
  database, re-import idempotency, path traversal

Writing the tests surfaced three defects, each fixed in its own commit with
a regression test: a false lump-sum deduction when some orders had no
commission rule, duplicate statement lines reported as rate mismatches, and
the sample generator recording rate-mismatch losses without VAT.

## Your data

Everything lives in one SQLite file, `data/hakedis.db`. Back it up by
copying it. The `data/` directory, `*.db`, logs and `.xlsx`/`.xls` exports
are git-ignored — real order and revenue data must never be committed.

## Project layout

| File | Role |
|---|---|
| `app.py` | HTTP server and JSON API (stdlib `http.server`) |
| `db.py` | SQLite schema |
| `rules.py` | Commission engine — "what should have been paid", with breakdown |
| `reconcile.py` | Order-level matching and discrepancy classification |
| `importers.py` | CSV/XLSX reading, Turkish number/date formats, cp1254, column guessing |
| `static/` | Front end (plain HTML + JS) |
| `make_sample.py`, `sample/` | Sample data generator and its output |
| `tests/` | Unit, regression and HTTP integration tests |
| `.github/workflows/` | CI |

## Status

- Verified only against generated sample data. Real statements will likely
  need column-mapping adjustments.
- No ready-made column mappings for Trendyol/Getir statement formats yet
  (the `import_profiles` table exists, no UI).
- Dispute tracking (open / sent / accepted / collected): table and API
  exist, no UI.
- Dispute list export is CSV (opens in Excel).
- Numbers with a single dot and no decimal part are ambiguous: `1.250` is
  read as 1.25, not 1,250. Exports with decimals (`1.250,00`) are fine.
- No month-over-month comparison.
