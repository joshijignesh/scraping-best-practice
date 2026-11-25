# Export formats

Five formats are supported. **Implement only the ones the user selects** while building the
project. If they don't choose, implement **CSV + Excel** (the default) and tell them. Copy only
the writers you need from this file.

| Key | File | Library (add to `requirements.txt` only if selected) |
|---|---|---|
| `csv` | `<name>_<scope>.csv` | stdlib |
| `excel` | `<name>_<scope>.xlsx` | `openpyxl` |
| `xml` | `<name>_<scope>.xml` | stdlib |
| `json` | `<name>_<scope>.json` | stdlib |
| `docx` | `<name>_<scope>.docx` | `python-docx` |

`<scope>` is `sample` or `full`.

```toml
# config.toml
[export]
formats = ["csv", "excel"]      # any of: csv, excel, xml, json, docx
basename = "site_records"
```

## Shape of `export.py`

Build `(columns, rows)` **once** from captures; every writer receives the same data, so all
formats agree (which `verify_export.py --compare` checks).

```python
from __future__ import annotations
import os, tempfile
from pathlib import Path

def build(captures, sample: bool) -> tuple[list[str], list[dict]]:
    """Read saved HTML/JSON → parsers → ordered columns + rows. No site access."""
    ...

def _atomic(path: Path, write) -> Path:
    """write(tmp_path) then rename, so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=path.suffix)
    os.close(fd)
    try:
        write(Path(tmp))
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return path

WRITERS = {}            # filled only with the selected formats, e.g.
# WRITERS = {"csv": (".csv", write_csv), "excel": (".xlsx", write_excel)}

def export(captures, out_dir: Path, basename: str, formats: list[str]) -> list[Path]:
    unknown = set(formats) - WRITERS.keys()
    if unknown:
        raise SystemExit(f"Format not implemented in this project: {', '.join(sorted(unknown))}")
    written = []
    for scope in ("sample", "full"):
        columns, rows = build(captures, sample=(scope == "sample"))
        for fmt in formats:
            ext, writer = WRITERS[fmt]
            path = out_dir / f"{basename}_{scope}{ext}"
            written.append(_atomic(path, lambda tmp: writer(tmp, columns, rows)))
    return written
```

CLI: `export` uses `config.export.formats`; `export --format json xml` overrides for one run.
Delete outputs of formats that are no longer selected so stale files don't mislead.

## Writers

### CSV (default)

```python
import csv

def write_csv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:   # BOM → Excel shows UTF-8 right
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: _csv_safe(r.get(k)) for k in columns})

def _csv_safe(v):
    """Dates as 'YYYY-MM-DD HH:MM'; guard against formula injection in spreadsheet apps."""
    if v is None:
        return ""
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d %H:%M")
    s = str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") and not _is_number(s) else s

def _is_number(s):
    try: float(s); return True
    except ValueError: return False
```

### Excel (default)

```python
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER = (Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F4E78"))
LINK = Font(color="0563C1", underline="single")
URL_COLUMNS = {"Document URL", "Source URL"}

def write_excel(path, columns, rows):
    wb = Workbook(); ws = wb.active; ws.title = "Data"
    ws.append(columns)
    for c in ws[1]:
        c.font, c.fill = HEADER
    for r in rows:
        ws.append([_xl(r.get(k)) for k in columns])
        for col, key in enumerate(columns, start=1):
            if key in URL_COLUMNS and r.get(key):
                cell = ws.cell(ws.max_row, col)
                cell.hyperlink, cell.font = r[key], LINK
    for col, key in enumerate(columns, start=1):
        width = min(60, max(len(key), *(len(str(r.get(key) or "")) for r in rows[:200])) + 2) if rows else len(key) + 2
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=isinstance(c.value, str) and len(c.value) > 60)
    wb.save(path)

def _xl(v):
    """Real datetimes stay datetimes; strip characters Excel rejects."""
    return ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v
```

Parent/child rows (e.g. a record and its amendments): set
`ws.row_dimensions[i].outline_level = 1` on child rows and
`ws.sheet_properties.outlinePr.summaryBelow = False` for collapsible groups; shade parent rows.

### XML (on request)

```python
import re
import xml.etree.ElementTree as ET

def _tag(name):
    """'Due Date & Time' -> 'due_date_time' (valid XML element name)."""
    t = re.sub(r"[^0-9a-zA-Z_]+", "_", name).strip("_").lower() or "field"
    return "f_" + t if t[0].isdigit() else t

def write_xml(path, columns, rows, root="records", item="record"):
    top = ET.Element(root, count=str(len(rows)))
    for r in rows:
        el = ET.SubElement(top, item)
        for k in columns:
            v = r.get(k)
            child = ET.SubElement(el, _tag(k), label=k)
            child.text = "" if v is None else (v.isoformat(sep=" ") if hasattr(v, "isoformat") else str(v))
    ET.indent(top)                                     # Python 3.9+
    ET.ElementTree(top).write(path, encoding="utf-8", xml_declaration=True)
```

If the client's system has an XSD, ask for it and map columns to its element names instead.

### JSON (on request)

```python
import json

def write_json(path, columns, rows):
    data = [{k: r.get(k) for k in columns} for r in rows]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"count": len(data), "columns": columns, "records": data},
                  f, ensure_ascii=False, indent=2, default=str)   # default=str handles datetimes
```

For very large outputs or streaming into other tools use JSON Lines (`.jsonl`, one object per line).
Nested child records (amendments under their parent) fit JSON naturally: nest them under
`"children"` if the user prefers that over flat rows, and say which you chose in the README.

### DOCX (on request)

```python
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.shared import Pt

def write_docx(path, columns, rows, title="Scraped records", table_columns=None):
    doc = Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = sec.page_height, sec.page_width
    doc.add_heading(title, level=1)
    doc.add_paragraph(f"{len(rows)} records")
    cols = table_columns or columns[:6]               # a Word table is unreadable past ~6-8 columns
    table = doc.add_table(rows=1, cols=len(cols)); table.style = "Light Grid Accent 1"
    for cell, name in zip(table.rows[0].cells, cols):
        cell.text = name
    for r in rows:
        cells = table.add_row().cells
        for cell, k in zip(cells, cols):
            v = r.get(k)
            cell.text = "" if v is None else str(v)
    for row in table.rows:
        for cell in row.cells:
            for p in cell.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(8)
    doc.save(path)
```

DOCX is a report, not a data interchange format: agree with the user which columns go in the
table (or a one-section-per-record layout for few, wide records), and keep CSV/Excel as the
complete data.

## Rules for all formats

- Same column names and order everywhere; same row count per scope.
- Dates: real datetimes in Excel; `YYYY-MM-DD HH:MM` text in CSV/XML/JSON/DOCX; state the timezone.
- Empty values are empty (`""` / `null`), never the strings `None`, `nan`, `N/A`.
- Sample and full are separate files; neither overwrites the other.
- After writing, run `verify_export.py` on the CSV/XLSX (and `--compare` them) — see
  [verification.md](verification.md). For XML/JSON, at minimum re-parse the file and compare
  the record count with the CSV.
