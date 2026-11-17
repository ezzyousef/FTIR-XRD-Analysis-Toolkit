"""
file_readers.py
Readers for FTIR spectra and XRD patterns across common export formats.

Confidence notes (important, read before trusting a parsed result):
  - Plain text (.xy/.txt/.dat/.csv), .uxd, .ras, .xrdml: format is documented/
    inferable from public instrument manuals -> HIGH confidence.
  - Bruker .raw (v1-v4 legacy binary): NOT publicly documented by Bruker.
    The reader below follows structure reverse-engineered by the open-source
    community (e.g. the `xylib` project conventions). It works on many common
    exports but is best-effort -> LOWER confidence. If it fails, export to
    ASCII (.xy/.uxd) from the instrument software instead, which is the
    officially supported route and what we recommend for anything you plan
    to publish or report.
"""
import struct
import re
import xml.etree.ElementTree as ET
import numpy as np


class ReadResult:
    def __init__(self, x, y, x_label="X", y_label="Y", metadata=None, confidence="high"):
        self.x = np.asarray(x, dtype=float)
        self.y = np.asarray(y, dtype=float)
        self.x_label = x_label
        self.y_label = y_label
        self.metadata = metadata or {}
        self.confidence = confidence  # "high" or "low" (best-effort binary parse)


_DECIMAL_COMMA = re.compile(r"\d,\d")


def _numbers(line):
    """The numbers on one data line. Separators: comma, tab, space or semicolon. Decimal
    commas ('12,5') are accepted when the separator is clearly something else: a semicolon,
    a tab, or spaces with no comma-space anywhere on the line."""
    s = line.strip()
    decimal_comma = bool(_DECIMAL_COMMA.search(s)) and (";" in s or "\t" in s or (" " in s and not re.search(r",\s", s)))
    if decimal_comma:
        parts = [p.replace(",", ".") for p in re.split(r"[\t ;]+", s)]
    elif ";" in s:
        parts = re.split(r"[;\t ]+", s)
    else:
        parts = re.split(r"[,\t ]+", s)
    nums = []
    for p in parts:
        try:
            nums.append(float(p))
        except ValueError:
            pass
    return nums


MAX_FILE_BYTES = 512 * 1024 * 1024   # a spectrum or pattern export is far smaller; refuse before reading


def _check_size(path):
    import os
    size = os.path.getsize(path)
    if size == 0:
        raise ValueError("The file is empty.")
    if size > MAX_FILE_BYTES:
        raise ValueError(f"The file is too large ({size / 1e6:.0f} MB; limit {MAX_FILE_BYTES / 1e6:.0f} MB) "
                         "for a spectrum or diffraction pattern.")
    return size


def _read_text(path):
    """The file's text. UTF-8 and UTF-16 with a byte-order mark are decoded as such (Windows
    instrument software often writes UTF-16); otherwise UTF-8, falling back to Latin-1, which
    keeps every byte. Files with NUL bytes and no UTF-16 mark are refused as binary."""
    _check_size(path)
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    if b"\x00" in raw:
        raise ValueError("This looks like a binary file, not a text export. Export the data as text "
                         "(.csv/.txt/.xy) from the instrument software.")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _text_lines(path):
    return _read_text(path).splitlines()


def _finite_rows(rows, line_numbers=None):
    """Drop rows with NaN/inf and say which file lines they were on, so nothing is lost silently.
    Returns (kept rows, warning text or None)."""
    keep, dropped = [], []
    for i, row in enumerate(rows):
        if all(np.isfinite(v) for v in row):
            keep.append(row)
        else:
            dropped.append(line_numbers[i] if line_numbers else None)
    if not dropped:
        return keep, None
    where = [str(n) for n in dropped if n is not None][:5]
    msg = f"{len(dropped)} row{'s' if len(dropped) != 1 else ''} with non-finite values (NaN/inf) dropped"
    if where:
        msg += " (line " + ", ".join(where) + ("…" if len(dropped) > 5 else "") + ")"
    return keep, msg


def _add_warning(meta, text):
    """Warnings are shown to the user when the file loads (ui_common.load_file_path)."""
    if text:
        meta["warning"] = f"{meta['warning']}; {text}" if meta.get("warning") else text


def _is_numeric_line(line, nums):
    """A data row: at least two numbers and no letters other than exponents or NaN/inf words."""
    if len(nums) < 2:
        return False
    return all(w.lower() in ("e", "nan", "inf", "infinity") for w in re.findall(r"[A-Za-z]+", line))


