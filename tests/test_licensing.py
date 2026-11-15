"""Licensing (labkit.licence): enforcement off, test-key licences, the Licence dialog.

Licences here are signed with a throwaway Ed25519 key generated in the test; the module's
PUBLIC_KEYS is monkeypatched to trust it. The real private key is never used.
"""
import base64
import importlib
import secrets
import sys
from datetime import date
from pathlib import Path

import pytest

import licensing
from labkit import licence

LABKIT_REPO = Path(r"E:\Lab Apps\labkit")
TEST_KID = "test-key"


@pytest.fixture
def make_licence():
    """labkit_issuer.issuer.make_licence, imported without leaving sys.path changed."""
    if not (LABKIT_REPO / "labkit_issuer" / "issuer.py").is_file():
        pytest.skip("labkit repository (issuer tool) not available")
    saved = list(sys.path)
    sys.path.insert(0, str(LABKIT_REPO))
    try:
        issuer = importlib.import_module("labkit_issuer.issuer")
    finally:
        sys.path[:] = saved
    return issuer.make_licence


@pytest.fixture
def test_key(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    monkeypatch.setattr(licensing, "PUBLIC_KEYS", {TEST_KID: base64.b64encode(raw).decode()})
    return key


@pytest.fixture
def store(tmp_path):
    return licence.LicenceStore(licensing.PRODUCT, folder=tmp_path / "licence")


def _claims(product=licensing.PRODUCT, **extra):
    claims = {"product": product, "edition": "pro", "kind": "academic", "serial": "FXT-00001",
              "lid": secrets.token_hex(16), "issued": date.today().isoformat(),
              "name": "Test User", "device": licensing.device_id(), "binding": "device"}
    claims.update(extra)
    return claims


def test_constants():
    assert licensing.PRODUCT == "ftir-xrd-toolkit"
    assert licensing.ENFORCE is False
    assert licensing.FREE_FEATURES == frozenset({"*"})
    assert licensing.RELEASE_DATE == date(2026, 11, 14)


def test_no_licence_is_not_ok_but_everything_allowed(store):
    status = licensing.status(store)
    assert not status.ok
    assert status.reason == "No licence installed."
    assert status.can_save
    for feature in ("origin-export", "pdf-report", "peak-fitting", "anything"):
        assert licensing.allowed(feature)
        assert licensing.allowed(feature, status)
    edition, sentence = licensing.describe(status)
    assert edition == "Free edition" and "All features are currently available" in sentence


def test_test_key_licence_installs_and_verifies(make_licence, test_key, store):
    text = make_licence(test_key, TEST_KID, _claims())
    claims = licensing.install(text, store)
    assert claims["product"] == licensing.PRODUCT
    assert store.licence_path.is_file()
    status = licensing.status(store)
    assert status.ok, status.reason
    assert status.edition == "pro"
    assert licensing.allowed("anything", status)
    edition, sentence = licensing.describe(status)
    assert "Pro" in edition and "Test User" in sentence


def test_licence_for_another_product_is_refused(make_licence, test_key, store):
    text = make_licence(test_key, TEST_KID, _claims(product="supercap-suite"))
    with pytest.raises(licence.LicenceError, match="not this application"):
        licensing.install(text, store)
    assert not store.licence_path.exists()
    assert not licensing.status(store).ok


def test_real_keys_do_not_trust_a_test_licence(make_licence, store):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    text = make_licence(Ed25519PrivateKey.generate(), "labapps-2026", _claims())
    with pytest.raises(licence.LicenceError):
        licensing.install(text, store)


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dialog_shows_device_id(qapp, store):
    from licence_dialog import LicenceDialog
    dlg = LicenceDialog(licence_store=store)
    assert dlg.device_edit.text() == licensing.device_id()
    assert dlg.device_edit.isReadOnly()
    assert licence.DEVICE_RE.match(dlg.device_edit.text())
    assert dlg.edition_label.text() == "Free edition"
    assert "No licence installed." in dlg.status_label.text()
    dlg.copy_request()
    from PySide6.QtGui import QGuiApplication
    assert QGuiApplication.clipboard().text() == licensing.activation_request()
    dlg.close()


def test_dialog_installs_file_and_reports_errors(qapp, make_licence, test_key, store, tmp_path):
    from licence_dialog import LicenceDialog
    dlg = LicenceDialog(licence_store=store)
    bad = tmp_path / "bad.json"
    bad.write_text(make_licence(test_key, TEST_KID, _claims(product="other-app")), encoding="utf-8")
    assert not dlg.install_path(str(bad))
    assert "not this application" in dlg.result_label.text()
    good = tmp_path / "good.json"
    good.write_text(make_licence(test_key, TEST_KID, _claims()), encoding="utf-8")
    assert dlg.install_path(str(good))
    assert dlg.result_label.text() == "Licence installed."
    assert dlg.edition_label.text().startswith("Pro edition")
    dlg.close()
