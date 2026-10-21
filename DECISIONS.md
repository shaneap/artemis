# Artemis Decision Tracker

Every time we agree on something, it gets an entry here. Keep this file in the repo root.

**How to use it**

* Add a new entry each time a decision is made or an open question gets answered.
* Never delete an entry. If a decision changes, mark the old one `Replaced by Dxxx` and write a new entry explaining what changed and why.
* Write the "Why" in your own words. If you can't explain it without looking something up, it isn't ready to be marked Decided.
* Status is one of: **Decided**, **Open**, **Proposed** (suggested but not agreed yet), **Replaced**.

---

## Summary

| ID | Decision | Status | Date |
|---|---|---|---|
| D001 | Coding agents write the code, Shane owns the decisions | Decided | 2026-09-27 |
| D002 | Grain is one item selection on one check | Decided | from handoff |
| D003 | Three schemas: raw, staging, analytics | Decided | from handoff |
| D004 | Loads must be idempotent | Decided | from handoff |
| D005 | Database is PostgreSQL | Decided | from handoff |
| D006 | Menu item prices are a Type 2 slowly changing dimension | Decided | from handoff |
| D007 | Floor plan is a slowly changing dimension | Decided | from handoff |
| D008 | Which column(s) uniquely identify an order | Open | |
| D009 | Sessions over 6 hours are flagged and left out of time metrics | Decided | 2026-09-28 |
| D010 | Data quality fixes happen in staging | Decided | 2026-09-28 |
| D011 | Raw layer skips files it has already loaded, using a file fingerprint | Decided | 2026-09-28 |
| D012 | Orders are identified by Toast's Order Id; items by Item Selection Id | Proposed | 2026-10-20 |
| D013 | When an order is in two exports, the export whose date range ends latest wins | Proposed | 2026-10-03 |
| D014 | Oversized parties go to the smallest listed combination, then the whole room | Proposed | 2026-10-20 |
| D015 | Order type rule, and which orders count toward spend-per-time metrics | Proposed | 2026-10-20 |
| D016 | The service-day cutoff is checked against seated orders only | Proposed | 2026-10-20 |

---

## Entries

### D001: Coding agents write the code, Shane owns the decisions
* **Status:** Decided, 2026-09-27
* **Decision:** Use Claude Code (and similar agents) to implement the project. Shane makes and defends every design choice.
* **Why:** Employers already use coding agents, and it lets the full project get built. The skill being shown is judgment, not typing.
* **What it replaces:** The earlier rule of building the database layer by hand, and the "cold rebuild" test.
* **What it changes:** The new test is a "cold explain" test. For every choice, Shane can say what was picked, what was rejected, and why, without looking it up. This tracker is how that gets recorded.

### D002: Grain is one item selection on one check
* **Status:** Decided (carried over from handoff)
* **Decision:** The smallest unit stored in the warehouse is a single item selection on a single check.
* **Why:** If data is rolled up to the check level when it's loaded, menu mix questions can't be answered later without reloading everything.
* **Rejected:** Storing one row per check. Storing one row per order.

### D003: Three schemas: raw, staging, analytics
* **Status:** Decided (carried over from handoff)
* **Decision:** `raw` holds each export exactly as received, stored as text, plus load details. `staging` converts types and cleans. `analytics` holds the dimensional model.
* **Why:** A bad file can be reloaded without breaking anything downstream, and every number can be traced back to the source row it came from.

### D004: Loads must be idempotent
* **Status:** Decided (carried over from handoff)
* **Decision:** Loading the same file twice changes nothing.
* **Why:** _Write this in your own words._
* **Note:** How this works depends on D008 and D011.

### D005: Database is PostgreSQL
* **Status:** Decided (carried over from handoff)
* **Why:** _Write this in your own words._

### D006: Menu item prices are a Type 2 slowly changing dimension
* **Status:** Decided (carried over from handoff)
* **Decision:** Each price version of a menu item gets its own row, with a surrogate key and a start and end date.
* **Why:** _Write this in your own words._

### D007: Floor plan is a slowly changing dimension
* **Status:** Decided (carried over from handoff)
* **Decision:** Track how POS table codes map to physical seating over time.
* **Why:** POS table codes don't map one to one to physical seating units. This mismatch made a large share of records look anomalous.
* **Still to settle:** Which type (Type 2 or something else), and why.

### D008: Which column(s) uniquely identify an order
* **Status:** Open
* **Current approach:** `merge_exports.py` matches orders on Opened + Table + # of Guests.
* **Concern:** Two parties seated at the same table in the same minute, or a guest count edited later, would cause rows to be wrongly merged or duplicated.
* **Option:** Use a Toast order or check ID column, if the exports include one.
* **Blocked on:** Step 0 of the phase one brief (column inventory).

