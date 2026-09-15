"""AppShell: the main window every lab application shares.

A navigation rail grouped into sections, pages built lazily, a status bar, toasts, a
Ctrl+K command palette, undo/redo, a light/dark switch and the Windows taskbar identity.
An application supplies an `AppInfo`, registers its pages and commands, and calls
`finalize()`.

Pages are ordinary QWidgets. The shell calls these optional hooks when a page has them:

    refresh()                 the page became visible
    on_theme_changed(theme)   redraw anything the stylesheet cannot reach (plots)
    on_open_file()            Ctrl+O
    on_export()               Ctrl+E
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from . import theme as T
from .history import History
from .widgets import CommandPalette, ToastHost

__all__ = ["AppInfo", "AppShell", "claim_taskbar_identity", "load_icon"]


@dataclass
class AppInfo:
    """Identity of one application: its name, author, lab and assets."""
    name: str
    version: str
    app_id: str                                     # Windows AppUserModelID, e.g. "EML.Supercap.1"
    short_name: str = ""
    tagline: str = ""
    description: str = ""
    author: str = "Ezzeldien Yousef"
    email: str = ""
    lab: str = ""
    lab_full: str = ""
    department: str = ""
    icon_path: str | Path | None = None
    logo_path: str | Path | None = None
    accent: str | None = None
    sources: list[str] = field(default_factory=list)
    organisation: str = "EML"

    @property
    def rail_name(self) -> str:
        return self.short_name or self.name


def claim_taskbar_identity(app_id: str) -> None:
    """Make Windows group the window under its own taskbar icon, not python.exe's.

    Must run before the first window is shown.
    """
    if sys.platform != "win32" or not app_id:
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:                                   # noqa: BLE001 - cosmetic only
        pass


def load_icon(path: str | Path | None) -> QIcon:
    if path and Path(path).is_file():
        icon = QIcon(str(path))
        if not icon.isNull():
            return icon
    return QIcon()


class _PageSlot(QWidget):
    """Holds a page's place in the stack until the page is first shown, then builds it."""

    def __init__(self, factory: Callable[[], QWidget], heading: str, subtitle: str, framed: bool):
        super().__init__()
        self._factory = factory
        self._heading = heading
        self._subtitle = subtitle
        self._framed = framed
        self.page: QWidget | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._build_pending = False

    @property
    def is_built(self) -> bool:
        return self.page is not None

    def ensure_built(self) -> QWidget:
        if self.page is None:
            self._build_now()
        return self.page

    def request_build(self) -> None:
        """Build one event-loop tick later, off the click's call stack.

        Building a heavy page synchronously inside the click handler blocks long enough
        for Windows to decide the window has stopped responding and to ghost it. Deferring
        by a single tick lets the click return first, at no visible cost.
        """
        if self.page is not None or self._build_pending:
            return
        self._build_pending = True
        QTimer.singleShot(0, self._build_now)

    def _build_now(self) -> None:
        self._build_pending = False
        if self.page is not None:
            return
        page = self._factory()
        if self._framed:
            frame = QWidget()
            outer = QVBoxLayout(frame)
            outer.setContentsMargins(26, 20, 26, 16)
            outer.setSpacing(12)
            if self._heading:
                title = QLabel(self._heading)
                title.setObjectName("PageTitle")
                outer.addWidget(title)
            if self._subtitle:
                sub = QLabel(self._subtitle)
                sub.setObjectName("PageSubtitle")
                sub.setWordWrap(True)
                outer.addWidget(sub)
            outer.addWidget(page, 1)
            self._layout.addWidget(frame)
        else:
            self._layout.addWidget(page)
        self.page = page
        hook = getattr(page, "on_theme_changed", None)
        shell = self.window()
        if callable(hook) and isinstance(shell, AppShell):
            hook(shell.theme)


@dataclass
class _PageEntry:
    key: str
    title: str
    glyph: str
    section: str
    slot: _PageSlot


