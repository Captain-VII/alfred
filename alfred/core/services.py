"""Registre léger des services partagés.

Les tools ont parfois besoin du LLM (résumé web), du TTS (annonce d'un minuteur)
ou de la configuration (alias d'applications). Plutôt que d'injecter ces
dépendances dans chaque signature de tool — ce qui polluerait le schéma JSON
exposé au LLM — les composants s'enregistrent ici au démarrage.

Tout est optionnel : un tool doit tolérer ``services.tts is None`` (tests).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from alfred.config import AlfredConfig, ConfigManager
    from alfred.core.context import ConversationContext


class Speaker(Protocol):
    """Interface minimale du TTS utilisée par les tools."""

    async def say(self, text: str, interrupt: bool = False) -> None: ...


class Notifier(Protocol):
    """Notification Windows (toast)."""

    def notify(self, title: str, message: str) -> None: ...


class Summarizer(Protocol):
    """Génération libre par le LLM (résumé, traduction…)."""

    async def complete(self, system: str, user: str, max_tokens: int = 200) -> str: ...


config_manager: ConfigManager | None = None
tts: Speaker | None = None
notifier: Notifier | None = None
llm: Summarizer | None = None
overlay: Any = None  # UI, pour afficher du texte (type évité pour ne pas importer PyQt ici)
context: ConversationContext | None = None  # historique court, pour « ferme-la »


def cfg() -> AlfredConfig:
    """Configuration courante (ou défaut si aucun gestionnaire n'est enregistré)."""
    if config_manager is None:
        from alfred.config import AlfredConfig

        return AlfredConfig()
    return config_manager.current


async def say(text: str) -> None:
    """Parle si un TTS est disponible, sinon ne fait rien."""
    if tts is not None:
        await tts.say(text)


def notify(title: str, message: str) -> None:
    if notifier is not None:
        notifier.notify(title, message)


def last_arg(key: str) -> str | None:
    """Dernier argument ``key`` utilisé par un tool (résolution d'anaphore : « ferme-la »)."""
    if context is None:
        return None
    return context.last_tool_arg(key)
