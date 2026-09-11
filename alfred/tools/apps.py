"""Applications : ouvrir, fermer, basculer — avec résolution floue des noms.

L'index est construit au premier usage (dans un thread) à partir :
- des raccourcis du menu Démarrer (utilisateur + tous les utilisateurs) ;
- des exécutables du PATH ;
- des alias définis dans ``config.yaml`` (``app_aliases``) ;
- de quelques emplacements courants (WindowsApps, Program Files).

« spotifaille », « le navigateur », « mon éditeur de code » → résolus par
alias puis par similarité (rapidfuzz).
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz, process

from alfred.core import services
from alfred.tools import _win
from alfred.tools.base import ToolError, tool

log = logging.getLogger(__name__)

FUZZY_THRESHOLD = 68

# Noms usuels → exécutables (complète les alias utilisateur)
_BUILTIN_ALIASES: dict[str, str] = {
    "navigateur": "firefox.exe|chrome.exe|msedge.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "firefox": "firefox.exe",
    "explorateur": "explorer.exe",
    "explorateur de fichiers": "explorer.exe",
    "fichiers": "explorer.exe",
    "calculatrice": "calc.exe",
    "bloc-notes": "notepad.exe",
    "bloc notes": "notepad.exe",
    "notepad": "notepad.exe",
    "terminal": "wt.exe|powershell.exe",
    "invite de commandes": "cmd.exe",
    "paramètres": "ms-settings:",
    "réglages": "ms-settings:",
    "éditeur de code": "Code.exe",
    "vs code": "Code.exe",
    "visual studio code": "Code.exe",
    "code": "Code.exe",
    "musique": "Spotify.exe",
    "spotify": "Spotify.exe",
    "discord": "Discord.exe",
    "steam": "steam.exe",
    "vlc": "vlc.exe",
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "outlook": "OUTLOOK.EXE",
    "gestionnaire des tâches": "taskmgr.exe",
    "paint": "mspaint.exe",
}

# Articles / déterminants à retirer avant la recherche
_STRIP_WORDS = re.compile(
    r"^(?:l'application |l'appli |l'app |application |appli |app |l'|le |la |les |mon |ma |mes |un |une |du |de la )+"
)


@dataclass(slots=True)
class AppEntry:
    name: str  # nom affiché (ex. « Spotify »)
    target: str  # chemin .lnk / .exe / URI
    exe: str  # nom de l'exécutable (ex. « spotify.exe »), pour fermer / détecter

    @property
    def key(self) -> str:
        return _normalize(self.name)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("’", "'")
    text = _STRIP_WORDS.sub("", text.strip())
    return re.sub(r"\s+", " ", text).strip()


def _lnk_target(path: Path) -> str:
    """Cible d'un raccourci .lnk (pywin32), ou le .lnk lui-même en cas d'échec."""
    try:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        shell = win32com.client.Dispatch("WScript.Shell")
        target = shell.CreateShortCut(str(path)).Targetpath
        if target and str(target).lower().endswith(".exe"):
            return str(target)
    except Exception:
        pass
    return str(path)


class AppIndex:
    def __init__(self) -> None:
        self._entries: list[AppEntry] = []
        self._lock = threading.Lock()
        self._built = False

    # ---- construction ------------------------------------------------
    def build(self) -> None:
        with self._lock:
            if self._built:
                return
            started = time.perf_counter()
            entries: dict[str, AppEntry] = {}
            for entry in self._scan_start_menu():
                entries.setdefault(entry.key, entry)
            for entry in self._scan_path():
                entries.setdefault(entry.key, entry)
            self._entries = list(entries.values())
            self._built = True
            log.info(
                "Index applications : %d entrées en %.0f ms",
                len(self._entries),
                (time.perf_counter() - started) * 1000,
            )

    def _scan_start_menu(self) -> list[AppEntry]:
        roots = [
            Path(os.environ.get("APPDATA", ""))
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs",
            Path(os.environ.get("PROGRAMDATA", ""))
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs",
        ]
        result: list[AppEntry] = []
        for root in roots:
            if not root.exists():
                continue
            for lnk in root.rglob("*.lnk"):
                name = lnk.stem
                if any(
                    w in name.lower() for w in ("uninstall", "désinstall", "readme", "help", "aide")
                ):
                    continue
                target = _lnk_target(lnk)
                exe = Path(target).name.lower() if target.lower().endswith(".exe") else ""
                result.append(AppEntry(name=name, target=str(lnk), exe=exe))
        return result

    def _scan_path(self) -> list[AppEntry]:
        result: list[AppEntry] = []
        seen: set[str] = set()
        for folder in os.environ.get("PATH", "").split(os.pathsep):
            p = Path(folder)
            if not p.is_dir():
                continue
            try:
                for exe in p.glob("*.exe"):
                    key = exe.stem.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    result.append(AppEntry(name=exe.stem, target=str(exe), exe=exe.name.lower()))
            except OSError:
                continue
        return result

    @property
    def entries(self) -> list[AppEntry]:
        if not self._built:
            self.build()
        return self._entries

    # ---- résolution --------------------------------------------------
    def resolve(self, spoken: str, aliases: dict[str, str] | None = None) -> AppEntry | None:
        """Nom parlé → entrée d'index, ou ``None``."""
        query = _normalize(spoken)
        if not query:
            return None
        merged = {**_BUILTIN_ALIASES, **{_normalize(k): v for k, v in (aliases or {}).items()}}

        # 1. Alias exact (utilisateur > intégrés)
        if query in merged:
            for candidate in merged[query].split("|"):
                entry = self._by_exe_or_uri(candidate)
                if entry is not None:
                    return entry

        # 2. Alias flou (« spotifaille » ≈ « spotify »)
        alias_match = process.extractOne(
            query, list(merged), scorer=fuzz.WRatio, score_cutoff=FUZZY_THRESHOLD + 10
        )
        if alias_match is not None:
            for candidate in merged[alias_match[0]].split("|"):
                entry = self._by_exe_or_uri(candidate)
                if entry is not None:
                    return entry

        # 3. Index : nom affiché
        entries = self.entries
        if not entries:
            return None
        keys = [e.key for e in entries]
        match = process.extractOne(query, keys, scorer=fuzz.WRatio, score_cutoff=FUZZY_THRESHOLD)
        if match is not None:
            return entries[match[2]]
        # 4. Index : nom d'exécutable sans extension
        stems = [e.exe.removesuffix(".exe") for e in entries]
        match = process.extractOne(query, stems, scorer=fuzz.WRatio, score_cutoff=FUZZY_THRESHOLD)
        if match is not None and match[0]:
            return entries[match[2]]
        return None

    def _by_exe_or_uri(self, candidate: str) -> AppEntry | None:
        candidate = candidate.strip()
        if candidate.endswith(":") or "://" in candidate:  # URI (ms-settings:)
            return AppEntry(name=candidate, target=candidate, exe="")
        exe = candidate.lower()
        for entry in self.entries:
            if entry.exe == exe:
                return entry
        # Exécutable absent de l'index mais résolvable via PATH / App Paths
        import shutil

        found = shutil.which(candidate)
        if found:
            return AppEntry(name=Path(found).stem, target=found, exe=Path(found).name.lower())
        app_path = _app_paths_lookup(candidate)
        if app_path:
            return AppEntry(
                name=Path(app_path).stem, target=app_path, exe=Path(app_path).name.lower()
            )
        return None


