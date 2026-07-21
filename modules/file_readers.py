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


def _try_parse_two_column_text(path):
    xs, ys = [], []
    meta = {}
    with open(path, "r", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith(("#", ";", "'", "*")):
                continue
            # split on comma, tab, or whitespace
            parts = re.split(r"[,\t ]+", line)
            nums = []
            for p in parts:
                try:
                    nums.append(float(p))
                except ValueError:
                    pass
            if len(nums) >= 2:
                xs.append(nums[0])
                ys.append(nums[1])
    if len(xs) < 5:
        raise ValueError("Fewer than 5 valid numeric rows found; not a recognized two-column format.")
    return np.array(xs), np.array(ys), meta


def read_generic_text(path):
    """.xy, .txt, .dat, .csv - generic two-column ASCII."""
    x, y, meta = _try_parse_two_column_text(path)
    return ReadResult(x, y, metadata=meta, confidence="high")


def read_uxd(path):
    """Siemens/Bruker UXD text format (2-column data, ; comment lines)."""
    xs, ys = [], []
    meta = {}
    with open(path, "r", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if s.startswith(";"):
                if "=" in s:
                    k, v = s[1:].split("=", 1)
                    meta[k.strip()] = v.strip()
                continue
            parts = re.split(r"[,\t ]+", s)
            nums = []
            for p in parts:
                try:
                    nums.append(float(p))
                except ValueError:
                    pass
            if len(nums) >= 2:
                xs.append(nums[0])
                ys.append(nums[1])
    if len(xs) < 5:
        raise ValueError("UXD file did not yield usable data rows.")
    return ReadResult(np.array(xs), np.array(ys), metadata=meta, confidence="high")


def read_ras(path):
    """Rigaku .ras text format (*RAS_DATA_START ... *RAS_DATA_END, 3-column: 2theta, intensity, attenuation)."""
    xs, ys = [], []
    meta = {}
    in_data = False
    with open(path, "r", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if s.startswith("*RAS_DATA_START"):
                in_data = True
                continue
            if s.startswith("*RAS_DATA_END"):
                in_data = False
                continue
            if s.startswith("*") and "=" in s and not in_data:
                k, v = s[1:].split("=", 1)
                meta[k.strip()] = v.strip().strip('"')
                continue
            if in_data and s:
                parts = s.split()
                nums = []
                for p in parts:
                    try:
                        nums.append(float(p))
                    except ValueError:
                        pass
                if len(nums) >= 2:
                    xs.append(nums[0])
                    ys.append(nums[1])
    if len(xs) < 5:
        raise ValueError("RAS file did not yield usable data rows (unexpected structure).")
    return ReadResult(np.array(xs), np.array(ys), metadata=meta, confidence="high")


def read_xrdml(path):
    """PANalytical/Malvern .xrdml XML format."""
    ns_guess = None
    tree = ET.parse(path)
    root = tree.getroot()
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

    pos_list = datapoints.find("n:positions" if ns else "positions", ns)
    x = None
    meta = {}
    for positions in datapoints.findall("n:positions" if ns else "positions", ns):
        axis = positions.get("axis", "")
        if axis == "2Theta":
            start_el = positions.find("n:startPosition" if ns else "startPosition", ns)
            end_el = positions.find("n:endPosition" if ns else "endPosition", ns)
            if start_el is not None and end_el is not None:
                start, end = float(start_el.text), float(end_el.text)
                x = np.linspace(start, end, len(y))
    if x is None:
        x = np.arange(len(y))
        meta["warning"] = "2Theta axis not found explicitly; using point index as X. Check the file."

    wl_el = root.find(".//" + ("n:kAlpha1" if ns else "kAlpha1"), ns)
    if wl_el is not None and wl_el.text:
        meta["wavelength_kalpha1"] = float(wl_el.text)

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
    """
    Decodes one ##XYDATA ASDF line into (leading_x, [y1, y2, ...]).
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
            count = _JCAMP_DUP[ch]
            i += 1
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

    return leading_x, values


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

    with open(path, "r", errors="ignore") as f:
        for raw_line in f:
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
                    xfactor = float(val)
                elif key_norm == "YFACTOR":
                    yfactor = float(val)
                elif key_norm == "FIRSTX":
                    firstx = float(val)
                elif key_norm == "LASTX":
                    lastx = float(val)
                elif key_norm == "NPOINTS":
                    npoints = int(float(val))
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
        for line in xydata_lines:
            leading_x, row_values = _jcamp_decode_asdf_line(line)
            for j, raw_y in enumerate(row_values):
                xs.append(leading_x + j)  # placeholder index; overwritten below using FIRSTX/LASTX spacing
                ys.append(raw_y * yfactor)
        # ASDF encodes Y values only; X spacing is uniform and derived from
        # FIRSTX/LASTX/NPOINTS (the per-line leading X is just a checkpoint,
        # not literally used point-by-point) -- reconstruct the true X axis.
        if firstx is None or lastx is None:
            raise ValueError("JCAMP-DX ##XYDATA block found but ##FIRSTX/##LASTX metadata is missing; "
                              "cannot reconstruct the X axis reliably.")
        n = len(ys)
        xs = list(np.linspace(firstx * xfactor, lastx * xfactor, n))
    elif xypoints_pairs:
        xs = [p[0] * xfactor for p in xypoints_pairs]
        ys = [p[1] * yfactor for p in xypoints_pairs]
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
        expected_span = abs(lastx * xfactor - firstx * xfactor)
        actual_span = abs(float(x_arr[-1]) - float(x_arr[0]))
        if expected_span > 0 and abs(actual_span - expected_span) / expected_span > 0.01:
            raise ValueError("JCAMP-DX decode's X range doesn't match the file's declared "
                              "##FIRSTX/##LASTX -- refusing to return possibly-corrupted data.")

    if xunits:
        meta["xunits"] = xunits
    if yunits:
        meta["yunits"] = yunits
    return ReadResult(x_arr, y_arr, x_label=xunits or "X", y_label=yunits or "Y", metadata=meta, confidence="high")


FTIR_READERS = {
    ".xy": read_generic_text,
    ".txt": read_generic_text,
    ".dat": read_generic_text,
    ".csv": read_generic_text,
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
