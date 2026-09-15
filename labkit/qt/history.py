"""Undo and redo for any application, by snapshot.

An application gives the history two functions — `capture()` returns its current state
and `restore(state)` puts one back — and calls `record(label)` after every action worth
undoing. The history never needs to know what the state is.

Snapshots are cheap when the state holds references to immutable objects (a tuple of
datasets or results rather than copies of their arrays), which is the recommended shape.
For mutable state, `capture()` should return a copy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

__all__ = ["History", "HISTORY_LIMIT"]

HISTORY_LIMIT = 50


@dataclass(frozen=True)
class _Entry:
    label: str
    state: Any


class History(QObject):
    """A linear undo stack. A new action after an undo discards the redo branch."""

    changed = Signal()
    restored = Signal(str, str)         # verb ("Undid" | "Redid"), action label

    def __init__(self, capture: Callable[[], Any], restore: Callable[[Any], None],
                 limit: int = HISTORY_LIMIT, initial_label: str = "Start"):
        super().__init__()
        self._capture = capture
        self._restore = restore
        self._limit = max(2, limit)
        self._entries: list[_Entry] = [_Entry(initial_label, capture())]
        self._index = 0
        self._restoring = False

    # -- recording -----------------------------------------------------------
    def record(self, label: str) -> None:
        """Remember the state *after* an action, so undo returns to before it."""
        if self._restoring:
            return                      # restoring state must not create new history
        del self._entries[self._index + 1:]
        self._entries.append(_Entry(label, self._capture()))
        if len(self._entries) > self._limit:
            self._entries.pop(0)
        self._index = len(self._entries) - 1
        self.changed.emit()

    def reset(self, label: str = "Start") -> None:
        """Forget everything — e.g. after opening a different session file."""
        self._entries = [_Entry(label, self._capture())]
        self._index = 0
        self.changed.emit()

    @property
    def is_restoring(self) -> bool:
        return self._restoring

    # -- navigation ----------------------------------------------------------
    def can_undo(self) -> bool:
        return self._index > 0

    def can_redo(self) -> bool:
        return self._index < len(self._entries) - 1

    def undo_label(self) -> str:
        return self._entries[self._index].label if self.can_undo() else ""

    def redo_label(self) -> str:
        return self._entries[self._index + 1].label if self.can_redo() else ""

    def undo(self) -> bool:
        if not self.can_undo():
            return False
        label = self._entries[self._index].label
        self._index -= 1
        self._apply(self._entries[self._index].state)
        self.restored.emit("Undid", label)
        return True

    def redo(self) -> bool:
        if not self.can_redo():
            return False
        self._index += 1
        entry = self._entries[self._index]
        self._apply(entry.state)
        self.restored.emit("Redid", entry.label)
        return True

    def _apply(self, state: Any) -> None:
        self._restoring = True
        try:
            self._restore(state)
        finally:
            self._restoring = False
        self.changed.emit()

    def __len__(self) -> int:
        return len(self._entries)
