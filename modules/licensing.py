"""
licensing.py
The application's use of the shared labkit licence SDK (labkit/licence.py).

Enforcement is OFF: the owner has not decided editions, prices or which features will be
paid. While ENFORCE is False every feature stays available (`allowed()` is always True) and
the licence status is informational only -- shown in Help › Licence… so a licence can already
be installed and checked. Nothing here touches the network.
"""
from __future__ import annotations

from datetime import date

from labkit import licence

PRODUCT = "ftir-xrd-toolkit"
PUBLIC_KEYS = {'labapps-2026': 'g93gW00t+FyNNul4QhlGPReeosESePiX9vmr0UEL6hs='}
RELEASE_DATE = date(2026, 11, 14)
ENFORCE = False
# Everything is free while ENFORCE is False. When pricing is decided, list here every feature
# that was available before, so no existing user loses what they had.
FREE_FEATURES = frozenset({"*"})


def store() -> licence.LicenceStore:
    return licence.LicenceStore(PRODUCT)


def status(licence_store: licence.LicenceStore | None = None) -> licence.Status:
    """The installed licence's status for this computer, today (never raises)."""
    try:
        return licence.check(PRODUCT, PUBLIC_KEYS, store=licence_store or store(),
                             release_date=RELEASE_DATE, free_features=FREE_FEATURES)
    except Exception as exc:                        # noqa: BLE001 - status must never break the app
        return licence.Status(ok=False, reason=f"The licence could not be checked: {exc}",
                              features=FREE_FEATURES)


def allowed(feature: str, current: licence.Status | None = None) -> bool:
    """May the user use `feature`? Always True while ENFORCE is False."""
    if not ENFORCE:
        return True
    current = current or status()
    return current.entitled(feature) or feature in FREE_FEATURES or "*" in FREE_FEATURES


def device_id() -> str:
    return licence.device_id(PRODUCT)


def activation_request() -> str:
    return licence.activation_request(PRODUCT)


def install(text: str, licence_store: licence.LicenceStore | None = None) -> dict:
    """Verify and save a licence file's text. Raises licence.LicenceError with a user sentence."""
    return (licence_store or store()).install(text, PRODUCT, PUBLIC_KEYS)


def describe(current: licence.Status) -> tuple[str, str]:
    """(edition line, status sentence) for the Licence dialog."""
    claims = current.claims or {}
    if current.ok:
        edition = f"{current.edition.title()} edition ({claims.get('kind', '')})".replace(" ()", "")
        holder = ", ".join(x for x in (claims.get("name", ""), claims.get("organisation", "")) if x)
        sentence = "Licensed" + (f" to {holder}" if holder else "") + "."
        if current.expires:
            sentence += f" Valid until {current.expires.isoformat()}."
        if claims.get("serial"):
            sentence += f" Serial {claims['serial']}."
    else:
        edition = "Free edition"
        sentence = current.reason or "No licence installed."
    if not ENFORCE:
        sentence += " All features are currently available without a licence."
    return edition, sentence