def _separator(line):
    """The field separator of a data line, by the same rules as _numbers."""
    s = line.strip()
    decimal_comma = bool(_DECIMAL_COMMA.search(s)) and (";" in s or "\t" in s or (" " in s and not re.search(r",\s", s)))
    if decimal_comma:
        return ";" if ";" in s else ("\t" if "\t" in s else " ")
    for sep in (";", ",", "\t"):
        if sep in s:
            return sep
    return " "


def _header_width(header, sep):
    """Number of fields in a delimited header line (trailing empty fields ignored), or None
    when the header does not use the data's delimiter."""
    import csv
    if sep == " " or sep not in header:
        return None
    fields = next(csv.reader([header], delimiter=sep))
    while fields and not fields[-1].strip():
        fields.pop()
    return len(fields)


def _try_parse_two_column_text(path):
    """Two-column numeric text. Header lines are skipped even when they happen to contain two
    numbers (e.g. 'Wavelength 1.5406 step 0.02'): the data are the longest block of
    consecutive numeric rows, so stray numeric lines before or after it are ignored, and the
    user is told.

    Record widths (as in supercap_suite's _clean_table): when the line just above the block
    is a delimited header (comma, semicolon or tab, the data's own separator), every data row
    must have exactly the header's number of fields; otherwise every row must have the same
    number of values as the block's usual row. A wider or narrower row is refused with its
    line number before any column is chosen or any NaN dropped. Whitespace-separated headers
    are not used for the width (a title line cannot be told from column names).
    Rows with NaN/inf are then dropped and reported."""
    blocks, current = [], []
    headers = {}                       # block index -> the text line just above it
    meta = {}
    previous_text = None               # the last non-blank line, if it was a text (non-data) line
    for lineno, line in enumerate(_text_lines(path), start=1):
        line = line.strip()
        if not line:
            continue
        if line.startswith(("#", ";", "'", "*")):
            if current:
                blocks.append(current)
                current = []
            previous_text = None
            continue
        nums = _numbers(line)
        if _is_numeric_line(line, nums):
            if not current and previous_text is not None:
                headers[len(blocks)] = previous_text
            current.append((lineno, nums, line))
            previous_text = None
        else:
            if current:
                blocks.append(current)
                current = []
            previous_text = line
    if current:
        blocks.append(current)
    best_i = max(range(len(blocks)), key=lambda i: len(blocks[i])) if blocks else None
    best = blocks[best_i] if blocks else []
    if len(best) < 5:
        raise ValueError("Fewer than 5 valid numeric rows found; not a recognized two-column format.")
    sep = _separator(best[0][2])
    header = headers.get(best_i)
    width = _header_width(header, sep) if header else None
    if width is not None and width >= 2:
        for lineno, nums, _ in best:
            if len(nums) != width:
                raise ValueError(f"Line {lineno} has {len(nums)} values but the header has {width} "
                                 f"(line {lineno}): the file is ragged. Fix that row and load it again.")
        usual = width
    else:
        widths = [len(nums) for _, nums, _ in best]
        usual = max(set(widths), key=widths.count)
        for lineno, nums, _ in best:
            if len(nums) != usual:
                raise ValueError(f"Line {lineno} has {len(nums)} values but the other data rows have {usual}: "
                                 f"the file is ragged at line {lineno}. Fix or remove that row and load it again.")
    best = [(n, nums) for n, nums, _ in best]
    if usual > 2:
        _add_warning(meta, f"{usual} values per row; the first two columns were used as x and y "
                           "(check for decimal commas in a comma-separated file)")
    if len(blocks) > 1:
        others = sum(len(b) for b in blocks) - len(best)
        _add_warning(meta, f"{len(blocks)} numeric blocks found; used the longest ({len(best)} rows), "
                           f"{others} numeric row{'s' if others != 1 else ''} elsewhere ignored")
    rows, msg = _finite_rows([(nums[0], nums[1]) for _, nums in best], [n for n, _ in best])
    _add_warning(meta, msg)
    if len(rows) < 5:
        raise ValueError("Fewer than 5 finite numeric rows found.")
    xs, ys = zip(*rows)
    return np.array(xs), np.array(ys), meta


