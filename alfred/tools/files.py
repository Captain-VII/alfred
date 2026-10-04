"""Fichiers : recherche par nom, ouverture, révélation dans l'explorateur.

Stratégie : Everything (voidtools) s'il est disponible — via le SDK
(``Everything64.dll``) ou l'outil ``es.exe`` — sinon parcours ``os.walk`` des
dossiers utilisateur avec un budget de temps.
"""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path

from rapidfuzz import fuzz

from alfred.core import services
from alfred.tools import _win
from alfred.tools.base import ToolError, tool

log = logging.getLogger(__name__)

WALK_BUDGET_S = 3.0
MAX_RESULTS = 10
_IGNORED_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    "appdata",
    ".cache",
    "site-packages",
    "$recycle.bin",
}

_EVERYTHING_DLL_CANDIDATES = [
    os.environ.get("EVERYTHING_DLL", ""),
    r"C:\Program Files\Everything\Everything64.dll",
    r"C:\Program Files\Everything\SDK\dll\Everything64.dll",
    str(Path.home() / "AppData" / "Local" / "Everything" / "Everything64.dll"),
]

# Derniers résultats, pour « ouvre-le » / « montre-le dans l'explorateur »
_last_results: list[Path] = []


def _user_folders() -> list[Path]:
    home = Path.home()
    names = ["Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music", "OneDrive"]
    return [home / n for n in names if (home / n).exists()]


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


# ----------------------------------------------------------------------
# Backends
# ----------------------------------------------------------------------


def _everything_dll() -> ctypes.WinDLL | None:  # type: ignore[name-defined]
    if not _win.IS_WINDOWS:
        return None
    for candidate in _EVERYTHING_DLL_CANDIDATES:
        if candidate and Path(candidate).exists():
            try:
                return ctypes.WinDLL(candidate)
            except OSError:
                continue
    return None


def _search_everything_sdk(dll: ctypes.WinDLL, query: str) -> list[Path]:  # type: ignore[name-defined]
    dll.Everything_SetSearchW(ctypes.c_wchar_p(query))
    dll.Everything_SetMax(MAX_RESULTS * 3)
    dll.Everything_SetRequestFlags(0x00000001 | 0x00000002)  # nom + chemin
    if not dll.Everything_QueryW(True):
        return []
    count = dll.Everything_GetNumResults()
    buffer = ctypes.create_unicode_buffer(1024)
    results: list[Path] = []
    for i in range(count):
        dll.Everything_GetResultFullPathNameW(i, buffer, 1024)
        p = Path(buffer.value)
        if p.is_file():
            results.append(p)
    return results


