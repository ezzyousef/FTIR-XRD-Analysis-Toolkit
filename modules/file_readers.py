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
    """Dispatch to the right reader based on file extension."""
    import os
    ext = os.path.splitext(path)[1].lower()
    if ext not in READERS:
        raise ValueError(
            f"Unsupported file extension '{ext}'. Supported: {', '.join(sorted(READERS))}. "
            "If your instrument exports something else, try exporting as ASCII (.xy/.txt) instead."
        )
    return READERS[ext](path)
