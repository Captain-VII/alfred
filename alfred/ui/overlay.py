"""Overlay d'invocation : fenêtre frameless, always-on-top, sur l'écran du curseur.

Toutes les méthodes publiques sont thread-safe : elles émettent des signaux Qt
(connexion en file d'attente) et peuvent donc être appelées depuis le thread
asyncio. Le widget lui-même vit dans le thread Qt principal.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QGuiApplication, QKeyEvent
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel, QLineEdit, QVBoxLayout, QWidget

from alfred.ui.theme import label, overlay_stylesheet, palette

STATE_LABELS = {
    "idle": "ALFRED",
    "listening": "J'ÉCOUTE",
    "thinking": "UN INSTANT",
    "speaking": "ALFRED",
    "input": "VOTRE COMMANDE",
    "confirm": "CONFIRMATION",
    "error": "CONTRETEMPS",
}


class Overlay(QWidget):
    # Signaux internes (thread-safe)
    _sig_state = pyqtSignal(str, str)
    _sig_reply = pyqtSignal(str)
    _sig_metrics = pyqtSignal(str)
    _sig_show = pyqtSignal(str)
    _sig_hide = pyqtSignal(int)

    def __init__(self, on_submit: Callable[[str], None], on_cancel: Callable[[], None]) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._on_submit = on_submit
        self._on_cancel = on_cancel
        self.setObjectName("overlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setFixedWidth(520)

        self._state = label(STATE_LABELS["idle"], "state")
        self._text = QLabel("")
        self._text.setWordWrap(True)
        self._reply = label("", "reply")
        self._reply.setWordWrap(True)
        self._metrics = label("", "metrics")
        self._metrics.hide()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Que puis-je pour vous ?")
        self._input.returnPressed.connect(self._submit)
        self._input.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)
        layout.addWidget(self._state)
        layout.addWidget(self._text)
        layout.addWidget(self._input)
        layout.addWidget(self._reply)
        layout.addWidget(self._metrics)

        # Conteneur peint : le QWidget racine est transparent, on stylise un enfant
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)
        self._anim = QPropertyAnimation(self._opacity, b"opacity", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

        self._sig_state.connect(self._apply_state)
        self._sig_reply.connect(self._apply_reply)
        self._sig_metrics.connect(self._apply_metrics)
        self._sig_show.connect(self._do_show)
        self._sig_hide.connect(self._do_hide_later)
        self.apply_theme()

    # ---- API thread-safe ---------------------------------------------
    def show_mode(self, mode: str) -> None:
        """``mode`` ∈ {voice, text}."""
        self._sig_show.emit(mode)

    def set_state(self, state: str, text: str = "") -> None:
        self._sig_state.emit(state, text)

    def set_reply(self, text: str) -> None:
        self._sig_reply.emit(text)

    def set_metrics(self, text: str) -> None:
        self._sig_metrics.emit(text)

    def hide_later(self, ms: int = 2500) -> None:
        self._sig_hide.emit(ms)

    def apply_theme(self) -> None:
        self.setStyleSheet(overlay_stylesheet(palette()))

    # ---- slots (thread Qt) -------------------------------------------
    def _apply_state(self, state: str, text: str) -> None:
        self._state.setText(STATE_LABELS.get(state, state.upper()))
        if state == "input":
            self._text.hide()
            self._input.show()
            self._input.setFocus()
        else:
            self._input.hide()
            self._text.setText(text)
            self._text.setVisible(bool(text))
        if state in ("listening", "input"):
            self._reply.clear()
            self._reply.hide()
            self._metrics.hide()
        self.adjustSize()

    def _apply_reply(self, text: str) -> None:
        self._reply.setText(text)
        self._reply.setVisible(bool(text))
        self.adjustSize()

    def _apply_metrics(self, text: str) -> None:
        self._metrics.setText(text)
        self._metrics.setVisible(bool(text))
        self.adjustSize()

    def _do_show(self, mode: str) -> None:
        self._hide_timer.stop()
        self.apply_theme()
        self._reply.clear()
        self._reply.hide()
        self._metrics.hide()
        self._input.clear()
        if mode == "text":
            self._apply_state("input", "")
        else:
            self._apply_state("listening", "")
        self.adjustSize()
        self._move_to_cursor_screen()
        self._opacity.setOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()
        if mode == "text":
            self._input.setFocus()
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _do_hide_later(self, ms: int) -> None:
        self._hide_timer.start(max(0, ms))

    def _fade_out(self) -> None:
        if not self.isVisible():
            return
        self._anim.stop()
        self._anim.setStartValue(self._opacity.opacity())
        self._anim.setEndValue(0.0)
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        self._anim.finished.connect(self._finish_hide)
        self._anim.start()

    def _finish_hide(self) -> None:
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        self.hide()

    def _move_to_cursor_screen(self) -> None:
        """Centre l'overlay horizontalement, dans le tiers supérieur de l'écran où est le curseur."""
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + geo.height() // 4
        self.move(QPoint(x, y))

    # ---- événements --------------------------------------------------
    def _submit(self) -> None:
        text = self._input.text().strip()
        if text:
            self._input.clear()
            self._on_submit(text)

    def keyPressEvent(self, event: QKeyEvent | None) -> None:
        if event is not None and event.key() == Qt.Key.Key_Escape:
            self._on_cancel()
            return
        super().keyPressEvent(event)
