"""Notifications Windows (toasts) avec repli sur pystray."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable

log = logging.getLogger(__name__)


class WindowsNotifier:
    """Implémente ``services.Notifier``."""

    def __init__(self, fallback: Callable[[str, str], None] | None = None) -> None:
        self._fallback = fallback
        self._toaster = None
        if sys.platform == "win32":
            try:
                from windows_toasts import WindowsToaster

                self._toaster = WindowsToaster("Alfred")
            except Exception:
                log.debug("windows-toasts indisponible, repli sur pystray", exc_info=True)

    def notify(self, title: str, message: str) -> None:
        if self._toaster is not None:
            try:
                from windows_toasts import Toast

                toast = Toast()
                toast.text_fields = [title, message]
                self._toaster.show_toast(toast)
                return
            except Exception:
                log.debug("Toast impossible", exc_info=True)
        if self._fallback is not None:
            self._fallback(message, title)
