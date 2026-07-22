"""
ui_common.py
Shared, reusable UI building blocks for the FTIR and XRD tabs: the trace
manager panel, a generic sortable data table, small modal dialogs, and the
Database Viewer / References dialogs.
"""
import os
import ttkbootstrap as tb
from tkinter import filedialog
from ttkbootstrap.dialogs import Messagebox
from ttkbootstrap.widgets.scrolled import ScrolledText, ScrolledFrame

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from trace_model import Trace, ColorCycle
from workers import BackgroundTask

_mplcursors_module = None
_mplcursors_checked = False


def _get_mplcursors():
    """
    Lazily imports mplcursors on first call and caches the result -- deferred
    (rather than a module-top import) so its ~0.4s cold-import cost isn't
    paid just to build the plot canvas; it's only actually needed once a
    trace with hover tooltips gets drawn, well after the window is already
    up. See the matching comment in ftir_analysis.py for the same rationale
    applied to scipy.
    """
    global _mplcursors_module, _mplcursors_checked
    if not _mplcursors_checked:
        _mplcursors_checked = True
        try:
            import mplcursors
            _mplcursors_module = mplcursors
        except ImportError:
            _mplcursors_module = None
    return _mplcursors_module


try:
    from tkinterdnd2 import DND_FILES
    DND_AVAILABLE_LIB = True
except ImportError:
    DND_AVAILABLE_LIB = False


# ============================= Small modal form dialog =============================

class MultiFieldDialog(tb.Toplevel):
    """
    A small modal form with one or more labeled text entries. Construct it and
    then read `.result` (a dict of {key: str}) -- None if the user cancelled.
    """
    def __init__(self, parent, title, fields, help_text=None):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.result = None
        self._vars = {}

        frm = tb.Frame(self, padding=18)
        frm.pack(fill="both", expand=True)

        if help_text:
            tb.Label(frm, text=help_text, wraplength=320, bootstyle="secondary").grid(
                row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
            row_offset = 1
        else:
            row_offset = 0

        first_entry = None
        for i, (key, label, default) in enumerate(fields):
            tb.Label(frm, text=label).grid(row=i + row_offset, column=0, sticky="w", pady=5, padx=(0, 12))
            var = tb.StringVar(value=default)
            ent = tb.Entry(frm, textvariable=var, width=22)
            ent.grid(row=i + row_offset, column=1, pady=5)
            if first_entry is None:
                first_entry = ent
            self._vars[key] = var

        btns = tb.Frame(frm)
        btns.grid(row=len(fields) + row_offset, column=0, columnspan=2, pady=(14, 0), sticky="e")
        tb.Button(btns, text="Cancel", bootstyle="secondary", command=self._cancel).pack(side="right", padx=4)
        tb.Button(btns, text="OK", bootstyle="primary", command=self._ok).pack(side="right", padx=4)

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())
        self.transient(parent)
        self.grab_set()
        if first_entry is not None:
            first_entry.focus_set()
            first_entry.selection_range(0, "end")
        self.wait_window(self)

    def _ok(self):
        self.result = {k: v.get() for k, v in self._vars.items()}
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def parse_float(value, field_name):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"'{field_name}' must be a number (got {value!r}).")


# ============================= Trace manager panel =============================

class TracePanel(tb.Frame):
    """
    Lists loaded traces (spectra/patterns) with a visibility toggle and lets the
    user pick which one is 'active' (the one detection/fitting/etc. operate on).
    """
    def __init__(self, parent, height=5):
        super().__init__(parent)
        self.on_active_change = None
        self.on_visibility_toggle = None
        self.on_remove = None
        self.on_clear = None

        cols = ("show", "label", "points")
        self.tree = tb.Treeview(self, columns=cols, show="headings", height=height, selectmode="browse")
        self.tree.heading("show", text="")
        self.tree.column("show", width=26, anchor="center", stretch=False)
        self.tree.heading("label", text="Loaded Traces (click to activate, click ● to hide)")
        self.tree.column("label", width=230, anchor="w")
        self.tree.heading("points", text="Pts")
        self.tree.column("points", width=55, anchor="center", stretch=False)
        self.tree.pack(fill="x", expand=False, side="top")
        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        btn_row = tb.Frame(self)
        btn_row.pack(fill="x", pady=(4, 0))
        tb.Button(btn_row, text="Remove", bootstyle="danger-outline", command=self._remove_clicked, width=10).pack(side="left", padx=(0, 4))
        tb.Button(btn_row, text="Clear All", bootstyle="secondary-outline", command=self._clear_clicked, width=10).pack(side="left")

    def refresh(self, traces, active_id):
        self.tree.delete(*self.tree.get_children())
        for t in traces:
            mark = "●" if t.visible else "○"
            iid = str(t.id)
            self.tree.insert("", "end", iid=iid, values=(mark, t.label, len(t.x)))
            tag = f"color{t.id}"
            self.tree.tag_configure(tag, foreground=t.color)
            self.tree.item(iid, tags=(tag,))
        if active_id is not None and str(active_id) in self.tree.get_children():
            self.tree.selection_set(str(active_id))

    def _on_click(self, event):
        row = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not row:
            return
        if col == "#1" and self.on_visibility_toggle:
            self.on_visibility_toggle(int(row))

    def _on_select(self, _event):
        sel = self.tree.selection()
        if sel and self.on_active_change:
            self.on_active_change(int(sel[0]))

    def _remove_clicked(self):
        sel = self.tree.selection()
        if sel and self.on_remove:
            self.on_remove(int(sel[0]))

    def _clear_clicked(self):
        if self.on_clear and Messagebox.yesno("Remove all loaded traces from this tab?", "Clear All") == "Yes":
            self.on_clear()