def read_generic_text(path):
    """.xy, .txt, .dat, .csv - generic two-column ASCII."""
    x, y, meta = _try_parse_two_column_text(path)
    return ReadResult(x, y, metadata=meta, confidence="high")


def read_uxd(path):
    """
    Siemens/Bruker UXD text format. Handles both data layouts:
      _2THETACOUNTS (or no marker): rows of '2theta  counts' pairs;
      _COUNTS: counts only, several per row, with the axis from _2THETA (or _START) and _STEPSIZE.
    Keys appear as '_KEY=value' (or '; KEY = value' comments). A file with several ranges
    returns the first and says so in metadata["warning"].
    """
    meta = {}
    ranges = []                       # [{"start", "step", "counts_mode", "pairs", "counts"}]
    cur = None

    def new_range():
        r = {"start": None, "step": None, "counts_mode": False, "pairs": [], "counts": []}
        ranges.append(r)
        return r

    for line in _text_lines(path):
        s = line.strip()
        if not s:
            continue
        if s.startswith(";"):
            if "=" in s:
                k, v = s[1:].split("=", 1)
                meta[k.strip()] = v.strip()
            continue
        if s.startswith("_"):
            key, _, val = s.partition("=")
            key, val = key.strip().upper(), val.strip()
            if key in ("_RANGE", "_DRIVE") or (key in ("_2THETA", "_START") and cur is not None
                                                 and (cur["pairs"] or cur["counts"])):
                cur = new_range()
            if cur is None:
                cur = new_range()
            if key in ("_2THETA", "_START") and val:
                try:
                    cur["start"] = float(val)
                except ValueError:
                    pass
            elif key == "_STEPSIZE" and val:
                try:
                    cur["step"] = float(val)
                except ValueError:
                    pass
            elif key == "_COUNTS":
                cur["counts_mode"] = True
            elif key == "_2THETACOUNTS":
                cur["counts_mode"] = False
            if val:
                meta.setdefault(key.lstrip("_"), val)
            continue
        nums = _numbers(s)
        if not nums:
            continue
        if cur is None:
            cur = new_range()
        if cur["counts_mode"]:
            cur["counts"].extend(nums)
        elif len(nums) >= 2:
            cur["pairs"].append((nums[0], nums[1]))
    usable = []
    for r in ranges:
        if r["counts_mode"] and r["counts"]:
            if r["start"] is None or not r["step"]:
                raise ValueError("UXD counts-only data without _2THETA/_START and _STEPSIZE: cannot build the 2θ axis.")
            y = np.array(r["counts"], dtype=float)
            # axis first, so dropping a non-finite count keeps its neighbours' angles
            rows, msg = _finite_rows(list(zip(r["start"] + r["step"] * np.arange(len(y)), y)))
        elif len(r["pairs"]) >= 5:
            rows, msg = _finite_rows(r["pairs"])
        else:
            continue
        if rows:
            xs, ys = zip(*rows)
            usable.append((np.array(xs), np.array(ys), msg))
    if not usable or len(usable[0][0]) < 5:
        raise ValueError("UXD file did not yield usable data rows.")
    if len(usable) > 1:
        meta["warning"] = f"{len(usable)} ranges in this file; loaded the first."
    _add_warning(meta, usable[0][2])
    return ReadResult(usable[0][0], usable[0][1], metadata=meta, confidence="high")


def read_ras(path):
    """
    Rigaku .ras text format: header lines '*KEY "value"' and intensity blocks between
    *RAS_INT_START and *RAS_INT_END with columns 2theta, intensity[, attenuation]. The
    intensity is multiplied by the attenuation factor when one is given. Several scans:
    the first is returned and metadata["warning"] says so. Files without *RAS_INT markers
    fall back to the numeric rows between *RAS_DATA_START and *RAS_DATA_END.
    """
    meta = {}
    scans, cur = [], None
    fallback, in_data = [], False
    for line in _text_lines(path):
        s = line.strip()
        if not s:
            continue
        if s.startswith("*"):
            tag = s.split()[0].upper()
            if tag == "*RAS_INT_START":
                cur = []
            elif tag == "*RAS_INT_END":
                if cur:
                    scans.append(cur)
                cur = None
            elif tag == "*RAS_DATA_START":
                in_data = True
            elif tag == "*RAS_DATA_END":
                in_data = False
            else:
                if "=" in s:
                    k, v = s[1:].split("=", 1)
                else:
                    k, _, v = s[1:].partition(" ")
                if k.strip():
                    meta.setdefault(k.strip(), v.strip().strip('"'))
            continue
        nums = _numbers(s)
        if len(nums) < 2:
            continue
        row = (nums[0], nums[1] * (nums[2] if len(nums) >= 3 and nums[2] > 0 else 1.0))
        if cur is not None:
            cur.append(row)
        elif in_data:
            fallback.append(row)
    rows = scans[0] if scans else fallback
    if len(rows) < 5:
        raise ValueError("RAS file did not yield usable data rows (unexpected structure).")
    if len(scans) > 1:
        meta["warning"] = f"{len(scans)} scans in this file; loaded the first."
    rows, msg = _finite_rows(rows)
    _add_warning(meta, msg)
    if len(rows) < 5:
        raise ValueError("RAS file did not yield 5 finite data rows.")
    xs, ys = zip(*rows)
    return ReadResult(np.array(xs), np.array(ys), metadata=meta, confidence="high")


