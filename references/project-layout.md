# Project layout and code skeletons

## Tree

```
<project>/
  <pkg>/
    __init__.py
    __main__.py    CLI: run | log | export | verify | status | clean   (+ run lock, logging)
    config.py      loads config.toml into a dataclass; rejects unknown keys; validates enums
    fetcher.py     the ONLY module that talks to the site: session, throttle, retries,
                   block-page detection, capture(html + screenshot)
                   (Scrapy: spiders/<site>.py + pipelines.py instead)
    parsers.py     raw HTML/JSON -> dicts. Pure functions, no network, no disk
    captures.py    data/captures/ layout: read/write, staging + atomic commit, cleanup
    runs.py        data/runs/<run_id>/: screenshots, manifest, run.log, summary.json, pruning
    scraper.py     one run: read list -> decide what to fetch -> capture each -> summary
    export.py      captures -> only the selected formats (csv, excel by default)
    preview.py     captures -> console records + data check  (the `log` command)
    verify.py      cross-verify written export files (copy of templates/verify_export.py)
  tests/
    fixtures/      real pages saved from the site, one per page type (+ edge cases)
    test_parsers.py
    test_export.py
  scripts/
    setup.sh       venv, pip install -r requirements.txt, playwright install chromium (if used)
    run.sh         exec .venv/bin/python -m <pkg> run "$@"
    export.sh      exec .venv/bin/python -m <pkg> export "$@"
    log.sh         exec .venv/bin/python -m <pkg> log "$@"
    schedule.sh    from templates/schedule.sh (step 9 only)
  config.toml
  requirements.txt  pinned versions (==)
  README.md
  .gitignore        from templates/gitignore
  data/             gitignored
    captures/       latest raw pages per record (source of truth for exports)
    runs/<run_id>/  per-run evidence: screenshots/, manifest.json, run.log, summary.json
    exports/        <name>_sample.* and <name>_full.*
    logs/           scheduler stdout/stderr
    last_run.json   copy of the latest summary (for `status`)
    .run.lock
```

## Captures layout (example)

```
captures/
  list/<view>_page_<n>.html            list pages as last read
  records/<record_id>/
    meta.json                          list row, list_hash, first_seen, captured_at
    detail.html                        one file per page type
    <subpage>.html
    children/<child_id>/<tab>.html     popups / amendments / nested pages
    document_url.txt                   stable link recorded from the site's own click
```

Rules:
- Re-capture a record into `records/.staging_<id>/`, then swap it in with `rename` only when
  complete. Copy forward cached children that were not re-fetched.
- `meta.json.list_hash` = hash of the list-row fields that signal change (title, due date,
  amendment icon). Incremental decision = new | hash changed | older than `refresh_after_days`
  | a child/link missing. Otherwise read from captures.
- Delete records that left the site **only** when the whole list was read with no gaps.

## config.py

```python
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

@dataclass
class Config:
    base_url: str = ""
    mode: str = "incremental"               # incremental | full
    refresh_after_days: int = 7
    min_delay_seconds: float = 2.0
    navigation_timeout_seconds: int = 60
    retries: int = 2
    abort_after_consecutive_failures: int = 5
    headless: bool = True
    sample_size: int = 20
    screenshots: bool = True
    screenshot_format: str = "png"          # png | jpeg
    keep_runs: int = 20
    formats: list = field(default_factory=lambda: ["csv", "excel"])
    basename: str = "records"
    data_dir: Path = ROOT / "data"

def load_config(path: Path | None = None) -> Config:
    path = path or ROOT / "config.toml"
    raw = tomllib.loads(path.read_text()) if path.exists() else {}
    known, cfg = {f.name for f in fields(Config)}, Config()
    for section in raw.values():
        for k, v in section.items():
            if k not in known:
                raise ValueError(f"Unknown setting in {path.name}: {k}")
            setattr(cfg, k, v)
    cfg.data_dir = Path(cfg.data_dir) if Path(cfg.data_dir).is_absolute() else ROOT / cfg.data_dir
    assert cfg.mode in ("incremental", "full"), "mode must be incremental|full"
    assert set(cfg.formats) <= {"csv", "excel", "xml", "json", "docx"}, "unknown export format"
    return cfg
```

## Run lock and clean (in `__main__.py`)

```python
import fcntl, shutil

def acquire_lock(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    fh = open(data_dir / ".run.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)   # Windows: use msvcrt.locking or portalocker
        return fh
    except BlockingIOError:
        fh.close(); return None

CACHE_PATHS = [".scrapy", "http_cache.sqlite", "storage_state.json"]   # framework caches to wipe

def clean(cfg, keep_runs=False, dry_run=True) -> list[str]:
    targets = [p for p in cfg.data_dir.iterdir() if p.name != ".run.lock"
               and not (keep_runs and p.name == "runs")] if cfg.data_dir.exists() else []
    targets += [ROOT / c for c in CACHE_PATHS if (ROOT / c).exists()]
    if not dry_run:
        for p in targets:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    return [str(p.relative_to(ROOT)) for p in targets]
```