# ============================= Generic data table =============================

class DataTable(tb.Frame):
    """A Treeview + scrollbar wrapper for showing lists of dict rows with a formatter."""
    def __init__(self, parent, columns, height=10, widths=None):
        super().__init__(parent)
        self.columns = columns
        keys = [c[0] for c in columns]
        self.tree = tb.Treeview(self, columns=keys, show="headings", height=height)
        for key, heading in columns:
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=(widths or {}).get(key, 110), anchor="center")
        vsb = tb.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._rows_data = []
        self.on_select = None
        self.tree.bind("<<TreeviewSelect>>", self._emit_select)

    def set_rows(self, rows, formatter):
        self.tree.delete(*self.tree.get_children())
        self._rows_data = list(rows)
        for i, r in enumerate(self._rows_data):
            self.tree.insert("", "end", iid=str(i), values=formatter(r))

    def clear(self):
        self.tree.delete(*self.tree.get_children())
        self._rows_data = []

    def _emit_select(self, _event):
        sel = self.tree.selection()
        if sel and self.on_select:
            idx = int(sel[0])
            if 0 <= idx < len(self._rows_data):
                self.on_select(self._rows_data[idx])


def save_figure_snapshot(fig, path):
    fig.savefig(path, dpi=150, bbox_inches="tight")
    return path


# ========================= Periodic Table Element Picker =========================

# (symbol, row, col) for the standard 18-column periodic table layout, with
# lanthanides/actinides pulled out to their own two rows below the main body
# (rows 8/9, columns 3-17) -- exactly like the wall-chart layout, and like the
# "chemical filter" element picker in commercial XRD search/match software.
_PERIODIC_TABLE_LAYOUT = [
    ("H", 1, 1), ("He", 1, 18),
    ("Li", 2, 1), ("Be", 2, 2), ("B", 2, 13), ("C", 2, 14), ("N", 2, 15), ("O", 2, 16), ("F", 2, 17), ("Ne", 2, 18),
    ("Na", 3, 1), ("Mg", 3, 2), ("Al", 3, 13), ("Si", 3, 14), ("P", 3, 15), ("S", 3, 16), ("Cl", 3, 17), ("Ar", 3, 18),
    ("K", 4, 1), ("Ca", 4, 2), ("Sc", 4, 3), ("Ti", 4, 4), ("V", 4, 5), ("Cr", 4, 6), ("Mn", 4, 7), ("Fe", 4, 8),
    ("Co", 4, 9), ("Ni", 4, 10), ("Cu", 4, 11), ("Zn", 4, 12), ("Ga", 4, 13), ("Ge", 4, 14), ("As", 4, 15),
    ("Se", 4, 16), ("Br", 4, 17), ("Kr", 4, 18),
    ("Rb", 5, 1), ("Sr", 5, 2), ("Y", 5, 3), ("Zr", 5, 4), ("Nb", 5, 5), ("Mo", 5, 6), ("Tc", 5, 7), ("Ru", 5, 8),
    ("Rh", 5, 9), ("Pd", 5, 10), ("Ag", 5, 11), ("Cd", 5, 12), ("In", 5, 13), ("Sn", 5, 14), ("Sb", 5, 15),
    ("Te", 5, 16), ("I", 5, 17), ("Xe", 5, 18),
    ("Cs", 6, 1), ("Ba", 6, 2), ("Hf", 6, 4), ("Ta", 6, 5), ("W", 6, 6), ("Re", 6, 7), ("Os", 6, 8), ("Ir", 6, 9),
    ("Pt", 6, 10), ("Au", 6, 11), ("Hg", 6, 12), ("Tl", 6, 13), ("Pb", 6, 14), ("Bi", 6, 15), ("Po", 6, 16),
    ("At", 6, 17), ("Rn", 6, 18),
    ("Fr", 7, 1), ("Ra", 7, 2), ("Rf", 7, 4), ("Db", 7, 5), ("Sg", 7, 6), ("Bh", 7, 7), ("Hs", 7, 8), ("Mt", 7, 9),
    ("Ds", 7, 10), ("Rg", 7, 11), ("Cn", 7, 12), ("Nh", 7, 13), ("Fl", 7, 14), ("Mc", 7, 15), ("Lv", 7, 16),
    ("Ts", 7, 17), ("Og", 7, 18),
    ("La", 9, 3), ("Ce", 9, 4), ("Pr", 9, 5), ("Nd", 9, 6), ("Pm", 9, 7), ("Sm", 9, 8), ("Eu", 9, 9), ("Gd", 9, 10),
    ("Tb", 9, 11), ("Dy", 9, 12), ("Ho", 9, 13), ("Er", 9, 14), ("Tm", 9, 15), ("Yb", 9, 16), ("Lu", 9, 17),
    ("Ac", 10, 3), ("Th", 10, 4), ("Pa", 10, 5), ("U", 10, 6), ("Np", 10, 7), ("Pu", 10, 8), ("Am", 10, 9),
    ("Cm", 10, 10), ("Bk", 10, 11), ("Cf", 10, 12), ("Es", 10, 13), ("Fm", 10, 14), ("Md", 10, 15), ("No", 10, 16),
    ("Lr", 10, 17),
]


