"""
app_info.py
Name, version and asset paths -- importable before anything heavy (the splash screen and
--version use it).
"""
import os
import sys

APP_NAME = "FTIR & XRD Analysis Toolkit"
APP_VERSION = "3.0.0"
APP_ID = "EML.FTIRXRDToolkit.Analysis.3"
AUTHOR_NAME = "Ezzeldien Yousef"
AUTHOR_EMAIL = "ezzyousef@aucegypt.edu"

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(rel_path):
    """An asset path in development and in a PyInstaller build."""
    base = getattr(sys, "_MEIPASS", None) or PROJECT_ROOT
    return os.path.join(base, rel_path)