def _app_paths_lookup(exe: str) -> str | None:
    """``HKLM/HKCU\\...\\App Paths\\<exe>`` : où Windows enregistre les exécutables installés."""
    if not _win.IS_WINDOWS:
        return None
    import winreg

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(
                hive, rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{exe}"
            ) as key:
                value, _ = winreg.QueryValueEx(key, "")
                value = str(value).strip('"')
                if Path(value).exists():
                    return value
        except OSError:
            continue
    return None


INDEX = AppIndex()


def _resolve_or_fail(spoken: str) -> AppEntry:
    spoken = spoken.strip()
    if not spoken:
        raise ToolError("quelle application ?")
    entry = INDEX.resolve(spoken, services.cfg().app_aliases)
    if entry is None:
        raise ToolError(f"je ne trouve pas d'application nommée « {spoken} ».")
    return entry


def _anaphora(app: str) -> str:
    """« ferme-la » : si aucun nom n'est donné, reprend la dernière application mentionnée."""
    if app.strip():
        return app
    previous = services.last_arg("app")
    if previous:
        return previous
    raise ToolError("de quelle application parlez-vous ?")


_APP_RE = r"(?P<app>[\w\s'’.+-]+?)"

# ----------------------------------------------------------------------
# Tools
# ----------------------------------------------------------------------


