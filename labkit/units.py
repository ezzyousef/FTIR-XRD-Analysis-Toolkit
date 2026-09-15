"""Turn a column name into a readable label and a unit.

Instrument software and analysis code name columns in two ways, and Origin wants both as
a separate Long Name and Units:

    "Stress (MPa)"             ->  ("Stress", "MPa")
    "k (mW/(m·K))"             ->  ("k", "mW/(m·K)")          nested brackets survive
    "heat_flow_mw"             ->  ("Heat flow", "mW")
    "capacitance_f_per_g"      ->  ("Capacitance", "F/g")
    "scan_rate_mv_per_s"       ->  ("Scan rate", "mV/s")
"""
from __future__ import annotations

import re

__all__ = ["split_label", "split_bracketed_unit", "split_snake_unit", "UNIT_TOKENS"]

# snake_case token -> unit as it should be printed. Only unambiguous tokens are listed:
# "a" is amperes only when it is the final token of a name that has a quantity before it.
UNIT_TOKENS: dict[str, str] = {
    "s": "s", "ms": "ms", "min": "min", "h": "h", "hr": "h",
    "v": "V", "mv": "mV", "a": "A", "ma": "mA", "ua": "µA", "na": "nA",
    "w": "W", "mw": "mW", "kw": "kW", "wh": "Wh", "mwh": "mWh",
    "j": "J", "kj": "kJ", "mj": "mJ",
    "f": "F", "mf": "mF", "uf": "µF",
    "c": "°C", "degc": "°C", "k": "K",
    "ohm": "Ω", "ohms": "Ω", "mohm": "mΩ", "kohm": "kΩ",
    "hz": "Hz", "khz": "kHz", "mhz": "mHz",
    "g": "g", "mg": "mg", "kg": "kg",
    "cm": "cm", "mm": "mm", "um": "µm", "nm": "nm", "m": "m",
    "cm2": "cm²", "mm2": "mm²", "m2": "m²", "cm3": "cm³", "ml": "mL", "l": "L",
    "pct": "%", "percent": "%",
    "cp": "cP", "mpa": "mPa", "pa": "Pa", "kpa": "kPa", "mpas": "mPa·s", "pas": "Pa·s",
    "rpm": "rpm", "deg": "°", "rad": "rad",
    "cm1": "cm⁻¹", "invcm": "cm⁻¹",
    "au": "a.u.", "counts": "counts", "cps": "cps",
    "s_per_cm": "S/cm", "ms_per_cm": "mS/cm",
    "dyn": "dyn", "dyn_per_cm2": "dyn/cm²",
}

_BRACKET_PAIRS = {")": "(", "]": "["}


def split_bracketed_unit(name: str) -> tuple[str, str] | None:
    """Split a trailing bracketed unit, matching brackets so nesting survives."""
    text = name.strip()
    if not text or text[-1] not in _BRACKET_PAIRS:
        return None
    close, open_ = text[-1], _BRACKET_PAIRS[text[-1]]
    depth = 0
    for i in range(len(text) - 1, -1, -1):
        if text[i] == close:
            depth += 1
        elif text[i] == open_:
            depth -= 1
            if depth == 0:
                label, unit = text[:i].strip(), text[i + 1:-1].strip()
                return (label, unit) if label and 0 < len(unit) <= 24 else None
    return None


def split_snake_unit(name: str) -> tuple[str, str] | None:
    """Recognise `quantity_unit` and `quantity_unit_per_unit` snake_case names."""
    text = name.strip().lower()
    if "_" not in text or " " in text:
        return None
    tokens = [t for t in text.split("_") if t]
    if len(tokens) < 2:
        return None

    # "..._x_per_y" -> unit "x/y"
    if len(tokens) >= 4 and tokens[-2] == "per" and tokens[-3] in UNIT_TOKENS and tokens[-1] in UNIT_TOKENS:
        unit = f"{UNIT_TOKENS[tokens[-3]]}/{UNIT_TOKENS[tokens[-1]]}"
        return _label_from(tokens[:-3]), unit
    if tokens[-1] in UNIT_TOKENS and len(tokens) >= 2:
        return _label_from(tokens[:-1]), UNIT_TOKENS[tokens[-1]]
    return None


def _label_from(tokens: list[str]) -> str:
    words = " ".join(tokens)
    return words[:1].upper() + words[1:] if words else ""


def split_label(name: str) -> tuple[str, str]:
    """Best readable (label, unit) for any column name. Unit is "" when there is none."""
    raw = str(name)
    for parser in (split_bracketed_unit, split_snake_unit):
        parsed = parser(raw)
        if parsed:
            return parsed
    cleaned = re.sub(r"_+", " ", raw).strip()
    return (cleaned[:1].upper() + cleaned[1:]) if cleaned else raw, ""
