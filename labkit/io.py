"""Safe import/export primitives shared by the lab applications. No Qt, no science.

- `preview_table(path)`: look at a delimited text file before importing it: columns, units,
  inferred kinds, missing values, and warnings a person should see first. It never guesses
  silently: anything it had to assume (delimiter, decimal comma, encoding) is reported.
- `atomic_save(path, write)`: a save that either completes or leaves the old file untouched.
- `Provenance`: where an exported result came from (source file and digest, parameters, versions),
  written beside the export so the numbers can be traced.

Calculations stay in each application: this module only moves and describes data.
"""
from __future__ import annotations

import csv
import hashlib
import io as _io
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .units import split_label

MAX_PREVIEW_BYTES = 256 * 1024 * 1024     # refuse to scan larger files for a preview
SAMPLE_ROWS = 2000                        # rows examined for kinds and missing values
MISSING = {"", "nan", "na", "n/a", "null", "none", "-", "--", "#n/a", "#div/0!", "#value!"}


@dataclass
class ColumnPreview:
    name: str               # header exactly as in the file
    label: str              # header without its unit
    unit: str               # "" when the header carries none
    kind: str               # number | text | mixed | empty
    missing: int            # blank or not-a-number cells among the sampled rows
    non_finite: int         # inf / -inf cells
    example: str            # first non-missing value


@dataclass
class TablePreview:
    path: str
    encoding: str
    delimiter: str
    decimal: str            # "." or ","
    header_row: int         # 0-based line index of the header
    rows_sampled: int
    truncated: bool         # more rows exist than were sampled
    columns: list[ColumnPreview] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.columns) and any(c.kind == "number" for c in self.columns)


class PreviewError(ValueError):
    """The file cannot be previewed as a table (with a sentence for the user)."""


def _read_text(path: Path) -> tuple[str, str, list[str]]:
    size = path.stat().st_size
    if size > MAX_PREVIEW_BYTES:
        raise PreviewError(f"The file is {size / 1e6:.0f} MB; previews are limited to {MAX_PREVIEW_BYTES / 1e6:.0f} MB.")
    raw = path.read_bytes()
    if b"\x00" in raw[:4096] and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise PreviewError("This looks like a binary file, not a text table.")
    notes = []
    # UTF-16 only with a byte-order mark: without one it "decodes" almost any even-length file into garbage
    encodings = ("utf-16", "utf-8-sig", "cp1252") if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "cp1252")
    for enc in encodings:
        try:
            text = raw.decode(enc)
            if enc == "cp1252":
                notes.append("The file is not UTF-8; it was read as Windows-1252. Check accented characters and unit symbols.")
            return text, enc, notes
        except UnicodeError:
            continue
    raise PreviewError("The file's text encoding could not be read.")


def _to_number(cell: str, decimal: str) -> float | None:
    s = cell.strip()
    if decimal == ",":
        s = s.replace(".", "").replace(",", ".") if s.count(",") == 1 else s
    try:
        return float(s)
    except ValueError:
        return None