class PeriodicTableDialog(tb.Toplevel):
    """
    A clickable periodic table for picking which elements your sample
    contains, then filtering the reference database down to phases that
    contain all of them -- much faster than scrolling/typing names when you
    don't know the exact compound name or formula, only its composition.

    Construct, let the user toggle elements and click Apply/Clear, then read
    `.result`: a list of element symbols if Apply was clicked, an empty list
    if Clear was clicked, or None if the dialog was closed/cancelled without
    changing anything.
    """
    def __init__(self, parent, initial_selection=None):
        super().__init__(parent)
        self.title("Select Elements")
        self.resizable(False, False)
        self.result = None
        self.selected = set(initial_selection or [])
        self._buttons = {}

        tb.Label(self, text="Click elements present in your sample, then Apply Filter.\n"
                             "Only phases containing ALL selected elements will be shown.",
                 bootstyle="secondary", padding=(10, 10, 10, 0)).pack(anchor="w")

        grid = tb.Frame(self, padding=10)
        grid.pack()
        for symbol, row, col in _PERIODIC_TABLE_LAYOUT:
            btn = tb.Button(grid, text=symbol, width=4,
                             bootstyle="success" if symbol in self.selected else "secondary-outline",
                             command=lambda s=symbol: self._toggle(s))
            btn.grid(row=row, column=col, padx=1, pady=1)
            self._buttons[symbol] = btn

        btn_row = tb.Frame(self, padding=10)
        btn_row.pack(fill="x")
        self.selection_label = tb.Label(btn_row, text=self._selection_text(), bootstyle="info")
        self.selection_label.pack(side="left")
        tb.Button(btn_row, text="Clear", bootstyle="danger-outline",
                  command=self._clear).pack(side="right", padx=4)
        tb.Button(btn_row, text="Apply Filter", bootstyle="success",
                  command=self._apply).pack(side="right", padx=4)

    def _selection_text(self):
        return f"Selected: {', '.join(sorted(self.selected)) or '(none)'}"

    def _toggle(self, symbol):
        if symbol in self.selected:
            self.selected.remove(symbol)
            self._buttons[symbol].configure(bootstyle="secondary-outline")
        else:
            self.selected.add(symbol)
            self._buttons[symbol].configure(bootstyle="success")
        self.selection_label.configure(text=self._selection_text())

    def _clear(self):
        self.result = []
        self.destroy()

    def _apply(self):
        self.result = sorted(self.selected)
        self.destroy()


# ==================== HighScore Reference Database (.hsrdb) Import ====================

