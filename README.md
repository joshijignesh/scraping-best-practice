# scraping-best-practice

A [Claude Code](https://claude.com/claude-code) **skill** that makes every web scraping project
follow the same ten gated steps: structure, export, debug, cross-verify, screenshots, clean
re-fetch, sample, full run, approved scheduling and version control. It works with any
framework (Playwright, Scrapy, requests/httpx + BeautifulSoup/lxml/selectolax, or a site's own
JSON API).

The workflow comes from a production scraper for a JavaScript-heavy procurement portal: CSRF
tokens, popups, document links, incremental runs, CSV + Excel output. It is written so the next
project starts from what worked there, not from a blank file.

## Why

Most scrapers start as one script that goes straight to a full crawl and writes a CSV nobody
checked. This skill enforces an order instead:

| # | Step | Gate before moving on |
|---|---|---|
| 1 | **Structure**: probe the site, pick the framework, scaffold the standard layout | Framework, fields and unique key agreed |
| 2 | **Export option**: CSV + Excel by default; XML, JSON, DOCX on request | Schema and selected formats agreed |
| 3 | **Debug before final result**: `--limit`, `--id`, `--headed`, console preview | Real records look right |
| 4 | **Cross-verify** the written files, not the in-memory data | Verification report clean |
| 5 | **Screenshots of every site visit**: one folder per run, with manifest | Iterations can be compared |
| 6 | **Force clean & fresh re-fetch**: clears captures, caches and sessions | `clean` / `--fresh` work |
| 7 | **Sample first** | Client approves the sample |
| 8 | **Full scrape**, incremental and resumable | Counts match the site |
| 9 | **Schedule** weekly / every 15 days / monthly | Only after client approval, on demand |
| 10 | **Push** to the named GitHub repo | No data or secrets committed |

Core rules: fetching and parsing are separate (raw HTML/JSON is saved first and every export is
built from it); data is never read from screenshots; captures are swapped in atomically; requests
are throttled, retried and guarded by a lock; settings live in `config.toml`.

## Install

Globally (available in every project):

```bash
git clone https://github.com/joshijignesh/scraping-best-practice.git ~/.claude/skills/scraping-best-practice
```

For one project only:

```bash
git clone https://github.com/joshijignesh/scraping-best-practice.git .claude/skills/scraping-best-practice
```

Update later with `git -C ~/.claude/skills/scraping-best-practice pull`.

## Use

In Claude Code, either type `/scraping-best-practice`, or just describe the job. The skill
loads on its own when you ask for things like:

- "Scrape the listings on example.com into Excel."
- "Set up a new scraper project for this portal, using Scrapy."
- "The export is missing rows, help me debug it."
- "Schedule this scraper every 15 days." (Claude asks for the client's approval first.)

Claude then goes through the steps in order and stops at each gate with the evidence:
console preview, verification report, file paths, screenshots folder.

## What's inside

```
SKILL.md                      the ten steps, gates, command contract, checklist
references/
  framework-choice.md         Playwright vs Scrapy vs httpx vs API: decision table + mapping
  project-layout.md           folder tree, config loader, run lock, clean, run recorder, loop
  export.md                   writer registry + CSV, Excel, XML, JSON, DOCX writers
  verification.md             debug toolkit, cross-verify checklist, report template
  scheduling.md               launchd, cron, systemd, GitHub Actions, Windows; 15-day cadence
  github.md                   local git from day one, pushing safely, what never to commit
templates/
  config.toml                 documented settings (unknown keys are rejected)
  gitignore                   keeps data, caches, sessions and secrets out of git
  verify_export.py            standalone cross-verifier for CSV / XLSX / JSON / XML
  schedule.sh                 weekly / every15 / monthly scheduler with an approval guard
```

### Templates on their own

The templates work without Claude, too.

**`verify_export.py`** checks an export file after it is written. It needs only the standard
library, plus `openpyxl` for `.xlsx`:

```bash
python templates/verify_export.py data/exports/records_full.csv \
  --key Ref --required ID Title --date-cols "Closing Date" --url-cols "Document URL" \
  --expected 150 --compare data/exports/records_full.xlsx --check-urls 3
```

It checks: row count against the site, unique key, required fill, dates parse, URLs well-formed
(and optionally live), placeholder strings like `None`/`nan`, whitespace, formula-injection
cells, empty columns, CSV vs XLSX vs JSON vs XML agreement, sample ⊂ full, and stale files.
Exit code `0` = passed, `1` = failures.

**`schedule.sh`** installs the schedule with launchd on macOS or crontab on Linux, and refuses to
run without an approval:

```bash
./scripts/schedule.sh weekly MON 07:00 --approved-by "Client name, 2026-11-26"
./scripts/schedule.sh every15 07:00    --approved-by "..."   # 1st and 15th of each month
./scripts/schedule.sh monthly 1 07:00  --approved-by "..."
./scripts/schedule.sh status | run-now | remove
```

## Responsible scraping

The skill tells Claude to check `robots.txt` and the site's terms, throttle requests, collect
only data you are entitled to, and stop to ask when it meets a captcha or bot protection. You
are responsible for how you use it.

## License

[MIT](LICENSE) © 2026 Jignesh Joshi