def read_xrdml(path):
    """PANalytical/Malvern .xrdml XML format."""
    _check_size(path)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:          # also expat's entity-amplification ("billion laughs") limit
        raise ValueError(f"Not a well-formed XML (.xrdml) file: {exc}") from None
    # namespace handling: xrdml uses a default namespace, detect it
    m = re.match(r"\{(.*)\}", root.tag)
    ns = {"n": m.group(1)} if m else {}

    def find(tag_path):
        return root.find(tag_path.format(n="n:") if ns else tag_path.format(n=""), ns)

    def findall(tag_path):
        return root.findall(tag_path.format(n="n:") if ns else tag_path.format(n=""), ns)

    scan = findall(".//{n}dataPoints/..")
    datapoints = root.find(".//" + ("n:dataPoints" if ns else "dataPoints"), ns)
    if datapoints is None:
        raise ValueError("No <dataPoints> element found - not a standard .xrdml file.")

    intensities_el = datapoints.find("n:intensities" if ns else "intensities", ns)
    counts_el = datapoints.find("n:counts" if ns else "counts", ns)
    y_el = intensities_el if intensities_el is not None else counts_el
    if y_el is None or not y_el.text:
        raise ValueError("No intensity/count data found in .xrdml file.")
    y = np.array([float(v) for v in y_el.text.split()])
    meta = {}
    att_el = datapoints.find("n:beamAttenuationFactors" if ns else "beamAttenuationFactors", ns)
    if att_el is not None and att_el.text:
        factors = np.array([float(v) for v in att_el.text.split()])
        if len(factors) == len(y):
            y = y * factors
            meta["attenuation"] = "beam attenuation factors applied"
    time_el = datapoints.find("n:commonCountingTime" if ns else "commonCountingTime", ns)
    if time_el is not None and time_el.text:
        meta["counting_time_s"] = float(time_el.text)
    n_scans = len(findall(".//{n}dataPoints"))
    if n_scans > 1:
        meta["warning"] = f"{n_scans} scans in this file; loaded the first."

    x = None
    for positions in datapoints.findall("n:positions" if ns else "positions", ns):
        axis = positions.get("axis", "")
        if axis == "2Theta":
            list_el = positions.find("n:listPositions" if ns else "listPositions", ns)
            start_el = positions.find("n:startPosition" if ns else "startPosition", ns)
            end_el = positions.find("n:endPosition" if ns else "endPosition", ns)
            if list_el is not None and list_el.text:
                values = np.array([float(v) for v in list_el.text.split()])
                if len(values) == len(y):
                    x = values
            elif start_el is not None and end_el is not None:
                start, end = float(start_el.text), float(end_el.text)
                x = np.linspace(start, end, len(y))
    if x is None:
        x = np.arange(len(y))
        meta["warning"] = "2Theta axis not found explicitly; using point index as X. Check the file."

    wl_el = root.find(".//" + ("n:kAlpha1" if ns else "kAlpha1"), ns)
    if wl_el is not None and wl_el.text:
        meta["wavelength_kalpha1"] = float(wl_el.text)

    ok = np.isfinite(x) & np.isfinite(y)
    if not ok.all():
        _add_warning(meta, f"{int((~ok).sum())} point(s) with non-finite values (NaN/inf) dropped")
        x, y = x[ok], y[ok]
    return ReadResult(x, y, x_label="2Theta (deg)", y_label="Intensity (counts)",
                       metadata=meta, confidence="high")


