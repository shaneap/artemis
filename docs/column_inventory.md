# Column Inventory: Toast Exports (Phase 1, Step 0)

Generated 2026-09-27 from the files in `data/exports/`. Input for decision D008.

All counts come from reading every file as plain text (Python `csv` module, no type
conversion). "Line" means a physical line in the file, with the header as line 1.

## 1. Files

| File | Bytes | SHA256 (first 16) | Lines | Header repeats mid-file | Data rows | Opened range |
|---|---|---|---|---|---|---|
| `OrderDetails_2026_01_15-2026_07_15.csv` | 416,686 | `ff632ab90688d4ab` | 6,631 | 1 (line 3522) | 6,629 | 2026-01-15 16:05 → 2026-07-15 23:43 |
| `OrderDetails_2026_03_15-2026_06_15.csv` | 213,534 | `084019e021934cb4` | 3,255 | 0 | 3,254 | 2026-03-15 16:04 → 2026-06-14 20:48 |
| `OrderDetails_2026_05_30-2026_06_06.csv` | 16,123 | `886a1392e6f0d189` | 249 | 0 | 248 | 2026-05-30 16:01 → 2026-06-06 01:04 |

Format notes that matter for a loader:

* All three use CRLF line endings, no BOM, comma delimiter, no quoted fields, and a constant
  field count on every line.
* The 01_15 file has **no trailing newline**, so `wc -l` reports 6,630 instead of 6,631.
* The 01_15 file is two report chunks glued together. The header is repeated on line 3522, and
  the 20 lines just before it (3502–3521) are repeated exactly just after it (3523–3542). These
  are the only exact duplicate rows in that file.
* The 03_15 file has 3 exact duplicate rows (6 lines involved) with no repeated header.
* "Data rows" above excludes the header lines and includes exact duplicates.

## 2. Export types

All files are the same Toast report (`OrderDetails`), but they come in two column layouts.

### Type A: 10 columns, with `Total` and `Duration`

1 file (`2026_01_15-2026_07_15`), **6,629 data rows** (6,609 after removing exact duplicates).

| # | Column | Blank | Distinct | Example values |
|---|---|---|---|---|
| 1 | `Opened` | 0 | 6,134 | `1/15/26 4:05 PM` |
| 2 | `# of Guests` | 0 | 19 | `2`, `0`, `1` |
| 3 | `Table` | 376 | 33 | `O3`, `B7`, `BD1` |
| 4 | `Discount Amount` | 0 | 165 | `0`, `9`, `42` |
| 5 | `Amount` | 0 | 627 | `94`, `127` |
| 6 | `Tip` | 0 | 828 | `30`, `23.8` |
| 7 | `Gratuity` | 0 | 106 | `0`, `175.6` |
| 8 | `Total` | 0 | 3,906 | `132.57` |
| 9 | `Closed` | 37 | 4,808 | `1/15/26 5:25 PM` |
| 10 | `Duration (Opened to Paid)` | 9 | 4,810 | `1:14:12` (H:MM:SS) |

Money is written without trailing zeros (`0`, `23.8`).

### Type B: 9 columns, with `Tax`, no `Total` or `Duration`

2 files, **3,502 data rows** (3,499 after removing exact duplicates).

| # | Column | Blank (03_15 / 05_30) | Example values |
|---|---|---|---|
| 1 | `Opened` | 0 / 0 | `3/15/26 4:04 PM` |
| 2 | `# of Guests` | 0 / 0 | `6`, `4` |
| 3 | `Table` | 170 / 17 | `BD1`, `O1` |
| 4 | `Discount Amount` | 0 / 0 | `0.00`, `5.20` |
| 5 | `Amount` | 0 / 0 | `335.00` |
| 6 | `Tax` | 0 / 0 | `30.58` |
| 7 | `Tip` | 0 / 0 | `20.00` |
| 8 | `Gratuity` | 0 / 0 | `67.00` |
| 9 | `Closed` | 16 / 2 | `3/15/26 7:05 PM` |

Money is always written with two decimals (`0.00`).

**Across both types:** 3 files, 10,131 data rows, 10,108 after removing exact duplicates within
each file. The 8 shared columns have the same names in both types; the column order differs
(`Tax` sits between `Amount` and `Tip`).

## 3. Unique ID candidates

**No export contains an order ID, check ID, check number, or item selection ID.** None of the
columns can serve as an ID alone:

| Column | Unique within a file? | Ever blank? | Notes |
|---|---|---|---|
| `Opened` | No (6,134 distinct in 6,629 rows) | Never | Minute precision only |
| `Closed` | No | Yes (37 / 16 / 2) | Many checks share a batch close time, e.g. `4:18 AM`, `4:29 AM` |
| `Duration (Opened to Paid)` | No (4,810 distinct) | Yes (9) | Type A only; second precision |
| `Table` | No | Yes (376 / 170 / 17) | Code, not an ID |
| `Total` | No | Never | Type A only |

