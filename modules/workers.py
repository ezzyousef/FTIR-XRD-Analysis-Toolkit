"""
workers.py
Runs a slow, pure computation (database matching, batch peak fitting --
anything with no Tk widget access) on a background thread so the window
stays responsive (draggable, other tab clickable) instead of freezing
solid until it returns. Tkinter itself is not thread-safe, so the result
is handed back to the main thread via root.after() polling rather than
touched directly from the worker thread.

Usage:
    task = BackgroundTask(root, lambda: slow_pure_function(data),
                           on_success=lambda result: ...,
                           on_error=lambda exc: ...)
    task.start()
"""
import threading
import queue


class BackgroundTask:
    def __init__(self, root, fn, on_success, on_error=None, poll_ms=80):
        self.root = root
        self.fn = fn
        self.on_success = on_success
        self.on_error = on_error
        self.poll_ms = poll_ms
        self._q = queue.Queue()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        self.root.after(self.poll_ms, self._poll)

    def _run(self):
        try:
            result = self.fn()
        except Exception as e:  # deliberately broad: report back, never crash the thread silently
            self._q.put(("error", e))
        else:
            self._q.put(("ok", result))

    def _poll(self):
        try:
            status, payload = self._q.get_nowait()
        except queue.Empty:
            self.root.after(self.poll_ms, self._poll)
            return
        if status == "ok":
            self.on_success(payload)
        elif self.on_error:
            self.on_error(payload)
