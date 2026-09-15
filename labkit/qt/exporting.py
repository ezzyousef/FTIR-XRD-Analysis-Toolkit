"""Export controls every application shows the same way.

`ExportBar` is a compact row of buttons — Send to Origin, Save Origin project, Close
Origin, Excel, figures, LabTalk package — wired to one `OriginWorker`. The application
supplies callables that return what to export, so the bar knows nothing about the data:

    books()     -> list[OriginBook]        what goes to Origin
    report()    -> ExcelReport | None      what goes to Excel
    figures()   -> list[FigureSpec]        what gets saved as images
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QMenu, QPushButton, QToolButton, QWidget)

from ..excel import ExcelReport, write_workbook
from ..figure import FigureSpec, render, save
from ..origin import OriginBook, origin_available, write_labtalk_package
from .origin_worker import OriginWorker

__all__ = ["ExportBar", "last_directory", "remember_directory"]

_last_dir: dict[str, str] = {}


def last_directory(kind: str = "export") -> str:
    return _last_dir.get(kind, str(Path.home()))


def remember_directory(path: str, kind: str = "export") -> None:
    p = Path(path)
    _last_dir[kind] = str(p if p.is_dir() else p.parent)


class ExportBar(QWidget):
    def __init__(self, *, worker: OriginWorker | None,
                 books: Callable[[], Sequence[OriginBook]] | None = None,
                 report: Callable[[], ExcelReport | None] | None = None,
                 figures: Callable[[], Sequence[FigureSpec]] | None = None,
                 notify: Callable[[str, str], None] | None = None,
                 theme: Callable[[], str] | None = None,
                 project_name: Callable[[], str] | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._worker = worker
        self._books = books
        self._report = report
        self._figures = figures
        self._notify = notify or (lambda message, level: None)
        self._theme = theme or (lambda: "light")
        self._project_name = project_name or (lambda: "Project")
        # Several bars can share one OriginWorker (a page bar, a menu bar…). Each reports
        # only the requests it started, so one Origin result never produces several toasts.
        self._requests: set[int] = set()

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.btn_origin = QToolButton()
        self.btn_origin.setText("Send to Origin")
        self.btn_origin.setObjectName("Primary")
        self.btn_origin.setPopupMode(QToolButton.MenuButtonPopup)
        self.btn_origin.clicked.connect(self.send_to_origin)
        menu = QMenu(self.btn_origin)
        self.act_save = menu.addAction("Save Origin project…", self.save_origin_project)
        self.act_close = menu.addAction("Close Origin", self.close_origin)
        menu.addSeparator()
        menu.addAction("Write LabTalk package (no Origin needed)…", self.write_package)
        self.btn_origin.setMenu(menu)

        self.btn_excel = QPushButton("Export to Excel…")
        self.btn_excel.clicked.connect(self.export_excel)
        self.btn_figures = QPushButton("Save figures…")
        self.btn_figures.clicked.connect(self.save_figures)

        if books is not None:
            row.addWidget(self.btn_origin)
        if report is not None:
            row.addWidget(self.btn_excel)
        if figures is not None:
            row.addWidget(self.btn_figures)
        row.addStretch(1)

        ok, why = origin_available()
        self._origin_ok = ok
        self.btn_origin.setToolTip(
            "Builds styled workbooks and graphs in OriginLab. Every send adds to the same "
            "Origin project." if ok else f"{why}\nUse the arrow menu to write a LabTalk "
            "package that rebuilds the project on a machine with Origin.")
        if worker is not None:
            worker.busy_changed.connect(self._on_busy)
            worker.finished.connect(self._on_finished)
        self._sync_menu()

    # -- Origin ----------------------------------------------------------------
    def send_to_origin(self) -> None:
        books = self._collect_books()
        if not books:
            return
        if not self._origin_ok or self._worker is None:
            self._notify("OriginLab is not available here — writing a LabTalk package instead.", "warning")
            self.write_package(books)
            return
        self._notify("Sending to Origin… (starting Origin can take 10–20 s)", "info")
        self._requests.add(self._worker.send(books, theme="light"))

    def save_origin_project(self) -> None:
        if self._worker is None or not self._worker.session_active:
            self._notify("Nothing has been sent to Origin yet.", "warning")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Origin project", str(Path(last_directory("origin")) / f"{self._project_name()}.opju"),
            "Origin project (*.opju)")
        if path:
            remember_directory(path, "origin")
            self._requests.add(self._worker.save(path))

    def close_origin(self) -> None:
        if self._worker is not None:
            self._requests.add(self._worker.close_origin())

    def write_package(self, books: Sequence[OriginBook] | None = None) -> None:
        books = list(books) if books else self._collect_books()
        if not books:
            return
        folder = QFileDialog.getExistingDirectory(self, "Folder for the Origin package",
                                                  last_directory("origin"))
        if not folder:
            return
        remember_directory(folder, "origin")
        try:
            result = write_labtalk_package(books, folder, project_name=self._project_name())
        except Exception as exc:                            # noqa: BLE001 - shown to the user
            self._notify(f"Could not write the Origin package: {exc}", "error")
            return
        self._notify(result.summary(), "success")

    def _collect_books(self) -> list[OriginBook]:
        try:
            books = [b for b in (self._books() if self._books else []) if b.figures or b.table or b.results]
        except Exception as exc:                            # noqa: BLE001 - shown to the user
            self._notify(f"Could not prepare the Origin export: {exc}", "error")
            return []
        if not books:
            self._notify("Nothing to send yet — load data and run an analysis first.", "warning")
        return books

    def _on_busy(self, busy: bool) -> None:
        self.btn_origin.setEnabled(not busy)
        self.btn_origin.setText("Working in Origin…" if busy else "Send to Origin")

    def _on_finished(self, request_id: int, action: str, ok: bool, message: str, _payload) -> None:
        self._sync_menu()
        if request_id not in self._requests:
            return                              # another bar's request
        self._requests.discard(request_id)
        self._notify(message, "success" if ok else "error")

    def _sync_menu(self) -> None:
        active = bool(self._worker is not None and self._worker.session_active)
        self.act_save.setEnabled(active)
        self.act_close.setEnabled(active)

    # -- Excel -------------------------------------------------------------------
    def export_excel(self) -> None:
        try:
            report = self._report() if self._report else None
        except Exception as exc:                            # noqa: BLE001
            self._notify(f"Could not prepare the Excel export: {exc}", "error")
            return
        if report is None or not (report.analyses or report.tables):
            self._notify("Nothing to export yet — load data and run an analysis first.", "warning")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export to Excel", str(Path(last_directory("excel")) / f"{self._project_name()}.xlsx"),
            "Excel workbook (*.xlsx)")
        if not path:
            return
        remember_directory(path, "excel")
        try:
            written = write_workbook(report, path)
        except PermissionError:
            self._notify("That workbook is open in Excel — close it and try again.", "error")
            return
        except Exception as exc:                            # noqa: BLE001
            self._notify(f"Excel export failed: {exc}", "error")
            return
        self._notify(f"Workbook written to {written.name}", "success")

    # -- figures -------------------------------------------------------------------
    def save_figures(self) -> None:
        specs = [s for s in (self._figures() if self._figures else []) if not s.is_empty]
        if not specs:
            self._notify("No figures to save yet.", "warning")
            return
        folder = QFileDialog.getExistingDirectory(self, "Folder for the figures", last_directory("figures"))
        if not folder:
            return
        remember_directory(folder, "figures")
        written = 0
        for i, spec in enumerate(specs, start=1):
            try:
                figure = render(spec, theme="light", size="double_column")
                save(figure, Path(folder) / f"{i:02d}_{spec.slug()}.png", dpi="print")
                written += 1
            except Exception as exc:                        # noqa: BLE001
                self._notify(f"{spec.title}: {exc}", "error")
        self._notify(f"Saved {written} figure(s) at 300 dpi to {folder}", "success" if written else "warning")
