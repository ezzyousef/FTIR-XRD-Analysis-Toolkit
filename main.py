"""
FTIR & XRD Analysis Toolkit -- Professional Edition
Desktop application entry point.

Run with:      python main.py
Package to .exe with:  build_exe.bat  (Windows, see README.md)
"""
import os
import sys
import traceback
import tkinter as tk

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules"))

APP_DIR = os.path.dirname(os.path.abspath(__file__))
APP_TITLE = "FTIR & XRD Analysis Toolkit — Professional Edition"

LIGHT_THEMES = ["flatly", "cosmo", "journal", "litera", "lumen", "minty",
                "pulse", "sandstone", "united", "yeti", "morph", "simplex", "cerculean"]
DARK_THEMES = ["darkly", "superhero", "solar", "cyborg", "vapor"]

# Populated by _prewarm_heavy_imports(), after the splash screen is already on
# screen -- see that function's docstring for why these aren't just ordinary
# top-of-file imports.
tb = Messagebox = ScrolledText = None
app_config = ftir_analysis = xrd_analysis = None
FTIRTab = XRDTab = None
DatabaseViewerDialog = ReferencesDialog = AboutDialog = None
tkinterdnd2 = None
DND_LIB_AVAILABLE = False


def resource_path(rel_path):
    """Handle asset paths both in dev and when frozen by PyInstaller."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel_path)
    return os.path.join(APP_DIR, rel_path)


def _show_splash():
    """
    A plain-tkinter (no ttkbootstrap, no matplotlib) window that paints
    almost instantly, shown BEFORE _prewarm_heavy_imports() below -- cold-
    importing matplotlib/scipy/ttkbootstrap/reportlab takes a few real
    seconds. Without something on screen during that wait, Windows shows its
    own "app isn't responding yet" placeholder (a generic icon + wobble)
    instead, which reads as broken/slow rather than just starting up.
    Falls back to no logo (text only) if the EML logo asset is missing, so a
    missing image never fails startup.
    """
    splash = tk.Tk()
    splash.overrideredirect(True)
    splash.configure(bg="#ffffff")
    try:
        splash.attributes("-topmost", True)
    except Exception:
        pass

    border = tk.Frame(splash, bg="#2453ff", padx=1, pady=1)
    border.pack()
    inner = tk.Frame(border, bg="#ffffff", padx=36, pady=28)
    inner.pack()

    logo_path = resource_path(os.path.join("assets", "eml_logo.png"))
    if os.path.exists(logo_path):
        try:
            img = tk.PhotoImage(file=logo_path)
            logo_label = tk.Label(inner, image=img, bg="#ffffff")
            logo_label.image = img  # keep a reference so it isn't garbage-collected
            logo_label.pack(pady=(0, 16))
        except Exception:
            pass

    tk.Label(inner, text="FTIR & XRD Analysis Toolkit", font=("Segoe UI", 13, "bold"),
             bg="#ffffff", fg="#1b1e22").pack()
    tk.Label(inner, text="Professional Edition", font=("Segoe UI", 9),
             bg="#ffffff", fg="#666666").pack(pady=(0, 14))
    tk.Label(inner, text="Loading...", font=("Segoe UI", 9), bg="#ffffff", fg="#999999").pack()

    splash.update_idletasks()
    w, h = splash.winfo_reqwidth(), splash.winfo_reqheight()
    sw, sh = splash.winfo_screenwidth(), splash.winfo_screenheight()
    splash.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
    if splash:
        splash.update()
    return splash


def _prewarm_heavy_imports(splash=None):
    """
    Imports every slow, dependency-heavy module ONE AT A TIME, pumping the
    splash window's event loop (splash.update()) between each -- a single
    monolithic block of imports blocks the message loop for its entire
    multi-second cold-import duration in one uninterrupted stretch, which
    Windows' DWM can treat as the window having hung (repainting its own
    ghost/peek preview for it -- the "icon appears and disappears" symptom).
    Splitting the imports with update() calls in between keeps the splash's
    message pump alive throughout, so Windows never considers it stuck.

    Binds every name as a MODULE global (not a local of this function) via
    the `global` statement, since MainWindow's methods below reference them
    as ordinary module-level names -- Python only resolves those lookups
    when a method actually runs, which is safely after this function has
    already populated them.
    """
    global tb, Messagebox, ScrolledText
    global app_config, ftir_analysis, xrd_analysis, FTIRTab, XRDTab
    global DatabaseViewerDialog, ReferencesDialog, AboutDialog
    global tkinterdnd2, DND_LIB_AVAILABLE

    # Pin the matplotlib backend explicitly, before anything else touches
    # matplotlib: without this, matplotlib's own backend auto-discovery can
    # pick whatever GUI toolkit happens to be importable in the environment
    # (e.g. Qt, if another project's PySide6 is on the same machine/venv)
    # even though this app only ever uses the Tk canvas -- which then drags
    # a needless ~100MB Qt runtime into the PyInstaller build.
    import matplotlib
    matplotlib.use("TkAgg")
    if splash:
        splash.update()

    import ttkbootstrap as tb
    from ttkbootstrap.dialogs import Messagebox
    from ttkbootstrap.widgets.scrolled import ScrolledText
    if splash:
        splash.update()

    import app_config
    if splash:
        splash.update()

    import ftir_analysis
    import xrd_analysis
    if splash:
        splash.update()

    from ftir_tab import FTIRTab
    from xrd_tab import XRDTab
    if splash:
        splash.update()

    from ui_common import DatabaseViewerDialog, ReferencesDialog, AboutDialog
    if splash:
        splash.update()

    try:
        import tkinterdnd2
        DND_LIB_AVAILABLE = True
    except ImportError:
        DND_LIB_AVAILABLE = False
    if splash:
        splash.update()


class MainWindow:
    def __init__(self):
        if app_config is None:
            # Constructed directly without going through main() first (e.g. a
            # test/verification script) -- run the deferred imports now
            # instead of failing with a confusing "NoneType has no attribute"
            # error. main() itself always calls this before MainWindow(), so
            # this is a no-op on the normal startup path.
            _prewarm_heavy_imports(None)
        self.cfg = app_config.load_config()
        theme = self.cfg.get("theme", "flatly")
        if theme not in LIGHT_THEMES + DARK_THEMES:
            theme = "flatly"

        self.root = tb.Window(themename=theme)
        self.root.title(APP_TITLE)
        self.root.geometry("1440x880")
        self.root.minsize(1100, 700)
        self.root.report_callback_exception = self._handle_exception

        icon_ico = resource_path(os.path.join("assets", "icon.ico"))
        if os.path.exists(icon_ico):
            try:
                self.root.iconbitmap(icon_ico)
            except Exception:
                pass

        self.dnd_ready = False
        if DND_LIB_AVAILABLE:
            try:
                tkinterdnd2.TkinterDnD.require(self.root)
                self.dnd_ready = True
            except Exception:
                self.dnd_ready = False

        self.ftir_db = ftir_analysis.load_database(resource_path(os.path.join("database", "ftir_reference_db.json")))
        self.xrd_db = xrd_analysis.load_xrd_database(resource_path(os.path.join("database", "xrd_reference_db.json")))

        self.theme_var = tb.StringVar(value=theme)
        self.status_msg_var = tb.StringVar(value="Ready.")
        self.status_coords_var = tb.StringVar(value="")

        self._build_menu()
        self._build_body()
        self._build_status_bar()
        self._bind_shortcuts()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------------- menu

    def _build_menu(self):
        menubar = tb.Menu(self.root)
        self.root.configure(menu=menubar)

        file_menu = tb.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Load Spectrum/Pattern...  (Ctrl+O)", command=self._load_into_current_tab)
        self.recent_menu = tb.Menu(file_menu, tearoff=False)
        file_menu.add_cascade(label="Open Recent", menu=self.recent_menu)
        self._refresh_recent_menu()
        file_menu.add_separator()
        file_menu.add_command(label="Save Session...  (Ctrl+S)", command=self._save_current_session)
        file_menu.add_command(label="Load Session...", command=self._load_current_session)
        file_menu.add_separator()
        file_menu.add_command(label="Export PDF Report...  (Ctrl+E)", command=self._export_current_report)
        file_menu.add_separator()
        file_menu.add_command(label="Exit  (Ctrl+Q)", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tb.Menu(menubar, tearoff=False)
        light_menu = tb.Menu(view_menu, tearoff=False)
        for name in LIGHT_THEMES:
            light_menu.add_radiobutton(label=name.title(), variable=self.theme_var, value=name,
                                        command=lambda n=name: self.set_theme(n))
        view_menu.add_cascade(label="Light Themes", menu=light_menu)
        dark_menu = tb.Menu(view_menu, tearoff=False)
        for name in DARK_THEMES:
            dark_menu.add_radiobutton(label=name.title(), variable=self.theme_var, value=name,
                                       command=lambda n=name: self.set_theme(n))
        view_menu.add_cascade(label="Dark Themes", menu=dark_menu)
        view_menu.add_separator()
        view_menu.add_command(label="Toggle Light/Dark", command=self._toggle_light_dark)
        menubar.add_cascade(label="View", menu=view_menu)

        tools_menu = tb.Menu(menubar, tearoff=False)
        tools_menu.add_command(label="Reference Database Viewer...  (Ctrl+D)", command=self.open_database_viewer)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = tb.Menu(menubar, tearoff=False)
        help_menu.add_command(label="Data Sources & References...", command=self.open_references)
        help_menu.add_command(label="About...", command=self.open_about)
        menubar.add_cascade(label="Help", menu=help_menu)

    def _refresh_recent_menu(self):
        self.recent_menu.delete(0, "end")
        recent = self.cfg.get("recent_files", [])
        if not recent:
            self.recent_menu.add_command(label="(no recent files)", state="disabled")
            return
        for path in recent:
            label = path if len(path) < 70 else "..." + path[-67:]
            self.recent_menu.add_command(label=label, command=lambda p=path: self._open_recent(p))

    def _open_recent(self, path):
        if not os.path.exists(path):
            Messagebox.show_warning(f"File no longer exists:\n{path}", "Not Found")
            return
        tab = self._current_tab()
        tab.load_file_path(path, tab.default_reader)

    # ---------------------------------------------------------------- body

    def _build_body(self):
        self.notebook = tb.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=(6, 0))

        import file_readers
        self.ftir_tab = FTIRTab(self.notebook, self)
        self.ftir_tab.default_reader = file_readers.read_ftir_any
        self.notebook.add(self.ftir_tab, text="  FTIR Analysis  ")

        self.xrd_tab = XRDTab(self.notebook, self)
        self.xrd_tab.default_reader = file_readers.read_any
        self.notebook.add(self.xrd_tab, text="  XRD Analysis  ")

        self.about_tab = self._build_about_tab()
        self.notebook.add(self.about_tab, text="  About  ")

    def _build_about_tab(self):
        frame = tb.Frame(self.notebook, padding=24)

        logo_path = resource_path(os.path.join("assets", "eml_logo.png"))
        if os.path.exists(logo_path):
            try:
                img = tb.PhotoImage(file=logo_path)
                logo_label = tb.Label(frame, image=img)
                logo_label.image = img  # keep a reference so it isn't garbage-collected
                logo_label.pack(anchor="w", pady=(0, 14))
            except Exception:
                pass

        tb.Label(frame, text="FTIR & XRD Analysis Toolkit", font=("", 18, "bold"), bootstyle="primary").pack(anchor="w")
        tb.Label(frame, text="Professional Edition — built for the Energy Materials Laboratory (EML)",
                 bootstyle="secondary").pack(anchor="w", pady=(0, 14))

        body = ScrolledText(frame, height=18, autohide=True)
        body.pack(fill="both", expand=True)
        body.text.insert("1.0",
            "FTIR tab\n"
            "  - Load spectra (multi-trace overlay), smoothing, baseline correction, normalization\n"
            "  - Automatic peak detection with adjustable sensitivity\n"
            "  - Screening match against a 224-material reference database (polymers, hydrogels,\n"
            "    salts, inorganic oxides/minerals, organic/biomolecules, elements & allotropes) plus\n"
            "    67 generic functional-group correlations -- restrict the search to one category\n"
            "    (e.g. just Organic/Biomolecules) for more accurate, faster matching\n"
            "  - Gaussian / Lorentzian / pseudo-Voigt peak fitting\n"
            "  - Calculators: %T <-> Absorbance, peak area, FWHM, Beer-Lambert concentration\n\n"
            "XRD tab\n"
            "  - Load patterns (.xy/.txt/.dat/.csv, .uxd, .ras, .xrdml, best-effort Bruker .raw)\n"
            "  - Peak detection, Bragg d-spacing, Scherrer crystallite size, Williamson-Hall\n"
            "    size/strain separation, % crystallinity, and both a quick single-peak\n"
            "    cubic lattice parameter and an iterative multi-peak lattice refinement\n"
            "    (cubic/tetragonal/hexagonal/orthorhombic, with automatic outlier rejection)\n"
            "  - Screening match against a 23-phase reference database (metals, oxides, minerals,\n"
            "    salts, semiconductors, carbon allotropes) by wavelength-independent d-spacing --\n"
            "    also restrictable by category, extensible via CSV import\n"
            "  - Gaussian / Lorentzian / pseudo-Voigt peak fitting\n\n"
            "Every tool\n"
            "  - Every database entry and every calculation carries a literature citation --\n"
            "    click the (i) button next to a tool, or see Help > Data Sources & References\n"
            "  - PDF report export, session save/load, drag & drop file loading, light/dark themes\n\n"
            "This toolkit is a heuristic screening aid, not a certified identification service --\n"
            "always confirm anything consequential against a certified reference spectrum/card or\n"
            "an expert. See Help > Data Sources & References for exactly which literature the\n"
            "built-in databases are compiled from."
        )
        body.text.configure(state="disabled")

        tb.Button(frame, text="View Data Sources & References", bootstyle="primary",
                  command=self.open_references).pack(anchor="w", pady=(14, 0))
        return frame

    def _current_tab(self):
        widget_name = self.notebook.select()
        widget = self.root.nametowidget(widget_name)
        return widget

    # ---------------------------------------------------------------- status bar

    def _build_status_bar(self):
        bar = tb.Frame(self.root, padding=(10, 4))
        bar.pack(fill="x", side="bottom")
        tb.Label(bar, textvariable=self.status_msg_var, bootstyle="secondary").pack(side="left")
        tb.Label(bar, textvariable=self.status_coords_var, bootstyle="secondary").pack(side="left", padx=20)
        db_counts = (f"FTIR DB: {sum(len(self.ftir_db.get(c, [])) for c in ftir_analysis.MATERIAL_CATEGORIES)} materials   |   "
                     f"XRD DB: {len(self.xrd_db.get('phases', []))} phases")
        tb.Label(bar, text=db_counts, bootstyle="secondary").pack(side="right")

    def set_status_message(self, msg):
        self.status_msg_var.set(msg)

    def set_status_coords(self, text):
        self.status_coords_var.set(text)

    # ---------------------------------------------------------------- shortcuts

    def _bind_shortcuts(self):
        self.root.bind("<Control-o>", lambda e: self._load_into_current_tab())
        self.root.bind("<Control-s>", lambda e: self._save_current_session())
        self.root.bind("<Control-e>", lambda e: self._export_current_report())
        self.root.bind("<Control-d>", lambda e: self.open_database_viewer())
        self.root.bind("<Control-q>", lambda e: self._on_close())

    def _load_into_current_tab(self):
        tab = self._current_tab()
        if tab is self.ftir_tab:
            tab._load_spectrum()
        elif tab is self.xrd_tab:
            tab._load_pattern()
        else:
            Messagebox.show_info("Switch to the FTIR or XRD Analysis tab first.", "No Active Analysis Tab")

    def _save_current_session(self):
        tab = self._current_tab()
        if tab in (self.ftir_tab, self.xrd_tab):
            tab.save_session()

    def _load_current_session(self):
        tab = self._current_tab()
        if tab in (self.ftir_tab, self.xrd_tab):
            tab.load_session()

    def _export_current_report(self):
        tab = self._current_tab()
        if tab in (self.ftir_tab, self.xrd_tab):
            tab.export_pdf_report()

    # ---------------------------------------------------------------- theming

    def set_theme(self, name):
        try:
            self.root.style.theme_use(name)
        except Exception:
            return
        self.theme_var.set(name)
        self.cfg["theme"] = name
        app_config.save_config(self.cfg)

    def _toggle_light_dark(self):
        current = self.theme_var.get()
        if current in DARK_THEMES:
            self.set_theme(self.cfg.get("_last_light", "flatly"))
        else:
            self.cfg["_last_light"] = current
            self.set_theme("darkly")

    # ---------------------------------------------------------------- dialogs

    def open_database_viewer(self):
        DatabaseViewerDialog(self.root, self.ftir_db, ftir_analysis,
                              lambda: xrd_analysis.merged_database(self.xrd_db), xrd_analysis)

    def open_references(self):
        ReferencesDialog(self.root, self.ftir_db, self.xrd_db)

    def open_about(self):
        AboutDialog(self.root, icon_path=resource_path(os.path.join("assets", "icon.png")))

    # ---------------------------------------------------------------- shared helpers used by tabs

    def note_recent_file(self, path):
        app_config.add_recent_file(self.cfg, path)
        self.cfg["last_dir"] = os.path.dirname(path)
        app_config.save_config(self.cfg)
        self._refresh_recent_menu()

    def parse_dnd_paths(self, data):
        try:
            paths = self.root.tk.splitlist(data)
        except Exception:
            paths = data.split()
        return [p for p in paths if os.path.isfile(p)]

    # ---------------------------------------------------------------- lifecycle

    def _handle_exception(self, exc_type, exc_value, exc_tb):
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        print(msg, file=sys.stderr)
        try:
            Messagebox.show_error(f"{exc_type.__name__}: {exc_value}\n\nSee console/log for full details.",
                                   "Unexpected Error")
        except Exception:
            pass

    def _on_close(self):
        app_config.save_config(self.cfg)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    splash = _show_splash()
    _prewarm_heavy_imports(splash)
    # Destroy the splash's plain tk.Tk() root COMPLETELY before creating the
    # real tb.Window() root -- ttkbootstrap's Style engine configures colored
    # "bootstyle" variants (primary.TButton, success.TButton, etc.) against
    # whichever Tk interpreter it thinks is current, and two live Tk roots
    # at once make it register those styles on the wrong one, silently
    # falling back to plain undecorated ttk widgets (no crash, just no
    # color). Only ever one Tk root alive at a time avoids that entirely.
    splash.destroy()
    app = MainWindow()
    app.root.lift()
    app.root.focus_force()
    app.run()


if __name__ == "__main__":
    main()
