"""Exécuteur : confirmation, gestion d'erreurs, persona, LLM simulé."""

from __future__ import annotations

import asyncio

import pytest
from alfred.config import AlfredConfig, RouterConfig
from alfred.core.context import ConversationContext
from alfred.core.executor import Executor, is_no, is_yes
from alfred.core.llm import LLMReply, LLMUnavailable, ToolCall
from alfred.core.router import Router
from alfred.persona.responses import categories, pick
from alfred.tools.base import all_tools


class Harness:
    def __init__(
        self,
        cfg: AlfredConfig | None = None,
        llm: object | None = None,
        confirm_answer: bool = True,
    ) -> None:
        self.cfg = cfg or AlfredConfig()
        self.spoken: list[str] = []
        self.questions: list[str] = []
        self.confirm_answer = confirm_answer
        self.context = ConversationContext(5)
        router = Router(RouterConfig(), all_tools(), semantic=None)
        self.executor = Executor(self.cfg, router, llm, self.context, self._speak, self._confirm)  # type: ignore[arg-type]

    async def _speak(self, text: str) -> None:
        self.spoken.append(text)

    async def _confirm(self, question: str) -> bool:
        self.questions.append(question)
        return self.confirm_answer


async def test_level1_tool_executes_and_speaks(system) -> None:
    h = Harness()
    result = await h.executor.handle("monte le son")
    assert result.tool == "set_volume"
    assert result.metrics.level == 1
    assert "Volume à 60 pour cent" in h.spoken[-1]
    assert system.volume == 60
    assert h.context.last() is not None and h.context.last().tool == "set_volume"


async def test_destructive_tool_asks_confirmation(system) -> None:
    h = Harness(confirm_answer=False)
    result = await h.executor.handle("éteins l'ordinateur")
    assert result.cancelled
    assert h.questions and "éteint" in h.questions[0].lower()
    assert system.called("shutdown") == []


async def test_destructive_tool_confirmed(system) -> None:
    h = Harness(confirm_answer=True)
    result = await h.executor.handle("éteins l'ordinateur")
    assert not result.cancelled
    assert system.called("shutdown") == [(5,)]


async def test_confirmation_disabled_in_config(system) -> None:
    cfg = AlfredConfig()
    cfg.behavior.confirm_destructive = False
    h = Harness(cfg)
    await h.executor.handle("redémarre le pc")
    assert h.questions == []
    assert system.called("restart") == [(5,)]


async def test_tool_error_is_spoken_not_raised(system) -> None:
    h = Harness()
    result = await h.executor.handle("mets le volume à beaucoup")
    assert result.tool == "set_volume"
    assert "beaucoup" in h.spoken[-1]
    assert system.called("set_volume") == []


async def test_unexpected_exception_never_propagates(system, monkeypatch) -> None:
    from alfred.tools import _win

    def boom() -> int:
        raise RuntimeError("COM cassé")

    monkeypatch.setattr(_win, "get_volume", boom)
    h = Harness()
    result = await h.executor.handle("monte le son")
    assert "RuntimeError" in h.spoken[-1]
    assert result.metrics.tool == "set_volume"


async def test_slow_tool_gets_early_acknowledgement(system, monkeypatch) -> None:
    from alfred.core import executor as ex

    monkeypatch.setattr(ex, "ACK_DELAY_S", 0.01)

    async def slow_get() -> int:
        await asyncio.sleep(0.05)
        return 50

    from alfred.tools import _win

    monkeypatch.setattr(
        _win,
        "run_blocking",
        lambda fn, *a: slow_get() if fn is _win.get_volume else asyncio.sleep(0),
    )
    h = Harness()
    await h.executor.handle("monte le son")
    assert len(h.spoken) == 2
    assert h.spoken[0] in {pick("wait", detail="") for _ in range(20)} | {
        "Un instant, monsieur.",
        "Je m'en occupe.",
        "Tout de suite.",
    }


