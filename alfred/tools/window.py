"""Fenêtres : minimiser, maximiser, fermer, basculer, organiser côte à côte, bureau."""

from __future__ import annotations

from rapidfuzz import fuzz, process

from alfred.tools import _win
from alfred.tools.base import ToolError, tool


def _active_or_fail() -> int:
    hwnd = _win.foreground_window()
    if not hwnd:
        raise ToolError("aucune fenêtre active.")
    return hwnd


def _find_window(query: str) -> tuple[int, str]:
    windows = _win.list_windows()
    if not windows:
        raise ToolError("aucune fenêtre ouverte.")
    q = query.lower().strip()
    labels = [f"{title} {exe}".lower() for _, title, exe in windows]
    match = process.extractOne(q, labels, scorer=fuzz.partial_ratio, score_cutoff=65)
    if match is None:
        raise ToolError(f"aucune fenêtre ne correspond à « {query} ».")
    hwnd, title, _ = windows[match[2]]
    return hwnd, title


@tool(
    name="minimize_window",
    description="Réduit la fenêtre active (ou celle nommée) dans la barre des tâches.",
    examples=["réduis la fenêtre", "minimise", "réduis cette fenêtre", "minimise spotify"],
    patterns=[
        r"(?:réduis|minimise|réduit)(?: (?:la |cette )?fenêtre)?(?: (?:de |d')?(?P<target>.+))?"
    ],
    params={"target": "Nom de l'application ou titre ; vide = fenêtre active"},
    category="fenêtres",
)
async def minimize_window(target: str = "") -> str:
    hwnd = (
        (await _win.run_blocking(_find_window, target))[0]
        if target.strip()
        else await _win.run_blocking(_active_or_fail)
    )
    await _win.run_blocking(_win.show_window, hwnd, "minimize")
    return ""


@tool(
    name="maximize_window",
    description="Agrandit la fenêtre active (ou celle nommée) en plein écran.",
    examples=[
        "agrandis la fenêtre",
        "maximise",
        "plein écran",
        "agrandis cette fenêtre",
        "maximise le navigateur",
    ],
    patterns=[
        r"(?:agrandis|maximise|agrandit)(?: (?:la |cette )?fenêtre)?(?: (?:de |d')?(?P<target>.+))?",
        r"(?:mets? (?:en |la fenêtre en ))?plein écran",
    ],
    params={"target": "Nom de l'application ou titre ; vide = fenêtre active"},
    category="fenêtres",
)
async def maximize_window(target: str = "") -> str:
    hwnd = (
        (await _win.run_blocking(_find_window, target))[0]
        if target.strip()
        else await _win.run_blocking(_active_or_fail)
    )
    await _win.run_blocking(_win.show_window, hwnd, "maximize")
    return ""


@tool(
    name="close_window",
    description="Ferme la fenêtre active (ou celle nommée). L'application peut demander d'enregistrer.",
    examples=["ferme la fenêtre", "ferme cette fenêtre", "ferme la fenêtre active"],
    patterns=[r"ferme (?:la |cette )?fenêtre(?: active| courante)?(?: (?:de |d')?(?P<target>.+))?"],
    params={"target": "Nom de l'application ou titre ; vide = fenêtre active"},
    category="fenêtres",
)
async def close_window(target: str = "") -> str:
    hwnd = (
        (await _win.run_blocking(_find_window, target))[0]
        if target.strip()
        else await _win.run_blocking(_active_or_fail)
    )
    await _win.run_blocking(_win.close_window, hwnd)
    return "Fenêtre fermée."


@tool(
    name="restore_window",
    description="Restaure la fenêtre active à sa taille normale (ni réduite ni agrandie).",
    examples=[
        "restaure la fenêtre",
        "taille normale",
        "sors du plein écran",
        "quitte le plein écran",
    ],
    patterns=[
        r"restaure (?:la )?fenêtre",
        r"taille normale",
        r"(?:sors|quitte) (?:du |le )?plein écran",
    ],
    category="fenêtres",
)
async def restore_window() -> str:
    hwnd = await _win.run_blocking(_active_or_fail)
    await _win.run_blocking(_win.show_window, hwnd, "restore")
    return ""


@tool(
    name="snap_windows",
    description="Organise deux fenêtres côte à côte : la fenêtre active à gauche et la précédente à droite (ou celles nommées).",
    examples=[
        "mets les fenêtres côte à côte",
        "organise côte à côte",
        "partage l'écran en deux",
        "spotify à gauche et firefox à droite",
    ],
    patterns=[
        r"(?:mets |organise |range |place )?(?:les (?:deux )?fenêtres )?côte à côte",
        r"(?:partage|divise|sépare) l'écran(?: en deux)?",
        r"(?P<left>.+?) à gauche (?:et|,) (?P<right>.+?) à droite",
    ],
    params={
        "left": "Fenêtre à placer à gauche (vide = active)",
        "right": "Fenêtre à placer à droite (vide = précédente)",
    },
    category="fenêtres",
)
async def snap_windows(left: str = "", right: str = "") -> str:
    windows = await _win.run_blocking(_win.list_windows)
    if len(windows) < 2:
        raise ToolError("il faut au moins deux fenêtres.")
    active = await _win.run_blocking(_win.foreground_window)
    if left.strip():
        left_hwnd = (await _win.run_blocking(_find_window, left))[0]
    else:
        left_hwnd = active if active else windows[0][0]
    if right.strip():
        right_hwnd = (await _win.run_blocking(_find_window, right))[0]
    else:
        right_hwnd = next((h for h, _, _ in windows if h != left_hwnd), windows[1][0])
    x, y, w, h = await _win.run_blocking(_win.work_area)
    half = w // 2
    await _win.run_blocking(_win.move_window, left_hwnd, x, y, half, h)
    await _win.run_blocking(_win.move_window, right_hwnd, x + half, y, w - half, h)
    await _win.run_blocking(_win.focus_window, left_hwnd)
    return "Fenêtres côte à côte."


@tool(
    name="show_desktop",
    description="Réduit toutes les fenêtres pour afficher le bureau.",
    examples=[
        "montre le bureau",
        "affiche le bureau",
        "réduis tout",
        "minimise tout",
        "cache toutes les fenêtres",
    ],
    patterns=[
        r"(?:montre|affiche|va sur) (?:le )?bureau",
        r"(?:réduis|minimise|cache) (?:tout|toutes les fenêtres)",
    ],
    category="fenêtres",
)
async def show_desktop() -> str:
    await _win.run_blocking(_win.minimize_all)
    return ""


@tool(
    name="switch_window",
    description="Bascule vers une fenêtre par son titre ou le nom de son application.",
    examples=[
        "bascule sur la fenêtre de firefox",
        "passe à la fenêtre discord",
        "va sur la fenêtre du terminal",
    ],
    patterns=[r"(?:bascule|passe|va) (?:sur|à|vers) la fenêtre (?:de |du |d')?(?P<target>.+)"],
    params={"target": "Titre de fenêtre ou nom d'application"},
    category="fenêtres",
)
async def switch_window(target: str) -> str:
    hwnd, title = await _win.run_blocking(_find_window, target)
    await _win.run_blocking(_win.focus_window, hwnd)
    return f"{title[:40]} est au premier plan."
