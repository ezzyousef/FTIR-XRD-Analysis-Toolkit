"""
session_io.py
Save/restore a full analysis session (loaded traces, detected peaks, mode,
etc.) to a single JSON project file (.ftirxrd) so users can pick up work later.
"""
import json
import numpy as np


def _to_jsonable(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    return obj


def save_session(path, app_state):
    """app_state: a plain dict describing everything needed to restore the session."""
    payload = _to_jsonable(app_state)
    payload["_format"] = "ftir_xrd_toolkit_session"
    payload["_version"] = 1
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def load_session(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("_format") != "ftir_xrd_toolkit_session":
        raise ValueError("This file is not a recognized FTIR/XRD Toolkit session file.")
    return data
