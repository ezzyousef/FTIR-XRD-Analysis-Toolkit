"""Reusable interface pieces shared by every lab application.

Cards, metric tiles, toasts, a drop zone, a FigureSpec plot canvas, rendered formulas,
result tables and the Ctrl+K command palette. Pages describe *what* they show; these
describe how it looks, so every application looks the same.
"""
from __future__ import annotations

import math
from typing import Callable, Iterable, Sequence

from PySide6.QtCore import (QEasingCurve, QEvent, QPoint, QPropertyAnimation, QSize, Qt,
                            QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
                               QDoubleSpinBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QSizePolicy, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..figure import FigureSpec, format_number as format_value
from . import theme as T

__all__ = [
    "Card", "MetricTile", "Toast", "ToastHost", "DropZone", "PlotCanvas", "CommandPalette",
    "SectionLabel", "HLine", "Pill", "ResultTable", "FieldRow", "icon_label", "scrollable",
    "OptionEditor", "EmptyState", "BusyBar", "FormulaLabel",
]


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def HLine() -> QFrame:
    line = QFrame()
    line.setObjectName("HLine")
    line.setFixedHeight(1)
    return line


def SectionLabel(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SectionTitle")
    return label


def Pill(text: str, kind: str = "good") -> QLabel:
    label = QLabel(text)
    label.setObjectName({"good": "PillGood", "warn": "PillWarn", "bad": "PillBad"}.get(kind, "PillGood"))
    label.setAlignment(Qt.AlignCenter)
    return label


def icon_label(glyph: str, size: int = 15) -> QLabel:
    """A text glyph used as an icon — no image assets to ship or scale."""
    label = QLabel(glyph)
    font = label.font()
    font.setPointSizeF(size)
    label.setFont(font)
    label.setAlignment(Qt.AlignCenter)
    label.setStyleSheet("background: transparent;")
    return label


def scrollable(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    area.setFrameShape(QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    return area


# ---------------------------------------------------------------------------
class Card(QFrame):
    """A titled panel. `body` is the layout callers add their content to."""

    def __init__(self, title: str = "", subtitle: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(10)

        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        self._title = QLabel(title)
        self._title.setObjectName("SectionTitle")
        self.header.addWidget(self._title)
        self.header.addStretch(1)
        if title:
            outer.addLayout(self.header)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("Hint")
            sub.setWordWrap(True)
            outer.addWidget(sub)
            self._subtitle = sub
        else:
            self._subtitle = None

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(9)
        outer.addLayout(self.body, 1)

    def set_title(self, text: str) -> None:
        self._title.setText(text)

    def set_subtitle(self, text: str) -> None:
        if self._subtitle is not None:
            self._subtitle.setText(text)

    def add_header_widget(self, widget: QWidget) -> None:
        self.header.addWidget(widget)


class MetricTile(QFrame):
    """One headline number."""

    def __init__(self, label: str, value: str = "—", unit: str = "",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Tile")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 11, 13, 11)
        layout.setSpacing(2)
        self._label = QLabel(label.upper())
        self._label.setObjectName("TileLabel")
        self._label.setWordWrap(True)
        row = QHBoxLayout()
        row.setSpacing(5)
        self._value = QLabel(value)
        self._value.setObjectName("TileValue")
        self._unit = QLabel(unit)
        self._unit.setObjectName("TileUnit")
        row.addWidget(self._value)
        row.addWidget(self._unit, 0, Qt.AlignBottom)
        row.addStretch(1)
        layout.addWidget(self._label)
        layout.addLayout(row)

    def set_value(self, value: str, unit: str | None = None) -> None:
        self._value.setText(value)
        if unit is not None:
            self._unit.setText(unit)


class EmptyState(QWidget):
    """What a page shows before there is anything to show."""

    action = Signal()

    def __init__(self, glyph: str, title: str, hint: str, button: str = "",
                 parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(9)
        layout.addWidget(icon_label(glyph, 30), 0, Qt.AlignCenter)
        head = QLabel(title)
        head.setObjectName("SectionTitle")
        head.setAlignment(Qt.AlignCenter)
        note = QLabel(hint)
        note.setObjectName("Hint")
        note.setAlignment(Qt.AlignCenter)
        note.setWordWrap(True)
        note.setMaximumWidth(460)
        layout.addWidget(head)
        layout.addWidget(note, 0, Qt.AlignCenter)
        if button:
            btn = QPushButton(button)
            btn.setObjectName("Primary")
            btn.clicked.connect(self.action.emit)
            layout.addWidget(btn, 0, Qt.AlignCenter)


class BusyBar(QWidget):
    """A thin indeterminate bar that appears only while work is running."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        from PySide6.QtWidgets import QProgressBar
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setFixedHeight(4)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)
        self.setVisible(False)

    def start(self) -> None:
        self.setVisible(True)

    def stop(self) -> None:
        self.setVisible(False)


# ---------------------------------------------------------------------------
class Toast(QFrame):
    """A short message that fades in over the window and leaves on its own."""

    def __init__(self, message: str, level: str = "info", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(f"Toast{level.capitalize()}")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(9)
        glyph = {"info": "ℹ", "success": "✓", "warning": "⚠", "error": "✕"}.get(level, "ℹ")
        layout.addWidget(icon_label(glyph, 12))
        text = QLabel(message)
        text.setObjectName("ToastText")
        text.setWordWrap(True)
        text.setMaximumWidth(420)
        layout.addWidget(text, 1)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(26)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(0, 0, 0, 70))
        self.setGraphicsEffect(shadow)


class ToastHost(QWidget):
    """Stacks toasts in the corner of the window and expires them.

    Toasts are placed explicitly, each at the height its text needs for its width. A layout
    sized from sizeHint ignores word-wrapped text, so a two-line toast was given one line's
    height and the stack overlapped on a real window manager.
    """

    SPACING = 8
    MAX_WIDTH = 460

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._toasts: list[Toast] = []
        self._repositioning = False

    def show_message(self, message: str, level: str = "info", msec: int = 4200) -> None:
        toast = Toast(message, level, self)
        self._toasts.append(toast)
        toast.show()

        fade = QPropertyAnimation(toast, b"windowOpacity", toast)
        fade.setDuration(160)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.start(QPropertyAnimation.DeleteWhenStopped)

        while len(self._toasts) > 4:
            self._dismiss(self._toasts[0])
        QTimer.singleShot(msec, lambda: self._dismiss(toast))
        self._reposition()

    def _dismiss(self, toast: Toast) -> None:
        if toast not in self._toasts:
            return
        self._toasts.remove(toast)
        toast.hide()
        toast.deleteLater()
        self._reposition()

    def _reposition(self) -> None:
        """Park the stack in the bottom-right corner of the window.

        `setGeometry` fires our own `resizeEvent`, so without the guard this recurses
        until the stack overflows — which only shows up under a real window manager.
        """
        parent = self.parentWidget()
        if parent is None or self._repositioning:
            return
        self._repositioning = True
        try:
            limit = min(self.MAX_WIDTH, max(parent.width() - 52, 200))
            sizes = []
            for toast in self._toasts:
                w = min(max(toast.sizeHint().width(), 220), limit)
                h = toast.heightForWidth(w) if toast.hasHeightForWidth() else toast.sizeHint().height()
                sizes.append((w, max(h, toast.minimumSizeHint().height(), 1)))
            width = max((w for w, _h in sizes), default=320)
            height = max(sum(h for _w, h in sizes) + self.SPACING * max(len(sizes) - 1, 0), 1)
            target = (parent.width() - width - 26, parent.height() - height - 46, width, height)
            if (self.x(), self.y(), self.width(), self.height()) != target:
                self.setGeometry(*target)
            y = 0
            for toast, (w, h) in zip(self._toasts, sizes):      # oldest at the top
                toast.setGeometry(width - w, y, w, h)
                y += h + self.SPACING
            self.raise_()
        finally:
            self._repositioning = False

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._reposition()


# ---------------------------------------------------------------------------
class DropZone(QFrame):
    """Drag files here, or click to browse."""

    files_dropped = Signal(list)
    clicked = Signal()

    def __init__(self, title: str = "Drop data files here",
                 hint: str = "CSV · TSV · TXT · DAT · XLSX · JSON · NPZ — or click to browse",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setProperty("hot", "false")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(128)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(5)
        layout.addWidget(icon_label("⬇", 22), 0, Qt.AlignCenter)
        head = QLabel(title)
        head.setObjectName("DropTitle")
        head.setAlignment(Qt.AlignCenter)
        note = QLabel(hint)
        note.setObjectName("DropHint")
        note.setAlignment(Qt.AlignCenter)
        note.setWordWrap(True)
        layout.addWidget(head)
        layout.addWidget(note)

    def _set_hot(self, hot: bool) -> None:
        self.setProperty("hot", "true" if hot else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_hot(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_hot(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_hot(False)
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


# ---------------------------------------------------------------------------
class PlotCanvas(QWidget):
    """A matplotlib figure embedded in Qt, with a toolbar and theme support."""

    def __init__(self, parent: QWidget | None = None, toolbar: bool = True):
        super().__init__(parent)
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
        from matplotlib.figure import Figure

        self._figure = Figure(figsize=(7.2, 4.6), dpi=100)
        self.canvas = FigureCanvasQTAgg(self._figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        if toolbar:
            self.toolbar = NavigationToolbar2QT(self.canvas, self)
            self.toolbar.setIconSize(QSize(17, 17))
            layout.addWidget(self.toolbar)
        else:
            self.toolbar = None
        layout.addWidget(self.canvas, 1)
        self._spec: FigureSpec | None = None
        self._theme = "light"
        self._metrics = None

    @property
    def figure(self):
        return self._figure

    @property
    def spec(self) -> FigureSpec | None:
        return self._spec

    def show_figure(self, spec: FigureSpec, theme: str = "light", metrics=None,
                    palette_name: str | None = None, legend: bool = True) -> None:
        """Render a FigureSpec. `metrics` is (name, value, unit) triples for a results box."""
        from ..figure import render

        self._spec, self._theme, self._metrics = spec, theme, metrics
        render(spec, theme=theme, size="screen", figure=self._figure, metrics=metrics,
               palette_name=palette_name, legend=legend)
        self._tint_toolbar(theme)
        self.canvas.draw_idle()

    def set_theme(self, theme: str) -> None:
        """Re-draw the current figure in another theme."""
        self._theme = theme
        self._tint_toolbar(theme)
        if self._spec is not None:
            self.show_figure(self._spec, theme, self._metrics)

    def _tint_toolbar(self, theme: str) -> None:
        """Recolour the matplotlib toolbar icons for the theme.

        matplotlib tints its icons once, from the toolbar's palette, when the toolbar is
        built. A stylesheet never changes that palette, so on a dark theme the icons stay
        black on black. Setting the palette and regenerating the icons fixes it.
        """
        bar = self.toolbar
        if bar is None or getattr(self, "_tinted_for", None) == theme:
            return
        from PySide6.QtGui import QColor, QPalette
        tokens = T.colours(theme)
        palette = bar.palette()
        for role, key in ((QPalette.Window, "bg"), (QPalette.Button, "bg"),
                          (QPalette.WindowText, "fg"), (QPalette.ButtonText, "fg")):
            palette.setColor(role, QColor(tokens[key]))
        bar.setPalette(palette)
        actions = getattr(bar, "_actions", {})
        for text, _tip, image, callback in getattr(bar, "toolitems", ()):
            if text and callback in actions and image:
                try:
                    actions[callback].setIcon(bar._icon(image + ".png"))
                except Exception:                           # noqa: BLE001 - cosmetic
                    pass
        self._tinted_for = theme

    def show_message(self, text: str, theme: str = "light") -> None:
        from ..style import THEMES
        t = THEMES.get(theme, THEMES["light"])
        self._spec = None
        self._figure.clear()
        self._figure.patch.set_facecolor(t.background)
        self._figure.text(0.5, 0.5, text, ha="center", va="center",
                          color=t.muted, fontsize=12)
        self.canvas.draw_idle()

    def save(self, path: str, dpi="print") -> None:
        from ..figure import save
        save(self._figure, path, dpi=dpi)


# ---------------------------------------------------------------------------
class FormulaLabel(QLabel):
    """Renders a LaTeX formula as an image using matplotlib's mathtext.

    Falls back to the raw source if mathtext cannot parse it, which is better than an
    empty box — the reader can still see what the equation is meant to be.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setStyleSheet("background: transparent;")
        self._source = ""
        self._theme = "light"

    def set_formula(self, latex: str, theme: str = "light") -> None:
        self._source, self._theme = latex or "", theme
        self._render()

    def _render(self) -> None:
        latex = (self._source or "").strip()
        if not latex:
            self.setPixmap(QPixmap())
            self.setText("")
            return
        pixmap = _render_mathtext(latex, self._theme)
        if pixmap is None:
            self.setPixmap(QPixmap())
            self.setText(latex)
            self.setObjectName("Mono")
        else:
            self.setText("")
            self.setPixmap(pixmap)
        self.setToolTip(latex)


_FORMULA_CACHE: dict[tuple[str, str], QPixmap | None] = {}


def _render_mathtext(latex: str, theme: str) -> QPixmap | None:
    key = (latex, theme)
    if key in _FORMULA_CACHE:
        return _FORMULA_CACHE[key]
    pixmap: QPixmap | None = None
    try:
        import io
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        colour = T.colours(theme)["fg"]
        figure = Figure(figsize=(0.1, 0.1), dpi=180)
        figure.patch.set_alpha(0.0)
        FigureCanvasAgg(figure)
        text = figure.text(0, 0, f"${latex.strip('$')}$", fontsize=13, color=colour)
        figure.canvas.draw()
        bbox = text.get_window_extent(figure.canvas.get_renderer())
        figure.set_size_inches(bbox.width / 180 + 0.12, bbox.height / 180 + 0.12)
        buffer = io.BytesIO()
        figure.savefig(buffer, format="png", transparent=True, bbox_inches="tight",
                       pad_inches=0.02, dpi=180)
        buffer.seek(0)
        image = QPixmap()
        if image.loadFromData(buffer.read(), "PNG") and not image.isNull():
            # drawn at 180 dpi, shown at logical size, so it stays crisp on a HiDPI screen
            image.setDevicePixelRatio(180 / 96)
            pixmap = image
    except Exception:                                          # noqa: BLE001 - fall back to text
        pixmap = None
    _FORMULA_CACHE[key] = pixmap
    return pixmap


class ResultTable(QTableWidget):
    """A read-only metrics table that sizes itself sensibly."""

    def __init__(self, headers: Sequence[str], parent: QWidget | None = None):
        super().__init__(0, len(headers), parent)
        self.setHorizontalHeaderLabels(list(headers))
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(29)
        self.setShowGrid(False)
        self.setWordWrap(False)
        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        header.setHighlightSections(False)
        for i in range(len(headers) - 1):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)

    def fill(self, rows: Iterable[Sequence]) -> None:
        rows = list(rows)
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                if isinstance(value, float):
                    text = format_value(value) if math.isfinite(value) else "n/a"
                else:
                    text = "" if value is None else str(value)
                item = QTableWidgetItem(text)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                item.setToolTip(text)
                self.setItem(r, c, item)


class FieldRow(QWidget):
    """A labelled input with an optional unit selector and help text."""

    changed = Signal()

    def __init__(self, label: str, widget: QWidget, unit_widget: QWidget | None = None,
                 help_text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(8)
        name = QLabel(label)
        name.setMinimumWidth(160)
        name.setWordWrap(True)
        top.addWidget(name, 3)
        top.addWidget(widget, 3)
        if unit_widget is not None:
            top.addWidget(unit_widget, 2)
        layout.addLayout(top)
        if help_text:
            hint = QLabel(help_text)
            hint.setObjectName("Hint")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        self.widget = widget
        self.unit_widget = unit_widget


class OptionEditor(QWidget):
    """Builds inputs for a measurement's options and reads them back."""

    changed = Signal()

    def __init__(self, options, parent: QWidget | None = None):
        super().__init__(parent)
        self._editors: dict[str, tuple[str, QWidget]] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for option in options:
            widget = self._make(option)
            layout.addWidget(FieldRow(option.label, widget, help_text=option.help))
        layout.addStretch(1)

    def _make(self, option) -> QWidget:
        kind = option.kind
        if kind == "bool":
            box = QCheckBox()
            box.setChecked(bool(option.default))
            box.toggled.connect(self.changed.emit)
            self._editors[option.key] = ("bool", box)
            return box
        if kind == "choice":
            combo = QComboBox()
            combo.addItems(list(option.choices))
            if option.default in option.choices:
                combo.setCurrentText(str(option.default))
            combo.currentTextChanged.connect(self.changed.emit)
            self._editors[option.key] = ("choice", combo)
            return combo
        if kind == "int":
            spin = QSpinBox()
            spin.setRange(int(option.minimum or 0), int(option.maximum or 10_000))
            spin.setValue(int(option.default or 0))
            spin.valueChanged.connect(self.changed.emit)
            self._editors[option.key] = ("int", spin)
            return spin
        if kind == "range":
            edit = QLineEdit(", ".join(f"{v:g}" for v in (option.default or ())))
            edit.setPlaceholderText("comma-separated values")
            edit.editingFinished.connect(self.changed.emit)
            self._editors[option.key] = ("range", edit)
            return edit
        edit = QLineEdit("" if option.default is None else f"{option.default:g}")
        edit.setPlaceholderText("leave blank to skip" if option.default is None else "")
        edit.editingFinished.connect(self.changed.emit)
        self._editors[option.key] = ("float", edit)
        return edit

    def values(self) -> dict:
        out: dict = {}
        for key, (kind, widget) in self._editors.items():
            if kind == "bool":
                out[key] = widget.isChecked()
            elif kind == "choice":
                out[key] = widget.currentText()
            elif kind == "int":
                out[key] = widget.value()
            elif kind == "range":
                parts = [p.strip() for p in widget.text().replace(";", ",").split(",")]
                values = []
                for p in parts:
                    try:
                        values.append(float(p))
                    except ValueError:
                        continue
                out[key] = tuple(values) if values else None
            else:
                text = widget.text().strip()
                if not text:
                    out[key] = None
                else:
                    try:
                        out[key] = float(text)
                    except ValueError:
                        out[key] = None
        return out


# ---------------------------------------------------------------------------
class CommandPalette(QDialog):
    """Ctrl+K: type a few letters, hit Enter. Every action in the app lives here."""

    def __init__(self, commands: Sequence[tuple[str, str, Callable[[], None]]],
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setObjectName("Palette")
        self.setModal(True)
        self._commands = list(commands)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(0)
        self.input = QLineEdit()
        self.input.setObjectName("PaletteInput")
        self.input.setPlaceholderText("Type a command…   (Esc to close)")
        layout.addWidget(self.input)
        self.list = QListWidget()
        self.list.setObjectName("PaletteList")
        self.list.setFrameShape(QFrame.NoFrame)
        layout.addWidget(self.list, 1)

        self.input.textChanged.connect(self._filter)
        self.input.returnPressed.connect(self._run_selected)
        self.list.itemActivated.connect(lambda _i: self._run_selected())
        self.input.installEventFilter(self)
        self.resize(560, 400)
        self._filter("")

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.input and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Down, Qt.Key_Up):
                row = self.list.currentRow() + (1 if event.key() == Qt.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(row, self.list.count() - 1)))
                return True
        return super().eventFilter(obj, event)

    def _filter(self, text: str) -> None:
        query = text.strip().lower()
        self.list.clear()
        for name, group, _fn in self._commands:
            haystack = f"{name} {group}".lower()
            if query and not all(part in haystack for part in query.split()):
                continue
            item = QListWidgetItem(f"{name}      ·  {group}")
            item.setData(Qt.UserRole, name)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _run_selected(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        name = item.data(Qt.UserRole)
        self.accept()
        for cmd_name, _group, fn in self._commands:
            if cmd_name == name:
                QTimer.singleShot(0, fn)
                return

    def show_centred(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            centre = parent.mapToGlobal(parent.rect().center())
            self.move(centre.x() - self.width() // 2, centre.y() - self.height() // 2 - 60)
        self.input.clear()
        self.input.setFocus()
        self.show()