def read_bruker_raw(path):
    """
    Best-effort reader for legacy Bruker .raw (RAW1/RAW2-style) binary files.
    Format is NOT officially published by Bruker; this follows structure
    reverse-engineered by the open-source diffraction community. Treat
    output with lower confidence than text-format readers - verify peak
    positions against a known standard if possible, and prefer ASCII
    export from the instrument software when accuracy matters.
    """
    _check_size(path)
    with open(path, "rb") as f:
        data = f.read()

    header = data[:4]
    meta = {"raw_header_bytes": header.hex()}

    # RAW1.01 style (older Bruker/Siemens) - fairly consistent layout
    if data[:7] in (b"RAW1.01", b"RAW2.00", b"RAW1.00"):
        try:
            n_points = struct.unpack_from("<I", data, 4)[0]
            step = struct.unpack_from("<f", data, 8)[0]
            start = struct.unpack_from("<f", data, 12)[0]
            # data block offset varies by sub-version; try the common 256-byte header
            for offset in (256, 712, 300):
                try:
                    y = np.frombuffer(data, dtype="<f4", count=n_points, offset=offset)
                    if len(y) == n_points and np.all(np.isfinite(y)) and y.max() > 0:
                        x = start + step * np.arange(n_points)
                        return ReadResult(x, y, x_label="2Theta (deg)", y_label="Intensity (counts)",
                                           metadata=meta, confidence="low")
                except Exception:
                    continue
        except Exception:
            pass

    raise ValueError(
        "Could not confidently parse this .raw file - Bruker's binary format is "
        "undocumented and varies by instrument/software version. Please export "
        "the pattern as ASCII (.xy, .uxd, or .txt) from your diffractometer "
        "software and load that instead; it is the reliable path."
    )


# ---------------- JCAMP-DX (.jdx/.dx) -- the standard spectroscopy interchange format ----------------
# Used by NIST Chemistry WebBook, SDBS, and essentially every FTIR instrument
# vendor's ASCII export option. Full JCAMP-DX 5.01 support: plain ##XYPOINTS
# pairs, and the compressed ##XYDATA=(X++(Y..Y)) ASDF encoding (SQZ/DIF/DUP
# pseudo-digits). The ASDF decoder is intricate enough that a subtle bug could
# silently produce a WRONG spectrum rather than an obvious failure -- so after
# decoding, the result is strictly cross-checked against the file's own
# declared ##NPOINTS/##FIRSTX/##LASTX metadata, and this reader refuses to
# return data that doesn't reconcile rather than guessing.

_JCAMP_SQZ = {"@": 0, "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8, "I": 9,
              "a": -1, "b": -2, "c": -3, "d": -4, "e": -5, "f": -6, "g": -7, "h": -8, "i": -9}
_JCAMP_DIF = {"%": 0, "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "O": 6, "P": 7, "Q": 8, "R": 9,
              "j": -1, "k": -2, "l": -3, "m": -4, "n": -5, "o": -6, "p": -7, "q": -8, "r": -9}
_JCAMP_DUP = {"S": 1, "T": 2, "U": 3, "V": 4, "W": 5, "X": 6, "Y": 7, "Z": 8, "s": 9}
_JCAMP_SPECIAL = set(_JCAMP_SQZ) | set(_JCAMP_DIF) | set(_JCAMP_DUP)


def _jcamp_decode_asdf_line(line):
    """Decodes one ##XYDATA ASDF line into (leading_x, [y1, y2, ...])."""
    leading_x, values, _ = _jcamp_decode_asdf_line_ex(line)
    return leading_x, values


