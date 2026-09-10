"""Historique court de conversation (les N derniers tours).

Sert à deux choses :

- donner au LLM le contexte immédiat (« ferme-la » après « ouvre Spotify ») ;
- résoudre localement, sans LLM, les anaphores les plus simples via
  :meth:`ConversationContext.last_tool_arg`.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from time import time
from typing import Any


@dataclass(slots=True)
class Turn:
    user: str
    assistant: str
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time)


class ConversationContext:
    def __init__(self, max_turns: int = 5) -> None:
        self._turns: deque[Turn] = deque(maxlen=max(1, max_turns))

    # ---- écriture ----------------------------------------------------
    def add(
        self, user: str, assistant: str, tool: str | None = None, args: dict[str, Any] | None = None
    ) -> None:
        self._turns.append(Turn(user=user, assistant=assistant, tool=tool, args=dict(args or {})))

    def clear(self) -> None:
        self._turns.clear()

    def set_max_turns(self, n: int) -> None:
        items = list(self._turns)
        self._turns = deque(items[-max(1, n) :], maxlen=max(1, n))

    # ---- lecture -----------------------------------------------------
    @property
    def turns(self) -> list[Turn]:
        return list(self._turns)

    def last(self) -> Turn | None:
        return self._turns[-1] if self._turns else None

    def last_tool_arg(self, key: str, max_age_s: float = 120.0) -> str | None:
        """Dernière valeur d'un argument (ex. ``app``) utilisée récemment par un tool."""
        now = time()
        for turn in reversed(self._turns):
            if now - turn.timestamp > max_age_s:
                break
            if turn.tool and key in turn.args and turn.args[key]:
                return str(turn.args[key])
        return None

    def as_messages(self) -> list[dict[str, str]]:
        """Format « messages » pour le LLM : alternance user / assistant."""
        messages: list[dict[str, str]] = []
        for turn in self._turns:
            messages.append({"role": "user", "content": turn.user})
            content = turn.assistant
            if turn.tool:
                content = f"[{turn.tool}] {content}"
            messages.append({"role": "assistant", "content": content})
        return messages
