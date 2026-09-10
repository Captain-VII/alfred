"""Utilitaires Windows partagés par les tools (isolés pour être mockés en tests).

Tout appel système passe par ici : les tests remplacent ces fonctions et
aucun test ne touche réellement au volume, aux fenêtres ou aux processus.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import os
import subprocess
import sys
from collections.abc import Callable
from typing import Any, TypeVar

log = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
T = TypeVar("T")


async def run_blocking(func: Callable[..., T], *args: Any) -> T:
    """Exécute un appel bloquant (COM, subprocess) hors de la boucle asyncio."""
    return await asyncio.to_thread(func, *args)


# ----------------------------------------------------------------------
# Touches virtuelles
# ----------------------------------------------------------------------

VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3
KEYEVENTF_KEYUP = 0x0002


def press_vk(code: int) -> None:
    """Simule l'appui sur une touche virtuelle (touches média, volume)."""
    if not IS_WINDOWS:
        log.debug("press_vk(%#x) ignoré hors Windows", code)
        return
    user32 = ctypes.windll.user32
    user32.keybd_event(code, 0, 0, 0)
    user32.keybd_event(code, 0, KEYEVENTF_KEYUP, 0)


# ----------------------------------------------------------------------
# Volume (pycaw / CoreAudio)
# ----------------------------------------------------------------------


def _endpoint_volume() -> Any:
    """Interface IAudioEndpointVolume du périphérique de sortie par défaut (pycaw ≥ 2024 et ancien)."""
    from pycaw.pycaw import AudioUtilities

    device = AudioUtilities.GetSpeakers()
    if hasattr(device, "EndpointVolume"):  # pycaw ≥ 20240210 : objet AudioDevice
        return device.EndpointVolume
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import IAudioEndpointVolume

    interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return interface.QueryInterface(IAudioEndpointVolume)


def get_volume() -> int:
    """Volume système en pourcentage (0-100)."""
    if not IS_WINDOWS:
        return 50
    vol = _endpoint_volume()
    return round(float(vol.GetMasterVolumeLevelScalar()) * 100)


def set_volume(percent: int) -> None:
    if not IS_WINDOWS:
        return
    percent = max(0, min(100, percent))
    vol = _endpoint_volume()
    vol.SetMasterVolumeLevelScalar(percent / 100, None)
    if percent > 0:
        vol.SetMute(0, None)


def set_mute(mute: bool) -> None:
    if not IS_WINDOWS:
        return
    _endpoint_volume().SetMute(1 if mute else 0, None)


def is_muted() -> bool:
    if not IS_WINDOWS:
        return False
    return bool(_endpoint_volume().GetMute())


# ----------------------------------------------------------------------
# Luminosité
# ----------------------------------------------------------------------


def get_brightness() -> int:
    import screen_brightness_control as sbc

    values = sbc.get_brightness()
    return int(values[0]) if values else 50


def set_brightness(percent: int) -> None:
    import screen_brightness_control as sbc

    sbc.set_brightness(max(0, min(100, percent)))


# ----------------------------------------------------------------------
# Alimentation / session
# ----------------------------------------------------------------------


def lock_workstation() -> None:
    if IS_WINDOWS:
        ctypes.windll.user32.LockWorkStation()


def sleep_pc() -> None:
    if IS_WINDOWS:
        # SetSuspendState(hibernate=False, forceCritical=False, disableWakeEvent=False)
        ctypes.windll.powrprof.SetSuspendState(0, 0, 0)


def shutdown_pc(delay_s: int = 5) -> None:
    if IS_WINDOWS:
        subprocess.Popen(
            ["shutdown", "/s", "/t", str(delay_s)], creationflags=subprocess.CREATE_NO_WINDOW
        )


def restart_pc(delay_s: int = 5) -> None:
    if IS_WINDOWS:
        subprocess.Popen(
            ["shutdown", "/r", "/t", str(delay_s)], creationflags=subprocess.CREATE_NO_WINDOW
        )


def abort_shutdown() -> None:
    if IS_WINDOWS:
        subprocess.run(["shutdown", "/a"], creationflags=subprocess.CREATE_NO_WINDOW, check=False)


# ----------------------------------------------------------------------
# Capture d'écran
# ----------------------------------------------------------------------


def screenshot(path: str) -> str:
    import mss
    import mss.tools

    with mss.mss() as sct:
        monitor = sct.monitors[0]  # tous les écrans
        img = sct.grab(monitor)
        mss.tools.to_png(img.rgb, img.size, output=path)
    return path


# ----------------------------------------------------------------------
# Ne pas déranger (Focus Assist / notifications)
# ----------------------------------------------------------------------

_DND_KEY = r"Software\Microsoft\Windows\CurrentVersion\PushNotifications"


