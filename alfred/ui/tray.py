"""Icône de la barre système (pystray) : pause, réglages, logs, mises à jour, redémarrage, quitter.

pystray tourne dans son propre thread (``run_detached``). Les callbacks reçus
sont relayés vers l'application via de simples callables ; l'application se
charge de passer dans le bon thread (Qt ou asyncio).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from alfred.config import assets_dir

log = logging.getLogger(__name__)


def _make_icon(paused: bool = False) -> Image.Image:
    """Charge ``assets/icons/alfred.png`` si présent, sinon dessine un monogramme « A »."""
    path = assets_dir() / "icons" / ("alfred_paused.png" if paused else "alfred.png")
    if path.exists():
        try:
            return Image.open(path).convert("RGBA")
        except OSError:
            pass
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    color = (120, 120, 120, 255) if paused else (201, 162, 39, 255)
    draw.ellipse((2, 2, size - 2, size - 2), fill=(30, 31, 36, 255), outline=color, width=3)
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    try:
        font = ImageFont.truetype("georgia.ttf", 38)
    except OSError:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), "A", font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1] - 2), "A", fill=color, font=font)
    return img


def save_default_icons(folder: Path) -> None:
    """Génère les PNG/ICO par défaut (utilisé par le script de build)."""
    folder.mkdir(parents=True, exist_ok=True)
    _make_icon(False).save(folder / "alfred.png")
    _make_icon(True).save(folder / "alfred_paused.png")
    _make_icon(False).resize((256, 256)).save(
        folder / "alfred.ico", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)]
    )


class Tray:
    def __init__(
        self,
        on_toggle_pause: Callable[[], None],
        on_settings: Callable[[], None],
        on_logs: Callable[[], None],
        on_check_updates: Callable[[], None],
        on_restart: Callable[[], None],
        on_quit: Callable[[], None],
        on_invoke: Callable[[], None],
    ) -> None:
        import pystray

        self._pystray = pystray
        self._paused = False
        self._on_toggle_pause = on_toggle_pause
        menu = pystray.Menu(
            pystray.MenuItem("Invoquer Alfred", lambda: on_invoke(), default=True),
            pystray.MenuItem(
                lambda _: "Reprendre" if self._paused else "Mettre en pause", self._toggle
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Réglages…", lambda: on_settings()),
            pystray.MenuItem("Ouvrir les logs", lambda: on_logs()),
            pystray.MenuItem("Vérifier les mises à jour", lambda: on_check_updates()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Redémarrer Alfred", lambda: on_restart()),
            pystray.MenuItem("Quitter", lambda: on_quit()),
        )
        self._icon = pystray.Icon("alfred", _make_icon(), "Alfred — à votre service", menu)

    def _toggle(self) -> None:
        self._on_toggle_pause()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self._icon.icon = _make_icon(paused)
        self._icon.title = "Alfred — en pause" if paused else "Alfred — à votre service"
        try:
            self._icon.update_menu()
        except Exception:
            pass

    def notify(self, message: str, title: str = "Alfred") -> None:
        """Notification simple via pystray (secours si windows-toasts est absent)."""
        try:
            self._icon.notify(message, title)
        except Exception:
            log.debug("Notification tray impossible", exc_info=True)

    def start(self) -> None:
        self._icon.run_detached()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            pass