class HsrdbImportDialog(tb.Toplevel):
    """
    Search a reference database -- either this app's own bundled COD
    (Crystallography Open Database) database (~511,000 phases, opened
    automatically if present) or an external PANalytical/Malvern HighScore
    .hsrdb file you point it at -- and import selected phases into your
    local user-phase library.

    Both backends (modules/cod_database.py and modules/hsrdb_reader.py)
    expose the same function names/summary-dict shape, so this dialog
    doesn't need to know or care which one it's talking to. An external file
    is opened read-only wherever you keep it and is never bundled, embedded,
    or committed by this app -- only the specific entries you explicitly
    import get added to your local user-phases store (see
    xrd_analysis.add_user_phases), each one carrying its own Crystallography
    Open Database (COD) citation. See modules/hsrdb_reader.py and
    modules/cod_database.py for exactly what was verified about the file
    formats and where the data comes from.
    """
    def __init__(self, parent, app, xrd_module, on_imported=None):
        super().__init__(parent)
        self.app = app
        self.xrd_module = xrd_module
        self.on_imported = on_imported
        self.con = None
        self.backend = None
        self.element_filter = []
        self._results = []

        self.title("Search Reference Database (bundled COD / HighScore .hsrdb)")
        self.geometry("920x600")
        self._build_ui()

        bundled_path = getattr(self.app, "cod_db_path", None)
        last_path = self.app.cfg.get("hsrdb_path", "")
        if bundled_path and os.path.exists(bundled_path):
            self._open_file(bundled_path)
        elif last_path and os.path.exists(last_path):
            self._open_file(last_path)

    def _build_ui(self):
        top = tb.Frame(self, padding=10)
        top.pack(fill="x")
        self.path_label = tb.Label(top, text="No file open.", bootstyle="secondary")
        self.path_label.pack(side="left", fill="x", expand=True)
        tb.Button(top, text="Open .hsrdb File...", bootstyle="info", command=self._choose_file).pack(side="right")

        search_row = tb.Frame(self, padding=(10, 0))
        search_row.pack(fill="x")
        tb.Label(search_row, text="Search name/formula:").pack(side="left")
        self.query_var = tb.StringVar()
        ent = tb.Entry(search_row, textvariable=self.query_var, width=26)
        ent.pack(side="left", padx=6)
        ent.bind("<Return>", lambda e: self._search())
        tb.Button(search_row, text="Select Elements...", command=self._open_element_picker).pack(side="left", padx=6)
        self.element_label = tb.Label(search_row, text="", bootstyle="info")
        self.element_label.pack(side="left", padx=(0, 6))
        tb.Button(search_row, text="Search", bootstyle="primary", command=self._search).pack(side="left")

        body = tb.Frame(self, padding=10)
        body.pack(fill="both", expand=True)
        self.results_table = DataTable(
            body, [("name", "Name"), ("code", "Reference Code"), ("system", "System"), ("formula", "Formula")],
            height=16, widths={"name": 240, "code": 130, "system": 90, "formula": 300})
        self.results_table.pack(fill="both", expand=True)
        select_row = tb.Frame(body)
        select_row.pack(fill="x", pady=(4, 0))
        tb.Label(select_row, text="Ctrl/Shift-click to select multiple rows (many materials have several "
                                   "phases/polymorphs -- select all the ones you want, then import together).",
                 bootstyle="secondary", font=("", 8)).pack(side="left")
        tb.Button(select_row, text="Select All Results", bootstyle="secondary-outline",
                  command=self._select_all_results).pack(side="right")

        bottom = tb.Frame(self, padding=10)
        bottom.pack(fill="x")
        self.status_label = tb.Label(bottom, text="Open a .hsrdb file to begin.", bootstyle="secondary")
        self.status_label.pack(side="left")
        tb.Button(bottom, text="Import Selected to My Phases", bootstyle="success",
                  command=self._import_selected).pack(side="right")

    def _choose_file(self):
        path = filedialog.askopenfilename(filetypes=[("HighScore Reference Database", "*.hsrdb"), ("All files", "*.*")])
        if not path:
            return
        self._open_file(path)

    def _open_file(self, path):
        import hsrdb_reader
        import cod_database
        con = None
        backend = None
        errors = []
        for candidate in (hsrdb_reader, cod_database):
            try:
                con = candidate.open_hsrdb(path)
                backend = candidate
                break
            except ValueError as e:
                errors.append(str(e))
        if con is None:
            Messagebox.show_error("\n\n".join(errors), "Open Failed")
            return
        n = backend.count_entries(con)
        self.con = con
        self.backend = backend
        is_bundled = getattr(self.app, "cod_db_path", None) and os.path.abspath(path) == os.path.abspath(self.app.cod_db_path)
        label = "Bundled COD database" if is_bundled else path
        self.path_label.configure(text=f"{label}   ({n:,} entries)")
        if not is_bundled:
            self.app.cfg["hsrdb_path"] = path
            from app_config import save_config
            save_config(self.app.cfg)
        self.status_label.configure(text=f"Opened -- {n:,} entries available. Search by name/formula or elements.")

    def _open_element_picker(self):
        dlg = PeriodicTableDialog(self, initial_selection=self.element_filter)
        self.wait_window(dlg)
        if dlg.result is not None:
            self.element_filter = dlg.result
            self.element_label.configure(text=f"Elements: {', '.join(self.element_filter) or '(none)'}")

    def _search(self):
        if self.con is None:
            Messagebox.show_warning("Open a .hsrdb file first.", "No File Open")
            return
        query = self.query_var.get()
        if not query and not self.element_filter:
            Messagebox.show_warning("Enter a search term or select elements first -- searching with no "
                                     "filter at all would try to list all 500,000+ entries.", "Search Too Broad")
            return
        self.status_label.configure(text="Searching...")
        self.update_idletasks()
        try:
            results = self.backend.search_hsrdb(self.con, query=query, elements=self.element_filter, limit=300)
        except Exception as e:
            Messagebox.show_error(str(e), "Search Failed")
            return
        self._results = results
        self.results_table.set_rows(results, lambda r: (
            r["compound_name"] or r["mineral_name"] or r["common_name"] or "(unnamed)",
            r.get("reference_code", ""), r.get("crystal_system", ""), r["formula"]))
        cap_note = " (capped at 300 -- narrow your search for a complete list)" if len(results) == 300 else ""
        self.status_label.configure(text=f"{len(results)} result(s){cap_note}.")

    def _select_all_results(self):
        children = self.results_table.tree.get_children()
        if not children:
            Messagebox.show_warning("Search for something first.", "No Results")
            return
        self.results_table.tree.selection_set(children)

    def _import_selected(self):
        sel = self.results_table.tree.selection()
        if not sel or self.con is None:
            Messagebox.show_warning("Search and select at least one row first.", "Nothing Selected")
            return
        imported = []
        errors = []
        for iid in sel:
            idx = int(iid)
            r = self.results_table._rows_data[idx]
            try:
                phase = self.backend.get_phase_detail(self.con, r["id"], top_n=20)
                imported.append(phase)
            except Exception as e:
                errors.append(f"{r.get('reference_code', '?')}: {e}")
        if imported:
            self.xrd_module.add_user_phases(imported)
            if self.on_imported:
                self.on_imported()
        msg = f"Imported {len(imported)} phase(s) to My Phases (local, persisted, cited to COD)."
        if errors:
            msg += "\n\nFailed:\n" + "\n".join(errors)
        Messagebox.show_info(msg, "Import Complete" if not errors else "Import Partially Complete")


# ============================= Database Viewer =============================