def _jcamp_decode_asdf_line_ex(line):
    """
    Decodes one ##XYDATA ASDF line into (leading_x, [y1, y2, ...], ended_in_dif).
    See the JCAMP-DX 5.01 spec (McDonald & Wilks, Appl. Spectrosc. 1988) for
    the SQZ (squeezed leading digit)/DIF (delta from previous)/DUP (repeat
    previous N times) pseudo-digit scheme implemented here.
    """
    i = 0
    n = len(line)

    def read_plain_number(start):
        j = start
        if j < n and line[j] in "+-":
            j += 1
        seen_digit = False
        while j < n and (line[j].isdigit() or line[j] == "."):
            j += 1
            seen_digit = True
        if not seen_digit:
            return None, start
        return line[start:j], j

    tok, i = read_plain_number(i)
    if tok is None:
        raise ValueError(f"JCAMP-DX data line does not start with a numeric X value: {line!r}")
    leading_x = float(tok)

    values = []
    last_value = None      # last actual Y value emitted (for DUP-of-absolute-value)
    last_was_dif = False    # whether the last emission came from a DIF (delta) token
    last_dif = 0.0

    while i < n:
        ch = line[i]
        if ch.isspace():
            i += 1
            continue

        if ch in _JCAMP_DUP:
            # The DUP count is the pseudo-digit plus any plain digits after it: 'T0' = 20.
            digits = str(_JCAMP_DUP[ch])
            i += 1
            while i < n and line[i].isdigit():
                digits += line[i]
                i += 1
            count = int(digits)
            # DUP repeats the previous emitted value (or delta step) so that
            # it appears `count` times in total -- 1 fewer than that many
            # additional emissions, since it already appeared once.
            if last_value is None:
                raise ValueError(f"JCAMP-DX DUP with no preceding value in line: {line!r}")
            for _ in range(count - 1):
                if last_was_dif:
                    last_value = last_value + last_dif
                values.append(last_value)
            continue

        if ch in _JCAMP_SQZ:
            digit = _JCAMP_SQZ[ch]
            i += 1
            rest, i = read_plain_number(i)
            if rest:
                # combine the sign of the SQZ digit with the following plain digits
                sign = -1.0 if digit < 0 else 1.0
                magnitude_str = str(abs(digit)) + rest
                value = sign * float(magnitude_str)
            else:
                # a bare SQZ digit like '@'/'A' with nothing following is itself the whole number
                value = float(digit)
            values.append(value)
            last_value = value
            last_was_dif = False
            continue

        if ch in _JCAMP_DIF:
            digit = _JCAMP_DIF[ch]
            i += 1
            rest, i = read_plain_number(i)
            if rest:
                sign = -1.0 if digit < 0 else 1.0
                magnitude_str = str(abs(digit)) + rest
                delta = sign * float(magnitude_str)
            else:
                delta = float(digit)
            if last_value is None:
                raise ValueError(f"JCAMP-DX DIF token before any absolute value in line: {line!r}")
            new_value = last_value + delta
            values.append(new_value)
            last_dif = delta
            last_value = new_value
            last_was_dif = True
            continue

        if ch in "+-." or ch.isdigit():
            tok, i = read_plain_number(i)
            value = float(tok)
            values.append(value)
            last_value = value
            last_was_dif = False
            continue

        raise ValueError(f"Unrecognized character {ch!r} in JCAMP-DX data line: {line!r}")

    return leading_x, values, last_was_dif