Composite keys, for information only (not a recommendation):

| Key (after removing exact duplicates) | 01_15 file: rows that still collide | 03_15 file | 05_30 file |
|---|---|---|---|
| Opened + Table + Guests | 83 | 30 | 10 |
| + Amount | 14 | 0 | 0 |
| + Amount + Closed | 8 | 0 | 0 |
| All columns | 0 (by definition) | 0 | 0 |

Every composite that becomes unique does so by including a field Toast can change after
service (Amount, Tip, Closed), so none of them is stable across pulls.

**No row is ever the item selection grain.** Each row is one check (or order) with totals, so
these exports cannot supply data at the D002 grain. See Questions.

## 4. Collisions on Opened + Table + # of Guests

"Rows in collision" means rows that share a key with at least one other row. "Rows that would
merge away" is how many rows would disappear if each key kept only one row.

### Within a single file

| File | Rows | Colliding groups | Rows in collision | Rows that would merge away | Largest group | Groups with blank `Table` |
|---|---|---|---|---|---|---|
| 01_15, as received | 6,629 | 58 | 123 | 65 | 3 | |
| 01_15, exact duplicates removed | 6,609 | 38 | 83 | 45 | 3 | 28 of 38 |
| 03_15, as received | 3,254 | 17 | 36 | 19 | 3 | |
| 03_15, exact duplicates removed | 3,251 | 14 | 30 | 16 | 3 | 11 of 14 |
| 05_30, as received | 248 | 4 | 10 | 6 | 3 | 3 of 4 |

The existing `data/orders_merged.csv` (6,609 rows) has the same 38 groups / 83 rows as the
deduplicated 01_15 file.

About three quarters of the collisions involve a blank `Table`. A typical example from the
05_30 file: six checks opened at `6/4/26 8:51–8:55 AM`, blank table, 1 guest, all closed at
`6/5/26 4:29 AM`, with amounts from 89.49 to 950.53. They look like distinct checks, not
duplicates. Most of the rest are split checks at one table in the same minute (for example,
`6/3/26 7:42 PM`, `B4`, 1 guest: one at 0.00 and one at 19.00).

### Across files (same order seen in two pulls)

Compared over each pair's overlapping date range, after removing exact duplicates:

| Older pull → newer pull | Older keys missing from newer | Keys where row count differs | Older rows unchanged in newer* |
|---|---|---|---|
| 05_30 → 03_15 | 0 | 0 | 242 of 243 |
| 05_30 → 01_15 | 0 | 0 | 247 of 248 |
| 03_15 → 01_15 | 0 | 3 | 3,251 of 3,251 |

\* Compared on the 8 shared columns, with money normalized so `0` and `0.00` match.

* Every key in an older pull is found in the newer pull. In these three files **no guest count
  was edited** between pulls (0 cases), so the concern in D008 has not happened yet in this
  data, but nothing in the export would prevent it.
* The one changed row in the 05_30 pull is the known `6/5 6:37 PM O1` tip revision.
* **The 3 row count mismatches are a real ambiguity.** For each, the 03_15 pull has one row and
  the 01_15 pull has two rows that are identical except for `Duration` (a few seconds apart):

  ```
  03_15 line 533:   3/31/26 2:29 PM,1,,0.00,80.00,7.30,0.00,0.00,4/1/26 4:18 AM
  01_15 line 2954:  3/31/26 2:29 PM,1,,0,80,0,0,87.3,4/1/26 4:18 AM,0:00:18
  01_15 line 2955:  3/31/26 2:29 PM,1,,0,80,0,0,87.3,4/1/26 4:18 AM,0:00:27
  ```

  Same for `4/1/26 10:04 AM` (blank table) and `4/17/26 7:04 PM E1` (a 0.00 check). Without an
  ID there is no way to tell from the data whether these are two real checks that the Type B
  layout happens to render identically, or one check duplicated by the Type A export.

### Note on the current merge

D008 describes `merge_exports.py` as matching on Opened + Table + # of Guests. The code
actually adds a fourth part: an occurrence number within each colliding group, assigned by
sorting on Amount then Discount Amount (`_add_occurrence`, `merge_exports.py:224`). So it
already avoids collapsing the 45 same-key rows in the 01_15 file, but the match then depends
on Amount, which is a field Toast can revise.

## 5. How this was produced

Ad hoc Python scripts (not committed) reading each file with `csv.reader` and pandas using
`dtype=str`. Exact duplicates were detected on all source columns of a file. No project file
was modified.