class DatabaseViewerDialog(tb.Toplevel):
    """
    Browse the built-in FTIR reference database and XRD phase database, see
    every peak/line and its literature source, and (for XRD) import extra
    phases from a CSV the user transcribed from their own reference source.
    """
    def __init__(self, parent, ftir_db, ftir_module, xrd_db_provider, xrd_module, on_phases_imported=None):
        super().__init__(parent)
        self.title("Reference Database Viewer")
        self.geometry("880x600")
        self.ftir_db = ftir_db
        self.ftir_module = ftir_module
        self.xrd_db_provider = xrd_db_provider  # callable() -> merged xrd db (built-in + user)
        self.xrd_module = xrd_module
        self.on_phases_imported = on_phases_imported

        nb = tb.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        self.ftir_frame = tb.Frame(nb, padding=8)
        self.xrd_frame = tb.Frame(nb, padding=8)
        nb.add(self.ftir_frame, text="FTIR Reference Database")
        nb.add(self.xrd_frame, text="XRD Phase Database")

        self._build_ftir_tab()
        self._build_xrd_tab()

    def _build_ftir_tab(self):
        top = tb.Frame(self.ftir_frame)
        top.pack(fill="x")
        tb.Label(top, text="Search:").pack(side="left")
        self.ftir_query = tb.StringVar()
        ent = tb.Entry(top, textvariable=self.ftir_query, width=30)
        ent.pack(side="left", padx=6)
        ent.bind("<KeyRelease>", lambda e: self._refresh_ftir())

        self.ftir_cat = tb.StringVar(value="all")
        cats = ["all"] + self.ftir_module.MATERIAL_CATEGORIES
        combo = tb.Combobox(top, textvariable=self.ftir_cat, values=cats, state="readonly", width=20)
        combo.pack(side="left", padx=6)
        combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_ftir())

        body = tb.Frame(self.ftir_frame)
        body.pack(fill="both", expand=True, pady=(8, 0))

        self.ftir_list = DataTable(body, [("name", "Material"), ("category", "Category"), ("npeaks", "# Peaks"), ("source", "Source")],
                                    height=16, widths={"name": 260, "category": 90, "npeaks": 60, "source": 220})
        self.ftir_list.pack(side="left", fill="both", expand=True)
        self.ftir_list.on_select = self._show_ftir_detail

        detail_frame = tb.Frame(body)
        detail_frame.pack(side="left", fill="both", expand=True, padx=(8, 0))
        tb.Label(detail_frame, text="Reference Peaks", bootstyle="secondary").pack(anchor="w")
        self.ftir_detail = DataTable(detail_frame, [("range", "Range (cm-1)"), ("assignment", "Assignment"), ("intensity", "Intensity")],
                                      height=16, widths={"range": 90, "assignment": 260, "intensity": 90})
        self.ftir_detail.pack(fill="both", expand=True)

        self._refresh_ftir()

    def _refresh_ftir(self):
        cat = None if self.ftir_cat.get() == "all" else self.ftir_cat.get()
        entries = self.ftir_module.search_database(self.ftir_db, self.ftir_query.get(), category=cat)
        self.ftir_list.set_rows(entries, lambda e: (e["name"], e["category"], len(e["peaks"]), e.get("source", "")))
        self.ftir_detail.clear()

    def _show_ftir_detail(self, entry):
        self.ftir_detail.set_rows(entry["peaks"], lambda p: (f"{p['range'][0]}-{p['range'][1]}", p["assignment"], p.get("intensity", "")))

    def _build_xrd_tab(self):
        self.xrd_element_filter = []

        top = tb.Frame(self.xrd_frame)
        top.pack(fill="x")
        tb.Label(top, text="Search:").pack(side="left")
        self.xrd_query = tb.StringVar()
        ent = tb.Entry(top, textvariable=self.xrd_query, width=30)
        ent.pack(side="left", padx=6)
        ent.bind("<KeyRelease>", lambda e: self._refresh_xrd())

        tb.Button(top, text="Select Elements (Periodic Table)...", bootstyle="primary",
                  command=self._open_element_picker).pack(side="left", padx=6)

        tb.Button(top, text="Import Phases from CSV...", bootstyle="info", command=self._import_csv).pack(side="right", padx=4)
        tb.Button(top, text="Remove Selected User Phase", bootstyle="danger-outline", command=self._remove_user_phase).pack(side="right", padx=4)

        filter_row = tb.Frame(self.xrd_frame)
        filter_row.pack(fill="x")
        self.xrd_element_filter_label = tb.Label(filter_row, text="", bootstyle="info")
        self.xrd_element_filter_label.pack(side="left")

        body = tb.Frame(self.xrd_frame)
        body.pack(fill="both", expand=True, pady=(8, 0))

        self.xrd_list = DataTable(body, [("name", "Phase"), ("category", "Category"), ("system", "Crystal System"), ("nlines", "# Lines"), ("source", "Source")],
                                   height=16, widths={"name": 220, "category": 90, "system": 100, "nlines": 55, "source": 180})
        self.xrd_list.pack(side="left", fill="both", expand=True)
        self.xrd_list.on_select = self._show_xrd_detail

        detail_frame = tb.Frame(body)
        detail_frame.pack(side="left", fill="both", expand=True, padx=(8, 0))
        tb.Label(detail_frame, text="Reference Lines", bootstyle="secondary").pack(anchor="w")
        self.xrd_detail = DataTable(detail_frame, [("d", "d (A)"), ("hkl", "hkl"), ("intensity", "Rel. Intensity")],
                                     height=16, widths={"d": 90, "hkl": 90, "intensity": 100})
        self.xrd_detail.pack(fill="both", expand=True)

        self._refresh_xrd()

    def _open_element_picker(self):
        dlg = PeriodicTableDialog(self, initial_selection=self.xrd_element_filter)
        self.wait_window(dlg)
        if dlg.result is not None:
            self.xrd_element_filter = dlg.result
            self._refresh_xrd()

    def _refresh_xrd(self):
        db = self.xrd_db_provider()
        entries = self.xrd_module.search_xrd_database(db, self.xrd_query.get(), elements=self.xrd_element_filter)
        self.xrd_list.set_rows(entries, lambda p: (p["name"], p.get("category", ""), p.get("crystal_system", ""), len(p["peaks"]), p.get("source", "")))
        self.xrd_detail.clear()
        if self.xrd_element_filter:
            self.xrd_element_filter_label.configure(
                text=f"Element filter: {', '.join(self.xrd_element_filter)} ({len(entries)} matching phase(s))")
        else:
            self.xrd_element_filter_label.configure(text="")

    def _show_xrd_detail(self, phase):
        rows = sorted(phase["peaks"], key=lambda r: -r.get("rel_intensity", 0))
        self.xrd_detail.set_rows(rows, lambda p: (f"{p['d_A']:.4f}", p.get("hkl", ""), p.get("rel_intensity", "")))

    def _import_csv(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="Import Reference Phases from CSV",
                                           filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            new_phases = self.xrd_module.import_phases_from_csv(path)
            self.xrd_module.add_user_phases(new_phases)
        except Exception as e:
            Messagebox.show_error(str(e), "Import Failed")
            return
        Messagebox.show_info(f"Imported {len(new_phases)} phase(s) from {os.path.basename(path)}.", "Import Complete")
        self._refresh_xrd()
        if self.on_phases_imported:
            self.on_phases_imported()

    def _remove_user_phase(self):
        sel = self.xrd_list.tree.selection()
        if not sel:
            Messagebox.show_warning("Select a phase in the list first.", "No Selection")
            return
        idx = int(sel[0])
        entry = self.xrd_list._rows_data[idx]
        user_names = {p["name"] for p in self.xrd_module.load_user_phases()}
        if entry["name"] not in user_names:
            Messagebox.show_warning("Only user-imported phases can be removed here (built-in phases are read-only).", "Not Removable")
            return
        self.xrd_module.remove_user_phase(entry["name"])
        self._refresh_xrd()
        if self.on_phases_imported:
            self.on_phases_imported()


# ============================= References dialog =============================

class ReferencesDialog(tb.Toplevel):
    """Shows the full bibliography behind the FTIR + XRD reference databases."""
    def __init__(self, parent, ftir_db, xrd_db):
        super().__init__(parent)
        self.title("Data Sources & References")
        self.geometry("640x520")

        frm = tb.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)

        tb.Label(frm, text="Data Sources & References", font=("", 14, "bold"), bootstyle="primary").pack(anchor="w")
        tb.Label(frm, text="Every material/phase entry in the built-in databases carries a 'source' tag "
                            "referencing one or more of the works below. This toolkit compiles well-known, "
                            "published correlation tables and crystallographic constants -- it is a screening "
                            "aid, not a certified reference measurement. Always confirm anything consequential "
                            "against the certified source directly.",
                 wraplength=580, justify="left", bootstyle="secondary").pack(anchor="w", pady=(4, 12))

        text = ScrolledText(frm, height=20, autohide=True)
        text.pack(fill="both", expand=True)

        seen = {}
        for db in (ftir_db, xrd_db):
            for ref in db.get("_meta", {}).get("references", []):
                seen[ref["id"]] = ref["citation"]

        lines = []
        lines.append("FTIR reference database note:")
        lines.append("  " + ftir_db.get("_meta", {}).get("note", ""))
        lines.append("")
        lines.append("XRD reference database note:")
        lines.append("  " + xrd_db.get("_meta", {}).get("note", ""))
        lines.append("")
        lines.append("Bibliography:")
        for i, (rid, citation) in enumerate(sorted(seen.items()), 1):
            lines.append(f"  [{rid}] {citation}")

        text.text.insert("end", "\n".join(lines))
        text.text.configure(state="disabled")

        tb.Button(frm, text="Close", bootstyle="primary", command=self.destroy).pack(anchor="e", pady=(12, 0))


