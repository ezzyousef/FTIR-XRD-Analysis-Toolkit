"""
workers.py
Runs a slow, pure computation (database matching, batch peak fitting -- anything that
touches no widget) on a background QThread so the window stays responsive instead of
freezing until it returns.

The result comes back through a signal. Connect it to a method of a QObject that lives
on the interface thread (a tab, a window): Qt then delivers it on that thread. A plain
function or lambda would be called on the worker thread, where touching widgets crashes.

Usage (inside a QWidget):
    worker = Worker(lambda: slow_pure_function(data), token=7, parent=self)
    worker.succeeded.connect(self._on_done)        # receives (token, result)
    worker.failed.connect(self._on_failed)          # receives (token, message)
    worker.start()
"""
from PySide6.QtCore import QThread, Signal


class Worker(QThread):
    succeeded = Signal(object, object)          # token, result
    failed = Signal(object, str)                # token, message

    def __init__(self, fn, token=None, parent=None):
        super().__init__(parent)
        self._fn = fn
        self.token = token

    def run(self):
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 - reported to the user, never lost silently
            self.failed.emit(self.token, str(exc) or type(exc).__name__)
        else:
            self.succeeded.emit(self.token, result)