def read_jcampdx(path):
    """
    JCAMP-DX (.jdx/.dx) reader -- the standard IR/Raman/UV-Vis spectroscopy
    interchange format (NIST WebBook, SDBS, and most instrument software's
    ASCII export all use it). Supports ##XYPOINTS=(XY..XY) (plain x,y pairs)
    and the compressed ##XYDATA=(X++(Y..Y)) ASDF encoding.
    """
    meta = {}
    xydata_lines = []
    xypoints_pairs = []
    mode = None
    xfactor, yfactor = 1.0, 1.0
    firstx = lastx = npoints = None
    xunits = yunits = None

    def header_number(key, val, cast=float):
        try:
            return cast(float(val))
        except ValueError:
            raise ValueError(f"JCAMP-DX header ##{key}={val!r} is not a number.") from None

    for raw_line in _text_lines(path):
        line = raw_line.rstrip("\n\r")
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("##"):
            mode = None
            body = stripped[2:]
            if "=" not in body:
                continue
            key, val = body.split("=", 1)
            key_norm = key.strip().upper().replace(" ", "")
            val = val.strip()
            if key_norm in ("XYDATA",):
                mode = "xydata"
                continue
            if key_norm in ("XYPOINTS",):
                mode = "xypoints"
                continue
            if key_norm == "XFACTOR":
                xfactor = header_number("XFACTOR", val)
            elif key_norm == "YFACTOR":
                yfactor = header_number("YFACTOR", val)
            elif key_norm == "FIRSTX":
                firstx = header_number("FIRSTX", val)
            elif key_norm == "LASTX":
                lastx = header_number("LASTX", val)
            elif key_norm == "NPOINTS":
                npoints = header_number("NPOINTS", val, int)
            elif key_norm == "XUNITS":
                xunits = val
            elif key_norm == "YUNITS":
                yunits = val
            elif key_norm == "END":
                mode = None
            else:
                meta[key.strip()] = val
            continue
        if stripped.startswith("$$"):
            continue  # comment line
        if mode == "xydata":
            xydata_lines.append(stripped)
        elif mode == "xypoints":
            for pair in re.split(r"[;\s]+", stripped):
                if "," in pair:
                    a, b = pair.split(",", 1)
                    try:
                        xypoints_pairs.append((float(a), float(b)))
                    except ValueError:
                        pass

    xs, ys = [], []
    if xydata_lines:
        first_leading_x = None
        prev_last, prev_dif = None, False
        line_starts = []            # (line number, raw leading X, index of the point that X belongs to)
        for lineno, line in enumerate(xydata_lines, start=1):
            leading_x, row_values, ended_dif = _jcamp_decode_asdf_line_ex(line)
            if first_leading_x is None:
                first_leading_x = leading_x
            # The leading X is the abscissa of the line's first ordinate; with a DIF Y-check that
            # ordinate is the previous line's last point, so it sits one index back.
            line_starts.append((lineno, leading_x, len(ys) - (1 if (prev_dif and row_values) else 0)))
            if prev_dif and row_values:
                # DIF form: the line repeats the previous line's last ordinate as a Y-value check.
                if abs(row_values[0] - prev_last) > 1e-9 * max(1.0, abs(prev_last)):
                    raise ValueError(f"JCAMP-DX Y-value check failed on data line {lineno} ({line!r}): it should "
                                     f"start with {prev_last:g}, the previous line's last value. The file is "
                                     "damaged or not standard; re-export it.")
                row_values = row_values[1:]
            if row_values:
                prev_last, prev_dif = row_values[-1], ended_dif
            ys.extend(v * yfactor for v in row_values)
        # ASDF encodes Y values only; X spacing is uniform from FIRSTX to LASTX. FIRSTX/LASTX are
        # actual values (already multiplied by XFACTOR, JCAMP-DX 4.24), while the X at the start of
        # each data line is raw. The first line's raw X decides which convention the writer used.
        if firstx is None or lastx is None:
            raise ValueError("JCAMP-DX ##XYDATA block found but ##FIRSTX/##LASTX metadata is missing; "
                              "cannot reconstruct the X axis reliably.")
        lead = first_leading_x * xfactor
        tol = 1e-3 * max(abs(firstx), abs(lastx), 1e-12)
        if xfactor != 1.0 and abs(lead - firstx) > tol and abs(lead - firstx * xfactor) <= tol:
            firstx, lastx = firstx * xfactor, lastx * xfactor      # writer stored raw FIRSTX/LASTX
        xs = list(np.linspace(firstx, lastx, len(ys)))
        # X-value check: every line's leading X (times XFACTOR) must fall on the abscissa of its
        # point, within half a step. The axis itself is built from FIRSTX/LASTX, so without this
        # check a corrupt line coordinate would go unnoticed.
        if len(ys) > 1:
            step = (lastx - firstx) / (len(ys) - 1)
            tol = 0.5 * abs(step) + 1e-9 * max(abs(firstx), abs(lastx), 1.0)
            for lineno, raw_x, idx in line_starts:
                expected = firstx + step * idx
                if abs(raw_x * xfactor - expected) > tol:
                    raise ValueError(f"JCAMP-DX X-value check failed on data line {lineno}: it starts at "
                                     f"X = {raw_x * xfactor:g} but its first point should be at {expected:g} "
                                     "(abscissa from FIRSTX/LASTX/NPOINTS). The file is damaged; re-export it.")
    elif xypoints_pairs:
        xs = [p[0] * xfactor for p in xypoints_pairs]
        ys = [p[1] * yfactor for p in xypoints_pairs]
        # FIRSTX/LASTX are physical values: compare the scaled data endpoints with them directly
        # (position, not only span). A writer that stored raw endpoints is accepted too.
        if firstx is not None and lastx is not None and len(xs) > 1:
            span = abs(lastx - firstx) or 1.0
            tol = 0.01 * span

            def close(a, b):
                return abs(xs[0] - a) <= tol and abs(xs[-1] - b) <= tol
            if close(firstx, lastx):
                pass
            elif xfactor != 1.0 and close(firstx * xfactor, lastx * xfactor):
                firstx, lastx = firstx * xfactor, lastx * xfactor
            else:
                raise ValueError(f"JCAMP-DX data run from {xs[0]:g} to {xs[-1]:g} but the file declares "
                                 f"##FIRSTX={firstx:g}/##LASTX={lastx:g} -- refusing to return possibly-"
                                 "corrupted data.")
    else:
        raise ValueError("No ##XYDATA or ##XYPOINTS block found -- not a recognized JCAMP-DX file.")

    x_arr = np.array(xs, dtype=float)
    y_arr = np.array(ys, dtype=float)

    # Strict cross-check against the file's own declared metadata: if the
    # decode doesn't reconcile, refuse to return possibly-wrong data.
    if npoints is not None and len(y_arr) != npoints:
        raise ValueError(f"JCAMP-DX decode produced {len(y_arr)} points but the file declares "
                          f"##NPOINTS={npoints} -- refusing to return possibly-corrupted data. "
                          f"Try re-exporting as plain two-column ASCII instead.")
    if firstx is not None and lastx is not None and len(x_arr) > 1:
        expected_span = abs(lastx - firstx)
        actual_span = abs(float(x_arr[-1]) - float(x_arr[0]))
        if expected_span > 0 and abs(actual_span - expected_span) / expected_span > 0.01:
            raise ValueError("JCAMP-DX decode's X range doesn't match the file's declared "
                              "##FIRSTX/##LASTX -- refusing to return possibly-corrupted data.")

    finite = np.isfinite(x_arr) & np.isfinite(y_arr)
    if not finite.all():
        _add_warning(meta, f"{int((~finite).sum())} point(s) with non-finite values (NaN/inf) dropped")
        x_arr, y_arr = x_arr[finite], y_arr[finite]
    x_label = xunits or "X"
    unit = (xunits or "").strip().upper().replace(" ", "")
    to_wavenumber = {"MICROMETERS": 1e4, "MICRONS": 1e4, "UM": 1e4, "NANOMETERS": 1e7, "NM": 1e7}.get(unit)
    if to_wavenumber:
        if np.any(x_arr <= 0):
            raise ValueError(f"JCAMP-DX wavelength axis ({xunits}) has values <= 0; cannot convert to cm-1.")
        x_arr = to_wavenumber / x_arr                 # nu (cm-1) = 10^4 / lambda (um) = 10^7 / lambda (nm)
        x_label = "1/CM"
        _add_warning(meta, f"x axis converted from {xunits} to wavenumber (cm-1)")
    if xunits:
        meta["xunits"] = xunits
    if yunits:
        meta["yunits"] = yunits
    return ReadResult(x_arr, y_arr, x_label=x_label, y_label=yunits or "Y", metadata=meta, confidence="high")


