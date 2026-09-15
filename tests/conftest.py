import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULES_DIR = os.path.join(APP_DIR, "modules")
DB_DIR = os.path.join(APP_DIR, "database")

for _path in (MODULES_DIR, APP_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "Agg")
