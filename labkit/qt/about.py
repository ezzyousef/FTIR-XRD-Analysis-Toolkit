"""The About page: who made the application, for which lab, and what it runs on."""
from __future__ import annotations

import platform
import sys
from typing import Sequence

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..origin import origin_available
from . import theme as T
from .shell import AppInfo, app_pixmap
from .widgets import Card, HLine, MetricTile, scrollable

__all__ = ["AboutPage"]


class AboutPage(QWidget):
    def __init__(self, info: AppInfo, tiles: Sequence[tuple[str, str]] = (),
                 notify=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.info = info
        self._notify = notify
        self._links: list[tuple[QLabel, str, str]] = []

        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)
        layout.addWidget(self._identity())
        layout.addWidget(self._author())
        if tiles:
            layout.addWidget(self._tiles(tiles))
        if info.sources:
            layout.addWidget(self._sources())
        layout.addWidget(self._environment())
        layout.addStretch(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scrollable(host))
        self.on_theme_changed("light")

    def _identity(self) -> Card:
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(16)
        mark = QLabel()
        pixmap = app_pixmap(self.info, 240)
        if not pixmap.isNull():                         # fit a wide lab logo without squashing it
            pixmap = pixmap.scaled(170, 84, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        mark.setPixmap(pixmap)
        mark.setFixedSize(180, 92)
        mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet("background: transparent;")
        row.addWidget(mark, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(3)
        name = QLabel(self.info.name)
        name.setObjectName("PageTitle")
        name.setWordWrap(True)
        version = QLabel(f"Version {self.info.version}")
        version.setObjectName("Hint")
        text.addWidget(name)
        text.addWidget(version)
        if self.info.description or self.info.tagline:
            blurb = QLabel(self.info.description or self.info.tagline)
            blurb.setWordWrap(True)
            text.addSpacing(6)
            text.addWidget(blurb)
        row.addLayout(text, 1)
        card.body.addLayout(row)
        return card

    def _author(self) -> Card:
        card = Card("Made by")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(7)
        rows = [("Author", self.info.author, None)]
        if self.info.email:
            rows.append(("Email", self.info.email, f"mailto:{self.info.email}"))
        if self.info.lab:
            lab = f"{self.info.lab} — {self.info.lab_full}" if self.info.lab_full else self.info.lab
            rows.append(("Laboratory", lab, None))
        if self.info.department:
            rows.append(("Department", self.info.department, None))
        for r, (label, value, link) in enumerate(rows):
            key = QLabel(label)
            key.setObjectName("TileLabel")
            key.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(key, r, 0)
            field = QLabel(value)
            field.setWordWrap(True)
            field.setTextInteractionFlags(Qt.TextBrowserInteraction)
            if link:
                field.setOpenExternalLinks(False)
                field.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
                self._links.append((field, link, value))
            grid.addWidget(field, r, 1)
        grid.setColumnStretch(1, 1)
        card.body.addLayout(grid)
        buttons = QHBoxLayout()
        if self.info.email:
            email = QPushButton("Send an email")
            email.clicked.connect(lambda: QDesktopServices.openUrl(
                QUrl(f"mailto:{self.info.email}?subject={self.info.name}")))
            buttons.addWidget(email)
        copy = QPushButton("Copy contact details")
        copy.clicked.connect(self._copy_contact)
        buttons.addWidget(copy)
        buttons.addStretch(1)
        card.body.addWidget(HLine())
        card.body.addLayout(buttons)
        return card

    def _tiles(self, tiles) -> Card:
        card = Card("What is inside")
        grid = QGridLayout()
        grid.setSpacing(10)
        for i, (label, value) in enumerate(tiles):
            grid.addWidget(MetricTile(label, value), i // 4, i % 4)
        card.body.addLayout(grid)
        return card

    def _sources(self) -> Card:
        card = Card("Methods and sources")
        for citation in self.info.sources:
            label = QLabel("•  " + citation)
            label.setWordWrap(True)
            label.setTextFormat(Qt.RichText)
            card.body.addWidget(label)
        return card

    def _environment(self) -> Card:
        card = Card("Running on")
        parts = [f"Python {sys.version.split()[0]} on {platform.system()} {platform.release()}"]
        for module, label in (("PySide6", "PySide6"), ("numpy", "NumPy"), ("scipy", "SciPy"),
                              ("matplotlib", "matplotlib")):
            try:
                parts.append(f"{label} {__import__(module).__version__}")
            except Exception:                           # noqa: BLE001
                continue
        _ok, why = origin_available()
        text = QLabel("   ·   ".join(parts) + f"\n\nOriginLab: {why}")
        text.setObjectName("Hint")
        text.setWordWrap(True)
        card.body.addWidget(text)
        return card

    def _copy_contact(self) -> None:
        lines = [self.info.author, self.info.email]
        if self.info.lab:
            lines.append(f"{self.info.lab} — {self.info.lab_full}" if self.info.lab_full else self.info.lab)
        lines.append(self.info.department)
        QApplication.clipboard().setText("\n".join(line for line in lines if line))
        if callable(self._notify):
            self._notify("Contact details copied to the clipboard", "success")

    def on_theme_changed(self, theme: str) -> None:
        # Qt's default link blue is unreadable on the dark background.
        accent = T.colours(theme, self.info.accent)["accent"]
        for field, href, text in self._links:
            field.setText(f'<a href="{href}" style="color:{accent};text-decoration:none;">{text}</a>')
