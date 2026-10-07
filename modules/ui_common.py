"""
ui_common.py
Shared Qt building blocks for the FTIR and XRD pages: the trace list, a data table, small
form dialogs, and AnalysisTabBase -- multi-trace management, the plot, drag & drop, the
export bar, sessions, background work and undo snapshots.

Dialog helpers (ask_fields, show_message, ask_yes_no, get_save_path, get_open_paths) are
module functions so tests and the self-test can replace them.
"""
from __future__ import annotations

import copy
import csv
import os
import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

import exports
import session_io
from labkit.qt.exporting import ExportBar, last_directory, remember_directory
from labkit.qt.widgets import BusyBar, Card, PlotCanvas, scrollable
from labkit.style import THEMES
from trace_model import ColorCycle, Trace
from workers import Worker


# ============================= dialogs =============================

def parse_float(value, field_name):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"'{field_name}' must be a number (got {value!r}).")


def ask_fields(parent, title, fields, help_text=None):
    """A small modal form. `fields`: (key, label, default[, choices]) tuples; a field with
    choices is a drop-down. Returns {key: text}, or None when cancelled."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(20, 18, 20, 16)
    layout.setSpacing(12)
    if help_text:
        hint = QLabel(help_text)
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        hint.setMaximumWidth(420)
        layout.addWidget(hint)
    form = QFormLayout()
    form.setSpacing(9)
    editors = {}
    first = None
    for field in fields:
        key, label, default = field[0], field[1], field[2]
        choices = field[3] if len(field) > 3 else None
        if choices:
            editor = QComboBox()
            editor.addItems([str(c) for c in choices])
            if str(default) in [str(c) for c in choices]:
                editor.setCurrentText(str(default))
        else:
            editor = QLineEdit(str(default))
            editor.setMinimumWidth(180)
            if first is None:
                first = editor
        form.addRow(label, editor)
        editors[key] = editor
    layout.addLayout(form)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.button(QDialogButtonBox.Ok).setObjectName("Primary")
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)
    if first is not None:
        first.setFocus()
        first.selectAll()
    if dlg.exec() != QDialog.Accepted:
        return None
    return {k: (e.currentText() if isinstance(e, QComboBox) else e.text()) for k, e in editors.items()}


def show_message(parent, title, text, level="info"):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setTextFormat(Qt.PlainText)
    box.setTextInteractionFlags(Qt.TextSelectableByMouse)
    box.setIcon({"error": QMessageBox.Critical, "warning": QMessageBox.Warning}.get(level, QMessageBox.Information))
    box.exec()


def ask_yes_no(parent, title, text) -> bool:
    return QMessageBox.question(parent, title, text) == QMessageBox.Yes


def get_save_path(parent, title, default_name, file_filter, kind="export") -> str:
    path, _ = QFileDialog.getSaveFileName(parent, title, str(Path(last_directory(kind)) / default_name), file_filter)
    if path:
        remember_directory(path, kind)
    return path


def get_open_paths(parent, title, file_filter, kind="data") -> list[str]:
    paths, _ = QFileDialog.getOpenFileNames(parent, title, last_directory(kind), file_filter)
    if paths:
        remember_directory(paths[0], kind)
    return list(paths)


def show_formula(parent, title, text):
    box = QMessageBox(parent)
    box.setWindowTitle(f"Formula & source — {title}")
    box.setText(text)
    box.setTextFormat(Qt.PlainText)
    box.setTextInteractionFlags(Qt.TextSelectableByMouse)
    box.setIcon(QMessageBox.NoIcon)
    box.exec()


def _dot_icon(colour: str, size: int = 12) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(colour))
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return QIcon(pix)


# ============================= tables =============================

class DataTable(QTableWidget):
    """A read-only table of dict rows shown through a formatter; `on_select(row)` on click."""

    def __init__(self, headers, parent=None):
        super().__init__(0, len(headers), parent)
        self.setHorizontalHeaderLabels(list(headers))
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(27)
        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        header.setHighlightSections(False)
        for i in range(len(headers) - 1):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self._rows = []
        self.on_select = None
        self.itemSelectionChanged.connect(self._emit_select)

    @property
    def rows(self):
        return list(self._rows)

    def set_rows(self, rows, formatter):
        self.blockSignals(True)
        self._rows = list(rows)
        self.setRowCount(0)
        self.setRowCount(len(self._rows))
        for r, row in enumerate(self._rows):
            for c, value in enumerate(formatter(row)):
                text = "" if value is None else str(value)
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.setItem(r, c, item)
        self.blockSignals(False)

    def clear_rows(self):
        self.set_rows([], lambda _r: ())

    def cell_text(self, row, column):
        item = self.item(row, column)
        return item.text() if item is not None else ""

    def _emit_select(self):
        selected = self.selectionModel().selectedRows()
        if selected and self.on_select:
            idx = selected[0].row()
            if 0 <= idx < len(self._rows):
                self.on_select(self._rows[idx])


class TracePanel(QWidget):
    """Loaded traces: tick to show or hide, click a row to make it the active trace."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_active_change = None
        self.on_visibility_toggle = None
        self.on_remove = None
        self.on_clear = None
        self._ids: list[int] = []
        self._refreshing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Show", "Trace", "Points"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(27)
        self.table.setMinimumHeight(118)
        self.table.setMaximumHeight(190)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self._item_changed)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table)

        row = QHBoxLayout()
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setObjectName("Danger")
        self.btn_remove.clicked.connect(self._remove_clicked)
        self.btn_clear = QPushButton("Clear all")
        self.btn_clear.clicked.connect(self._clear_clicked)
        row.addWidget(self.btn_remove)
        row.addWidget(self.btn_clear)
        row.addStretch(1)
        layout.addLayout(row)

    def refresh(self, traces, active_id):
        self._refreshing = True
        try:
            self._ids = [t.id for t in traces]
            self.table.setRowCount(len(traces))
            for r, t in enumerate(traces):
                show = QTableWidgetItem()
                show.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                show.setCheckState(Qt.Checked if t.visible else Qt.Unchecked)
                self.table.setItem(r, 0, show)
                label = QTableWidgetItem(_dot_icon(t.color), t.label)
                label.setToolTip(str(t.metadata.get("path", t.label)))
                self.table.setItem(r, 1, label)
                points = QTableWidgetItem(str(len(t.x)))
                points.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, 2, points)
            if active_id in self._ids:
                self.table.selectRow(self._ids.index(active_id))
            else:
                self.table.clearSelection()
            self.btn_remove.setEnabled(bool(traces))
            self.btn_clear.setEnabled(bool(traces))
        finally:
            self._refreshing = False

    def selected_id(self):
        rows = self.table.selectionModel().selectedRows()
        return self._ids[rows[0].row()] if rows and rows[0].row() < len(self._ids) else None

    def _item_changed(self, item):
        if self._refreshing or item.column() != 0 or item.row() >= len(self._ids):
            return
        if self.on_visibility_toggle:
            self.on_visibility_toggle(self._ids[item.row()])

    def _selection_changed(self):
        if self._refreshing:
            return
        trace_id = self.selected_id()
        if trace_id is not None and self.on_active_change:
            self.on_active_change(trace_id)

    def _remove_clicked(self):
        trace_id = self.selected_id()
        if trace_id is not None and self.on_remove:
            self.on_remove(trace_id)

    def _clear_clicked(self):
        if self._ids and self.on_clear and ask_yes_no(self, "Clear all", "Remove every loaded trace from this page?"):
            self.on_clear()


