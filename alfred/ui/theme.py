"""Thème sombre / clair suivant Windows, et feuilles de style Qt partagées."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from PyQt6.QtWidgets import QLabel


def label(text: str, object_name: str = "") -> QLabel:
    """QLabel avec objectName (pour les feuilles de style), en une ligne."""
    widget = QLabel(text)
    if object_name:
        widget.setObjectName(object_name)
    widget.setWordWrap(True)
    return widget


@dataclass(frozen=True, slots=True)
class Palette:
    bg: str
    bg_alt: str
    fg: str
    fg_muted: str
    accent: str
    border: str
    error: str


DARK = Palette(
    bg="#1e1f24",
    bg_alt="#2a2b31",
    fg="#f2f2f2",
    fg_muted="#9a9ca6",
    accent="#c9a227",
    border="#3a3b42",
    error="#e06c75",
)
LIGHT = Palette(
    bg="#fbfaf7",
    bg_alt="#efede7",
    fg="#1d1d1f",
    fg_muted="#6b6b70",
    accent="#8a6d0b",
    border="#d9d6cf",
    error="#c0392b",
)


def windows_uses_dark_theme() -> bool:
    """Lit ``AppsUseLightTheme`` dans le registre (Windows 10/11)."""
    if sys.platform != "win32":
        return True
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value) == 0
    except OSError:
        return True


def palette() -> Palette:
    return DARK if windows_uses_dark_theme() else LIGHT


def overlay_stylesheet(p: Palette) -> str:
    return f"""
    QWidget#overlay {{
        background-color: {p.bg};
        border: 1px solid {p.border};
        border-radius: 14px;
    }}
    QLabel {{ color: {p.fg}; font-family: 'Segoe UI'; font-size: 15px; background: transparent; }}
    QLabel#state {{ color: {p.accent}; font-size: 12px; font-weight: 600; letter-spacing: 1px; }}
    QLabel#metrics {{ color: {p.fg_muted}; font-size: 11px; font-family: 'Cascadia Mono', 'Consolas', monospace; }}
    QLabel#reply {{ color: {p.fg_muted}; font-size: 14px; font-style: italic; }}
    QLineEdit {{
        background-color: {p.bg_alt}; color: {p.fg}; border: 1px solid {p.border};
        border-radius: 8px; padding: 8px 12px; font-family: 'Segoe UI'; font-size: 15px;
        selection-background-color: {p.accent};
    }}
    QLineEdit:focus {{ border: 1px solid {p.accent}; }}
    """


def dialog_stylesheet(p: Palette) -> str:
    return f"""
    QDialog, QWizard, QWidget {{ background-color: {p.bg}; color: {p.fg}; font-family: 'Segoe UI'; font-size: 13px; }}
    QTabWidget::pane {{ border: 1px solid {p.border}; border-radius: 6px; }}
    QTabBar::tab {{ background: {p.bg_alt}; color: {p.fg_muted}; padding: 8px 14px; border-top-left-radius: 6px; border-top-right-radius: 6px; }}
    QTabBar::tab:selected {{ color: {p.fg}; background: {p.bg}; border: 1px solid {p.border}; border-bottom: none; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
        background-color: {p.bg_alt}; color: {p.fg}; border: 1px solid {p.border}; border-radius: 6px; padding: 5px 8px;
    }}
    QComboBox QAbstractItemView {{ background-color: {p.bg_alt}; color: {p.fg}; selection-background-color: {p.accent}; }}
    QPushButton {{
        background-color: {p.bg_alt}; color: {p.fg}; border: 1px solid {p.border}; border-radius: 6px; padding: 6px 14px;
    }}
    QPushButton:hover {{ border-color: {p.accent}; }}
    QPushButton:default {{ background-color: {p.accent}; color: {p.bg}; font-weight: 600; }}
    QCheckBox {{ spacing: 8px; }}
    QGroupBox {{ border: 1px solid {p.border}; border-radius: 6px; margin-top: 12px; padding-top: 8px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; color: {p.fg_muted}; }}
    QProgressBar {{ border: 1px solid {p.border}; border-radius: 6px; text-align: center; background: {p.bg_alt}; color: {p.fg}; }}
    QProgressBar::chunk {{ background-color: {p.accent}; border-radius: 5px; }}
    QLabel#hint {{ color: {p.fg_muted}; font-size: 12px; }}
    QLabel#error {{ color: {p.error}; }}
    """
