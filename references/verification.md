# Debugging and cross-verification

## Step 3 — debug toolkit (build it before the first real export)

| Need | Tool |
|---|---|
| See what the browser does | `run --headed --id <ID>` |
| Small fast loop | `run --limit 3` |
| One record end to end | `run --id <ID>` then `log --id <ID>` |
| More detail | `--log-level DEBUG` (log URL, status, selector waited for, bytes) |
| Parsed records without touching the site | `log` (prints every non-empty field + data check) |
| Visual confirmation | screenshots in `data/runs/<run_id>/screenshots/` |
| Parser regression | save the page to `tests/fixtures/`, add a test, fix, re-run tests |

Data-check lines printed by `log` (adapt the names to the project):

```
  OK  150/150 records captured
  OK  required fields (ID, Title, Closing Date) present
  !!  54/56 documents have a link: 1042, 1077
  OK  12/12 child records have their text
```

Triage a failure in this order:
1. **Blocked?** Captcha, login page, "Security Page", 403/429 → new session, slow down, check
   terms. Never parse a block page as data.
2. **Timing?** Element not there yet → wait for the specific selector / navigation, not a sleep.
3. **Layout changed?** Compare the saved HTML with the fixture; update parser + fixture.
4. **Genuinely missing on the site?** Leave the cell empty and note it; don't invent values.

## Step 4 — cross-verify the written files

Run `templates/verify_export.py` on every export (copy it into the project):

```bash
python scripts/verify_export.py data/exports/records_full.csv \
  --key Ref --required "ID" "Title" \
  --date-cols "Closing Date" --url-cols "Document URL" \
  --expected 150 --compare data/exports/records_full.xlsx \
  --check-urls 3 --json data/runs/<run_id>/verify_full.json
```

| Check | Fails (`!!`) when |
|---|---|
| File opens / parses | Unreadable, wrong encoding, corrupt xlsx |
| Header | Empty or duplicate column names |
| Row count | `!= --expected` (the count the site itself shows) |
| Unique key | Duplicates or empty keys |
| Required columns | Missing column or any empty value |
| Dates | A non-empty value in a date column doesn't parse |
| URLs | Not `http(s)://host/...`; with `--check-urls K`, K random URLs don't answer |
| Placeholders | Literal `None`, `nan`, `null`, `NaT` in cells |
| Whitespace | Leading/trailing spaces in values (WARN) |
| Formula injection | Cells starting with `=`, `+`, `-`, `@` that aren't numbers (WARN) |
| Empty columns | A column that is empty in every row (WARN, maybe a broken selector) |
| `--compare` | The other file (CSV vs XLSX, sample vs full subset) has different columns, row count, or key set |

Exit code: `0` all OK (warnings allowed), `1` any `!!`.

Notes from real use:
- Pass to `--required` only columns that are filled on **every** row. With parent/child rows
  (a record + its amendments), parent-only columns like `Title` are blank on child rows by
  design. Check those per row type, or filter to parent rows first.
- **Stale files are the most common cross-format mismatch.** On the first real run, the CSV
  failed `--compare` against the XLSX (a 2-row difference, a missing `Document URL` column). The
  XLSX had been re-exported after the last scrape and the CSV had not. Always write every selected
  format in one `export` command, and read the "written in the same export run" line.

For XML / JSON outputs, re-parse them and compare the record count and key set with the CSV
(a three-line check is enough: `ET.parse(...).getroot().findall("record")`, `json.load(...)["records"]`).

### Count reconciliation

Always state the chain to the user:

```
site says 150 → list pages read 150 (no S.No gaps) → captured 150 → exported 150 rows (+38 child rows)
```

If any number differs, stop and explain before calling the run done.

### Manual spot-check (do it every time)

Pick 3–5 random records (`random.sample`, include one with children / documents). For each,
open the live page (or its screenshot from this run) next to the exported row and compare every
field. Click one document link from the Excel file in a clean browser (no cookies) to prove it
works without a login.

### Report template for the user

```
Verification — records_full.csv (run 20261126-0700_incremental)
  OK  file opens (utf-8-sig, 188 rows, 31 columns)
  OK  row count 188 = expected 188
  OK  key "Ref" unique, none empty
  OK  required ID, Title: 100% filled
  OK  dates parse in "Closing Date" (188/188)
  !!  "Document URL": 2 malformed: 1042 (1), 1077
  OK  CSV and XLSX agree (columns, rows, keys)
Spot-check: 1003, 1018, 1101 match the live site.
Explanation of !!: the site shows no document for those two; left empty on purpose → fixed check.
```
