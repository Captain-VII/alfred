"""Client Ollama : tool calling, streaming, warm-up, modèle de secours.

Utilise directement l'API HTTP ``/api/chat`` via ``httpx`` (async) pour rester
léger et contrôler finement les timeouts. Le modèle est préchargé avec
``keep_alive`` au démarrage pour ne jamais payer le chargement en cours d'usage.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from alfred.config import LLMConfig

log = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """Ollama injoignable ou modèle absent."""


@dataclass(slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class LLMReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    latency_ms: float = 0.0


_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


class OllamaClient:
    def __init__(self, cfg: LLMConfig) -> None:
        self._cfg = cfg
        self._client = httpx.AsyncClient(
            base_url=cfg.host, timeout=httpx.Timeout(cfg.timeout_s, connect=2.0)
        )
        self._available = False

    # ---- configuration -----------------------------------------------
    def apply(self, cfg: LLMConfig) -> None:
        """Rechargement à chaud : nouvelle base_url / timeout / modèle."""
        if cfg.host != self._cfg.host or cfg.timeout_s != self._cfg.timeout_s:
            self._client = httpx.AsyncClient(
                base_url=cfg.host, timeout=httpx.Timeout(cfg.timeout_s, connect=2.0)
            )
        self._cfg = cfg

    @property
    def available(self) -> bool:
        return self._available

    @property
    def model(self) -> str:
        return self._cfg.model

    async def close(self) -> None:
        await self._client.aclose()

    # ---- disponibilité / préchargement --------------------------------
    async def ping(self) -> bool:
        try:
            r = await self._client.get("/api/tags", timeout=2.0)
            self._available = r.status_code == 200
        except httpx.HTTPError:
            self._available = False
        return self._available

    async def list_models(self) -> list[str]:
        try:
            r = await self._client.get("/api/tags", timeout=3.0)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except (httpx.HTTPError, KeyError, ValueError):
            return []

    async def has_model(self, name: str | None = None) -> bool:
        name = name or self._cfg.model
        models = await self.list_models()
        base = name.split(":")[0]
        return any(m == name or (":" not in name and m.split(":")[0] == base) for m in models)

    async def pull(self, name: str | None = None) -> AsyncIterator[dict[str, Any]]:
        """Télécharge un modèle ; itère sur les événements de progression."""
        name = name or self._cfg.model
        async with self._client.stream("POST", "/api/pull", json={"name": name}, timeout=None) as r:
            async for line in r.aiter_lines():
                if line.strip():
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue

    async def warm_up(self) -> None:
        """Charge le modèle en mémoire (``keep_alive``) et lance une requête à vide."""
        if not await self.ping():
            log.warning("Ollama injoignable sur %s", self._cfg.host)
            return
        try:
            await self._client.post(
                "/api/generate",
                json={"model": self._cfg.model, "prompt": "", "keep_alive": self._cfg.keep_alive},
                timeout=120.0,
            )
            # Requête réelle minuscule : compile les caches CUDA / kernels.
            await self._client.post(
                "/api/chat",
                json={
                    "model": self._cfg.model,
                    "messages": [{"role": "user", "content": "Bonjour."}],
                    "stream": False,
                    "keep_alive": self._cfg.keep_alive,
                    "options": {"num_predict": 1},
                },
                timeout=120.0,
            )
            log.info("Modèle %s préchargé", self._cfg.model)
        except httpx.HTTPError as exc:
            log.warning("Warm-up impossible : %s", exc)

    # ---- appels ------------------------------------------------------
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> LLMReply:
        """Appel non streamé avec tool calling. Bascule sur le modèle de secours en cas d'échec."""
        primary = model or self._cfg.model
        try:
            return await self._chat_once(messages, tools, primary)
        except (httpx.TimeoutException, httpx.HTTPError, LLMUnavailable) as exc:
            fallback = self._cfg.fallback_model
            if fallback and fallback != primary:
                log.warning("%s ne répond pas (%s), bascule sur %s", primary, exc, fallback)
                try:
                    return await self._chat_once(messages, tools, fallback)
                except (httpx.HTTPError, LLMUnavailable) as exc2:
                    raise LLMUnavailable(str(exc2)) from exc2
            raise LLMUnavailable(str(exc)) from exc

    async def _chat_once(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, model: str
    ) -> LLMReply:
        loop = asyncio.get_running_loop()
        started = loop.time()
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": self._cfg.keep_alive,
            "options": {"temperature": self._cfg.temperature, "num_predict": 160},
        }
        if tools:
            payload["tools"] = tools
        r = await self._client.post("/api/chat", json=payload)
        if r.status_code == 404:
            raise LLMUnavailable(f"modèle {model} introuvable")
        r.raise_for_status()
        data = r.json()
        msg = data.get("message", {})
        calls: list[ToolCall] = []
        for call in msg.get("tool_calls", []) or []:
            fn = call.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            calls.append(ToolCall(name=str(fn.get("name", "")), arguments=dict(args or {})))
        self._available = True
        return LLMReply(
            text=(msg.get("content") or "").strip(),
            tool_calls=calls,
            model=model,
            latency_ms=(loop.time() - started) * 1000,
        )

    async def stream_sentences(
        self, messages: list[dict[str, Any]], model: str | None = None
    ) -> AsyncIterator[str]:
        """Stream la réponse et la découpe en phrases dès qu'elles sont complètes (pour le TTS)."""
        payload = {
            "model": model or self._cfg.model,
            "messages": messages,
            "stream": True,
            "keep_alive": self._cfg.keep_alive,
            "options": {"temperature": self._cfg.temperature, "num_predict": 200},
        }
        buffer = ""
        try:
            async with self._client.stream("POST", "/api/chat", json=payload) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        continue
                    buffer += chunk.get("message", {}).get("content", "")
                    parts = _SENTENCE_END.split(buffer)
                    if len(parts) > 1:
                        for sentence in parts[:-1]:
                            if sentence.strip():
                                yield sentence.strip()
                        buffer = parts[-1]
                    if chunk.get("done"):
                        break
        except httpx.HTTPError as exc:
            raise LLMUnavailable(str(exc)) from exc
        if buffer.strip():
            yield buffer.strip()

    async def complete(self, system: str, user: str, max_tokens: int = 200) -> str:
        """Génération libre (résumé, traduction). Implémente ``services.Summarizer``."""
        payload = {
            "model": self._cfg.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "keep_alive": self._cfg.keep_alive,
            "options": {"temperature": 0.2, "num_predict": max_tokens},
        }
        try:
            r = await self._client.post("/api/chat", json=payload, timeout=self._cfg.timeout_s * 3)
            r.raise_for_status()
            return (r.json().get("message", {}).get("content") or "").strip()
        except httpx.HTTPError as exc:
            raise LLMUnavailable(str(exc)) from exc