class AboutDialog(tb.Toplevel):
    def __init__(self, parent, icon_path=None):
        super().__init__(parent)
        self.title("About")
        self.resizable(False, False)
        frm = tb.Frame(self, padding=24)
        frm.pack()

        if icon_path and os.path.exists(icon_path):
            try:
                img = tb.PhotoImage(file=icon_path)
                img = img.subsample(max(1, img.width() // 96))
                lbl = tb.Label(frm, image=img)
                lbl.image = img
                lbl.pack(pady=(0, 10))
            except Exception:
                pass

        tb.Label(frm, text="FTIR & XRD Analysis Toolkit", font=("", 15, "bold"), bootstyle="primary").pack()
        tb.Label(frm, text="Professional Edition", bootstyle="secondary").pack(pady=(0, 10))
        tb.Label(frm, text=(
            "A desktop toolkit for FTIR spectral identification and XRD pattern\n"
            "analysis: peak detection, database phase/material matching, peak\n"
            "fitting, Williamson-Hall analysis, PDF reporting, and session save/load.\n\n"
            "All reference data is drawn from published literature (see\n"
            "Help > Data Sources & References) and is a screening aid, not a\n"
            "certified identification."
        ), justify="center").pack(pady=(0, 14))
        tb.Button(frm, text="Close", bootstyle="primary", command=self.destroy).pack()


# ============================= Shared analysis-tab scaffolding =============================

class AnalysisTabBase(tb.Frame):
    """
    Common scaffolding shared by the FTIR and XRD tabs: multi-trace management,
    a matplotlib plot with toolbar/hover-tooltips/coordinate-readout, drag &
    drop file loading, and a results Notebook. Subclasses provide the controls
    panel and the per-point plotting/formatting logic.
    """
    def __init__(self, parent, app, x_label, y_label, invert_x=False):
        super().__init__(parent)
        self.app = app
        self.x_label = x_label
        self.y_label = y_label
        self.invert_x = invert_x

        self.traces = []
        self.active_id = None
        self.color_cycle = ColorCycle()
        self.reference_overlay = None  # set by subclasses: {"label": str, ...} -- see set_reference_overlay

        outer = tb.Frame(self)
        outer.pack(fill="both", expand=True)

        left_container = tb.Frame(outer, width=340)
        left_container.pack(side="left", fill="y")
        left_container.pack_propagate(False)
        self.controls_scroll = ScrolledFrame(left_container, autohide=True)
        self.controls_scroll.pack(fill="both", expand=True)
        self.controls = self.controls_scroll

        right = tb.Frame(outer)
        right.pack(side="right", fill="both", expand=True)

        trace_card = tb.Labelframe(self.controls, text="Loaded Traces", padding=8, bootstyle="primary")
        trace_card.pack(fill="x", padx=6, pady=(6, 6))
        self.trace_panel = TracePanel(trace_card)
        self.trace_panel.pack(fill="x")
        self.trace_panel.on_active_change = self._on_trace_active_change
        self.trace_panel.on_visibility_toggle = self._on_trace_visibility_toggle
        self.trace_panel.on_remove = self._on_trace_remove
        self.trace_panel.on_clear = self._on_trace_clear

        plot_frame = tb.Frame(right)
        plot_frame.pack(fill="both", expand=True)
        self.fig = Figure(figsize=(7, 4.6), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self._reset_axes()
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        toolbar = NavigationToolbar2Tk(self.canvas, plot_frame)
        toolbar.update()
        self.canvas.mpl_connect("motion_notify_event", self._on_plot_motion)

        self.results_notebook = tb.Notebook(right)
        self.results_notebook.pack(fill="both", expand=False, pady=(6, 0))

        self._register_dnd(self.canvas.get_tk_widget())

    # ---- axes / plotting ----

    def _reset_axes(self):
        self.ax.clear()
        self.ax.set_xlabel(self.x_label)
        self.ax.set_ylabel(self.y_label)
        self.ax.grid(True, alpha=0.25)
        if self.invert_x:
            self.ax.invert_xaxis()

    def redraw(self):
        self._reset_axes()
        artists_for_cursor = []
        for t in self.traces:
            if not t.visible:
                continue
            is_active = (t.id == self.active_id)
            line, = self.ax.plot(t.x, t.y, lw=1.8 if is_active else 1.0,
                                  color=t.color, alpha=1.0 if is_active else 0.55,
                                  label=t.label)
            artists_for_cursor.append(line)
            if is_active:
                self._plot_active_extras(t)
        if self.reference_overlay:
            self._draw_reference_overlay()
        if len(self.traces) > 1 or self.reference_overlay:
            visible = [t for t in self.traces if t.visible]
            if visible or self.reference_overlay:
                self.ax.legend(fontsize=7, loc="best", framealpha=0.85)
        if self.invert_x and self.ax.get_xlim()[0] < self.ax.get_xlim()[1]:
            self.ax.invert_xaxis()

        mplcursors = _get_mplcursors()
        if mplcursors and artists_for_cursor:
            try:
                if hasattr(self, "_cursor") and self._cursor is not None:
                    self._cursor.remove()
            except Exception:
                pass
            try:
                self._cursor = mplcursors.cursor(artists_for_cursor, hover=True)
                self._cursor.connect("add", self._format_cursor_annotation)
            except Exception:
                self._cursor = None

        self.canvas.draw()

    def _format_cursor_annotation(self, sel):
        x, y = sel.target
        sel.annotation.set_text(f"{x:.2f}, {y:.4f}")

    def _plot_active_extras(self, trace):
        """Hook: subclasses draw peak markers etc. for the active trace."""
        pass

    def _draw_reference_overlay(self):
        """Hook: subclasses draw the selected database match's reference peaks/lines."""
        pass

    def set_reference_overlay(self, overlay):
        """
        overlay: a subclass-defined dict describing which material/phase's
        reference peaks to draw (e.g. {"label": name, "peaks": [...]}), or
        None to clear it. Set when the user selects a row in the Database
        Matches / Phase Matches table, so its reference bands are drawn on
        top of the active spectrum/pattern for direct visual comparison.
        """
        self.reference_overlay = overlay
        self.redraw()

    def clear_reference_overlay(self):
        if self.reference_overlay is not None:
            self.reference_overlay = None
            self.redraw()

    def _on_plot_motion(self, event):
        if event.inaxes != self.ax or event.xdata is None:
            self.app.set_status_coords("")
            return
        self.app.set_status_coords(f"x={event.xdata:,.2f}   y={event.ydata:,.4f}")

    # ---- trace management ----

    def add_trace(self, label, x, y, metadata=None):
        t = Trace(label, x, y, self.color_cycle.next(), metadata=metadata)
        self.traces.append(t)
        self.active_id = t.id
        self._on_traces_changed()
        return t

    def get_active(self):
        for t in self.traces:
            if t.id == self.active_id:
                return t
        return None

    # ---- OriginLab-compatible export ----

    def export_originlab_dialog(self):
        """
        Save every open trace as X/Y column pairs with 'Long Name' and 'Units'
        header rows -- the classic 'Origin ASCII' layout that OriginLab's
        Import Wizard (and plain drag-and-drop) recognizes automatically,
        turning each column pair straight into an XY worksheet/graph.
        """
        if not self.traces:
            Messagebox.show_warning("Load a spectrum/pattern first.", "No Data")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                             filetypes=[("CSV (Origin ASCII)", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.export_originlab_csv(path)
        except Exception as e:
            Messagebox.show_error(str(e), "Export Failed")
            return
        Messagebox.show_info(f"Saved {len(self.traces)} trace(s) to {path}.\n\n"
                              "In OriginLab: File > Import > Import Wizard (or just drag the "
                              "file onto an empty worksheet) -- row 1 becomes column Long Names, "
                              "row 2 becomes Units.", "Exported for OriginLab")

    def export_originlab_csv(self, path):
        import csv
        import re

        def plain(label):
            # strip matplotlib mathtext markup (e.g. "cm$^{-1}$" -> "cm-1")
            # so the units row is plain text Origin's import wizard can read.
            return re.sub(r"[${}^\\]", "", label)

        max_len = max(len(t.x) for t in self.traces)
        header1, header2 = [], []
        for t in self.traces:
            header1 += [f"{t.label} X", f"{t.label} Y"]
            header2 += [plain(self.x_label), plain(self.y_label)]
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(header1)
            w.writerow(header2)
            for i in range(max_len):
                row = []
                for t in self.traces:
                    if i < len(t.x):
                        row += [t.x[i], t.y[i]]
                    else:
                        row += ["", ""]
                w.writerow(row)

    def export_graph_dialog(self):
        """
        Export the current plot as an image. SVG/EPS/PDF are vector formats
        OriginLab can import as an editable graph page; PNG is a flat raster
        snapshot (matches the one embedded in the PDF report).
        """
        path = filedialog.asksaveasfilename(
            defaultextension=".svg",
            filetypes=[("SVG (vector)", "*.svg"), ("EPS (vector)", "*.eps"), ("PDF (vector)", "*.pdf"),
                       ("PNG (raster, 300 dpi)", "*.png"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.fig.savefig(path, dpi=300, bbox_inches="tight")
        except Exception as e:
            Messagebox.show_error(str(e), "Export Failed")
            return
        Messagebox.show_info(f"Saved plot to {path}.", "Exported")

    def _on_traces_changed(self):
        self.trace_panel.refresh(self.traces, self.active_id)
        self.redraw()
        self.on_active_trace_changed()

    def on_active_trace_changed(self):
        """Hook: subclasses refresh their results tables for the new active trace."""
        pass

    def _on_trace_active_change(self, trace_id):
        self.active_id = trace_id
        self.redraw()
        self.on_active_trace_changed()

    def _on_trace_visibility_toggle(self, trace_id):
        for t in self.traces:
            if t.id == trace_id:
                t.visible = not t.visible
        self._on_traces_changed()

    def _on_trace_remove(self, trace_id):
        self.traces = [t for t in self.traces if t.id != trace_id]
        if self.active_id == trace_id:
            self.active_id = self.traces[-1].id if self.traces else None
        self._on_traces_changed()

    def _on_trace_clear(self):
        self.traces = []
        self.active_id = None
        self._on_traces_changed()

    # ---- file loading / drag & drop ----

    def load_file_dialog(self, filetypes, reader):
        path = filedialog.askopenfilename(filetypes=filetypes)
        if not path:
            return
        self.load_file_path(path, reader)

    def load_file_path(self, path, reader):
        try:
            result = reader(path)
        except Exception as e:
            Messagebox.show_error(str(e), "Load Error")
            return
        meta = dict(result.metadata) if getattr(result, "metadata", None) else {}
        meta["confidence"] = getattr(result, "confidence", "high")
        meta["path"] = path
        self.add_trace(os.path.basename(path), result.x, result.y, metadata=meta)
        self.app.note_recent_file(path)
        conf_note = "" if meta["confidence"] == "high" else "  [LOW CONFIDENCE PARSE - verify against ASCII export]"
        self.app.set_status_message(f"Loaded {os.path.basename(path)}: {len(result.x)} points.{conf_note}")

    def _register_dnd(self, widget):
        if not DND_AVAILABLE_LIB or not getattr(self.app, "dnd_ready", False):
            return
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            pass

    def _on_drop(self, event):
        paths = self.app.parse_dnd_paths(event.data)
        for path in paths:
            self.handle_dropped_file(path)

    def handle_dropped_file(self, path):
        """Hook: subclasses call load_file_path with their own reader."""
        pass

    # ---- formula/source traceability ----

    def make_action_row(self, parent, text, command, bootstyle="secondary", info_title=None, info_text=None, pady=2):
        """A button, optionally paired with a small (i) button that shows the
        formula/citation behind it -- one-click traceability for every result."""
        row = tb.Frame(parent)
        row.pack(fill="x", pady=pady)
        tb.Button(row, text=text, command=command, bootstyle=bootstyle).pack(side="left", fill="x", expand=True)
        if info_text:
            tb.Button(row, text="ⓘ", width=3, bootstyle="secondary-outline",
                      command=lambda: self.show_formula(info_title or text, info_text)).pack(side="left", padx=(4, 0))
        return row

    def show_formula(self, title, text):
        from formula_sources import show_formula_dialog
        show_formula_dialog(self.app.root, title, text)

    # ---- background work (keeps the window responsive during slow matching/fitting) ----

    def run_background(self, compute_fn, on_success, busy_text="Working..."):
        """
        Runs compute_fn() (a plain callable touching no Tk widgets) on a
        background thread, showing a small busy overlay meanwhile, then
        calls on_success(result) back on the main thread. Any exception in
        compute_fn is reported via a Messagebox instead of crashing.

        If a second background operation is started before the first one
        finishes (e.g. the user clicks Match to Database twice with
        different category filters before the first result arrives), only
        the most recently REQUESTED one's result is applied -- otherwise
        whichever happens to finish last would silently overwrite the
        newer request's result with a stale one.
        """
        self._bg_generation = getattr(self, "_bg_generation", 0) + 1
        my_generation = self._bg_generation
        overlay = BusyOverlay(self.app.root, busy_text)

        def _on_success(result):
            overlay.destroy()
            if my_generation != self._bg_generation:
                return  # superseded by a newer request -- discard this stale result
            on_success(result)

        def _on_error(exc):
            overlay.destroy()
            if my_generation != self._bg_generation:
                return
            Messagebox.show_error(str(exc), "Error")

        BackgroundTask(self.app.root, compute_fn, _on_success, _on_error).start()


class BusyOverlay(tb.Toplevel):
    """A small centered, borderless 'working...' indicator shown during a background task."""
    def __init__(self, parent, text="Working..."):
        super().__init__(parent)
        self.overrideredirect(True)
        self.transient(parent)
        frm = tb.Frame(self, padding=20, bootstyle="light")
        frm.pack()
        tb.Label(frm, text=text, bootstyle="primary").pack(pady=(0, 8))
        pb = tb.Progressbar(frm, mode="indeterminate", bootstyle="info-striped", length=220)
        pb.pack()
        pb.start(12)
        self.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width() // 2 - self.winfo_width() // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - self.winfo_height() // 2
        self.geometry(f"+{max(px, 0)}+{max(py, 0)}")
        try:
            self.grab_set()
        except Exception:
            pass