def _search_es_exe(es: str, query: str) -> list[Path]:
    out = subprocess.run(
        [es, "-n", str(MAX_RESULTS * 3), "-sort", "date-modified-descending", query],
        capture_output=True,
        text=True,
        timeout=5,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return [
        Path(line.strip())
        for line in out.stdout.splitlines()
        if line.strip() and Path(line.strip()).is_file()
    ]


def _search_walk(query: str) -> list[Path]:
    """Repli : parcours des dossiers utilisateur, borné en temps, classé par similarité."""
    q = _fold(query)
    tokens = q.split()
    deadline = time.perf_counter() + WALK_BUDGET_S
    scored: list[tuple[float, Path]] = []
    for root in _user_folders():
        for dirpath, dirnames, filenames in os.walk(root):
            if time.perf_counter() > deadline:
                break
            dirnames[:] = [
                d for d in dirnames if d.lower() not in _IGNORED_DIRS and not d.startswith(".")
            ]
            for fn in filenames:
                folded = _fold(fn)
                if all(t in folded for t in tokens):
                    scored.append((100.0, Path(dirpath) / fn))
                else:
                    score = fuzz.partial_ratio(q, folded)
                    if score >= 80:
                        scored.append((float(score), Path(dirpath) / fn))
    # La date est relevée une fois par fichier, pas à chaque comparaison : deux appels
    # système par comparaison coûtent cher, et un fichier temporaire qui disparaît entre
    # exists() et stat() ferait échouer toute la recherche.
    dated: list[tuple[float, float, Path]] = []
    for score, path in scored:
        try:
            mtime = path.stat().st_mtime
        except OSError:  # fichier disparu ou illisible : il passe en dernier
            mtime = 0.0
        dated.append((score, mtime, path))
    dated.sort(key=lambda s: (-s[0], -s[1]))
    return [p for _, _, p in dated[: MAX_RESULTS * 3]]


def search_files(query: str) -> list[Path]:
    """Recherche par nom, backend le plus rapide disponible. Filtre les fichiers système."""
    query = query.strip()
    results: list[Path] = []
    dll = _everything_dll()
    if dll is not None:
        try:
            results = _search_everything_sdk(dll, query)
            log.debug("Everything SDK : %d résultats", len(results))
        except Exception:
            log.debug("Everything SDK indisponible", exc_info=True)
    if not results:
        es = shutil.which("es")
        if es:
            try:
                results = _search_es_exe(es, query)
                log.debug("es.exe : %d résultats", len(results))
            except (subprocess.SubprocessError, OSError):
                log.debug("es.exe indisponible", exc_info=True)
    if not results:
        results = _search_walk(query)
    home = str(Path.home()).lower()
    preferred = [
        p for p in results if str(p).lower().startswith(home) and "appdata" not in str(p).lower()
    ]
    others = [p for p in results if p not in preferred]
    return (preferred + others)[:MAX_RESULTS]


def _pick(name: str) -> Path:
    """Résout un nom (ou vide = dernier résultat) vers un fichier existant."""
    global _last_results
    if not name.strip():
        if _last_results:
            return _last_results[0]
        previous = services.last_arg("name")
        if previous:
            name = previous
        else:
            raise ToolError("de quel fichier parlez-vous ?")
    results = search_files(name)
    if not results:
        raise ToolError(f"aucun fichier nommé « {name} ».")
    _last_results = results
    return results[0]


# ----------------------------------------------------------------------
# Tools
# ----------------------------------------------------------------------


@tool(
    name="find_file",
    description="Recherche des fichiers par nom (ou fragment de nom) dans les dossiers de l'utilisateur, ou partout si Everything est installé.",
    examples=[
        "cherche le fichier budget",
        "trouve mon cv",
        "où est le fichier rapport 2024",
        "recherche le document facture",
        "trouve la photo de la plage",
    ],
    patterns=[
        r"(?:cherche|trouve|recherche|où est|retrouve) (?:le |la |mon |ma |mes |les )?(?:fichier|document|doc|photo|image|vidéo|pdf|fichiers) (?:nommé |appelé |qui s'appelle )?(?P<name>.+)",
    ],
    params={"name": "Nom ou fragment du nom du fichier"},
    category="fichiers",
)
async def find_file(name: str) -> str:
    global _last_results
    results = await _win.run_blocking(search_files, name)
    if not results:
        raise ToolError(f"aucun fichier nommé « {name} ».")
    _last_results = results
    first = results[0]
    where = first.parent.name or str(first.parent)
    if len(results) == 1:
        return f"Un fichier : {first.name}, dans {where}."
    return f"{len(results)} fichiers, le plus pertinent est {first.name}, dans {where}. Dites « ouvre-le » ou « montre-le »."


@tool(
    name="open_file",
    description="Ouvre un fichier avec son application par défaut. Sans nom, ouvre le dernier fichier trouvé.",
    examples=["ouvre le fichier budget", "ouvre-le", "ouvre mon cv", "ouvre le document facture"],
    patterns=[
        r"ouvre[- ](?:le|la|ce fichier|ce document)",
        r"ouvre (?:le |la |mon |ma )?(?:fichier|document|doc|pdf|photo|image|vidéo) (?:nommé |appelé )?(?P<name>.+)",
    ],
    params={"name": "Nom du fichier ; vide = dernier résultat de recherche"},
    category="fichiers",
)
async def open_file(name: str = "") -> str:
    path = await _win.run_blocking(_pick, name)
    await _win.run_blocking(_win.open_path, str(path))
    return f"{path.name} est ouvert."


@tool(
    name="reveal_file",
    description="Affiche un fichier dans l'explorateur Windows (dossier ouvert, fichier sélectionné).",
    examples=[
        "montre-le dans l'explorateur",
        "où se trouve le fichier budget",
        "affiche le fichier cv dans l'explorateur",
        "montre le dossier du fichier",
    ],
    patterns=[
        r"(?:montre|affiche|révèle)[- ](?:le|la|moi le fichier)?(?: dans l'explorateur)?",
        r"(?:montre|affiche|révèle) (?:le |la )?(?:fichier|document) (?P<name>.+?)(?: dans l'explorateur)?",
        r"où se trouve (?:le |la )?(?:fichier|document) (?P<name>.+)",
    ],
    params={"name": "Nom du fichier ; vide = dernier résultat de recherche"},
    category="fichiers",
)
async def reveal_file(name: str = "") -> str:
    path = await _win.run_blocking(_pick, name)
    await _win.run_blocking(_win.reveal_in_explorer, str(path))
    return f"{path.name} est affiché dans l'explorateur."
