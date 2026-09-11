"""Tools système : volume, luminosité, veille, verrouillage, arrêt, capture, ne-pas-déranger.

Ce module sert d'exemple de référence : chaque tool déclare ses patterns de
niveau 1, ses exemples de niveau 2 et ses paramètres pour le niveau 3.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from alfred.tools import _win
from alfred.tools.base import ToolError, tool

# Nombres en toutes lettres que Whisper produit parfois (« mets le son à cinquante »)
_WORD_NUMBERS: dict[str, int] = {
    "zéro": 0,
    "cinq": 5,
    "dix": 10,
    "quinze": 15,
    "vingt": 20,
    "vingt-cinq": 25,
    "vingt cinq": 25,
    "trente": 30,
    "trente-cinq": 35,
    "quarante": 40,
    "quarante-cinq": 45,
    "cinquante": 50,
    "soixante": 60,
    "soixante-dix": 70,
    "soixante dix": 70,
    "quatre-vingts": 80,
    "quatre vingts": 80,
    "quatre-vingt": 80,
    "quatre-vingt-dix": 90,
    "cent": 100,
    "moitié": 50,
    "maximum": 100,
    "max": 100,
    "fond": 100,
    "minimum": 0,
}


def parse_level(raw: str, current: int, step: int = 10) -> int:
    """Interprète « 30 », « 30 % », « +10 », « -20 », « plus », « moins », « cinquante », « à fond ».

    Retourne une valeur absolue bornée à [0, 100].
    """
    text = raw.strip().lower().replace("%", "").replace("pour cent", "").strip()
    if text in {"plus", "monte", "augmente", "up"}:
        return min(100, current + step)
    if text in {"moins", "baisse", "diminue", "down"}:
        return max(0, current - step)
    m = re.fullmatch(r"([+-])\s*(\d+)", text)
    if m:
        delta = int(m.group(2)) * (1 if m.group(1) == "+" else -1)
        return max(0, min(100, current + delta))
    if text.isdigit():
        return max(0, min(100, int(text)))
    if text in _WORD_NUMBERS:
        return _WORD_NUMBERS[text]
    raise ToolError(f"je n'ai pas compris le niveau « {raw} ».")


def _resolve(level: str, up: str, down: str, delta: str, current: int, what: str) -> int:
    """Logique commune volume / luminosité : direction + delta, ou niveau explicite."""
    step = delta or "10"
    if up:
        return parse_level(f"+{step}", current)
    if down:
        return parse_level(f"-{step}", current)
    if level:
        return parse_level(level, current)
    raise ToolError(f"précisez un niveau de {what}.")


# ----------------------------------------------------------------------
# Volume
# ----------------------------------------------------------------------


@tool(
    name="set_volume",
    description="Règle le volume système : valeur absolue (0-100), delta relatif (+10 / -10) ou mot-clé (plus / moins).",
    examples=[
        "monte le son",
        "baisse le volume",
        "mets le volume à 30 %",
        "augmente le son",
        "réduis le volume",
        "mets le son à fond",
        "volume à cinquante",
        "plus fort",
        "moins fort",
    ],
    patterns=[
        r"(?P<up>monte|augmente|hausse) (?:un peu )?(?:le )?(?:son|volume)(?: un peu)?(?: de (?P<delta>\d+))?",
        r"(?P<down>baisse|diminue|réduis) (?:un peu )?(?:le )?(?:son|volume)(?: un peu)?(?: de (?P<delta>\d+))?",
        r"(?:mets|règle|met|passe) (?:le )?(?:son|volume) (?:à|a|sur|au) (?P<level>[\w\s-]+?)(?: ?%| pour cent)?",
        r"(?:volume|son) (?:à|a|sur|au) (?P<level>[\w\s-]+?)(?: ?%| pour cent)?",
        r"(?P<up>plus) fort",
        r"(?P<down>moins) fort",
    ],
    params={
        "level": (
            "Niveau sonore cible, en pourcentage : « 25 » pour un quart, « 50 » pour la moitié, "
            "« 100 » pour le maximum. Accepte aussi un delta relatif : « +10 » pour monter, « -10 » pour baisser."
        ),
        "up": "Usage interne : présent si la commande demande d'augmenter",
        "down": "Usage interne : présent si la commande demande de baisser",
        "delta": "Usage interne : amplitude du delta",
    },
    internal=["up", "down", "delta"],
    category="système",
)
async def set_volume(level: str = "", up: str = "", down: str = "", delta: str = "") -> str:
    current = await _win.run_blocking(_win.get_volume)
    target = _resolve(level, up, down, delta, current, "volume")
    await _win.run_blocking(_win.set_volume, target)
    return f"Volume à {target} pour cent."


@tool(
    name="mute",
    description="Coupe ou rétablit le son du système.",
    examples=["coupe le son", "mute", "silence", "remets le son", "rétablis le son", "muet"],
    patterns=[
        r"(?:coupe|couper) (?:le )?(?:son|volume)",
        r"(?:mute|muet|silence)",
        r"(?:remets|rétablis|remet|réactive) (?:le )?(?:son|volume)",
    ],
    params={"muted": "true pour couper, false pour rétablir ; vide = basculer"},
    category="système",
)
async def mute(muted: str = "") -> str:
    if muted == "":
        target = not await _win.run_blocking(_win.is_muted)
    else:
        target = muted.strip().lower() in {"true", "1", "oui", "vrai"}
    await _win.run_blocking(_win.set_mute, target)
    return "Son coupé." if target else "Son rétabli."


# ----------------------------------------------------------------------
# Luminosité
# ----------------------------------------------------------------------


@tool(
    name="set_brightness",
    description="Règle la luminosité de l'écran : valeur absolue 0-100, delta (+10 / -10) ou mot-clé.",
    examples=[
        "monte la luminosité",
        "baisse la luminosité",
        "luminosité à 40 %",
        "écran plus lumineux",
        "écran moins lumineux",
        "mets la luminosité au maximum",
    ],
    patterns=[
        r"(?P<up>monte|augmente) (?:la )?luminosité(?: de (?P<delta>\d+))?",
        r"(?P<down>baisse|diminue|réduis) (?:la )?luminosité(?: de (?P<delta>\d+))?",
        r"(?:mets |règle )?(?:la )?luminosité (?:à|a|sur|au) (?P<level>[\w\s-]+?)(?: ?%| pour cent)?",
        r"écran (?P<up>plus) lumineux",
        r"écran (?P<down>moins) lumineux",
    ],
    params={
        "level": (
            "Luminosité cible en pourcentage : « 40 », « 100 » pour le maximum. "
            "Accepte aussi un delta relatif : « +10 » / « -10 »."
        ),
        "up": "Usage interne",
        "down": "Usage interne",
        "delta": "Usage interne",
    },
    internal=["up", "down", "delta"],
    category="système",
)
async def set_brightness(level: str = "", up: str = "", down: str = "", delta: str = "") -> str:
    try:
        current = await _win.run_blocking(_win.get_brightness)
    except Exception as exc:
        raise ToolError("cet écran ne permet pas de régler la luminosité.") from exc
    target = _resolve(level, up, down, delta, current, "luminosité")
    await _win.run_blocking(_win.set_brightness, target)
    return f"Luminosité à {target} pour cent."


# ----------------------------------------------------------------------
# Session / alimentation
# ----------------------------------------------------------------------


@tool(
    name="lock",
    description="Verrouille la session Windows.",
    examples=["verrouille", "verrouille l'écran", "verrouille la session", "verrouillage"],
    patterns=[r"verrouill(?:e|age)(?: (?:l'écran|la session|le pc|l'ordinateur))?"],
    category="système",
)
async def lock() -> str:
    await _win.run_blocking(_win.lock_workstation)
    return "Session verrouillée."


@tool(
    name="sleep",
    description="Met l'ordinateur en veille.",
    examples=["mets en veille", "veille", "mise en veille", "endors l'ordinateur"],
    patterns=[
        r"(?:mets? (?:le pc |l'ordinateur )?en )?veille",
        r"mise en veille",
        r"endors (?:le pc|l'ordinateur)",
    ],
    category="système",
)
async def sleep() -> str:
    await _win.run_blocking(_win.sleep_pc)
    return "Bonne nuit."


@tool(
    name="shutdown",
    description="Éteint l'ordinateur (après confirmation).",
    examples=["éteins l'ordinateur", "arrête le pc", "extinction", "éteins tout"],
    patterns=[
        r"(?:éteins|arrête|éteindre|arrêter) (?:le pc|l'ordinateur|la machine|tout)",
        r"extinction",
    ],
    confirm=True,
    category="système",
)
async def shutdown() -> str:
    await _win.run_blocking(_win.shutdown_pc, 5)
    return "Extinction dans cinq secondes."


@tool(
    name="restart",
    description="Redémarre l'ordinateur (après confirmation).",
    examples=["redémarre l'ordinateur", "redémarre le pc", "reboot"],
    patterns=[r"redémarre (?:le pc|l'ordinateur|la machine)", r"reboot"],
    confirm=True,
    category="système",
)
async def restart() -> str:
    await _win.run_blocking(_win.restart_pc, 5)
    return "Redémarrage dans cinq secondes."


@tool(
    name="abort_shutdown",
    description="Annule un arrêt ou un redémarrage programmé.",
    examples=["annule l'arrêt", "annule l'extinction", "annule le redémarrage"],
    patterns=[r"annule (?:l'arrêt|l'extinction|le redémarrage)"],
    category="système",
)
async def abort_shutdown() -> str:
    await _win.run_blocking(_win.abort_shutdown)
    return "Arrêt annulé."


# ----------------------------------------------------------------------
# Capture d'écran
# ----------------------------------------------------------------------


@tool(
    name="screenshot",
    description="Prend une capture de tous les écrans et l'enregistre dans le dossier Images.",
    examples=["capture d'écran", "fais une capture", "screenshot", "prends une capture d'écran"],
    patterns=[r"(?:fais |prends |prend )?(?:une )?capture(?: d'écran)?", r"screenshot"],
    category="système",
)
async def screenshot() -> str:
    folder = Path.home() / "Pictures" / "Alfred"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"capture_{datetime.now():%Y-%m-%d_%H-%M-%S}.png"
    await _win.run_blocking(_win.screenshot, str(path))
    return "Capture enregistrée dans le dossier Images."


# ----------------------------------------------------------------------
# Ne pas déranger
# ----------------------------------------------------------------------


@tool(
    name="do_not_disturb",
    description="Active ou désactive le mode ne-pas-déranger (notifications Windows).",
    examples=[
        "ne pas déranger",
        "active le mode ne pas déranger",
        "désactive le mode ne pas déranger",
        "coupe les notifications",
        "remets les notifications",
    ],
    patterns=[
        r"(?:active |mets |mode )?(?:le mode )?ne pas déranger",
        r"(?:coupe|désactive|bloque) les notifications",
        r"(?:remets|réactive|active) les notifications",
        r"désactive (?:le mode )?ne pas déranger",
    ],
    params={"enabled": "true pour activer, false pour désactiver ; vide = basculer"},
    category="système",
)
async def do_not_disturb(enabled: str = "") -> str:
    if enabled == "":
        target = not await _win.run_blocking(_win.get_do_not_disturb)
    else:
        target = enabled.strip().lower() in {"true", "1", "oui", "vrai"}
    await _win.run_blocking(_win.set_do_not_disturb, target)
    return "Mode ne pas déranger activé." if target else "Notifications rétablies."
