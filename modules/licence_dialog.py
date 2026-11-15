"""
licence_dialog.py
Help › Licence…: the edition and licence status, this computer's device id, and the two
offline steps of activation -- copy an activation request, install a licence file.
No network access: the request is copied to the clipboard for the user to send themselves.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout)

import licensing
from labkit import licence
from labkit.qt.widgets import HLine, SectionLabel

LICENCE_FILTER = "Licence files (*.json *.lic *.txt);;All files (*)"


def get_licence_path(parent) -> str:
    """Ask for a licence file (a module function so tests can replace it)."""
    path, _ = QFileDialog.getOpenFileName(parent, "Install licence file", "", LICENCE_FILTER)
    return path


class LicenceDialog(QDialog):
    def __init__(self, parent=None, licence_store: licence.LicenceStore | None = None):
        super().__init__(parent)
        self.setWindowTitle("Licence")
        self.setModal(True)
        self._store = licence_store or licensing.store()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        self.edition_label = SectionLabel("")
        self.edition_label.setAccessibleName("Edition")
        layout.addWidget(self.edition_label)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setMaximumWidth(480)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status_label.setAccessibleName("Licence status")
        layout.addWidget(self.status_label)
        self.warnings_label = QLabel("")
        self.warnings_label.setObjectName("WarnText")
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setMaximumWidth(480)
        self.warnings_label.setAccessibleName("Licence warnings")
        layout.addWidget(self.warnings_label)
        layout.addWidget(HLine())

        form = QFormLayout()
        self.device_edit = QLineEdit(licensing.device_id())
        self.device_edit.setReadOnly(True)
        self.device_edit.setMinimumWidth(220)
        self.device_edit.setAccessibleName("This computer's device id")
        device_caption = QLabel("This computer's &device id:")
        device_caption.setBuddy(self.device_edit)
        form.addRow(device_caption, self.device_edit)
        layout.addLayout(form)

        hint = QLabel("To activate, copy the activation request and send it to the publisher; "
                      "then install the licence file you receive. Nothing is sent from this application.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        hint.setMaximumWidth(480)
        layout.addWidget(hint)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.setMaximumWidth(480)
        self.result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.result_label.setAccessibleName("Result")
        self.result_label.hide()
        layout.addWidget(self.result_label)

        buttons = QHBoxLayout()
        self.copy_button = QPushButton("&Copy activation request")
        self.copy_button.clicked.connect(self.copy_request)
        self.install_button = QPushButton("&Install licence file…")
        self.install_button.setObjectName("Primary")
        self.install_button.clicked.connect(self.install_file)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.accept)
        for b in (self.copy_button, self.install_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.close_button.setDefault(True)
        self.refresh()

    def refresh(self) -> None:
        current = licensing.status(self._store)
        edition, sentence = licensing.describe(current)
        self.edition_label.setText(edition)
        self.status_label.setText(sentence)
        self.warnings_label.setText("\n".join(current.warnings))
        self.warnings_label.setVisible(bool(current.warnings))

    def _show_result(self, text: str, ok: bool) -> None:
        self.result_label.setObjectName("GoodText" if ok else "BadText")
        self.result_label.style().unpolish(self.result_label)
        self.result_label.style().polish(self.result_label)
        self.result_label.setText(text)
        self.result_label.show()

    def copy_request(self) -> None:
        request = licensing.activation_request()
        QGuiApplication.clipboard().setText(request)
        self._show_result(f"Activation request copied to the clipboard:\n{request}", True)

    def install_file(self) -> None:
        path = get_licence_path(self)
        if not path:
            return
        self.install_path(path)

    def install_path(self, path: str) -> bool:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            self._show_result("That file could not be read.", False)
            return False
        try:
            licensing.install(text, self._store)
        except licence.LicenceError as exc:
            self._show_result(str(exc), False)
            return False
        self.refresh()
        self._show_result("Licence installed.", True)
        return True
