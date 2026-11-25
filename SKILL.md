---
name: scraping-best-practice
description: Step-by-step best-practice workflow to start, build, or restructure any web scraping project, whatever the framework (Playwright, Scrapy, requests/httpx + BeautifulSoup/lxml/selectolax, or a site's JSON API). Use whenever the user wants to scrape a website or portal into CSV/Excel/XML/JSON/DOCX, set up a new scraper project, add export/sample/full runs, debug extraction, keep screenshots of every site visit, force a clean re-fetch, schedule weekly / every-15-days / monthly runs, or push a scraper to GitHub. Enforces the order: structure → export → debug → cross-verify → screenshots → clean/fresh → sample → full → (client-approved) schedule → GitHub.
---

# Scraping Best Practice

A gated, ten-step workflow for every scraping project. It was distilled from a production
scraper (a tender portal behind CSRF tokens, ~170 records, incremental daily runs, CSV + Excel
output) but is framework-agnostic: the steps and the folder contract stay the same whether the
fetcher is Playwright, Scrapy, httpx or an API client.

**Never jump straight to a full scrape.** Each step ends with a gate. Do not start the next
step until the gate is met, and show the user the evidence (console output, report, file paths).

## Core principles

1. **Fetch and parse are separate.** Save every raw response (HTML / JSON) to disk first.
   Build every output from the saved copies. Exports, previews and checks never touch the site.
2. **Data comes from HTML/JSON, never from screenshots.** Screenshots are evidence for humans
   (OCR misreads digits and dates).
3. **Sample → full → schedule.** A full run only after the sample is approved; a schedule only
   after the client approves the full result and asks for it.
4. **Every run leaves evidence:** a log, a `summary.json`, screenshots, and a manifest, in its
   own timestamped run folder, so site-visit iterations can be compared.
5. **Atomic writes.** Capture into a staging folder, swap in only when complete. A run that dies
   halfway never leaves half-updated data.
6. **Be polite and robust.** Throttle (min delay between requests), retry with backoff and a new
   session, abort after N consecutive failures, one run at a time (lock file), detect block pages
   (captcha / "security page" / 403 / empty result) as a distinct error.
7. **Settings in `config.toml`, not code.** Reject unknown keys so typos fail loudly.
8. **Incremental by default**, with `--full` (re-fetch all) and `--fresh` (wipe, then re-fetch).
9. **Respect the site.** Check `robots.txt` and the terms of use, scrape only public data the
   user is entitled to, avoid collecting personal data that isn't needed.

## The ten steps

| # | Step | Gate before moving on |
|---|---|---|
| 1 | Structure (probe site, pick framework, scaffold) | User agrees on framework, fields, unique key |
| 2 | Export option (CSV, Excel default; XML, JSON, DOCX on request) | Output schema + selected formats agreed |
| 3 | Debug before final result | Console preview of real records looks right |
| 4 | Cross-verify the export | Verification report has no unexplained `!!` |
| 5 | Screenshots per site visit | Each run has its own folder of screenshots + manifest |
| 6 | Force clean & fresh re-fetch | `clean` (dry-run → `--yes`) and `run --fresh` work |
| 7 | Sample first | **User/client approves the sample** |
| 8 | Full scrape | Full export verified, counts match the site |
| 9 | Schedule (weekly / 15 days / monthly) | **Only on explicit client approval and on demand** |
| 10 | Push to the GitHub repo | Pushed to the repo the user named |

Version control starts at step 1 (`git init`, commit at every gate); step 10 is when it goes to
the remote.

---

### Step 1 — Structure

**1a. Probe the site before writing code.** Answer, and write the answers into the README:

- Does a plain HTTP GET return the data? Or is it JS-rendered, behind CSRF tokens / hashed form
  fields, a login, or a captcha?
- Is there a JSON/XHR API behind the page (browser DevTools → Network)? An API beats HTML.
- Pagination type (page numbers, "load more", cursor, infinite scroll) and total count shown.
- List page → detail page → sub-pages/popups/documents: map every page type you need.
- Volume (records, pages) and a polite rate. `robots.txt` and terms of use.
- Does the list contain duplicates or skip records across pages? (Real case: one sort order
  repeated rows and dropped others; reading a second sort order and merging by ID fixed it.)

Save one real copy of every page type to `tests/fixtures/` during the probe.

**1b. Choose the framework** with [references/framework-choice.md](references/framework-choice.md).
Record *why* in the README ("Why Playwright and not Scrapy: …").

**1c. Scaffold** the standard layout — see [references/project-layout.md](references/project-layout.md)
for the full tree, module responsibilities and code skeletons:

```
<project>/
  <pkg>/  __main__.py  config.py  fetcher.py  parsers.py  captures.py
          runs.py  scraper.py  export.py  verify.py
  tests/  fixtures/  test_parsers.py  test_export.py
  scripts/ setup.sh  run.sh  export.sh  schedule.sh
  config.toml  requirements.txt (pinned)  README.md  .gitignore
  data/   (gitignored) captures/  runs/  exports/  last_run.json
```

One module talks to the site (`fetcher.py` / the spider). Parsers are pure functions.
Start from [templates/config.toml](templates/config.toml) and [templates/gitignore](templates/gitignore).
Run `git init` and make the first commit.

**Gate:** confirm with the user: framework, the field list (output columns), the unique key of a
record, which pages are in scope, and the export formats (step 2).

### Step 2 — Export option

**Ask the user which formats this project needs.** Five are supported; build **only the ones
selected**. Don't code every format up front.

| Format | Default? | Library | Typical use |
|---|---|---|---|
| CSV | **yes** | stdlib `csv` (`utf-8-sig`) | Universal, imports anywhere |
| Excel (`.xlsx`) | **yes** | `openpyxl` | Client-facing: real dates, clickable links, frozen header, filters |
| XML | on request | stdlib `xml.etree.ElementTree` | ERP / legacy system imports |
| JSON | on request | stdlib `json` | APIs, apps, nested records |
| DOCX | on request | `python-docx` | Printable report / client document |

If the user doesn't choose, implement **CSV + Excel** and say so. Record the choice in
`config.toml` (`[export] formats = ["csv", "excel"]`) and the README. Adding a format later means
adding one writer function and one entry to the registry. Nothing else changes.

Define the schema before scraping at scale: column order, unique key, types (dates as real dates),
one row per record (child rows, e.g. amendments, follow their parent with a `Ref` like `123 (2)`).
All writers take the same `(columns, rows)` built once from captures, so every format carries the
same data.

- Exports are built **from captures**, never during fetching: `export` (formats from config) or
  `export --format csv json` to override. One command writes **all** selected formats, so no
  format goes stale while another is refreshed.
- Separate files per scope: `<name>_sample.*` and `<name>_full.*`. Delete stale outputs first;
  write to a temp file and rename (atomic).
- Store stable URLs only (record the link the site's own click opens; don't store short-lived
  redirect targets).

Writer registry and a snippet for each of the five formats: [references/export.md](references/export.md).

### Step 3 — Debug before final result

Make the scraper easy to look into **before** any final output is produced:

- `run --limit 3`, `run --id <ID ...>`, `run --headed` (watch the browser), `--log-level DEBUG`.
- A `log` command prints full parsed records + a data check from captures (no site access).
- Every parse problem → save that page into `tests/fixtures/`, write a failing test, fix the
  parser (parse by label text, not by cell position).
- Distinguish errors: block page / timeout / layout change / genuinely missing field.
- Don't "fix" flakiness with longer sleeps blindly: wait for the specific element/navigation.

**Gate:** show the user the console preview of 3–5 real records and the data-check lines.

### Step 4 — Cross-verify the export

Verify the **written file**, not the in-memory data. Run
[templates/verify_export.py](templates/verify_export.py) (copy it into the project as
`<pkg>/verify.py` or `scripts/verify_export.py`):

```bash
python scripts/verify_export.py data/exports/<name>_full.csv --key Ref \
  --required "ID" "Title" --date-cols "Due Date" --url-cols "Document URL" \
  --expected <count shown on site> --compare data/exports/<name>_full.xlsx
```

It checks: file opens, header sane, row count vs expected, key unique and non-empty, required
fill rate, dates parse, URLs well-formed (optionally live-checks a few), CSV and Excel agree,
leftover `None`/`nan`/whitespace, formula-injection cells. Then **spot-check 3–5 random records
against the live site or the screenshots**. Full checklist: [references/verification.md](references/verification.md).

**Gate:** report has no `!!` lines, or each one is explained to the user.

### Step 5 — Screenshots of every site visit (iteration history)

- `data/captures/` = the **latest** raw HTML/JSON per record (source of truth for exports).
- `data/runs/<YYYYmmdd-HHMMSS>_<mode>/` = **one folder per run**, kept for comparison:
  `screenshots/`, `run.log`, `summary.json` (counts, warnings, status), `manifest.json`
  (every URL visited, time, HTTP status, sha256 of the HTML, screenshot path).
- Full-page screenshots; expand fixed-height iframes / scroll containers first. Name them
  `<page-type>_<record-id>.png`. `jpeg` is 3–5× smaller than `png`.
- `keep_runs` in config prunes old run folders (default 20). HTTP-only frameworks (Scrapy,
  httpx) save raw responses per run; screenshots are optional there (render saved HTML with
  Playwright if the client wants pictures).

Recorder skeleton: [references/project-layout.md](references/project-layout.md#runs-recorder).

### Step 6 — Force clean & fresh re-fetch

- `clean` lists what it would delete; `clean --yes` deletes it. `run --fresh` = clean + full run.
- Clears **all old references**: captures, staging folders, exports, `last_run.json`, HTTP caches
  (`.scrapy/httpcache`, `requests-cache` DBs), Scrapy `JOBDIR`, browser `storage_state` / cookies,
  incremental hashes. Keeps config, code and `tests/fixtures/`. `--keep-runs` keeps run history.
- Never runs while another run holds the lock. Always confirm with the user before `--yes`.

### Step 7 — Always produce a sample first

`run --sample` (first page, or `sample_size` records, default 10–50) → `export` → `verify`.
Hand the user: the `_sample.csv/.xlsx` paths, the console preview, the verification report and
the screenshots folder of that run.

**Gate:** the user/client approves the sample (fields, formats, values). Loop steps 3–5 until then.

### Step 8 — Full scrape

`run` (incremental) or `run --full` → `export` → `verify --expected <site total>`.
- Progress logs `[n/N] <id>: <reason>`; failures are recorded and the run continues.
- Re-running resumes: unchanged records are read from captures, only new/changed/failed ones
  are fetched. Remove records that left the site only when the whole list was read completely.
- Exit code non-zero when anything failed or the list was incomplete.

**Gate:** report total on site vs captured vs exported, failures, warnings, and the output paths.

### Step 9 — Schedule the automation (approval-gated)

**Do not schedule anything unless the client approved the full result and the user explicitly
asks for it.** Ask which cadence, day and time, then use
[templates/schedule.sh](templates/schedule.sh) (macOS launchd / Linux cron):

```bash
./scripts/schedule.sh weekly MON 07:00   --approved-by "Client name, 2026-11-26"
./scripts/schedule.sh every15 07:00      --approved-by "…"   # 1st and 15th of each month
./scripts/schedule.sh monthly 1 07:00    --approved-by "…"
./scripts/schedule.sh status | run-now | remove
```

The approval is logged in `schedule_approvals.log`. Scheduled jobs run the full incremental run
+ export + verify, use the lock, log to `data/logs/`, and notify on failure. Other targets
(systemd timers, GitHub Actions cron, Windows Task Scheduler) and caveats (macOS can't run
launchd jobs from `~/Documents` without Full Disk Access): [references/scheduling.md](references/scheduling.md).

### Step 10 — Push to the specific GitHub repo

Ask for the exact repo (`owner/name`) and branch if not given; never guess or create a public repo
on your own. Make sure `.gitignore` excludes `data/`, `.venv/`, `.env`, cookies/`storage_state`,
logs **before** the first `git add`. Review `git status`, commit, add the remote, push; tag
milestones (`v0.1-sample`, `v1.0-full`, `v1.1-scheduled`). Scraped data and credentials are never
committed unless the user explicitly asks. Steps: [references/github.md](references/github.md).

---

## Command contract (every project exposes these)

| Command | Touches site? | Purpose |
|---|---|---|
| `run --sample` | yes | Sample run (step 7) |
| `run` / `run --full` / `run --fresh` | yes | Incremental / re-fetch all / wipe then re-fetch |
| `run --id X --limit N --headed` | yes | Debug a record (step 3) |
| `log [--id X]` | no | Print parsed records + data check |
| `export [--format csv excel xml json docx] [--sample]` | no | Build outputs from captures (default: formats in config) |
| `verify` | no | Cross-verify the written files (step 4) |
| `status` | no | Last run summary + warnings |
| `clean [--yes] [--keep-runs]` | no | Dry-run / wipe all saved data |

Wrap them in `scripts/*.sh` so the client can run them without knowing Python.

## Reporting to the user at each gate

- What ran (command), how long, counts (on site / fetched / from cache / failed).
- Paths: export files, run folder with screenshots, log.
- The verification report lines, and any warning with your explanation.
- The next step and what you need from them (approval, repo name, cadence).

## Finished project checklist

- [ ] README: what it scrapes, commands, output columns, "why this framework", known gaps
- [ ] `config.toml` documented; unknown keys rejected
- [ ] Parser tests on real fixtures pass
- [ ] Sample approved → full verified → counts match
- [ ] Each run has its own screenshots + manifest + summary
- [ ] `clean` / `--fresh` tested
- [ ] Schedule installed only with logged approval
- [ ] Pushed to the named repo; no data or secrets committed
