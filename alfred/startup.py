"""Démarrage avec Windows via ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``.

Pas de tâche planifiée : une simple valeur de registre, visible et
désactivable depuis le Gestionnaire des tâches.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "Alfred"


def launch_command() -> str:
    """Commande à enregistrer : l'exécutable gelé, ou ``pythonw -m alfred`` en développement."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimized'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{interpreter}" -m alfred --minimized'


def is_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
            return True
    except OSError:
        return False


def set_enabled(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, launch_command())
            log.info("Démarrage automatique activé")
        else:
            try:
                winreg.DeleteValue(key, _VALUE_NAME)
                log.info("Démarrage automatique désactivé")
            except FileNotFoundError:
                pass
