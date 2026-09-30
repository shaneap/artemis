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