@tool(
    name="open_app",
    description="Ouvre (lance) une application installée. Le nom peut être approximatif ou un alias (navigateur, musique…).",
    examples=[
        "ouvre spotify",
        "lance le navigateur",
        "démarre vs code",
        "ouvre la calculatrice",
        "lance discord",
        "ouvre mon éditeur de code",
        "démarre le terminal",
    ],
    patterns=[
        rf"(?:ouvre|lance|démarre|exécute|open) (?:moi )?(?:l'application |l'appli |l'app )?{_APP_RE}",
    ],
    params={"app": "Nom de l'application, alias ou description (« le navigateur »)"},
    category="applications",
)
async def open_app(app: str) -> str:
    entry = await _win.run_blocking(_resolve_or_fail, app)
    try:
        await _win.run_blocking(_win.start_process, entry.target)
    except OSError as exc:
        raise ToolError(f"{entry.name} refuse de se lancer.") from exc
    return f"{entry.name} est ouvert."


@tool(
    name="close_app",
    description="Ferme une application en cours d'exécution (fermeture propre des fenêtres, puis arrêt du processus).",
    examples=[
        "ferme spotify",
        "quitte discord",
        "ferme le navigateur",
        "ferme-la",
        "ferme cette application",
    ],
    patterns=[
        r"(?:ferme|quitte|arrête|tue)[- ](?:la|le|ça|cette application|cette appli|l'application|l'appli)",
        rf"(?:ferme|quitte|arrête|tue) (?:l'application |l'appli |l'app )?{_APP_RE}",
    ],
    params={"app": "Nom de l'application ; vide = la dernière application mentionnée"},
    category="applications",
)
async def close_app(app: str = "") -> str:
    app = _anaphora(app)
    entry = await _win.run_blocking(_resolve_or_fail, app)
    if not entry.exe:
        raise ToolError(f"je ne sais pas fermer {entry.name}.")
    windows = await _win.run_blocking(_win.list_windows)
    targets = [hwnd for hwnd, _title, exe in windows if exe.lower() == entry.exe]
    for hwnd in targets:
        await _win.run_blocking(_win.close_window, hwnd)
    if targets:
        # Laisse à l'application le temps de fermer proprement (dialogue d'enregistrement éventuel)
        import asyncio

        await asyncio.sleep(1.5)
    running = await _win.run_blocking(_win.running_process_names)
    if entry.exe in running and not targets:
        killed = await _win.run_blocking(_win.kill_process_by_name, entry.exe)
        if killed == 0:
            raise ToolError(f"{entry.name} ne semble pas ouvert.")
    elif entry.exe not in running and not targets:
        raise ToolError(f"{entry.name} n'est pas ouvert.")
    return f"{entry.name} est fermé."


@tool(
    name="focus_app",
    description="Met au premier plan la fenêtre d'une application déjà ouverte.",
    examples=[
        "bascule sur spotify",
        "va sur le navigateur",
        "montre-moi discord",
        "passe sur vs code",
        "affiche firefox",
    ],
    patterns=[
        rf"(?:bascule|passe|va|switch) (?:sur|vers|à) {_APP_RE}",
        rf"(?:montre|affiche)(?:-moi)? (?!(?:le |la |les |mon |ma |mes |ce |cette )?(?:bureau|fichier|document|fenêtre|dossier|photo|image)\b){_APP_RE}",
    ],
    params={"app": "Nom de l'application ou titre de fenêtre"},
    category="applications",
)
async def focus_app(app: str) -> str:
    app = _anaphora(app)
    windows = await _win.run_blocking(_win.list_windows)
    if not windows:
        raise ToolError("aucune fenêtre n'est ouverte.")
    entry = INDEX.resolve(app, services.cfg().app_aliases)
    query = _normalize(app)
    candidates: list[tuple[int, str]] = []
    for hwnd, title, exe in windows:
        if entry is not None and entry.exe and exe.lower() == entry.exe:
            candidates.insert(0, (hwnd, title))
        else:
            candidates.append((hwnd, title))
    if (
        entry is None
        or not entry.exe
        or (candidates[0][0] == windows[0][0] and entry.exe != windows[0][2].lower())
    ):
        # Pas d'exécutable identifié : recherche floue sur les titres de fenêtres
        titles = [_normalize(t) for _, t in candidates]
        match = process.extractOne(query, titles, scorer=fuzz.partial_ratio, score_cutoff=70)
        if match is None:
            raise ToolError(f"aucune fenêtre ne correspond à « {app} ».")
        hwnd, title = candidates[match[2]]
    else:
        hwnd, title = candidates[0]
    await _win.run_blocking(_win.focus_window, hwnd)
    label = entry.name if entry is not None else title
    return f"{label} est au premier plan."
