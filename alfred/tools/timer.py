"""Minuteurs et rappels : notification Windows + annonce vocale + son.

« rappelle-moi dans 20 minutes de sortir le gâteau », « minuteur de 5 minutes »,
« dans une heure et demie, rappelle-moi d'appeler Marc ».
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

from alfred.core import services
from alfred.tools.base import ToolError, tool

log = logging.getLogger(__name__)

_NUMBER_WORDS: dict[str, float] = {
    "un": 1,
    "une": 1,
    "deux": 2,
    "trois": 3,
    "quatre": 4,
    "cinq": 5,
    "six": 6,
    "sept": 7,
    "huit": 8,
    "neuf": 9,
    "dix": 10,
    "onze": 11,
    "douze": 12,
    "treize": 13,
    "quatorze": 14,
    "quinze": 15,
    "seize": 16,
    "vingt": 20,
    "trente": 30,
    "quarante": 40,
    "cinquante": 50,
    "soixante": 60,
    "quart": 0.25,
    "demi": 0.5,
    "demie": 0.5,
}
_UNITS: dict[str, float] = {
    "seconde": 1,
    "secondes": 1,
    "sec": 1,
    "s": 1,
    "minute": 60,
    "minutes": 60,
    "min": 60,
    "mn": 60,
    "heure": 3600,
    "heures": 3600,
    "h": 3600,
}
_DURATION_TOKEN = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)?|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")?\s*"
    r"(?P<unit>secondes?|sec|minutes?|min|mn|heures?|h)\b"
    r"(?:\s*(?:et\s+)?(?P<half>demie?|quart))?",
    re.IGNORECASE,
)


def parse_duration(text: str) -> float:
    """« 20 minutes », « 1 h 30 », « une heure et demie », « 90 secondes », « un quart d'heure » → secondes."""
    t = text.lower().replace("’", "'").strip()
    t = re.sub(r"\bun quart d'heure\b", "15 minutes", t)
    t = re.sub(r"\bune demi[- ]heure\b", "30 minutes", t)
    t = re.sub(r"\btrois quarts d'heure\b", "45 minutes", t)
    t = re.sub(r"(\d+)\s*h\s*(\d+)\b", r"\1 heures \2 minutes", t)
    total = 0.0
    for m in _DURATION_TOKEN.finditer(t):
        raw = (m.group("num") or "1").replace(",", ".")
        num = float(raw) if raw.replace(".", "", 1).isdigit() else _NUMBER_WORDS.get(raw, 1)
        unit = m.group("unit").lower()
        seconds = _UNITS.get(unit, _UNITS.get(unit.rstrip("s"), 60))
        total += num * seconds
        if m.group("half"):
            total += seconds * (0.5 if m.group("half").startswith("demi") else 0.25)
    if total <= 0:
        raise ToolError(f"je n'ai pas compris la durée « {text} ».")
    return total