### D009: Sessions over 6 hours are flagged and left out of time metrics
* **Status:** Decided, 2026-09-28
* **Problem:** Tickets left open in the POS make sessions look far longer than they were, which inflates VPCPM and TPCPM denominators.
* **Decision:** Any session longer than 6 hours is most likely a mistake (a ticket that was never closed).
* **Why:** _Write this in your own words._
* **Rejected:** Winsorizing at the 99th percentile, which always changes exactly 1% of rows whether or not they are real.
* **Handling:** Flag these rows in staging and leave them out of time based metrics (the rows stay in the data, just marked).
* **Why this handling:** A forgotten ticket's real length is unknown, so cutting it to 6 hours would still leave a fake 6 hour dinner in the numbers.
* **Rejected handling:** Capping long sessions at 6 hours.
* **To check:** Plot session lengths to confirm there is a gap near 6 hours, and sanity check the number with Ed.

### D010: Data quality fixes happen in staging
* **Status:** Decided, 2026-09-28
* **Decision:** The combined table fix and the session duration fix (D009) get applied in the staging layer, never in raw.
* **Why:** Raw stays an exact copy of what Toast gave us. If a fix turns out to be wrong, change the rule in staging and rebuild from raw. Fixing raw directly would destroy the original with no way to undo it.
* **Rejected:** Cleaning data while loading it, which is simpler but makes every mistake permanent.

### D011: Raw layer skips files it has already loaded, using a file fingerprint
* **Status:** Decided, 2026-09-28
* **Decision:** Each export file gets a fingerprint (SHA256 hash). The loader keeps a list of fingerprints it has loaded and skips any file already on the list. The same order showing up in two different pulls is expected, and staging keeps the newest version (after D008 is settled).
* **Why:** It's closer to how real production pipelines work: only new files get loaded, and there's a record of when each file first came in.
* **Rejected:** Wiping raw and reloading every file on each run. Simpler, but loses the load history and gets slower as files pile up.
* **Rejected:** Removing duplicate orders while loading into raw, since that needs a reliable order ID (D008) and would erase what older pulls said.

### D012: Orders are identified by Toast's Order Id; items by Item Selection Id
* **Status:** Proposed, 2026-10-20 (would answer D008)
* **Decision:** Every export since 2026-09-30 carries Toast's Order Id, Check Id and Item Selection Id. Staging keeps one row per Order Id and one row per Item Selection Id. The old Opened + Table + # of Guests key is retired.
* **Why:** _Write this in your own words._
* **Evidence:** Order Id was unique within every pull checked, and every repeat across pulls was an identical copy from two files sharing a boundary date. The old key collided on about 0.7% of rows (split checks rung in the same minute at the same table).
* **Rejected:** Keeping the Opened + Table + # of Guests key with an occurrence index (what `legacy/merge_exports.py` does).

### D013: When an order is in two exports, the export whose date range ends latest wins
* **Status:** Proposed (agreed 2026-10-03; mark Decided once the Why is written)
* **Decision:** If the same Order Id or Item Selection Id appears in more than one export, staging keeps the copy from the file whose date range (from the Toast file name) ends latest. Files without a dated name rank last; ties fall back to load order.
* **Why:** _Write this in your own words._
* **Rejected:** Keeping the copy from the most recently loaded file, because loading an older export later would overwrite newer data.

### D014: Oversized parties go to the smallest listed combination, then the whole room
* **Status:** Proposed, 2026-10-20 (settles the "which type" question in D007)
* **Decision:** The floor plan is stored as one row per table per layout period, with start and end dates (old layout until 2025-11-24 for Evangeline and 2026-02-14 for Black Duck). Each order is placed on its own table if the party fits, otherwise on the smallest listed combination that seats it, otherwise the whole room, otherwise flagged `over_capacity`. Nothing is removed.
* **Why:** _Write this in your own words._
* **Still open:** The two layout change dates are inferred from the last use of the retired table codes; the owner has confirmed the changes, not the dates. The capacity of the old BD3+BD4+BD5 (set to 7) and Open Lounge setups bigger than the pairs are unconfirmed. See `OPEN_QUESTIONS.md`.

### D015: Order type rule, and which orders count toward spend-per-time metrics
* **Status:** Proposed, 2026-10-20 (carried over from the legacy analysis)
* **Decision:** A check with a table is Seated. Without a table, $400 or more is Event-Catering, otherwise To-Go. Per-order VPCPM and TPCPM are only computed for Seated orders with a usable duration of 15 minutes to 6 hours and a believable guest count (30 or fewer, 12 or fewer at the bar).
* **Why:** _Write this in your own words._
* **Note:** Untabled event and to-go checks are often rung in the morning, so hour-of-night analysis uses seated trade only.

### D016: The service-day cutoff is checked against seated orders only
* **Status:** Proposed, 2026-10-20
* **Decision:** The check that no orders open near the 4 am service-day cutoff looks at seated orders only. Untabled checks in that window are still counted and reported.
* **Why:** _Write this in your own words._
* **Evidence:** The only order in the 3-5 am window was an untabled $400 Event-Catering check opened at exactly 3:00 am on 2025-12-20 and paid that afternoon, a back-office entry. No seated order opens between 3 am and 7 am, so the 4 am cutoff stands.
* **Rejected:** Moving the cutoff, or excluding that one order by hand.
