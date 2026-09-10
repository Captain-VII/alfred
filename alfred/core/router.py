"""Routage à trois niveaux.

1. **Exact / regex** (~0 ms) : patterns déclarés par les tools ;
2. **Sémantique** (~15 ms) : embeddings locaux des phrases d'exemple, cache disque ;
3. **LLM** (~600-1500 ms) : tool calling Ollama pour la formulation libre.

Le routeur ne fait que *décider* ; l'exécution est confiée à l'exécuteur.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from alfred.config import RouterConfig, cache_dir
from alfred.tools.base import ToolSpec, all_tools

log = logging.getLogger(__name__)

_EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@dataclass(slots=True)
class RouteDecision:
    level: int  # 1, 2, 3 (LLM) ou 0 (rien)
    tool: ToolSpec | None = None
    args: dict[str, Any] = field(default_factory=dict)
    score: float = 1.0
    latency_ms: float = 0.0


# ----------------------------------------------------------------------
# Normalisation
# ----------------------------------------------------------------------

_FILLERS = re.compile(
    r"^(?:alfred[,!]?\s+)?(?:s'il (?:te|vous) pla[iî]t[,]?\s+|peux-tu\s+|pourrais-tu\s+|pouvez-vous\s+|"
    r"est-ce que tu peux\s+|tu peux\s+|merci de\s+|veuillez\s+|je voudrais que tu\s+|j'aimerais que tu\s+)?"
)
_TRAILING = re.compile(r"[\s,.!?]*(?:s'il (?:te|vous) pla[iî]t|merci|alfred)?[\s,.!?]*$")


def normalize(text: str) -> str:
    """Minuscule, espaces normalisés, politesses et ponctuation finale retirées.

    Les accents sont conservés (les regex des tools en tiennent compte).
    """
    text = unicodedata.normalize("NFC", text).strip().lower()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("’", "'")
    text = _FILLERS.sub("", text, count=1)
    text = _TRAILING.sub("", text)
    return text.strip()


# ----------------------------------------------------------------------
# Niveau 2 : index sémantique
# ----------------------------------------------------------------------


class SemanticIndex:
    """Embeddings des phrases d'exemple de tous les tools, calculés une fois et cachés sur disque."""

    def __init__(self, tools: list[ToolSpec], cache_path: Path | None = None) -> None:
        self._tools = tools
        self._cache_path = cache_path or (cache_dir() / "semantic_index.npz")
        self._labels: list[tuple[str, str]] = []  # (tool_name, exemple)
        self._matrix: np.ndarray | None = None
        self._model: Any = None

    # ---- chargement --------------------------------------------------
    def _fingerprint(self) -> str:
        payload = json.dumps(
            {t.name: sorted(t.examples) for t in self._tools}, sort_keys=True, ensure_ascii=False
        ).encode()
        return hashlib.sha256(payload).hexdigest()[:16]

    def _load_model(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(
                model_name=_EMBED_MODEL, cache_dir=str(cache_dir() / "fastembed")
            )
        return self._model

    def build(self) -> None:
        """Charge le cache si l'empreinte correspond, sinon recalcule et sauvegarde."""
        self._labels = [(t.name, ex) for t in self._tools for ex in t.examples]
        if not self._labels:
            self._matrix = np.zeros((0, 1), dtype=np.float32)
            return
        fp = self._fingerprint()
        if self._cache_path.exists():
            try:
                data = np.load(self._cache_path, allow_pickle=False)
                if str(data["fingerprint"]) == fp:
                    self._matrix = data["matrix"]
                    log.info(
                        "Index sémantique chargé depuis le cache (%d exemples)", len(self._labels)
                    )
                    return
            except Exception:
                log.debug("Cache sémantique illisible, recalcul")
        started = time.perf_counter()
        self._matrix = self.embed([ex for _, ex in self._labels])
        try:
            np.savez(self._cache_path, matrix=self._matrix, fingerprint=np.array(fp))
        except OSError:
            log.debug("Impossible d'écrire le cache sémantique")
        log.info(
            "Index sémantique calculé en %.0f ms (%d exemples)",
            (time.perf_counter() - started) * 1000,
            len(self._labels),
        )

    def _warm_up(self) -> None:
        """Première inférence à vide : charge le modèle ONNX pour que la 1re requête réelle soit rapide."""
        try:
            self.embed(["bonjour"])
        except Exception:
            log.debug("Warm-up de l'index sémantique impossible", exc_info=True)

    def embed(self, texts: list[str]) -> np.ndarray:
        model = self._load_model()
        vectors = np.array(list(model.embed(texts)), dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms

    # ---- requête -----------------------------------------------------
    def query(self, text: str) -> tuple[str | None, float, str]:
        """Retourne ``(tool_name, score, exemple_le_plus_proche)``."""
        name, score, example, _ = self.query_with_runner_up(text)
        return name, score, example

    def query_with_runner_up(self, text: str) -> tuple[str | None, float, str, float]:
        """Comme :meth:`query`, plus le meilleur score d'un tool *différent* (pour la marge)."""
        if self._matrix is None or self._matrix.shape[0] == 0:
            return None, 0.0, "", 0.0
        vec = self.embed([text])[0]
        scores = self._matrix @ vec
        order = np.argsort(-scores)
        best = int(order[0])
        name, example = self._labels[best]
        runner_up = 0.0
        for idx in order[1:]:
            if self._labels[int(idx)][0] != name:
                runner_up = float(scores[int(idx)])
                break
        return name, float(scores[best]), example, runner_up

    @property
    def ready(self) -> bool:
        return self._matrix is not None


# ----------------------------------------------------------------------
# Routeur
# ----------------------------------------------------------------------


class Router:
    def __init__(
        self,
        cfg: RouterConfig,
        tools: list[ToolSpec] | None = None,
        semantic: SemanticIndex | None = None,
    ) -> None:
        self._cfg = cfg
        self._tools = tools if tools is not None else all_tools()
        self._semantic = semantic

    def apply(self, cfg: RouterConfig) -> None:
        self._cfg = cfg

    @property
    def tools(self) -> list[ToolSpec]:
        return self._tools

    def route(self, raw_text: str) -> RouteDecision:
        """Décide du niveau de traitement d'une commande."""
        started = time.perf_counter()
        text = normalize(raw_text)
        if not text:
            return RouteDecision(level=0)

        # ---- Niveau 1 ----------------------------------------------
        # Plusieurs patterns peuvent correspondre (« montre le bureau » : focus_app
        # capture « le bureau », show_desktop ne capture rien). On retient le plus
        # spécifique : celui dont les groupes capturent le moins de texte.
        best: tuple[int, ToolSpec, dict[str, Any]] | None = None
        for spec in self._tools:
            args = spec.match(text)
            if args is None:
                continue
            captured = sum(len(str(v)) for v in args.values())
            if best is None or captured < best[0]:
                best = (captured, spec, args)
        if best is not None:
            _, spec, args = best
            return RouteDecision(level=1, tool=spec, args=args, score=1.0, latency_ms=_ms(started))

        # ---- Niveau 2 ----------------------------------------------
        if self._semantic is not None and self._semantic.ready:
            name, score, example, runner_up = self._semantic.query_with_runner_up(text)
            if (
                name
                and score >= self._cfg.semantic_threshold
                and score - runner_up < self._cfg.semantic_margin
            ):
                log.debug(
                    "Niveau 2 : %s (%.2f) trop proche du suivant (%.2f) → LLM",
                    name,
                    score,
                    runner_up,
                )
            elif name and score >= self._cfg.semantic_threshold:
                matched = next((t for t in self._tools if t.name == name), None)
                if matched is not None:
                    # Un tool à paramètres obligatoires ne peut pas être appelé à l'aveugle :
                    # on tente d'extraire les paramètres depuis un pattern, sinon on laisse au LLM.
                    required = [p for p in matched.params.values() if p.required]
                    args = matched.match(text) or {}
                    if not required or all(p.name in args for p in required):
                        log.debug("Niveau 2 : %s (%.2f) ← « %s »", name, score, example)
                        return RouteDecision(
                            level=2, tool=matched, args=args, score=score, latency_ms=_ms(started)
                        )
                    log.debug("Niveau 2 : %s (%.2f) mais paramètres manquants → LLM", name, score)

        # ---- Niveau 3 ----------------------------------------------
        if self._cfg.enable_llm_fallback:
            return RouteDecision(level=3, latency_ms=_ms(started))
        return RouteDecision(level=0, latency_ms=_ms(started))


def _ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