def set_do_not_disturb(enabled: bool) -> None:
    """Active/désactive les toasts via le registre (approximation de l'assistant de concentration)."""
    if not IS_WINDOWS:
        return
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _DND_KEY) as key:
        winreg.SetValueEx(key, "ToastEnabled", 0, winreg.REG_DWORD, 0 if enabled else 1)


def get_do_not_disturb() -> bool:
    if not IS_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _DND_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "ToastEnabled")
            return int(value) == 0
    except OSError:
        return False


# ----------------------------------------------------------------------
# Processus / applications
# ----------------------------------------------------------------------


def start_process(target: str, args: list[str] | None = None) -> None:
    """Lance un exécutable, un raccourci ``.lnk`` ou une URI (``ms-settings:``)."""
    if not IS_WINDOWS:
        log.debug("start_process(%s) ignoré hors Windows", target)
        return
    if target.lower().endswith((".lnk", ".url")) or (":" in target and not os.path.exists(target)):
        os.startfile(target)
        return
    subprocess.Popen(
        [target, *(args or [])],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )


def open_path(path: str) -> None:
    if IS_WINDOWS:
        os.startfile(path)


def reveal_in_explorer(path: str) -> None:
    if IS_WINDOWS:
        subprocess.Popen(["explorer", "/select,", path])


def kill_process_by_name(exe_name: str) -> int:
    """Termine tous les processus portant ce nom. Retourne le nombre tués."""
    import psutil

    killed = 0
    exe_name = exe_name.lower()
    for proc in psutil.process_iter(["name"]):
        try:
            if (proc.info["name"] or "").lower() == exe_name:
                proc.terminate()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return killed


def running_process_names() -> set[str]:
    import psutil

    names: set[str] = set()
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"]:
                names.add(proc.info["name"].lower())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return names


# ----------------------------------------------------------------------
# Fenêtres (win32gui)
# ----------------------------------------------------------------------


def list_windows() -> list[tuple[int, str, str]]:
    """Fenêtres visibles : ``(hwnd, titre, nom_exe)``."""
    if not IS_WINDOWS:
        return []
    import psutil
    import win32gui
    import win32process

    result: list[tuple[int, str, str]] = []

    def _enum(hwnd: int, _: Any) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            exe = psutil.Process(pid).name()
        except Exception:
            exe = ""
        result.append((hwnd, title, exe))

    win32gui.EnumWindows(_enum, None)
    return result


def foreground_window() -> int:
    if not IS_WINDOWS:
        return 0
    import win32gui

    return int(win32gui.GetForegroundWindow())


def focus_window(hwnd: int) -> None:
    if not IS_WINDOWS:
        return
    import win32con
    import win32gui

    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    # Astuce classique : simuler ALT pour autoriser SetForegroundWindow.
    ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
    ctypes.windll.user32.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)
    win32gui.SetForegroundWindow(hwnd)


def show_window(hwnd: int, state: str) -> None:
    """``state`` ∈ {minimize, maximize, restore}."""
    if not IS_WINDOWS:
        return
    import win32con
    import win32gui

    cmd = {
        "minimize": win32con.SW_MINIMIZE,
        "maximize": win32con.SW_MAXIMIZE,
        "restore": win32con.SW_RESTORE,
    }[state]
    win32gui.ShowWindow(hwnd, cmd)


def close_window(hwnd: int) -> None:
    if not IS_WINDOWS:
        return
    import win32con
    import win32gui

    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)


def move_window(hwnd: int, x: int, y: int, w: int, h: int) -> None:
    if not IS_WINDOWS:
        return
    import win32con
    import win32gui

    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.MoveWindow(hwnd, x, y, w, h, True)


def work_area() -> tuple[int, int, int, int]:
    """Zone de travail de l'écran principal (sans la barre des tâches) : ``(x, y, w, h)``."""
    if not IS_WINDOWS:
        return (0, 0, 1920, 1080)
    import win32api
    import win32con

    left, top, right, bottom = win32api.GetMonitorInfo(
        win32api.MonitorFromPoint((0, 0), win32con.MONITOR_DEFAULTTONEAREST)
    )["Work"]
    return (left, top, right - left, bottom - top)


def minimize_all() -> None:
    """Affiche le bureau (Win+D)."""
    if not IS_WINDOWS:
        return
    import win32com.client

    win32com.client.Dispatch("Shell.Application").MinimizeAll()


# ----------------------------------------------------------------------
# Presse-papier
# ----------------------------------------------------------------------


def clipboard_read() -> str:
    import pyperclip

    return pyperclip.paste() or ""


def clipboard_write(text: str) -> None:
    import pyperclip

    pyperclip.copy(text)
