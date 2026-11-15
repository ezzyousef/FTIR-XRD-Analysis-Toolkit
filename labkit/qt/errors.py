"""One consistent way to tell the user that something failed.

    try:
        export(path)
    except Exception as exc:
        show_error(self, "The export could not be saved.", exc)

The dialog says what happened in a sentence, what the user can do about it, and keeps the
technical detail behind "Show details" (with the user's profile folder removed, so a
screenshot or a pasted report does not carry their account name).
"""
from __future__ import annotations

import errno
import re
import traceback

from PySide6.QtWidgets import QMessageBox, QWidget

# one or two backslashes: str(OSError) shows the file name in repr form, with doubled backslashes
_PROFILE = re.compile(r"""(?i)\b[A-Z]:\\{1,2}Users\\{1,2}(?!Public\\|Default\\)[^\\\s"']+""")
_HOME = re.compile(r"""(?<![\w.])/(?:home|Users)/(?!Shared/)[^/\s"']+""")


def redact(text: str) -> str:
    return _HOME.sub("~", _PROFILE.sub("%USERPROFILE%", text or ""))


def advice_for(exc: BaseException) -> str:
    """What the user can do, for the failures that have an obvious remedy. '' when there is none."""
    if isinstance(exc, PermissionError):
        return ("The file is open in another program or the folder is read-only. Close the file "
                "(for example in Excel or Origin), or choose another folder, and try again.")
    if isinstance(exc, FileNotFoundError):
        return "The file or folder no longer exists. Check that the drive is connected and choose it again."
    if isinstance(exc, IsADirectoryError):
        return "That is a folder, not a file. Choose a file name."
    if isinstance(exc, MemoryError):
        return "The computer ran out of memory. Close other programs or work with a smaller selection of the data."
    if isinstance(exc, UnicodeError):
        return "The file's text encoding could not be read. Save it as UTF-8 (or as CSV from Excel) and try again."
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return "The disk is full. Free some space or save to another drive."
    if isinstance(exc, TimeoutError):
        return "The operation took too long and was stopped. Check the connection to the instrument or the drive and try again."
    return ""


def details_for(exc: BaseException | None) -> str:
    if exc is None:
        return ""
    return redact("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip())


def error_box(parent: QWidget | None, summary: str, exc: BaseException | None = None, *, hint: str = "",
              title: str = "Something went wrong") -> QMessageBox:
    """Build the dialog without showing it (use show_error for the usual case)."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(summary)
    advice = hint or (advice_for(exc) if exc else "")
    reason = redact(str(exc)) if exc and str(exc) else ""
    box.setInformativeText("\n\n".join(x for x in (advice, reason) if x))
    details = details_for(exc)
    if details:
        box.setDetailedText(details)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.setDefaultButton(QMessageBox.StandardButton.Ok)
    box.setAccessibleName(title)
    box.setAccessibleDescription(". ".join(x for x in (summary, advice) if x))
    return box


def show_error(parent: QWidget | None, summary: str, exc: BaseException | None = None, *, hint: str = "",
               title: str = "Something went wrong") -> None:
    error_box(parent, summary, exc, hint=hint, title=title).exec()