async def test_concise_mode(system) -> None:
    cfg = AlfredConfig()
    cfg.persona.mode = "concise"
    h = Harness(cfg)
    await h.executor.handle("pause")  # media_play_pause renvoie "" → accusé générique
    assert h.spoken[-1] in {"Fait.", "Voilà.", "Bien."}


async def test_llm_unavailable(system) -> None:
    class DeadLLM:
        async def chat(self, messages, tools=None, model=None):
            raise LLMUnavailable("down")

    h = Harness(llm=DeadLLM())
    result = await h.executor.handle("quelle heure est-il sur mars")
    assert result.metrics.level == 3
    assert "modèle" in h.spoken[-1].lower() or "ollama" in h.spoken[-1].lower()


async def test_llm_tool_call_is_executed(system) -> None:
    class ToolLLM:
        async def chat(self, messages, tools=None, model=None):
            assert messages[0]["role"] == "system"
            assert any(t["function"]["name"] == "set_volume" for t in tools)
            return LLMReply(tool_calls=[ToolCall("set_volume", {"level": "25"})], model="fake")

    h = Harness(llm=ToolLLM())
    result = await h.executor.handle("j'aimerais un peu moins de bruit, un quart disons")
    assert result.tool == "set_volume"
    assert system.volume == 25
    assert result.metrics.llm_ms >= 0


async def test_llm_free_answer(system) -> None:
    class ChatLLM:
        async def chat(self, messages, tools=None, model=None):
            return LLMReply(text="Canberra, monsieur.", model="fake")

    h = Harness(llm=ChatLLM())
    await h.executor.handle("quelle est la capitale de l'australie")
    assert h.spoken[-1] == "Canberra, monsieur."
    assert h.context.last() is not None and h.context.last().assistant == "Canberra, monsieur."


async def test_no_llm_configured(system) -> None:
    h = Harness(llm=None)
    await h.executor.handle("raconte une blague")
    assert h.spoken


def test_yes_no_detection() -> None:
    assert is_yes("Oui.")
    assert is_yes("oui bien sûr")
    assert is_yes("d'accord")
    assert not is_yes("non merci")
    assert is_no("Non")
    assert is_no("annule tout")
    assert not is_no("oui")


def test_responses_have_both_modes() -> None:
    for cat in categories():
        assert pick(cat, "formal", "madame", "détail")
        assert pick(cat, "concise", "madame", "détail")
    assert pick("done", "inexistant") in {
        "C'est fait.",
        "C'est fait, monsieur.",
        "Voilà qui est fait.",
        "Bien, monsieur.",
        "À vos ordres.",
        "Comme vous voudrez.",
    }


def test_context_history_and_anaphora() -> None:
    ctx = ConversationContext(2)
    ctx.add("ouvre spotify", "Spotify est ouvert.", "open_app", {"app": "spotify"})
    ctx.add("monte le son", "Volume à 60.", "set_volume", {"up": "monte"})
    ctx.add("pause", "Fait.", "media_play_pause", {})
    assert len(ctx.turns) == 2  # borné
    assert ctx.last_tool_arg("app") is None  # sorti de l'historique
    ctx.add("ouvre firefox", "Firefox est ouvert.", "open_app", {"app": "firefox"})
    assert ctx.last_tool_arg("app") == "firefox"
    msgs = ctx.as_messages()
    assert msgs[0]["role"] == "user" and msgs[1]["role"] == "assistant"
    assert "[open_app]" in msgs[-1]["content"]


@pytest.mark.parametrize("mode", ["formal", "concise"])
def test_system_prompt_mentions_tools(mode: str) -> None:
    from alfred.persona.prompt import build_system_prompt

    prompt = build_system_prompt(mode, "madame")
    assert "madame" in prompt
    assert "set_volume" in prompt
    assert ("CONCIS" in prompt) == (mode == "concise")
