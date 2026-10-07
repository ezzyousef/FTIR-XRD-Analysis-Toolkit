"""
app_window.py
The application window, built on the lab's shared labkit shell (the same one as AeroLab
Studio, the DV1 Viscosity Logger and Supercap Suite): FTIR and XRD analysis pages, the FTIR
reference database, sources and About; menus, recent files, undo/redo and OriginLab.
"""
from __future__ import annotations

import html
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QSplitter, QTextBrowser, QVBoxLayout, QWidget

import app_config
import file_readers
import ftir_analysis
from app_info import APP_ID, APP_NAME, APP_VERSION, AUTHOR_EMAIL, AUTHOR_NAME, resource_path
from labkit.qt.about import AboutPage
from labkit.qt.history import History
from labkit.qt.origin_worker import OriginWorker
from labkit.qt.shell import AppInfo, AppShell
from ui_common import DataTable

ANALYSIS_PAGES = ("ftir", "xrd")
FTIR_ONLY_EXTENSIONS = {".jdx", ".dx", ".dpt"}
XRD_ONLY_EXTENSIONS = {".uxd", ".ras", ".xrdml", ".raw"}


def load_ftir_database():
    return ftir_analysis.load_database(resource_path(os.path.join("database", "ftir_reference_db.json")))


def material_count(db) -> int:
    return sum(len(db.get(cat, [])) for cat in ftir_analysis.MATERIAL_CATEGORIES)


def make_app_info(db) -> AppInfo:
    references = db.get("_meta", {}).get("references", [])
    return AppInfo(
        name=APP_NAME,
        short_name="FTIR & XRD Toolkit",
        version=APP_VERSION,
        app_id=APP_ID,
        tagline="FTIR spectra and X-ray diffraction patterns, analysed and exported",
        description="Multi-spectrum FTIR analysis with peak detection, processing, database screening and "
                    "peak fitting; XRD d-spacing, Scherrer and Williamson–Hall sizes, crystallinity and peak "
                    "fitting — with styled OriginLab graphs, Excel workbooks and PDF reports.",
        author=AUTHOR_NAME,
        email=AUTHOR_EMAIL,
        lab="EML",
        lab_full="Energy Materials Laboratory",
        icon_path=resource_path(os.path.join("assets", "icon.png")),
        logo_path=resource_path(os.path.join("assets", "eml_logo.png")),
        sources=[
            "Every calculation's equation and literature source: the ⓘ button beside it.",
            f"FTIR reference database: {material_count(db)} materials and "
            f"{len(db.get('functional_groups', []))} functional-group correlations compiled from "
            f"{len(references)} published sources — see Library › Sources &amp; references.",
            "Database matching is heuristic screening, not certified identification: confirm anything "
            "consequential against a certified reference spectrum (e.g. NIST WebBook, SDBS).",
            "XRD phase identification against reference cards is out of scope — use your diffractometer's "
            "search/match software, then bring the pattern here for the quantitative work.",
        ],
    )


class DatabasePage(QWidget):
    """Browse every material in the FTIR reference database, its bands and its source."""

    def __init__(self, db):
        super().__init__()
        self.db = db
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Search materials…")
        self.search.textChanged.connect(lambda _t: self.refresh())
        self.category = QComboBox()
        self.category.addItem("All categories", None)
        for key in ftir_analysis.MATERIAL_CATEGORIES:
            self.category.addItem(ftir_analysis.CATEGORY_LABELS[key], key)
        self.category.currentIndexChanged.connect(lambda _i: self.refresh())
        self.count = QLabel()
        self.count.setObjectName("Hint")
        row.addWidget(self.search, 1)
        row.addWidget(self.category)
        row.addWidget(self.count)
        layout.addLayout(row)
        splitter = QSplitter(Qt.Horizontal)
        self.materials = DataTable(["Material", "Category", "Bands", "Source"])
        self.materials.on_select = self._show_peaks
        self.peaks = DataTable(["Range (cm⁻¹)", "Assignment", "Intensity"])
        splitter.addWidget(self.materials)
        splitter.addWidget(self.peaks)
        splitter.setSizes([640, 460])
        layout.addWidget(splitter, 1)
        self.refresh()

    def refresh(self):
        entries = ftir_analysis.search_database(self.db, self.search.text(), category=self.category.currentData())
        self.materials.set_rows(entries, lambda e: (
            e["name"], ftir_analysis.CATEGORY_LABELS.get(e.get("category"), e.get("category", "")),
            len(e["peaks"]), e.get("source", "")))
        self.peaks.clear_rows()
        self.count.setText(f"{len(entries)} of {material_count(self.db)}")

    def _show_peaks(self, entry):
        self.peaks.set_rows(entry["peaks"], lambda p: (
            "IR-inactive" if p["range"] == [0, 0] or tuple(p["range"]) == (0, 0) else f"{p['range'][0]}–{p['range'][1]}",
            p["assignment"], p.get("intensity", "")))


