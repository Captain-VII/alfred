"""Média : lecture/pause, suivant, précédent, stop — via touches média virtuelles.

Fonctionne avec toute application qui écoute les touches média : Spotify,
YouTube dans le navigateur, VLC, Windows Media Player…
"""

from __future__ import annotations

from alfred.tools import _win
from alfred.tools.base import tool


@tool(
    name="media_play_pause",
    description="Met en pause ou reprend la lecture en cours (musique, vidéo).",
    examples=[
        "pause",
        "play",
        "lecture",
        "reprends la musique",
        "mets en pause",
        "continue la musique",
        "joue",
    ],
    patterns=[
        r"(?:mets? (?:la musique |la vidéo |ça )?en )?pause",
        r"(?:reprends|relance|continue|remets)(?: la (?:musique|lecture|vidéo))?",
        r"(?:play|lecture|joue|lis)(?: la musique)?",
    ],
    category="média",
)
async def media_play_pause() -> str:
    await _win.run_blocking(_win.press_vk, _win.VK_MEDIA_PLAY_PAUSE)
    return ""


@tool(
    name="media_next",
    description="Passe à la piste suivante.",
    examples=[
        "suivant",
        "piste suivante",
        "chanson suivante",
        "passe à la suivante",
        "skip",
        "musique suivante",
        "mets la chanson d'après",
        "la musique d'après",
        "morceau suivant",
        "titre suivant",
        "zappe cette chanson",
    ],
    patterns=[
        r"(?:piste |chanson |musique |morceau |titre )?suivante?",
        r"(?:passe|va) (?:à|au) (?:la |le )?(?:suivante?|morceau suivant|titre suivant)",
        r"(?:skip|zappe)(?: (?:cette|la) (?:chanson|musique|piste))?",
    ],
    category="média",
)
async def media_next() -> str:
    await _win.run_blocking(_win.press_vk, _win.VK_MEDIA_NEXT_TRACK)
    return ""


@tool(
    name="media_previous",
    description="Revient à la piste précédente.",
    examples=[
        "précédent",
        "piste précédente",
        "chanson précédente",
        "reviens en arrière",
        "remets la chanson d'avant",
        "morceau précédent",
        "titre précédent",
        "rejoue la musique d'avant",
        "retour au morceau précédent",
    ],
    patterns=[
        r"(?:piste |chanson |musique |morceau |titre )?précédente?",
        r"(?:reviens|retourne) (?:en arrière|à la précédente|au morceau précédent)",
        r"(?:remets|rejoue) (?:la (?:chanson|musique|piste) d'avant|le morceau d'avant)",
    ],
    category="média",
)
async def media_previous() -> str:
    await _win.run_blocking(_win.press_vk, _win.VK_MEDIA_PREV_TRACK)
    return ""


@tool(
    name="media_stop",
    description="Arrête complètement la lecture.",
    examples=["stop la musique", "arrête la musique", "coupe la musique", "arrête la lecture"],
    patterns=[r"(?:stop|arrête|coupe|stoppe) (?:la )?(?:musique|lecture|vidéo|son de la musique)"],
    category="média",
)
async def media_stop() -> str:
    await _win.run_blocking(_win.press_vk, _win.VK_MEDIA_STOP)
    return ""