FTIR_READERS = {
    ".xy": read_generic_text,
    ".txt": read_generic_text,
    ".dat": read_generic_text,
    ".csv": read_generic_text,
    ".dpt": read_generic_text,
    ".jdx": read_jcampdx,
    ".dx": read_jcampdx,
}

READERS = {
    ".xy": read_generic_text,
    ".txt": read_generic_text,
    ".dat": read_generic_text,
    ".csv": read_generic_text,
    ".uxd": read_uxd,
    ".ras": read_ras,
    ".xrdml": read_xrdml,
    ".raw": read_bruker_raw,
}


def read_any(path):
    """Dispatch to the right XRD reader based on file extension."""
    import os
    ext = os.path.splitext(path)[1].lower()
    if ext not in READERS:
        raise ValueError(
            f"Unsupported file extension '{ext}'. Supported: {', '.join(sorted(READERS))}. "
            "If your instrument exports something else, try exporting as ASCII (.xy/.txt) instead."
        )
    return READERS[ext](path)


def read_ftir_any(path):
    """Dispatch to the right FTIR reader based on file extension (adds JCAMP-DX to the generic-text formats)."""
    import os
    ext = os.path.splitext(path)[1].lower()
    if ext not in FTIR_READERS:
        raise ValueError(
            f"Unsupported file extension '{ext}'. Supported: {', '.join(sorted(FTIR_READERS))}. "
            "If your instrument exports something else, try exporting as ASCII (.csv/.txt) or JCAMP-DX (.jdx) instead."
        )
    return FTIR_READERS[ext](path)