def save_figure_snapshot(fig, path):
    fig.savefig(path, dpi=150, bbox_inches="tight")
    return path


# ============================= shared analysis page =============================

class AnalysisTabBase(QWidget):
    """Common scaffolding of the FTIR and XRD pages. Subclasses set KIND, READER,
    FILE_FILTER and LOAD_TEXT, add their controls with add_card(), and implement the hooks
    below (on_active_trace_changed, _plot_active_extras, session_settings, ...)."""

    KIND = "ftir"
    READER = None
    FILE_FILTER = "All files (*.*)"
    LOAD_TEXT = "Load file…"
    DROP_HINT = "…or drop files anywhere on this page."

    def __init__(self, app, x_label, y_label, invert_x=False):
        super().__init__()
        self.app = app
        self.x_label = x_label
        self.y_label = y_label
        self.invert_x = invert_x
        self.traces: list[Trace] = []
        self.active_id = None
        self.color_cycle = ColorCycle()
        self.reference_overlay = None
        self._bg_generation = 0
        self._pending: dict[int, tuple] = {}
        self._workers: list[Worker] = []
        self.setAcceptDrops(True)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        outer.addWidget(splitter)

        controls_host = QWidget()
        self.controls_layout = QVBoxLayout(controls_host)
        self.controls_layout.setContentsMargins(0, 0, 10, 0)
        self.controls_layout.setSpacing(12)
        self.controls_layout.addStretch(1)
        left = scrollable(controls_host)
        left.setMinimumWidth(310)
        splitter.addWidget(left)
        self.controls_host, self.controls_scroll, self.main_splitter = controls_host, left, splitter

        right = QSplitter(Qt.Vertical)
        plot_card = Card()
        self.busy = BusyBar()
        plot_card.body.addWidget(self.busy)
        self.plot = PlotCanvas()
        self.plot.canvas.mpl_connect("motion_notify_event", self._on_plot_motion)
        plot_card.body.addWidget(self.plot, 1)
        self.export_bar = ExportBar(worker=getattr(app, "origin", None), books=self.origin_books,
                                    report=self.excel_report, figures=self.export_figures,
                                    notify=app.notify, project_name=self.project_name)
        plot_card.body.addWidget(self.export_bar)
        right.addWidget(plot_card)
        self.results_tabs = QTabWidget()
        self.results_tabs.setMinimumHeight(170)
        # Scroll arrows when the tab titles do not fit, instead of widening the whole window.
        self.results_tabs.setUsesScrollButtons(True)
        self.results_tabs.tabBar().setExpanding(False)
        right.addWidget(self.results_tabs)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 2)
        right.setChildrenCollapsible(False)             # neither the plot nor the results may vanish
        right.setSizes([640, 260])
        self.right_splitter = right
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([400, 1000])      # the controls' natural width plus their scrollbar

        card = self.add_card("Loaded traces")
        load = QPushButton(self.LOAD_TEXT)
        load.setObjectName("Primary")
        load.clicked.connect(lambda _c=False: self.load_file_dialog())
        card.body.addWidget(load)
        hint = QLabel(self.DROP_HINT)
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        card.body.addWidget(hint)
        self.trace_panel = TracePanel()
        self.trace_panel.on_active_change = self._on_trace_active_change
        self.trace_panel.on_visibility_toggle = self._on_trace_visibility_toggle
        self.trace_panel.on_remove = self._on_trace_remove
        self.trace_panel.on_clear = self._on_trace_clear
        card.body.addWidget(self.trace_panel)

    def showEvent(self, event):  # noqa: N802 - Qt naming
        super().showEvent(event)
        if not getattr(self, "_controls_fitted", False):
            # The cards' size hints are only final once the stylesheet has been applied.
            self._controls_fitted = True
            self.fit_controls_width()

    def fit_controls_width(self):
        """Open the controls column at the width its contents need, so cards are not clipped."""
        need = self.controls_host.sizeHint().width() + self.controls_scroll.verticalScrollBar().sizeHint().width() + 4
        need = max(310, min(need, 470))
        self.controls_scroll.setMinimumWidth(need)
        total = max(sum(self.main_splitter.sizes()), 1400)
        self.main_splitter.setSizes([need, total - need])

    # ---- building helpers ----
    def add_card(self, title, subtitle=""):
        card = Card(title, subtitle)
        self.controls_layout.insertWidget(self.controls_layout.count() - 1, card)
        return card

    def action_button(self, text, fn, primary=False, info=None):
        """A button, optionally with an ⓘ button showing the formula and citation behind it."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        button = QPushButton(text)
        if primary:
            button.setObjectName("Primary")
        button.clicked.connect(lambda _c=False: fn())
        layout.addWidget(button, 1)
        if info:
            info_btn = QPushButton("ⓘ")
            info_btn.setObjectName("Ghost")
            info_btn.setFixedWidth(34)
            info_btn.setToolTip("Formula and literature source")
            info_btn.clicked.connect(lambda _c=False: self.show_formula(info[0], info[1]))
            layout.addWidget(info_btn)
        row.button = button
        return row

    @staticmethod
    def labelled(label, widget):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(label))
        layout.addStretch(1)
        layout.addWidget(widget)
        return row

    def show_formula(self, title, text):
        show_formula(self, title, text)

    # ---- plotting ----
    @property
    def theme(self):
        return getattr(self.app, "theme", "light")

    def export_options(self) -> dict:
        """mode / wavelength passed to the exports module."""
        return {}

    def figure_spec(self, title=""):
        return exports.spectrum_figure(self.KIND, self.traces, self.active_id, title=title, **self.export_options())

    def redraw(self):
        if not any(t.visible for t in self.traces):
            self.plot.show_message("Load a file to start — or drop files onto this page.", self.theme)
            return
        self.plot.show_figure(self.figure_spec(), self.theme)
        self._draw_extras(self.plot.figure, self.theme)
        self.plot.canvas.draw_idle()

    def _draw_extras(self, figure, theme):
        if not figure.axes:
            return
        ax = figure.axes[0]
        active = self.get_active()
        if active is not None and active.visible:
            self._plot_active_extras(ax, active, theme)
        if self.reference_overlay:
            self._draw_reference_overlay(ax, theme)
            try:
                figure.tight_layout(pad=0.9)        # make room for the overlay's title row
            except Exception:  # noqa: BLE001 - layout is best effort
                pass

    def _plot_active_extras(self, ax, trace, theme):
        """Hook: peak markers etc. for the active trace."""

    def _draw_reference_overlay(self, ax, theme):
        """Hook: the selected database match's reference bands."""

    @staticmethod
    def foreground(theme):
        return THEMES.get(theme, THEMES["light"]).foreground

    def snapshot_png(self, path):
        """The current plot, light theme, for the PDF report."""
        from labkit.figure import render
        figure = render(self.figure_spec(), theme="light", size="double_column")
        self._draw_extras(figure, "light")
        return save_figure_snapshot(figure, path)

    def set_reference_overlay(self, overlay):
        self.reference_overlay = overlay
        self.redraw()

    def clear_reference_overlay(self):
        if self.reference_overlay is not None:
            self.reference_overlay = None
            self.redraw()

    def on_theme_changed(self, theme):
        self.redraw()

    def _on_plot_motion(self, event):
        text = "" if event.inaxes is None or event.xdata is None else f"x = {event.xdata:,.2f}    y = {event.ydata:,.4g}"
        if hasattr(self.app, "status_right"):
            self.app.status_right.setText(text)

    # ---- page hooks ----
    def on_open_file(self):
        self.load_file_dialog()

    # ---- traces ----
    def add_trace(self, label, x, y, metadata=None):
        t = Trace(label, x, y, self.color_cycle.next(), metadata=metadata)
        self.traces.append(t)
        self.active_id = t.id
        self._on_traces_changed()
        return t

    def get_active(self):
        return next((t for t in self.traces if t.id == self.active_id), None)

    def require_active(self, message="Load a file first."):
        t = self.get_active()
        if t is None:
            self.app.notify(message, "warning")
        return t

    def record(self, label):
        recorder = getattr(self.app, "record_history", None)
        if callable(recorder):
            recorder(f"{self.KIND.upper()}: {label}")

    def _on_traces_changed(self):
        self.trace_panel.refresh(self.traces, self.active_id)
        self.redraw()
        self.on_active_trace_changed()

    def on_active_trace_changed(self):
        """Hook: refresh the results tables for the active trace."""

    def _on_trace_active_change(self, trace_id):
        if trace_id == self.active_id:
            return
        self.active_id = trace_id
        self.redraw()
        self.on_active_trace_changed()

    def _on_trace_visibility_toggle(self, trace_id):
        for t in self.traces:
            if t.id == trace_id:
                t.visible = not t.visible
                self.record(f"{'show' if t.visible else 'hide'} {t.label}")
        self._on_traces_changed()

    def _on_trace_remove(self, trace_id):
        removed = next((t for t in self.traces if t.id == trace_id), None)
        self.traces = [t for t in self.traces if t.id != trace_id]
        if self.active_id == trace_id:
            self.active_id = self.traces[-1].id if self.traces else None
        self._on_traces_changed()
        if removed is not None:
            self.record(f"remove {removed.label}")

    def _on_trace_clear(self):
        count = len(self.traces)
        self.traces = []
        self.active_id = None
        self.reference_overlay = None
        self._on_traces_changed()
        self.record(f"clear {count} trace(s)")

    # ---- undo snapshots ----
    def snapshot(self):
        return {"traces": copy.deepcopy(self.traces), "active_id": self.active_id}

    def restore(self, state):
        state = state or {"traces": [], "active_id": None}
        self.traces = copy.deepcopy(state["traces"])
        self.active_id = state["active_id"]
        self.reference_overlay = None
        self._on_traces_changed()

    # ---- loading / drag & drop ----
    def load_file_dialog(self):
        paths = get_open_paths(self, self.LOAD_TEXT.rstrip("…"), self.FILE_FILTER)
        if paths:
            self.load_paths(paths)

    def load_paths(self, paths):
        loaded = [p for p in paths if self.load_file_path(p, record=False)]
        if loaded:
            self.record(f"load {os.path.basename(loaded[0])}" if len(loaded) == 1 else f"load {len(loaded)} files")
        return loaded

    def load_file_path(self, path, reader=None, record=True):
        reader = reader or type(self).READER
        try:
            result = reader(path)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            show_message(self, "Could not load file", f"{os.path.basename(path)}\n\n{exc}", "error")
            return None
        meta = dict(result.metadata) if getattr(result, "metadata", None) else {}
        meta["confidence"] = getattr(result, "confidence", "high")
        meta["path"] = path
        trace = self.add_trace(os.path.basename(path), result.x, result.y, metadata=meta)
        note_recent = getattr(self.app, "note_recent_file", None)
        if callable(note_recent):
            note_recent(path)
        if meta["confidence"] == "high":
            self.app.notify(f"Loaded {trace.label}: {len(result.x)} points", "success")
        else:
            self.app.notify(f"Loaded {trace.label}: {len(result.x)} points — LOW-CONFIDENCE parse, "
                            "verify against an ASCII export", "warning")
        if record:
            self.record(f"load {trace.label}")
        return trace

    def dragEnterEvent(self, event):  # noqa: N802 - Qt naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802 - Qt naming
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        paths = [p for p in paths if os.path.isfile(p)]
        if paths:
            event.acceptProposedAction()
            self.load_paths(paths)

    # ---- background work ----
    def run_background(self, compute, on_success, busy_text="Working…"):
        """compute() runs on a worker thread (touching no widgets); on_success(result) runs
        here afterwards. Only the most recently started request's result is applied."""
        self._bg_generation += 1
        token = self._bg_generation
        self._pending = {token: (on_success,)}
        worker = Worker(compute, token=token, parent=self)
        worker.succeeded.connect(self._worker_succeeded)
        worker.failed.connect(self._worker_failed)
        worker.finished.connect(self._worker_finished)
        self._workers.append(worker)
        self._set_busy(True, busy_text)
        worker.start()

    def _worker_succeeded(self, token, result):
        callbacks = self._pending.pop(token, None)
        if callbacks is None:
            return                                  # superseded by a newer request
        self._set_busy(False)
        callbacks[0](result)

    def _worker_failed(self, token, message):
        if self._pending.pop(token, None) is None:
            return
        self._set_busy(False)
        show_message(self, "Calculation failed", message, "error")

    def _worker_finished(self):
        worker = self.sender()
        if worker in self._workers:
            self._workers.remove(worker)
            worker.deleteLater()

    def _set_busy(self, busy, text=""):
        if busy:
            self.busy.start()
        else:
            self.busy.stop()
        setter = getattr(self.app, "set_busy", None)
        if callable(setter):
            setter(busy, text)

    @property
    def is_busy(self):
        return bool(self._pending)

    def wait_for_workers(self, msec=15000):
        for worker in list(self._workers):
            worker.wait(msec)

    # ---- exports ----
    def project_name(self):
        active = self.get_active()
        return Path(active.label).stem if active else self.KIND

    def origin_books(self):
        return exports.origin_books(self.KIND, self.traces, self.active_id, **self.export_options())

    def excel_report(self):
        info = getattr(self.app, "info", None)
        return exports.excel_report(self.KIND, self.traces, self.active_id,
                                    version=getattr(info, "version", ""), author=getattr(info, "author", ""),
                                    settings=self.session_settings(), project=self.project_name(),
                                    **self.export_options())

    def export_figures(self):
        return [self.figure_spec(title=exports.AXES[self.KIND]["title"])] if self.traces else []

    def export_originlab_dialog(self):
        if not self.traces:
            self.app.notify("Load a spectrum or pattern first.", "warning")
            return
        path = get_save_path(self, "Export for OriginLab (CSV)", f"{self.project_name()}_origin.csv",
                             "CSV (Origin ASCII) (*.csv)")
        if not path:
            return
        try:
            self.export_originlab_csv(path)
        except Exception as exc:  # noqa: BLE001
            show_message(self, "Export failed", str(exc), "error")
            return
        self.app.notify(f"Saved {len(self.traces)} trace(s) for OriginLab — row 1 long names, row 2 units", "success")

    def export_originlab_csv(self, path):
        """Every trace as an X/Y column pair with 'Long Name' and 'Units' header rows -- the
        Origin ASCII layout Origin's Import Wizard (or drag and drop) recognises."""
        def plain(label):
            return re.sub(r"[${}^\\]", "", label)

        max_len = max(len(t.x) for t in self.traces)
        header1, header2 = [], []
        for t in self.traces:
            header1 += [f"{t.label} X", f"{t.label} Y"]
            header2 += [plain(self.x_label), plain(self.y_label)]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header1)
            w.writerow(header2)
            for i in range(max_len):
                row = []
                for t in self.traces:
                    row += [t.x[i], t.y[i]] if i < len(t.x) else ["", ""]
                w.writerow(row)

    def export_graph_dialog(self):
        if not self.traces:
            self.app.notify("Load a spectrum or pattern first.", "warning")
            return
        path = get_save_path(self, "Export graph", f"{self.project_name()}.svg",
                             "SVG (vector) (*.svg);;EPS (vector) (*.eps);;PDF (vector) (*.pdf);;PNG (300 dpi) (*.png)")
        if not path:
            return
        try:
            from labkit.figure import render
            figure = render(self.figure_spec(), theme="light", size="double_column")
            self._draw_extras(figure, "light")
            figure.savefig(path, dpi=300, bbox_inches="tight")
        except Exception as exc:  # noqa: BLE001
            show_message(self, "Export failed", str(exc), "error")
            return
        self.app.notify(f"Graph saved to {os.path.basename(path)}", "success")

    # ---- sessions ----
    def session_settings(self) -> dict:
        return {}

    def apply_session_settings(self, state: dict) -> None:
        pass

    def save_session(self, path=None):
        if not self.traces:
            self.app.notify("Nothing to save yet — load a file first.", "warning")
            return None
        path = path or get_save_path(self, "Save session", f"{self.project_name()}.ftirxrd",
                                     "FTIR/XRD session (*.ftirxrd)", kind="session")
        if not path:
            return None
        state = {"tab": self.KIND, **self.session_settings(), "active_id": self.active_id,
                 "traces": [{"label": t.label, "color": t.color, "visible": t.visible, "x": t.x, "y": t.y,
                             "y_raw": t.y_raw, "peaks": t.peaks, "matches": t.matches, "fg_hits": t.fg_hits,
                             "fits": t.fits, "metadata": t.metadata, "id": t.id} for t in self.traces]}
        try:
            session_io.save_session(path, state)
        except Exception as exc:  # noqa: BLE001
            show_message(self, "Save failed", str(exc), "error")
            return None
        self.app.notify(f"Session saved to {os.path.basename(path)}", "success")
        return path

    def load_session(self, path=None):
        if path is None:
            paths = get_open_paths(self, "Load session", "FTIR/XRD session (*.ftirxrd);;All files (*.*)", kind="session")
            path = paths[0] if paths else ""
        if not path:
            return False
        try:
            state = session_io.load_session(path)
        except Exception as exc:  # noqa: BLE001
            show_message(self, "Load failed", str(exc), "error")
            return False
        if state.get("tab") != self.KIND:
            other = "XRD" if self.KIND == "ftir" else "FTIR"
            show_message(self, "Wrong page", f"This session was saved from the {other} page — open it there.", "warning")
            return False
        self.apply_session_settings(state)
        self.traces = []
        for td in state.get("traces", []):
            t = Trace(td["label"], td["x"], td["y"], td["color"], metadata=td.get("metadata"))
            t.y_raw = __import__("numpy").array(td["y_raw"], dtype=float)
            t.visible = td.get("visible", True)
            t.peaks = td.get("peaks", [])
            t.matches = td.get("matches", [])
            t.fg_hits = td.get("fg_hits", [])
            t.fits = td.get("fits", [])
            self.traces.append(t)
        ids = [t.id for t in self.traces]
        # Trace ids are re-issued on load; the saved active index still picks the same trace.
        saved_ids = [td.get("id") for td in state.get("traces", [])]
        active = state.get("active_id")
        self.active_id = ids[saved_ids.index(active)] if active in saved_ids else (ids[-1] if ids else None)
        self.reference_overlay = None
        self._on_traces_changed()
        self.record(f"load session {os.path.basename(path)}")
        self.app.notify(f"Loaded session {os.path.basename(path)} ({len(self.traces)} trace(s))", "success")
        return True
