"""Run OriginLab on its own long-lived thread.

Two constraints meet here. Starting Origin takes ten to twenty seconds, so it cannot run
on the interface thread without the window freezing. And COM objects are bound to the
thread that created them, so an Origin session cannot be started on one worker and used
from another.

`OriginWorker` satisfies both: a single QThread owns one `OriginSession` for the life of
the application. Requests go in as queued signals and come back through `finished`, so
the window stays responsive and every COM call lands on the same thread.
"""
from __future__ import annotations

import itertools
import traceback
from typing import Any, Sequence

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..origin import OriginBook, OriginNotAvailable, OriginSession, export_to_origin

__all__ = ["OriginWorker"]


class _Executor(QObject):
    """Lives on the worker thread. Owns the session; never touched from the UI thread."""

    done = Signal(int, str, bool, str, object)      # id, action, ok, message, payload

    def __init__(self, visible: bool):
        super().__init__()
        self._visible = visible
        self._session: OriginSession | None = None

    @Slot(int, str, object)
    def run(self, request_id: int, action: str, args: Any) -> None:
        try:
            message, payload = getattr(self, f"_do_{action}")(args)
            self.done.emit(request_id, action, True, message, payload)
        except OriginNotAvailable as exc:
            self.done.emit(request_id, action, False, str(exc), None)
        except Exception as exc:                            # noqa: BLE001 - reported to the UI
            detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.done.emit(request_id, action, False, detail, None)

    def _session_or_new(self) -> OriginSession:
        if self._session is None:
            self._session = OriginSession(visible=self._visible)
        return self._session

    def _do_send(self, args) -> tuple[str, Any]:
        books, theme, palette = args
        session = self._session_or_new()
        pages = 0
        for book in books:
            pages += len(session.send(book, theme=theme, palette_name=palette))
        return (f"Sent {len(books)} workbook(s) and {pages} graph(s) to Origin "
                f"({session.books_sent} workbook(s) in this session)"), session.books_sent

    def _do_save(self, path) -> tuple[str, Any]:
        if self._session is None or not self._session.is_active:
            raise RuntimeError("Nothing has been sent to Origin yet.")
        saved = self._session.save(path)
        return f"Origin project saved to {saved.name}", str(saved)

    def _do_close(self, save_to) -> tuple[str, Any]:
        if self._session is None or not self._session.is_active:
            return "Origin was not open.", None
        self._session.close(save_to=save_to)
        self._session = None
        return "Origin closed.", None

    def _do_export(self, args) -> tuple[str, Any]:
        books, folder, options = args
        result = export_to_origin(books, folder, **options)
        return result.summary(), result


class OriginWorker(QObject):
    """The application's single gateway to Origin.

    `finished(request_id, action, ok, message, payload)` reports every request.
    `busy_changed(bool)` lets the interface show progress while Origin works.
    """

    finished = Signal(int, str, bool, str, object)
    busy_changed = Signal(bool)
    _request = Signal(int, str, object)

    def __init__(self, visible: bool = True, parent: QObject | None = None):
        super().__init__(parent)
        self._ids = itertools.count(1)
        self._pending: set[int] = set()
        self._session_active = False
        self._thread = QThread()
        self._thread.setObjectName("OriginWorker")
        self._executor = _Executor(visible)
        self._executor.moveToThread(self._thread)
        self._request.connect(self._executor.run)
        self._executor.done.connect(self._on_done)
        self._thread.start()

    # -- requests --------------------------------------------------------------
    def send(self, books: Sequence[OriginBook], *, theme: str = "light",
             palette_name: str | None = None) -> int:
        """Add workbooks and graphs to the running session, starting Origin if needed."""
        return self._submit("send", (list(books), theme, palette_name))

    def save(self, path: str) -> int:
        return self._submit("save", str(path))

    def close_origin(self, save_to: str | None = None) -> int:
        return self._submit("close", save_to)

    def export(self, books: Sequence[OriginBook], folder: str, **options) -> int:
        """One-shot export: build, save a project and images, close Origin."""
        return self._submit("export", (list(books), str(folder), options))

    # -- state -----------------------------------------------------------------
    @property
    def is_busy(self) -> bool:
        return bool(self._pending)

    @property
    def session_active(self) -> bool:
        """True once a send has succeeded and Origin has not been closed since."""
        return self._session_active

    def shutdown(self, wait_ms: int = 30_000) -> bool:
        """Close Origin and stop the thread. Call from the application's closeEvent.

        Qt aborts the process if a running QThread is destroyed, so this must run before
        the worker is deleted.
        """
        if self._thread.isRunning():
            if self._session_active:
                self._request.emit(next(self._ids), "close", None)
            self._thread.quit()
            return self._thread.wait(wait_ms)
        return True

    # -- plumbing ----------------------------------------------------------------
    def _submit(self, action: str, args: Any) -> int:
        request_id = next(self._ids)
        was_idle = not self._pending
        self._pending.add(request_id)
        if was_idle:
            self.busy_changed.emit(True)
        self._request.emit(request_id, action, args)
        return request_id

    @Slot(int, str, bool, str, object)
    def _on_done(self, request_id: int, action: str, ok: bool, message: str, payload: Any) -> None:
        self._pending.discard(request_id)
        if ok and action == "send":
            self._session_active = True
        elif action == "close" or (ok and action == "export"):
            self._session_active = self._session_active and action != "close"
        self.finished.emit(request_id, action, ok, message, payload)
        if not self._pending:
            self.busy_changed.emit(False)
