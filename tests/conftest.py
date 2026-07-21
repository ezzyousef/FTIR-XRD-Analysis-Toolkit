import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULES_DIR = os.path.join(APP_DIR, "modules")
DB_DIR = os.path.join(APP_DIR, "database")

if MODULES_DIR not in sys.path:
    sys.path.insert(0, MODULES_DIR)
