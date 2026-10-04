"""Exécuteur : orchestre routage → confirmation → exécution → réponse parlée.

Garanties :
- ne lève jamais vers l'appelant : tout échec devient une phrase prononcée ;
- le TTS démarre pendant l'exécution (accusé de réception immédiat) ;
- les tools ``confirm=True`` passent par une confirmation vocale/texte ;
- chaque étape est chronométrée (``Metrics``) pour l'overlay en mode debug.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from alfred.config import AlfredConfig
from alfred.core.context import ConversationContext
from alfred.core.llm import LLMReply, LLMUnavailable, OllamaClient
from alfred.core.router import RouteDecision, Router
from alfred.persona.prompt import build_system_prompt
from alfred.persona.responses import pick
from alfred.tools.base import ToolError, ToolSpec, get_tool

log = logging.getLogger(__name__)

# Fonction de confirmation : reçoit la question, renvoie True si l'utilisateur confirme.
ConfirmFn = Callable[[str], Awaitable[bool]]
# Fonction d'énonciation : (texte, interrompre ?) → attend la fin de la synthèse.
SpeakFn = Callable[[str], Awaitable[None]]

ACK_DELAY_S = 0.35  # au-delà, Alfred dit « un instant » pendant que le tool travaille

_YES = {
    "oui",
    "ouais",
    "confirme",
    "confirmé",
    "d'accord",
    "ok",
    "vas-y",
    "allez-y",
    "affirmatif",
    "certainement",
    "bien sûr",
}
_NO = {"non", "annule", "annuler", "stop", "laisse tomber", "négatif", "surtout pas"}


def is_yes(text: str) -> bool:
    t = text.strip().lower().rstrip(".!")
    return any(t == y or t.startswith(y + " ") for y in _YES)


def is_no(text: str) -> bool:
    t = text.strip().lower().rstrip(".!")
    return any(t == n or t.startswith(n + " ") for n in _NO)


@dataclass(slots=True)
class Metrics:
    route_ms: float = 0.0
    llm_ms: float = 0.0
    tool_ms: float = 0.0
    total_ms: float = 0.0
    level: int = 0
    tool: str = ""

    def as_text(self) -> str:
        parts = [f"niveau {self.level}"]
        if self.tool:
            parts.append(self.tool)
        parts.append(f"route {self.route_ms:.0f} ms")
        if self.llm_ms:
            parts.append(f"llm {self.llm_ms:.0f} ms")
        if self.tool_ms:
            parts.append(f"tool {self.tool_ms:.0f} ms")
        parts.append(f"total {self.total_ms:.0f} ms")
        return " · ".join(parts)


@dataclass(slots=True)
class ExecutionResult:
    spoken: str
    metrics: Metrics = field(default_factory=Metrics)
    tool: str | None = None
    cancelled: bool = False


class Executor:
    def __init__(
        self,
        cfg: AlfredConfig,
        router: Router,
        llm: OllamaClient | None,
        context: ConversationContext,
        speak: SpeakFn,
        confirm: ConfirmFn,
    ) -> None:
        self._cfg = cfg
        self._router = router
        self._llm = llm
        self._ctx = context
        self._speak = speak
        self._confirm = confirm

    def apply(self, cfg: AlfredConfig) -> None:
        self._cfg = cfg
        self._ctx.set_max_turns(cfg.behavior.history_turns)

    # ---- helpers persona ---------------------------------------------
    def _say(self, category: str, detail: str = "") -> str:
        p = self._cfg.persona
        return pick(category, p.mode, p.address, detail)

    # ---- point d'entrée ----------------------------------------------
    async def handle(self, text: str) -> ExecutionResult:
        """Traite une commande de bout en bout. Ne lève jamais."""
        started = time.perf_counter()
        metrics = Metrics()
        try:
            result = await self._handle_inner(text, metrics)
        except asyncio.CancelledError:
            return ExecutionResult(spoken="", metrics=metrics, cancelled=True)
        except Exception as exc:
            log.exception("Erreur inattendue pendant le traitement de « %s »", text)
            spoken = self._say("error", f"une erreur interne est survenue ({type(exc).__name__}).")
            await self._speak(spoken)
            result = ExecutionResult(spoken=spoken, metrics=metrics)
        result.metrics.total_ms = (time.perf_counter() - started) * 1000
        log.info("« %s » → %s", text, result.metrics.as_text())
        return result

    async def _handle_inner(self, text: str, metrics: Metrics) -> ExecutionResult:
        text = text.strip()
        if not text:
            spoken = self._say("nothing_heard")
            await self._speak(spoken)
            return ExecutionResult(spoken=spoken, metrics=metrics)

        decision: RouteDecision = self._router.route(text)
        metrics.route_ms = decision.latency_ms
        metrics.level = decision.level

        if decision.level in (1, 2) and decision.tool is not None:
            return await self._run_tool(text, decision.tool, decision.args, metrics)

        if decision.level == 3:
            return await self._run_llm(text, metrics)

        spoken = self._say("unknown")
        await self._speak(spoken)
        return ExecutionResult(spoken=spoken, metrics=metrics)

    # ---- exécution d'un tool -----------------------------------------
    async def _run_tool(
        self, text: str, spec: ToolSpec, args: dict[str, Any], metrics: Metrics
    ) -> ExecutionResult:
        metrics.tool = spec.name

        if spec.confirm and self._cfg.behavior.confirm_destructive:
            question = self._say(
                "confirm", spec.description.rstrip(".").lower().replace(" (après confirmation)", "")
            )
            if not await self._confirm(question):
                spoken = self._say("cancelled")
                await self._speak(spoken)
                self._ctx.add(text, spoken)
                return ExecutionResult(spoken=spoken, metrics=metrics, cancelled=True)

        started = time.perf_counter()
        # Le tool tourne en tâche ; si l'exécution dépasse ACK_DELAY_S, on prononce un
        # court accusé de réception pendant qu'elle se poursuit (TTS pendant l'exécution).
        task = asyncio.ensure_future(spec.invoke(**args))
        try:
            try:
                detail = await asyncio.wait_for(asyncio.shield(task), timeout=ACK_DELAY_S)
            except TimeoutError:
                await self._speak(self._say("wait"))
                detail = await task
        except asyncio.CancelledError:
            # Le shield absorbe l'annulation : sans cela le tool poursuivrait ses effets
            # de bord après un Échap, et son exception ne serait jamais récupérée.
            task.cancel()
            raise
        except ToolError as exc:
            spoken = self._say("error", str(exc))
            await self._speak(spoken)
            self._ctx.add(text, spoken, spec.name, args)
            metrics.tool_ms = (time.perf_counter() - started) * 1000
            return ExecutionResult(spoken=spoken, metrics=metrics, tool=spec.name)
        except Exception as exc:
            log.exception("Le tool %s a échoué", spec.name)
            spoken = self._say("error", f"{spec.name} a échoué ({type(exc).__name__}).")
            await self._speak(spoken)
            self._ctx.add(text, spoken, spec.name, args)
            metrics.tool_ms = (time.perf_counter() - started) * 1000
            return ExecutionResult(spoken=spoken, metrics=metrics, tool=spec.name)
        metrics.tool_ms = (time.perf_counter() - started) * 1000

        spoken = self._say("done_detail", detail) if detail else self._say("done")
        await self._speak(spoken)
        self._ctx.add(text, spoken, spec.name, args)
        return ExecutionResult(spoken=spoken, metrics=metrics, tool=spec.name)

    # ---- niveau 3 : LLM ----------------------------------------------
    async def _run_llm(self, text: str, metrics: Metrics) -> ExecutionResult:
        if self._llm is None:
            spoken = self._say("llm_down")
            await self._speak(spoken)
            return ExecutionResult(spoken=spoken, metrics=metrics)

        p = self._cfg.persona
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(p.mode, p.address)}
        ]
        messages.extend(self._ctx.as_messages())
        messages.append({"role": "user", "content": text})
        tools_schema = [t.json_schema() for t in self._router.tools]

        started = time.perf_counter()
        try:
            reply: LLMReply = await self._llm.chat(messages, tools_schema)
        except LLMUnavailable:
            metrics.llm_ms = (time.perf_counter() - started) * 1000
            spoken = self._say("llm_down")
            await self._speak(spoken)
            return ExecutionResult(spoken=spoken, metrics=metrics)
        metrics.llm_ms = (time.perf_counter() - started) * 1000

        # Le LLM a choisi un ou plusieurs tools : on les exécute dans l'ordre.
        if reply.tool_calls:
            spoken_parts: list[str] = []
            last_tool: str | None = None
            for call in reply.tool_calls:
                spec = get_tool(call.name)
                if spec is None:
                    log.warning("Le LLM a appelé un tool inconnu : %s", call.name)
                    continue
                result = await self._run_tool(text, spec, call.arguments, metrics)
                spoken_parts.append(result.spoken)
                last_tool = spec.name
                if result.cancelled:
                    break
            return ExecutionResult(spoken=" ".join(spoken_parts), metrics=metrics, tool=last_tool)

        # Réponse conversationnelle (question ouverte).
        spoken = reply.text or self._say("unknown")
        await self._speak(spoken)
        self._ctx.add(text, spoken)
        return ExecutionResult(spoken=spoken, metrics=metrics)