`clean` prints the dry-run list; `clean --yes` deletes; `run --fresh` = `clean(dry_run=False)` + full run.

## Runs recorder

One folder per run keeps every site visit's screenshots for comparison across iterations.

```python
import hashlib, json, logging, shutil
from datetime import datetime
from pathlib import Path

class RunRecorder:
    def __init__(self, data_dir: Path, mode: str, keep: int = 20, screenshot_format="png"):
        self.id = f"{datetime.now():%Y%m%d-%H%M%S}_{mode}"
        self.dir = data_dir / "runs" / self.id
        self.shots = self.dir / "screenshots"
        self.shots.mkdir(parents=True)
        self.ext = "jpg" if screenshot_format == "jpeg" else "png"
        self.fmt = screenshot_format
        self.manifest: list[dict] = []
        self.keep = keep
        fh = logging.FileHandler(self.dir / "run.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
        logging.getLogger().addHandler(fh)

    def screenshot_path(self, page_type: str, record_id: str = "") -> Path:
        name = f"{page_type}_{record_id}" if record_id else page_type
        return self.shots / f"{name}.{self.ext}"

    def visited(self, url: str, page_type: str, record_id: str, html: str,
                status: int | None = None, screenshot: Path | None = None) -> None:
        self.manifest.append({
            "time": datetime.now().isoformat(timespec="seconds"), "url": url,
            "page_type": page_type, "record_id": record_id, "status": status,
            "sha256": hashlib.sha256(html.encode()).hexdigest()[:16],
            "screenshot": str(screenshot.relative_to(self.dir)) if screenshot else None,
        })

    def finish(self, summary: dict, data_dir: Path) -> None:
        summary = {"run_id": self.id, **summary}
        (self.dir / "manifest.json").write_text(json.dumps(self.manifest, indent=2))
        (self.dir / "summary.json").write_text(json.dumps(summary, indent=2))
        (data_dir / "last_run.json").write_text(json.dumps(summary, indent=2))
        runs = sorted(p for p in self.dir.parent.iterdir() if p.is_dir())
        for old in runs[:-self.keep] if self.keep else []:
            shutil.rmtree(old)
```

Playwright capture helper (in `fetcher.py`):

```python
def capture(self, base: Path, html: str, page, recorder, page_type, record_id):
    base.parent.mkdir(parents=True, exist_ok=True)
    base.with_suffix(".html").write_text(html, encoding="utf-8")       # data source
    shot = None
    if self.cfg.screenshots:
        shot = recorder.screenshot_path(page_type, record_id)            # evidence, per run
        page.screenshot(path=str(shot), full_page=True, type=self.cfg.screenshot_format)
    recorder.visited(page.url, page_type, record_id, html, screenshot=shot)
```

Compare two iterations: `diff <(jq -r '.[]|.record_id+" "+.sha256' runs/A/manifest.json) <(jq … runs/B/manifest.json)`
shows exactly which pages changed between site visits.

## Fetcher essentials (any framework)

- `_throttle()` before every request: sleep until `min_delay_seconds` since the last one.
- `_check(response)` after every request: raise `BlockedError` on block-page markers.
- `new_session()` on retry: fresh cookies / browser context / CSRF token.
- Playwright: block calls to `localhost` helpers the site probes, dismiss dialogs, set
  `locale` / `timezone_id` to the site's, wait for `networkidle` or a specific selector.
- Record document links from the site's own click (`expect_popup` → URL), not by building them.

## Scraper loop essentials

```python
for n, (row, why) in enumerate(todo, 1):
    log.info("[%d/%d] %s: %s", n, len(todo), row["id"], why)
    try:
        retry(lambda: capture_record(row)); stats["fetched"] += 1; fails = 0
    except Exception as exc:
        stats["failed"] += 1; fails += 1; warnings.append(f"{row['id']}: {exc}")
        if fails >= cfg.abort_after_consecutive_failures:
            warnings.append("aborted: too many failures in a row"); break
status = "ok" if list_complete and not stats["failed"] else "partial"
return 0 if status == "ok" else 1
```

## Tests

- `test_parsers.py`: one test per page type on `tests/fixtures/*.html`, asserting real values.
- `test_export.py`: build captures in a temp dir from fixtures, write each selected format,
  re-read it, assert columns, row count, a known value, and that sample ⊂ full.
- Run: `.venv/bin/python -m unittest discover tests` (or `pytest`).