def preview_table(path: str | Path, *, delimiter: str | None = None, header_row: int | None = None) -> TablePreview:
    """Describe a delimited text file without importing it. Raises PreviewError with a user sentence."""
    path = Path(path)
    try:
        text, encoding, notes = _read_text(path)
    except OSError as e:
        raise PreviewError(f"The file could not be opened: {e.strerror or e}") from e
    lines = text.splitlines()
    if not any(line.strip() for line in lines):
        raise PreviewError("The file is empty.")
    warnings = list(notes)
    if delimiter is None:
        sample = "\n".join(lines[:50])
        counts = {d: sample.count(d) for d in ("\t", ";", ",", "|")}
        delimiter = max(counts, key=counts.get) if max(counts.values()) else None
        if delimiter is None:
            delimiter = " "
            warnings.append("No tab, comma or semicolon found: columns were split on spaces.")
    reader = (line.split() for line in lines) if delimiter == " " else csv.reader(_io.StringIO(text), delimiter=delimiter)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        raise PreviewError("The file has no rows.")
    width = max(len(r) for r in rows[:SAMPLE_ROWS + 50])

    # decimal comma: with ';' or tab as delimiter, cells like "1,25" that are numbers once the comma is a point
    def numeric_share(dec: str) -> float:
        cells = [c for r in rows[1:200] for c in r if c.strip()]
        return sum(_to_number(c, dec) is not None for c in cells) / max(1, len(cells))
    decimal = "."
    if delimiter != "," and numeric_share(",") > numeric_share(".") + 0.2:
        decimal = ","
        warnings.append("Numbers use a decimal comma (1,25). They will be read as 1.25.")

    if header_row is None:  # the last row, before the data starts, that is mostly text
        header_row = 0
        for i, r in enumerate(rows[:30]):
            filled = [c for c in r if c.strip()]
            if filled and sum(_to_number(c, decimal) is None for c in filled) >= max(1, len(filled) // 2 + 1):
                header_row = i
            elif filled and len(filled) >= max(2, width // 2):
                break
        if header_row > 0:
            warnings.append(f"{header_row} line(s) before the column names were treated as a preamble and skipped.")
    header = [c.strip() for c in rows[header_row]] + [""] * width
    data = rows[header_row + 1:]
    if not data:
        raise PreviewError("The file has column names but no data rows.")
    sample = data[:SAMPLE_ROWS]

    columns = []
    seen: dict[str, int] = {}
    for j in range(width):
        name = header[j] or f"Column {j + 1}"
        if not header[j]:
            warnings.append(f"Column {j + 1} has no name.")
        seen[name] = seen.get(name, 0) + 1
        cells = [(r[j].strip() if j < len(r) else "") for r in sample]
        present = [c for c in cells if c.lower() not in MISSING]
        numbers = [_to_number(c, decimal) for c in present]
        n_num = sum(v is not None for v in numbers)
        non_finite = sum(1 for v in numbers if v is not None and not math.isfinite(v))
        nan_cells = sum(1 for v in numbers if v is not None and math.isnan(v))
        if not present:
            kind = "empty"
        elif n_num == len(present):
            kind = "number"
        elif n_num == 0:
            kind = "text"
        else:
            kind = "mixed"
        label, unit = split_label(name)
        missing = len(cells) - len(present) + nan_cells
        columns.append(ColumnPreview(name, label, unit, kind, missing, non_finite - nan_cells,
                                     present[0] if present else ""))
        if kind == "mixed":
            bad = next(c for c, v in zip(present, numbers) if v is None)
            warnings.append(f"'{name}' mixes numbers and text (for example '{bad}'): {len(present) - n_num} cell(s) are not numbers.")
        if kind == "empty":
            warnings.append(f"'{name}' is empty.")
        elif missing:
            warnings.append(f"'{name}' has {missing} missing value(s) in the first {len(sample)} rows.")
        if non_finite - nan_cells:
            warnings.append(f"'{name}' contains infinite values.")
        if kind == "number" and not unit:
            warnings.append(f"'{name}' has no unit in its name.")
    for name, n in seen.items():
        if n > 1:
            warnings.append(f"The column name '{name}' appears {n} times.")
    ragged = sum(1 for r in sample if len(r) != width)
    if ragged:
        warnings.append(f"{ragged} row(s) have a different number of columns than the rest.")
    return TablePreview(str(path), encoding, delimiter, decimal, header_row, len(sample), len(data) > len(sample),
                        columns, list(dict.fromkeys(warnings)))


# ------------------------------------------------------------------------- saving
def atomic_save(path: str | Path, write: Callable[[Path], None], *, keep_backup: bool = False) -> Path:
    """Call `write(temp_path)` and move the result into place only if it succeeded.

    The temporary file is created in the destination folder so the final step is a rename on the
    same drive: a crash or an exception leaves the existing file exactly as it was.
    With keep_backup=True the previous file is kept beside it as '<name>.bak'.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=path.suffix + ".tmp", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        write(tmp)
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise OSError("nothing was written")
        with open(tmp, "rb+") as f:
            os.fsync(f.fileno())
        if keep_backup and path.exists():
            os.replace(path, path.with_name(path.name + ".bak"))
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return path


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


@dataclass
class Provenance:
    """Where a result came from. Values in `parameters` and `sources` must be JSON-serialisable."""
    application: str
    application_version: str
    method: str = ""                                   # e.g. "Savitzky-Golay smoothing, window 11, order 3"
    parameters: dict = field(default_factory=dict)
    sources: list[dict] = field(default_factory=list)  # [{"file": name, "sha256": ..., "bytes": ...}]
    notes: str = ""
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    labkit_version: str = ""

    def add_source(self, path: str | Path) -> "Provenance":
        """Record a source file by name, size and digest. The folder is not stored: it can name a person."""
        p = Path(path)
        self.sources.append({"file": p.name, "sha256": sha256_file(p), "bytes": p.stat().st_size})
        return self

    def to_dict(self) -> dict:
        from . import __version__
        data = asdict(self)
        data["labkit_version"] = self.labkit_version or __version__
        data["format"] = "labkit-provenance/1"
        return data

    def write_beside(self, export_path: str | Path) -> Path:
        """Write '<export>.provenance.json' next to an exported file, atomically."""
        target = Path(str(export_path) + ".provenance.json")
        text = json.dumps(self.to_dict(), indent=2, ensure_ascii=False, allow_nan=False)
        return atomic_save(target, lambda tmp: tmp.write_text(text + "\n", encoding="utf-8"))


def read_provenance(export_path: str | Path) -> dict | None:
    target = Path(str(export_path) + ".provenance.json")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("format") == "labkit-provenance/1" else None