class AppShell(QMainWindow):
    theme_changed = Signal(str)
    page_changed = Signal(str)

    def __init__(self, info: AppInfo, history: History | None = None):
        super().__init__()
        self.info = info
        self.history = history
        self.settings = QSettings(info.organisation, info.app_id or info.name)
        self._pages: dict[str, _PageEntry] = {}
        self._order: list[str] = []
        self._commands: list[tuple[str, str, Callable[[], None]]] = []
        self._close_hooks: list[Callable[[], bool | None]] = []
        self._menus: dict[str, object] = {}
        self._finalized = False
        self._theme = str(self.settings.value("theme", "light"))
        if self._theme not in ("light", "dark"):
            self._theme = "light"

        self.setWindowTitle(info.name)
        self.setWindowIcon(load_icon(info.icon_path))
        self.setMinimumSize(1100, 700)

        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self._rail = QFrame()
        self._rail.setObjectName("NavRail")
        self._rail.setFixedWidth(224)
        self._rail_layout = QVBoxLayout(self._rail)
        self._rail_layout.setContentsMargins(12, 16, 12, 14)
        self._rail_layout.setSpacing(2)
        row.addWidget(self._rail)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)
        right_layout.addWidget(self._build_status_bar())
        row.addWidget(right, 1)
        self.setCentralWidget(central)

        self.toasts = ToastHost(self)
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: dict[str, QPushButton] = {}
        if history is not None:
            history.changed.connect(self._update_history_buttons)
            history.restored.connect(lambda verb, label: self.notify(f"{verb}: {label}", "info"))

    # ------------------------------------------------------------------ building
    def add_page(self, key: str, title: str, factory: Callable[[], QWidget], *,
                 section: str = "", glyph: str = "•", heading: str | None = None,
                 subtitle: str = "", framed: bool = True, lazy: bool = True) -> None:
        if self._finalized:
            raise RuntimeError("add_page() must be called before finalize()")
        if key in self._pages:
            raise ValueError(f"duplicate page key {key!r}")
        slot = _PageSlot(factory, title if heading is None else heading, subtitle, framed)
        self._pages[key] = _PageEntry(key, title, glyph, section, slot)
        self._order.append(key)
        self.stack.addWidget(slot)
        if not lazy:
            slot.ensure_built()

    def add_command(self, name: str, group: str, fn: Callable[[], None]) -> None:
        self._commands.append((name, group, fn))

    def add_menu_action(self, menu: str, label: str, fn: Callable[[], None],
                        shortcut: str | QKeySequence | None = None) -> QAction:
        action = QAction(label, self)
        if shortcut:
            action.setShortcut(shortcut)
        action.triggered.connect(fn)
        self._menu(menu).addAction(action)
        return action

    def add_menu_separator(self, menu: str) -> None:
        self._menu(menu).addSeparator()

    def on_close(self, hook: Callable[[], bool | None]) -> None:
        """Run `hook` when the window closes. Returning False cancels the close."""
        self._close_hooks.append(hook)

    def finalize(self, start_page: str | None = None) -> None:
        """Build the rail, menus and shortcuts, apply the theme and show the first page."""
        self._build_rail()
        self._build_default_menus()
        self._build_shortcuts()
        self._finalized = True
        self.apply_theme(self._theme)
        remembered = str(self.settings.value("last_page", ""))
        key = start_page or (remembered if remembered in self._pages else self._order[0])
        self._pages[key].slot.ensure_built()
        self.go_to(key)
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1440, 900)

    def _menu(self, name: str):
        if name not in self._menus:
            self._menus[name] = self.menuBar().addMenu(name)
        return self._menus[name]

    def _build_rail(self) -> None:
        brand = QLabel(self.info.rail_name)
        brand.setObjectName("NavBrand")
        brand.setWordWrap(True)
        version = QLabel(f"v{self.info.version}")
        version.setObjectName("NavVersion")
        self._rail_layout.addWidget(brand)
        self._rail_layout.addWidget(version)
        self._rail_layout.addSpacing(8)

        if self.history is not None:
            history_row = QHBoxLayout()
            history_row.setSpacing(6)
            self.btn_undo = QPushButton("↶  Undo")
            self.btn_redo = QPushButton("↷  Redo")
            for btn, fn in ((self.btn_undo, self.undo), (self.btn_redo, self.redo)):
                btn.setObjectName("NavButton")
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(fn)
                history_row.addWidget(btn)
            self._rail_layout.addLayout(history_row)
            self._rail_layout.addSpacing(4)
            self._update_history_buttons()

        last_section = None
        for key in self._order:
            entry = self._pages[key]
            if entry.section and entry.section != last_section:
                label = QLabel(entry.section.upper())
                label.setObjectName("NavSection")
                self._rail_layout.addWidget(label)
                last_section = entry.section
            # "&" would otherwise become a keyboard mnemonic ("Sources & references" showed
            # as "Sources _references").
            btn = QPushButton(f"  {entry.glyph}   {entry.title.replace('&', '&&')}")
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, k=key: self.go_to(k))
            self._nav_group.addButton(btn)
            self._nav_buttons[key] = btn
            self._rail_layout.addWidget(btn)
        self._rail_layout.addStretch(1)
        hint = QLabel("Ctrl+K  ·  commands")
        hint.setObjectName("NavVersion")
        self._rail_layout.addWidget(hint)

    def _build_status_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(30)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)
        self.status_text = QLabel("Ready")
        self.status_text.setObjectName("StatusText")
        self.status_right = QLabel("")
        self.status_right.setObjectName("StatusText")
        layout.addWidget(self.status_text, 1)
        layout.addWidget(self.status_right)
        return bar

    def _build_default_menus(self) -> None:
        # Application menus registered before finalize() keep their position; these go last.
        if self.history is not None:
            self.action_undo = self.add_menu_action("&Edit", "&Undo", self.undo, QKeySequence.Undo)
            self.action_redo = self.add_menu_action("&Edit", "&Redo", self.redo, QKeySequence.Redo)
        for key in self._order:
            entry = self._pages[key]
            self.add_menu_action("&View", entry.title.replace("&", "&&"), lambda k=key: self.go_to(k))
        self.add_menu_separator("&View")
        self.add_menu_action("&View", "Toggle light / dark theme", self.toggle_theme, "Ctrl+T")
        self.add_menu_action("&View", "Command palette…", self.show_palette, "Ctrl+K")

        for key in self._order:
            entry = self._pages[key]
            self.add_command(f"Go to {entry.title}", entry.section or "Navigate",
                             lambda k=key: self.go_to(k))
        self.add_command("Toggle light / dark theme", "View", self.toggle_theme)
        if self.history is not None:
            self.add_command("Undo last action", "Edit", self.undo)
            self.add_command("Redo", "Edit", self.redo)

    def _build_shortcuts(self) -> None:
        """Window-wide shortcuts, skipping any key a menu action already owns.

        Qt treats two bindings of the same key as ambiguous and fires neither — so a
        redundant Ctrl+Y next to the Redo action (which is Ctrl+Y on Windows) would
        silently disable redo from the keyboard. Menu actions always win.
        """
        extras = [("Ctrl+P", self.show_palette),
                  ("Ctrl+Y", self.redo if self.history is not None else None),
                  ("Ctrl+O", lambda: self._call_page_hook("on_open_file")),
                  ("Ctrl+E", lambda: self._call_page_hook("on_export"))]
        extras += [(f"Ctrl+{i}", lambda k=key: self.go_to(k)) for i, key in enumerate(self._order[:9], start=1)]
        taken = self.bound_sequences()
        self._shortcuts: list[QShortcut] = []
        for text, fn in extras:
            if fn is None:
                continue
            sequence = QKeySequence(text).toString()
            if sequence in taken:
                continue
            self._shortcuts.append(QShortcut(QKeySequence(text), self, fn))
            taken.add(sequence)

    def bound_sequences(self) -> set[str]:
        """Every key sequence currently bound by a menu action or a shortcut."""
        taken: set[str] = set()
        for action in self.findChildren(QAction):
            for seq in action.shortcuts():
                if not seq.isEmpty():
                    taken.add(seq.toString())
        for shortcut in getattr(self, "_shortcuts", []):
            taken.add(shortcut.key().toString())
        return taken

    def shortcut_conflicts(self) -> list[str]:
        """Key sequences bound more than once — each one is dead in Qt. Should be empty."""
        seen: dict[str, int] = {}
        for action in self.findChildren(QAction):
            for seq in action.shortcuts():
                if not seq.isEmpty():
                    seen[seq.toString()] = seen.get(seq.toString(), 0) + 1
        for shortcut in getattr(self, "_shortcuts", []):
            key = shortcut.key().toString()
            seen[key] = seen.get(key, 0) + 1
        return sorted(k for k, n in seen.items() if n > 1)

    # ------------------------------------------------------------------ navigation
    def go_to(self, key: str) -> None:
        entry = self._pages.get(key)
        if entry is None:
            return
        self.stack.setCurrentWidget(entry.slot)
        button = self._nav_buttons.get(key)
        if button is not None:
            button.setChecked(True)
        if entry.slot.is_built:
            refresh = getattr(entry.slot.page, "refresh", None)
            if callable(refresh):
                refresh()
        else:
            entry.slot.request_build()
        self.settings.setValue("last_page", key)
        self.page_changed.emit(key)

    def page(self, key: str) -> QWidget:
        """The page widget for `key`, built now if it has not been shown yet."""
        return self._pages[key].slot.ensure_built()

    def is_page_built(self, key: str) -> bool:
        return self._pages[key].slot.is_built

    @property
    def page_keys(self) -> list[str]:
        return list(self._order)

    @property
    def current_key(self) -> str:
        widget = self.stack.currentWidget()
        return next((k for k, e in self._pages.items() if e.slot is widget), "")

    def current_page(self) -> QWidget | None:
        key = self.current_key
        return self._pages[key].slot.page if key else None

    def _call_page_hook(self, name: str) -> None:
        page = self.current_page()
        hook = getattr(page, name, None) if page is not None else None
        if callable(hook):
            hook()

    # ------------------------------------------------------------------ theme
    @property
    def theme(self) -> str:
        return self._theme

    def apply_theme(self, theme: str) -> None:
        self._theme = theme if theme in ("light", "dark") else "light"
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(T.stylesheet(self._theme, self.info.accent) + self.extra_stylesheet(self._theme))
        self.settings.setValue("theme", self._theme)
        for entry in self._pages.values():
            if entry.slot.is_built:
                hook = getattr(entry.slot.page, "on_theme_changed", None)
                if callable(hook):
                    hook(self._theme)
        self.theme_changed.emit(self._theme)

    def extra_stylesheet(self, theme: str) -> str:
        """Application-specific rules appended to the shared stylesheet (override)."""
        return ""

    def toggle_theme(self) -> None:
        self.apply_theme("dark" if self._theme == "light" else "light")

    # ------------------------------------------------------------------ feedback
    def notify(self, message: str, level: str = "info") -> None:
        """Status bar plus a toast. level: info | success | warning | error."""
        self.status_text.setText(message)
        self.toasts.show_message(message, level)

    def set_status(self, message: str, right: str | None = None) -> None:
        self.status_text.setText(message)
        if right is not None:
            self.status_right.setText(right)

    def set_busy(self, busy: bool, message: str = "") -> None:
        if busy and message:
            self.status_text.setText(message)
        if busy:
            QApplication.setOverrideCursor(Qt.BusyCursor)
        else:
            while QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()

    # ------------------------------------------------------------------ history
    def undo(self) -> None:
        if self.history is not None and not self.history.undo():
            self.notify("Nothing to undo.", "info")

    def redo(self) -> None:
        if self.history is not None and not self.history.redo():
            self.notify("Nothing to redo.", "info")

    def _update_history_buttons(self) -> None:
        if self.history is None or not hasattr(self, "btn_undo"):
            return
        can_undo, can_redo = self.history.can_undo(), self.history.can_redo()
        self.btn_undo.setEnabled(can_undo)
        self.btn_redo.setEnabled(can_redo)
        self.btn_undo.setToolTip(f"Undo {self.history.undo_label()}   (Ctrl+Z)" if can_undo else "Nothing to undo")
        self.btn_redo.setToolTip(f"Redo {self.history.redo_label()}   (Ctrl+Y)" if can_redo else "Nothing to redo")
        for action_name, enabled, label, verb in (
                ("action_undo", can_undo, self.history.undo_label(), "Undo"),
                ("action_redo", can_redo, self.history.redo_label(), "Redo")):
            action = getattr(self, action_name, None)
            if action is not None:
                action.setEnabled(enabled)
                action.setText(f"&{verb} {label}" if enabled else f"&{verb}")

    # ------------------------------------------------------------------ palette
    def show_palette(self) -> None:
        palette = CommandPalette(self._commands, self)
        palette.show_centred()

    # ------------------------------------------------------------------ lifecycle
    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        if hasattr(self, "toasts"):
            self.toasts._reposition()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        for hook in self._close_hooks:
            try:
                if hook() is False:
                    event.ignore()
                    return
            except Exception:                           # noqa: BLE001 - never trap the user
                pass
        self.settings.setValue("geometry", self.saveGeometry())
        super().closeEvent(event)


def app_pixmap(info: AppInfo, size: int = 64) -> QPixmap:
    for path in (info.logo_path, info.icon_path):
        if path and Path(path).is_file():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return load_icon(info.icon_path).pixmap(QSize(size, size))
