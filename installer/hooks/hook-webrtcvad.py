"""Hook PyInstaller pour ``webrtcvad``.

Le hook fourni par ``pyinstaller-hooks-contrib`` copie les métadonnées de la
distribution nommée ``webrtcvad``. Nous installons ``webrtcvad-wheels``, qui
fournit le même module sous un nom de distribution différent : le hook d'origine
échoue alors avec ``PackageNotFoundError`` et interrompt la construction.

Ce hook local est prioritaire sur celui de contrib et essaie les deux noms.
"""

from __future__ import annotations

from PyInstaller.utils.hooks import copy_metadata

datas = []
for distribution in ("webrtcvad-wheels", "webrtcvad"):
    try:
        datas = copy_metadata(distribution)
        break
    except Exception:  # noqa: BLE001 — distribution absente, on tente la suivante
        continue
