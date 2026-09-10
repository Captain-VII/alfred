"""Fixtures communes : tous les appels système sont mockés.

Aucun test n'ouvre une application, ne change le volume ni ne touche au registre.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# Isole la configuration utilisateur dans un dossier temporaire avant tout import d'alfred.config
os.environ.setdefault("APPDATA", str(Path(__file__).parent / "_appdata"))

from alfred.tools import _win
from alfred.tools.base import REGISTRY, load_all_tools


@pytest.fixture(scope="session", autouse=True)
def _load_tools() -> None:
    load_all_tools()
    assert REGISTRY, "aucun tool chargé"


class FakeSystem:
    """État simulé du système, modifié par les fonctions mockées de ``_win``."""

    def __init__(self) -> None:
        self.volume = 50
        self.muted = False
        self.brightness = 60
        self.dnd = False
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.windows: list[tuple[int, str, str]] = [
            (101, "Spotify Premium", "Spotify.exe"),
            (102, "Mozilla Firefox", "firefox.exe"),
            (103, "main.py - Visual Studio Code", "Code.exe"),
        ]
        self.foreground = 102
        self.processes = {"spotify.exe", "firefox.exe", "code.exe", "explorer.exe"}
        self.clipboard = "Bonjour le monde."

    def record(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))

    def called(self, name: str) -> list[tuple[Any, ...]]:
        return [args for n, args in self.calls if n == name]


@pytest.fixture
def system(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeSystem]:
    fake = FakeSystem()

    def _set_volume(v: int) -> None:
        fake.volume = v
        fake.record("set_volume", v)

    def _set_mute(m: bool) -> None:
        fake.muted = m
        fake.record("set_mute", m)

    def _set_brightness(v: int) -> None:
        fake.brightness = v
        fake.record("set_brightness", v)

    def _set_dnd(v: bool) -> None:
        fake.dnd = v
        fake.record("set_do_not_disturb", v)

    monkeypatch.setattr(_win, "get_volume", lambda: fake.volume)
    monkeypatch.setattr(_win, "set_volume", _set_volume)
    monkeypatch.setattr(_win, "is_muted", lambda: fake.muted)
    monkeypatch.setattr(_win, "set_mute", _set_mute)
    monkeypatch.setattr(_win, "get_brightness", lambda: fake.brightness)
    monkeypatch.setattr(_win, "set_brightness", _set_brightness)
    monkeypatch.setattr(_win, "get_do_not_disturb", lambda: fake.dnd)
    monkeypatch.setattr(_win, "set_do_not_disturb", _set_dnd)
    monkeypatch.setattr(_win, "press_vk", lambda code: fake.record("press_vk", code))
    monkeypatch.setattr(_win, "lock_workstation", lambda: fake.record("lock"))
    monkeypatch.setattr(_win, "sleep_pc", lambda: fake.record("sleep"))
    monkeypatch.setattr(_win, "shutdown_pc", lambda d=5: fake.record("shutdown", d))
    monkeypatch.setattr(_win, "restart_pc", lambda d=5: fake.record("restart", d))
    monkeypatch.setattr(_win, "abort_shutdown", lambda: fake.record("abort_shutdown"))
    monkeypatch.setattr(_win, "screenshot", lambda p: (fake.record("screenshot", p), p)[1])
    monkeypatch.setattr(_win, "start_process", lambda t, a=None: fake.record("start_process", t))
    monkeypatch.setattr(_win, "open_path", lambda p: fake.record("open_path", p))
    monkeypatch.setattr(_win, "reveal_in_explorer", lambda p: fake.record("reveal", p))
    monkeypatch.setattr(_win, "kill_process_by_name", lambda n: (fake.record("kill", n), 1)[1])
    monkeypatch.setattr(_win, "running_process_names", lambda: set(fake.processes))
    monkeypatch.setattr(_win, "list_windows", lambda: list(fake.windows))
    monkeypatch.setattr(_win, "foreground_window", lambda: fake.foreground)
    monkeypatch.setattr(_win, "focus_window", lambda h: fake.record("focus", h))
    monkeypatch.setattr(_win, "show_window", lambda h, s: fake.record("show_window", h, s))
    monkeypatch.setattr(_win, "close_window", lambda h: fake.record("close_window", h))
    monkeypatch.setattr(
        _win, "move_window", lambda h, x, y, w, hh: fake.record("move_window", h, x, y, w, hh)
    )
    monkeypatch.setattr(_win, "work_area", lambda: (0, 0, 1920, 1040))
    monkeypatch.setattr(_win, "minimize_all", lambda: fake.record("minimize_all"))
    monkeypatch.setattr(_win, "clipboard_read", lambda: fake.clipboard)
    monkeypatch.setattr(_win, "clipboard_write", lambda t: setattr(fake, "clipboard", t))
    yield fake
