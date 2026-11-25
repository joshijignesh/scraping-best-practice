#!/usr/bin/env python3
"""Cross-verify an exported file (CSV, XLSX, JSON or XML) after it was written.

Checks the file on disk, not the scraper's in-memory data:
  file opens · header sane · row count vs expected · unique non-empty key · required fill ·
  dates parse · URLs well-formed (optionally live-checked) · placeholder strings · whitespace ·
  formula-injection cells · empty columns · agreement with another export (--compare) ·
  sample is a subset of full (--subset-of).

Usage:
  python verify_export.py data/exports/records_full.csv --key Ref \
      --required "ID" "Title" --date-cols "Closing Date" --url-cols "Document URL" \
      --expected 150 --compare data/exports/records_full.xlsx --check-urls 3 \
      --json data/runs/<run_id>/verify_full.json

Exit code 0 = no failures (warnings allowed), 1 = at least one failure, 2 = file unreadable.
Needs openpyxl only for .xlsx files. Everything else is the standard library.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

PLACEHOLDERS = {"none", "nan", "null", "nat", "undefined"}
DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S",
    "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y",
    "%d %b %Y", "%d %B %Y",
)


# --------------------------------------------------------------------------- reading
def read_table(path: Path, sheet: str | None = None) -> tuple[list[str], list[list]]:
    """(header, rows as lists) for .csv / .xlsx / .json / .xml."""
    ext = path.suffix.lower()
    if ext == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as f:
            table = list(csv.reader(f))
        return (table[0], table[1:]) if table else ([], [])
    if ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb[sheet] if sheet else wb.active
        table = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        while table and all(v in (None, "") for v in table[-1]):
            table.pop()
        if not table:
            return [], []
        header = ["" if v is None else str(v) for v in table[0]]
        return header, [r + [None] * (len(header) - len(r)) for r in table[1:]]
    if ext in (".json", ".jsonl"):
        text = path.read_text(encoding="utf-8")
        if ext == ".jsonl":
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            data = json.loads(text)
            records = data.get("records", data) if isinstance(data, dict) else data
        header = list(data.get("columns", [])) if ext == ".json" and isinstance(data, dict) else []
        for rec in records:
            header += [k for k in rec if k not in header]
        return header, [[rec.get(k) for k in header] for rec in records]
    if ext == ".xml":
        root = ET.parse(path).getroot()
        header: list[str] = []
        rows_d = []
        for item in root:
            rec = {(child.get("label") or child.tag): (child.text or "") for child in item}
            header += [k for k in rec if k not in header]
            rows_d.append(rec)
        return header, [[r.get(k) for k in header] for r in rows_d]
    raise ValueError(f"Unsupported file type: {ext} (csv, xlsx, json, jsonl, xml)")


def as_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def parses_as_date(v) -> bool:
    if isinstance(v, (datetime, date)):
        return True
    s = as_text(v).strip()
    for fmt in DATE_FORMATS:
        try:
            datetime.strptime(s, fmt)
            return True
        except ValueError:
            pass
    try:
        datetime.fromisoformat(s)
        return True
    except ValueError:
        return False


def is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------- report
class Report:
    def __init__(self, path: Path):
        self.path = path
        self.lines: list[dict] = []

    def add(self, level: str, text: str, items: list[str] | None = None) -> None:
        self.lines.append({"level": level, "text": text, "items": list(items or [])})
        tag = {"ok": "  OK  ", "fail": "  !!  ", "warn": "  WARN"}[level]
        more = ""
        if items:
            more = f": {', '.join(map(str, items[:10]))}{' …' if len(items) > 10 else ''}"
        print(f"{tag} {text}{more}")

    def check(self, ok: bool, text: str, items: list[str] | None = None, warn_only: bool = False) -> None:
        self.add("ok" if ok else ("warn" if warn_only else "fail"), text, None if ok else items)

    @property
    def failed(self) -> bool:
        return any(line["level"] == "fail" for line in self.lines)


# --------------------------------------------------------------------------- checks
def verify(args) -> Report:
    path = Path(args.file)
    rep = Report(path)
    print(f"\nVerification — {path}")
    try:
        header, rows = read_table(path, args.sheet)
    except Exception as exc:  # noqa: BLE001
        rep.add("fail", f"file could not be read: {exc}")
        return rep
    rep.check(bool(header), f"file opens ({len(rows)} rows, {len(header)} columns)", ["no header row"])
    if not header:
        return rep

    dupes = sorted({h for h in header if header.count(h) > 1})
    blanks = [str(i + 1) for i, h in enumerate(header) if not str(h).strip()]
    rep.check(not dupes and not blanks, "header: names unique and non-empty",
              [f"duplicate {d!r}" for d in dupes] + [f"blank column #{b}" for b in blanks])

    col = {h: i for i, h in enumerate(header)}
    get = lambda r, name: r[col[name]] if col[name] < len(r) else None  # noqa: E731

    def key_of(r) -> str:
        return as_text(get(r, args.key)).strip() if args.key else ""

    if args.expected is not None:
        rep.check(len(rows) == args.expected, f"row count {len(rows)} = expected {args.expected}",
                  [f"got {len(rows)}"])
    rep.check(len(rows) > 0, "file has data rows", ["0 rows"])

    for name in [args.key] + list(args.required) + list(args.date_cols) + list(args.url_cols):
        if name and name not in col:
            rep.add("fail", f"column {name!r} missing", [f"have: {', '.join(header[:12])}…"])
    if args.key and args.key in col:
        keys = [key_of(r) for r in rows]
        empty = [str(i + 2) for i, k in enumerate(keys) if not k]
        seen, dup = set(), []
        for k in keys:
            if k and k in seen:
                dup.append(k)
            seen.add(k)
        rep.check(not empty, f"key {args.key!r} never empty", [f"row {e}" for e in empty])
        rep.check(not dup, f"key {args.key!r} unique", sorted(set(dup)))

    for name in args.required:
        if name in col:
            missing = [key_of(r) or f"row {i + 2}" for i, r in enumerate(rows) if not as_text(get(r, name)).strip()]
            rep.check(not missing, f"required {name!r}: {len(rows) - len(missing)}/{len(rows)} filled", missing)

    for name in args.date_cols:
        if name in col:
            vals = [(key_of(r) or f"row {i + 2}", get(r, name)) for i, r in enumerate(rows)]
            filled = [(k, v) for k, v in vals if as_text(v).strip()]
            bad = [f"{k}={as_text(v)!r}" for k, v in filled if not parses_as_date(v)]
            rep.check(not bad, f"dates parse in {name!r} ({len(filled) - len(bad)}/{len(filled)})", bad)

    urls: list[str] = []
    for name in args.url_cols:
        if name in col:
            bad = []
            for i, r in enumerate(rows):
                u = as_text(get(r, name)).strip()
                if not u:
                    continue
                p = urlparse(u)
                if p.scheme in ("http", "https") and p.netloc:
                    urls.append(u)
                else:
                    bad.append(key_of(r) or f"row {i + 2}")
            rep.check(not bad, f"URLs well-formed in {name!r} ({len(urls)} links)", bad)
    if args.check_urls and urls:
        sample = random.sample(urls, min(args.check_urls, len(urls)))
        dead = [f"{u[:80]} ({status})" for u in sample if (status := probe_url(u)) != "ok"]
        rep.check(not dead, f"{len(sample) - len(dead)}/{len(sample)} random URLs answer", dead)

    placeholder, spaces, formula = [], [], []
    for i, r in enumerate(rows):
        for h in header:
            v = get(r, h)
            if not isinstance(v, str) or not v:
                continue
            where = f"{key_of(r) or f'row {i + 2}'}/{h}"
            if v.strip().lower() in PLACEHOLDERS:
                placeholder.append(where)
            if v != v.strip():
                spaces.append(where)
            if v[0] in "=+-@" and not is_number(v):
                formula.append(where)
    rep.check(not placeholder, "no placeholder strings (None/nan/null)", placeholder)
    rep.check(not spaces, "no leading/trailing whitespace", spaces, warn_only=True)
    rep.check(not formula, "no formula-like cells (= + - @)", formula, warn_only=True)

    empty_cols = [h for h in header if rows and all(not as_text(get(r, h)).strip() for r in rows)]
    rep.check(not empty_cols, "no column empty in every row", empty_cols, warn_only=True)

    for other_path, mode in [(p, "compare") for p in args.compare] + [(p, "subset") for p in args.subset_of]:
        compare(rep, header, rows, key_of, Path(other_path), mode, args)
    return rep


def compare(rep: Report, header, rows, key_of, other: Path, mode: str, args) -> None:
    try:
        o_header, o_rows = read_table(other, args.sheet)
    except Exception as exc:  # noqa: BLE001
        rep.add("fail", f"{other.name}: could not be read: {exc}")
        return
    o_col = {h: i for i, h in enumerate(o_header)}
    o_keys = set()
    if args.key and args.key in o_col:
        o_keys = {as_text(r[o_col[args.key]]).strip() for r in o_rows}
    keys = {key_of(r) for r in rows} if args.key else set()

    if mode == "compare":
        gap = abs(rep.path.stat().st_mtime - other.stat().st_mtime)
        rep.check(gap < 600, f"written in the same export run as {other.name}",
                  [f"{gap / 60:.0f} min apart — one file is stale; re-export all formats together"],
                  warn_only=True)
        rep.check(header == o_header, f"same columns as {other.name}",
                  [f"only here: {sorted(set(header) - set(o_header))}",
                   f"only there: {sorted(set(o_header) - set(header))}"]
                  if set(header) != set(o_header) else ["same names, different order"])
        rep.check(len(rows) == len(o_rows), f"same row count as {other.name} ({len(rows)})",
                  [f"{len(rows)} vs {len(o_rows)}"])
        if args.key:
            rep.check(keys == o_keys, f"same keys as {other.name}",
                      sorted(keys ^ o_keys))
    else:
        if args.key:
            rep.check(keys <= o_keys, f"every key is also in {other.name}", sorted(keys - o_keys))
        rep.check(set(header) <= set(o_header), f"columns are a subset of {other.name}",
                  sorted(set(header) - set(o_header)))


def probe_url(url: str, timeout: int = 15) -> str:
    headers = {"User-Agent": "verify-export/1.0"}
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers=headers)
        if method == "GET":
            req.add_header("Range", "bytes=0-1023")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return "ok" if resp.status < 400 else f"HTTP {resp.status}"
        except urllib.error.HTTPError as exc:
            if method == "HEAD" and exc.code in (403, 405, 501):
                continue
            return f"HTTP {exc.code}"
        except Exception as exc:  # noqa: BLE001
            return type(exc).__name__
    return "failed"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Cross-verify an exported CSV/XLSX/JSON/XML file.")
    ap.add_argument("file")
    ap.add_argument("--key", help="unique key column, e.g. Ref")
    ap.add_argument("--required", nargs="*", default=[], help="columns that must never be empty")
    ap.add_argument("--date-cols", nargs="*", default=[], help="columns whose values must parse as dates")
    ap.add_argument("--url-cols", nargs="*", default=[], help="columns holding links")
    ap.add_argument("--expected", type=int, help="expected number of data rows (the count the site shows)")
    ap.add_argument("--compare", nargs="*", default=[], help="other exports that must hold the same data")
    ap.add_argument("--subset-of", nargs="*", default=[], help="exports this one must be a subset of (sample vs full)")
    ap.add_argument("--check-urls", type=int, default=0, metavar="K", help="live-check K random URLs")
    ap.add_argument("--sheet", help="xlsx sheet name (default: first sheet)")
    ap.add_argument("--json", help="also write the report to this JSON file")
    args = ap.parse_args(argv)

    rep = verify(args)
    fails = sum(line["level"] == "fail" for line in rep.lines)
    warns = sum(line["level"] == "warn" for line in rep.lines)
    print(f"\nResult: {'FAILED' if fails else 'PASSED'} ({fails} failures, {warns} warnings)")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(
            {"file": str(rep.path), "checked_at": datetime.now().isoformat(timespec="seconds"),
             "passed": not fails, "lines": rep.lines}, indent=2, ensure_ascii=False))
    if rep.lines and rep.lines[0]["text"].startswith("file could not be read"):
        return 2
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