class SourcesPage(QWidget):
    """The note and full bibliography behind the FTIR reference database."""

    def __init__(self, db):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        meta = db.get("_meta", {})
        refs = sorted(meta.get("references", []), key=lambda r: str(r.get("id", "")))
        items = "".join(f"<li><b>[{html.escape(str(r.get('id', '')))}]</b> {html.escape(str(r.get('citation', '')))}</li>"
                        for r in refs)
        text = QTextBrowser()
        text.setOpenExternalLinks(True)
        text.setHtml(
            "<p>Every material in the built-in FTIR database carries a <i>source</i> tag referring to one or more "
            "of the works below. The toolkit compiles published correlation tables and constants — a screening aid, "
            "not a certified reference measurement. Confirm anything consequential against the certified source.</p>"
            f"<p><b>Database note.</b> {html.escape(str(meta.get('note', '')))}</p>"
            f"<h3>Bibliography ({len(refs)})</h3><ol style='margin-left:-18px'>{items}</ol>"
            "<p>Equations and their sources for every calculation: the ⓘ button beside each tool.</p>")
        layout.addWidget(text)


class MainWindow(AppShell):
    def __init__(self):
        # Nothing may be set on self before the Qt base class exists, so the history reaches
        # the window through this holder.
        holder: dict = {}
        history = History(lambda: holder["w"]._capture_state() if "w" in holder else None,
                          lambda state: holder["w"]._restore_state(state) if "w" in holder else None,
                          initial_label="empty session")
        db = load_ftir_database()
        super().__init__(make_app_info(db), history=history)
        holder["w"] = self
        self.ftir_db = db
        self.cfg = app_config.load_config()
        self.origin = OriginWorker(visible=True, parent=self)
        self._last_analysis = "ftir"

        from ftir_tab import FTIRTab
        from xrd_tab import XRDTab
        self.add_page("ftir", "FTIR spectra", lambda: FTIRTab(self), section="Analyse", glyph="∿",
                      subtitle="Overlay spectra, detect and fit bands, screen the reference database, calculate.",
                      lazy=False)
        self.add_page("xrd", "XRD patterns", lambda: XRDTab(self), section="Analyse", glyph="◇",
                      subtitle="d-spacing, Scherrer and Williamson–Hall sizes, crystallinity and peak fitting.")
        self.add_page("database", "Reference database", lambda: DatabasePage(self.ftir_db), section="Library",
                      glyph="▤", subtitle=f"{material_count(db)} materials with their bands and literature sources.")
        self.add_page("sources", "Sources & references", lambda: SourcesPage(self.ftir_db), section="Library",
                      glyph="❝")
        self.add_page("about", "About", lambda: AboutPage(self.info, tiles=self._about_tiles(), notify=self.notify),
                      section="Help", glyph="ⓘ")
        self._build_menus()
        self.page_changed.connect(self._remember_analysis_page)
        self.on_close(self._on_close)
        self.finalize(start_page="ftir")
        self.history.reset("empty session")
        self.set_status("Ready", "")

    def notify(self, message: str, level: str = "info") -> None:
        """Routine confirmations go to the status bar only; toasts are kept for warnings and
        errors, so they do not stack over the results the user is reading."""
        if level in ("warning", "error"):
            super().notify(message, level)
        else:
            self.set_status(message)

    def _match_ftir(self):
        self.go_to("ftir")
        self.page("ftir").match_database()

    # ------------------------------------------------------------------ menus
    def _build_menus(self):
        f = "&File"
        self.add_menu_action(f, "&Open data files…", lambda: self._with_tab(lambda t: t.load_file_dialog()), "Ctrl+O")
        self._recent_menu = self._menu(f).addMenu("Open &recent")
        self._recent_menu.aboutToShow.connect(self._fill_recent_menu)
        self.add_menu_separator(f)
        self.add_menu_action(f, "&Save session…", lambda: self._with_tab(lambda t: t.save_session()), "Ctrl+S")
        self.add_menu_action(f, "&Load session…", lambda: self._with_tab(lambda t: t.load_session()), "Ctrl+L")
        self.add_menu_separator(f)
        self.add_menu_action(f, "Export PDF &report…", lambda: self._with_tab(lambda t: t.export_pdf_report()), "Ctrl+E")
        self.add_menu_action(f, "Export peak list (CSV)…", lambda: self._with_tab(lambda t: t.export_peaks_csv()))
        self.add_menu_action(f, "Export for OriginLab (CSV)…", lambda: self._with_tab(lambda t: t.export_originlab_dialog()))
        self.add_menu_action(f, "Export graph…", lambda: self._with_tab(lambda t: t.export_graph_dialog()))
        self.add_menu_separator(f)
        self.add_menu_action(f, "Send to &Origin", lambda: self._with_tab(lambda t: t.export_bar.send_to_origin()),
                             "Ctrl+Shift+O")
        self.add_menu_action(f, "Export to E&xcel…", lambda: self._with_tab(lambda t: t.export_bar.export_excel()),
                             "Ctrl+Shift+E")
        self.add_menu_separator(f)
        self.add_menu_action(f, "E&xit", self.close, "Ctrl+Q")
        self.add_menu_action("&Tools", "&Match FTIR spectrum to database", self._match_ftir, "Ctrl+M")
        self.add_menu_action("&Tools", "FTIR reference &database", lambda: self.go_to("database"), "Ctrl+D")
        self.add_menu_action("&Tools", "Sources && references", lambda: self.go_to("sources"))
        for name, group, fn in (
                ("Open data files", "File", lambda: self._with_tab(lambda t: t.load_file_dialog())),
                ("Save session", "File", lambda: self._with_tab(lambda t: t.save_session())),
                ("Load session", "File", lambda: self._with_tab(lambda t: t.load_session())),
                ("Export PDF report", "Export", lambda: self._with_tab(lambda t: t.export_pdf_report())),
                ("Send to Origin", "Export", lambda: self._with_tab(lambda t: t.export_bar.send_to_origin())),
                ("Export to Excel", "Export", lambda: self._with_tab(lambda t: t.export_bar.export_excel()))):
            self.add_command(name, group, fn)

    def _fill_recent_menu(self):
        self._recent_menu.clear()
        recent = [p for p in self.cfg.get("recent_files", []) if p]
        if not recent:
            action = self._recent_menu.addAction("(no recent files)")
            action.setEnabled(False)
            return
        for path in recent:
            label = path if len(path) < 70 else "…" + path[-67:]
            self._recent_menu.addAction(label.replace("&", "&&"), lambda p=path: self.open_files([p]))

    # ------------------------------------------------------------------ pages
    def _remember_analysis_page(self, key):
        if key in ANALYSIS_PAGES:
            self._last_analysis = key

    def _with_tab(self, fn):
        key = self.current_key if self.current_key in ANALYSIS_PAGES else self._last_analysis
        if self.current_key != key:
            self.go_to(key)
        return fn(self.page(key))

    def route_for(self, path) -> str:
        ext = os.path.splitext(path)[1].lower()
        if ext in FTIR_ONLY_EXTENSIONS:
            return "ftir"
        if ext in XRD_ONLY_EXTENSIONS:
            return "xrd"
        return self.current_key if self.current_key in ANALYSIS_PAGES else self._last_analysis

    def open_files(self, paths):
        existing = [p for p in paths if os.path.isfile(p)]
        for missing in set(paths) - set(existing):
            self.notify(f"File not found: {missing}", "warning")
        groups: dict[str, list] = {}
        for path in existing:
            groups.setdefault(self.route_for(path), []).append(path)
        for key, group in groups.items():
            self.go_to(key)
            self.page(key).load_paths(group)

    def note_recent_file(self, path):
        app_config.add_recent_file(self.cfg, path)
        self.cfg["last_dir"] = os.path.dirname(path)
        try:
            app_config.save_config(self.cfg)
        except OSError:
            pass

    # ------------------------------------------------------------------ undo / redo
    def record_history(self, label):
        self.history.record(label)

    def _capture_state(self):
        return {key: self.page(key).snapshot() for key in ANALYSIS_PAGES if self.is_page_built(key)}

    def _restore_state(self, state):
        if state is None:
            return
        for key in ANALYSIS_PAGES:
            if self.is_page_built(key):
                self.page(key).restore(state.get(key))

    # ------------------------------------------------------------------ about / close
    def _about_tiles(self):
        from labkit.origin import origin_available
        formats = set(getattr(file_readers, "READERS", {})) | set(getattr(file_readers, "FTIR_READERS", {}))
        return [("FTIR materials", str(material_count(self.ftir_db))),
                ("Functional groups", str(len(self.ftir_db.get("functional_groups", [])))),
                ("File formats", str(len(formats))),
                ("OriginLab", "available" if origin_available()[0] else "not installed")]

    def _on_close(self):
        for key in ANALYSIS_PAGES:
            if self.is_page_built(key):
                self.page(key).wait_for_workers(15000)
        try:
            app_config.save_config(self.cfg)
        except OSError:
            pass
        # Joins the Origin thread; Qt aborts the process if a running QThread is destroyed.
        self.origin.shutdown(15000)
        return None
