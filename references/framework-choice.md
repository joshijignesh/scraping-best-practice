# Choosing the fetch framework

Probe first (SKILL.md step 1a), then pick the **simplest tool that gets the real data**.
The rest of the project (captures, parsers, export, verify, runs) stays identical.

## Decision table

| What the probe shows | Use | Why |
|---|---|---|
| A JSON/XHR API returns the data | `httpx` / `requests` against the API | Structured, fast, stable. Save the JSON as the capture. |
| Plain GET returns full HTML, few hundred pages | `httpx` / `requests` + `selectolax` / `lxml` / `BeautifulSoup` | Simple, no browser. |
| Plain HTML, thousands+ pages, many domains, concurrency wanted | **Scrapy** | Scheduler, concurrency, autothrottle, retries, HTTP cache, `JOBDIR` resume. |
| JS-rendered content, CSRF/hashed form fields computed in JS, popups, clicks to reveal links | **Playwright** (Chromium, headless) | Runs the site's own JS. Call the site's own functions (`page.evaluate("getDetail('123')")`) instead of re-implementing them. |
| Scrapy scale + some JS pages | `scrapy-playwright` | Browser only where needed. |
| Login required | Any of the above + saved `storage_state` / session cookie in `.env` (never committed) | Ask the user for credentials handling. |
| Captcha / aggressive bot protection | Stop and discuss with the user | Check terms of use; consider an official API or data agreement. |

Real case: a tender portal returned a "Security Page" to every plain HTTP request because each
request carried a CSRF token and hashed fields computed by the portal's JavaScript. Playwright
calling the portal's own functions (e.g. `getDetail(id)`, `showPage(n)`, `viewAmendments()`) worked. Records
had to be fetched one at a time ≥ 2 s apart, so Scrapy's concurrency would not have helped.

## Parsers

- `selectolax` (fastest), `lxml` (XPath, fast), `BeautifulSoup` (forgiving, with `lxml` backend).
- Parse **by label text** ("Closing Date :") rather than cell position, so records with extra or
  missing fields still parse.
- Normalise text: `unicodedata.normalize("NFKC")`, replace `\xa0`, collapse whitespace.
- Convert dates to ISO (`YYYY-MM-DD HH:MM`) in the parser; keep timezone stated in the README.

## Mapping the standard layout onto each framework

| Module | requests/httpx | Playwright | Scrapy |
|---|---|---|---|
| `fetcher.py` | Client with throttle, retries, block-page check | `Portal` class: browser, context, `call()`, `open_popup()`, `capture()` | The spider (`spiders/<site>.py`), settings in `settings.py` fed from `config.toml` |
| `captures.py` | same | same | An item pipeline writes raw `response.text` into `data/captures/…` |
| `parsers.py` | pure functions | pure functions | pure functions called from `parse_*` callbacks (testable without Scrapy) |
| `scraper.py` | list → decide → capture loop | same | spider `start_requests` + `parse` callbacks; incremental decision via captures meta |
| `export.py` / `verify.py` | same | same | same — don't rely only on `FEEDS`, build outputs from captures |
| Screenshots | optional render of saved HTML | `page.screenshot(full_page=True)` | optional (`scrapy-playwright`) |
| Fresh clean | captures + `requests-cache` DB | captures + `storage_state` | captures + `.scrapy/httpcache` + `JOBDIR` |

## Politeness defaults

```toml
min_delay_seconds = 2.0          # Scrapy: DOWNLOAD_DELAY / AUTOTHROTTLE_ENABLED
retries = 2                      # with backoff + new session
abort_after_consecutive_failures = 5
navigation_timeout_seconds = 60
user_agent = ""                  # empty = framework/browser default; never impersonate a person
```

Block-page detection: check every response for markers (captcha, "Access denied", "Security
Page", login form where data was expected, HTTP 403/429, suspiciously empty list) and raise a
distinct `BlockedError` so retries start a new session instead of parsing garbage.