def humanize(seconds: float) -> str:
    seconds = round(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts: list[str] = []
    if h:
        parts.append(f"{h} heure{'s' if h > 1 else ''}")
    if m:
        parts.append(f"{m} minute{'s' if m > 1 else ''}")
    if s and not h:
        parts.append(f"{s} seconde{'s' if s > 1 else ''}")
    return " et ".join(parts) if parts else "quelques secondes"


@dataclass(slots=True)
class Timer:
    id: int
    label: str
    ends_at: float
    task: asyncio.Task[None] | None = field(default=None, repr=False)

    @property
    def remaining(self) -> float:
        return max(0.0, self.ends_at - time.time())


_timers: dict[int, Timer] = {}
_next_id = 1


async def _ring(timer: Timer) -> None:
    try:
        await asyncio.sleep(timer.remaining)
    except asyncio.CancelledError:
        return
    _timers.pop(timer.id, None)
    message = timer.label or "le temps est écoulé"
    log.info("Minuteur %d : %s", timer.id, message)
    services.notify("Alfred — rappel", message[0].upper() + message[1:])
    try:
        from alfred.audio.sounds import SoundPlayer

        SoundPlayer(True).play("timer")
    except Exception:
        pass
    address = services.cfg().persona.address
    spoken = (
        f"{address.capitalize()}, {message}."
        if timer.label
        else f"{address.capitalize()}, le temps est écoulé."
    )
    await services.say(spoken)


def _clean_label(label: str) -> str:
    label = label.strip().rstrip(".!?")
    label = re.sub(r"^(?:de |d'|que |pour )", "", label)
    return label


_DUR = r"(?P<duration>(?:\d+(?:[.,]\d+)?|une?|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|quinze|vingt|trente|quarante|cinquante)\s*(?:h|heures?|min|minutes?|mn|secondes?|sec)(?:\s*(?:\d+|et\s+demie?|et\s+quart|\d+\s*(?:min|minutes?)))?|un quart d'heure|une demi[- ]heure|trois quarts d'heure)"


@tool(
    name="set_timer",
    description="Programme un rappel ou un minuteur : notification Windows et annonce vocale à l'échéance.",
    examples=[
        "rappelle-moi dans 20 minutes",
        "minuteur de 5 minutes",
        "rappelle-moi dans une heure d'appeler Marc",
        "mets un minuteur de 10 minutes",
        "dans 30 secondes rappelle-moi de vérifier le four",
        "lance un chrono de 3 minutes",
    ],
    patterns=[
        rf"rappelle[- ]moi dans {_DUR}(?: (?P<label>.+))?",
        rf"dans {_DUR},? rappelle[- ]moi(?: (?P<label>.+))?",
        rf"(?:mets|lance|démarre|programme)? ?(?:un |le )?(?:minuteur|chrono|compte à rebours|timer|alarme) (?:de |d'|pour )?{_DUR}(?: (?:pour |: )?(?P<label>.+))?",
        rf"(?:minuteur|chrono|timer) {_DUR}",
    ],
    params={
        "duration": "Durée en langage naturel : « 20 minutes », « 1 h 30 », « 45 secondes »",
        "label": "Ce dont il faut se souvenir (optionnel) : « sortir le gâteau »",
    },
    category="minuteurs",
)
async def set_timer(duration: str, label: str = "") -> str:
    global _next_id
    seconds = parse_duration(duration)
    if seconds > 24 * 3600:
        raise ToolError("je ne programme pas de rappel au-delà de vingt-quatre heures.")
    label = _clean_label(label)
    timer = Timer(id=_next_id, label=label, ends_at=time.time() + seconds)
    _next_id += 1
    timer.task = asyncio.get_running_loop().create_task(_ring(timer))
    _timers[timer.id] = timer
    what = f" pour {label}" if label else ""
    return f"Rappel dans {humanize(seconds)}{what}."


@tool(
    name="list_timers",
    description="Énumère les minuteurs et rappels en cours.",
    examples=[
        "quels sont mes minuteurs",
        "liste les rappels",
        "combien de temps reste-t-il au minuteur",
        "mes rappels en cours",
    ],
    patterns=[
        r"(?:quels sont |liste |donne )?(?:mes |les )?(?:minuteurs|rappels|chronos)(?: en cours)?",
        r"combien de temps reste(?:-t-il)?(?: (?:au|sur le) (?:minuteur|chrono|rappel))?",
    ],
    category="minuteurs",
)
async def list_timers() -> str:
    if not _timers:
        return "Aucun rappel en cours."
    parts = [
        f"{humanize(t.remaining)}{' pour ' + t.label if t.label else ''}"
        for t in sorted(_timers.values(), key=lambda t: t.ends_at)
    ]
    if len(parts) == 1:
        return f"Un rappel : {parts[0]}."
    return f"{len(parts)} rappels : " + " ; ".join(parts) + "."


@tool(
    name="cancel_timer",
    description="Annule le prochain minuteur, ou tous les minuteurs.",
    examples=[
        "annule le minuteur",
        "annule le rappel",
        "supprime tous les minuteurs",
        "arrête le chrono",
        "annule tous les rappels",
    ],
    patterns=[
        r"(?:annule|supprime|arrête|stoppe) (?:le |mon |ce )?(?:minuteur|rappel|chrono|compte à rebours|timer|alarme)",
        r"(?:annule|supprime|arrête) (?P<all>tous) (?:les |mes )?(?:minuteurs|rappels|chronos|alarmes)",
    ],
    params={"all": "Usage interne : « tous » pour annuler tous les minuteurs"},
    internal=["all"],
    category="minuteurs",
)
async def cancel_timer(all: str = "") -> str:
    if not _timers:
        raise ToolError("aucun rappel n'est programmé.")
    if all:
        count = len(_timers)
        for t in list(_timers.values()):
            if t.task:
                t.task.cancel()
        _timers.clear()
        return f"{count} rappel{'s' if count > 1 else ''} annulé{'s' if count > 1 else ''}."
    nearest = min(_timers.values(), key=lambda t: t.ends_at)
    if nearest.task:
        nearest.task.cancel()
    _timers.pop(nearest.id, None)
    return f"Rappel{' pour ' + nearest.label if nearest.label else ''} annulé."


def active_timers() -> list[Timer]:
    return list(_timers.values())
