"""
app_config.py
Persisted user settings (theme, last-used directories, recent files) stored
as JSON under the OS-appropriate per-user config directory.
"""
import json
import os

APP_NAME = "FTIR_XRD_Toolkit"

DEFAULTS = {
    "theme": "flatly",
    "last_dir": "",
    "recent_files": [],
    "d_tolerance_pct": 1.5,
    "ftir_tolerance_cm1": 10.0,
}

MAX_RECENT = 10


def get_config_dir():
    base = os.getenv("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def get_config_path():
    return os.path.join(get_config_dir(), "config.json")


def load_config():
    path = get_config_path()
    cfg = dict(DEFAULTS)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(cfg):
    path = get_config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def add_recent_file(cfg, path):
    recent = [p for p in cfg.get("recent_files", []) if p != path]
    recent.insert(0, path)
    cfg["recent_files"] = recent[:MAX_RECENT]
    return cfg
