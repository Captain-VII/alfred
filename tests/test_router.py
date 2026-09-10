"""Routeur : normalisation, niveau 1 (regex) et niveau 2 (sémantique, index simulé)."""

from __future__ import annotations

import numpy as np
import pytest
from alfred.config import RouterConfig
from alfred.core.router import Router, SemanticIndex, normalize
from alfred.tools.base import all_tools, get_tool


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Monte le son !", "monte le son"),
        ("Alfred, ouvre Spotify s'il te plaît.", "ouvre spotify"),
        ("  Peux-tu   verrouiller l'écran ?", "verrouiller l'écran"),
        ("Est-ce que tu peux mettre en pause, merci", "mettre en pause"),
        ("PAUSE", "pause"),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.fixture
def router() -> Router:
    return Router(
        RouterConfig(semantic_threshold=0.82, enable_llm_fallback=True), all_tools(), semantic=None
    )


@pytest.mark.parametrize(
    ("text", "tool", "args"),
    [
        ("monte le son", "set_volume", {"up": "monte"}),
        ("baisse le volume de 20", "set_volume", {"down": "baisse", "delta": "20"}),
        ("mets le volume à 30 %", "set_volume", {"level": "30"}),
        ("volume à cinquante", "set_volume", {"level": "cinquante"}),
        ("plus fort", "set_volume", {"up": "plus"}),
        ("coupe le son", "mute", {}),
        ("verrouille l'écran", "lock", {}),
        ("mets en veille", "sleep", {}),
        ("éteins l'ordinateur", "shutdown", {}),
        ("capture d'écran", "screenshot", {}),
        ("ouvre spotify", "open_app", {"app": "spotify"}),
        ("lance le navigateur", "open_app", {"app": "le navigateur"}),
        ("ferme-la", "close_app", {}),
        ("ferme discord", "close_app", {"app": "discord"}),
        ("bascule sur firefox", "focus_app", {"app": "firefox"}),
        ("pause", "media_play_pause", {}),
        ("suivant", "media_next", {}),
        ("piste précédente", "media_previous", {}),
        (
            "rappelle-moi dans 20 minutes de sortir le gâteau",
            "set_timer",
            {"duration": "20 minutes", "label": "de sortir le gâteau"},
        ),
        ("minuteur de 5 minutes", "set_timer", {"duration": "5 minutes"}),
        ("annule le minuteur", "cancel_timer", {}),
        ("cherche sur internet la météo à lyon", "web_search", {"query": "la météo à lyon"}),
        ("lis le presse-papier", "read_clipboard", {}),
        ("traduis le presse-papier en espagnol", "translate_clipboard", {"language": "espagnol"}),
        ("réduis la fenêtre", "minimize_window", {}),
        ("mets les fenêtres côte à côte", "snap_windows", {}),
        ("montre le bureau", "show_desktop", {}),
        ("cherche le fichier budget 2024", "find_file", {"name": "budget 2024"}),
        ("ouvre-le", "open_file", {}),
        ("ne pas déranger", "do_not_disturb", {}),
    ],
)
def test_level1_routes(router: Router, text: str, tool: str, args: dict[str, str]) -> None:
    decision = router.route(text)
    assert decision.level == 1, f"« {text} » → niveau {decision.level}"
    assert decision.tool is not None and decision.tool.name == tool, (
        f"« {text} » → {decision.tool and decision.tool.name}"
    )
    for key, value in args.items():
        assert decision.args.get(key) == value, f"{key}: {decision.args}"


def test_level1_latency(router: Router) -> None:
    decision = router.route("monte le son")
    assert decision.latency_ms < 5.0


def test_free_form_goes_to_llm(router: Router) -> None:
    decision = router.route("quelle est la capitale de l'australie")
    assert decision.level == 3
    assert decision.tool is None


def test_no_llm_fallback_when_disabled() -> None:
    router = Router(RouterConfig(enable_llm_fallback=False), all_tools(), semantic=None)
    assert router.route("raconte-moi une histoire").level == 0


def test_empty_text(router: Router) -> None:
    assert router.route("   ").level == 0


# ----------------------------------------------------------------------
# Niveau 2 : index sémantique avec un modèle d'embedding simulé
# ----------------------------------------------------------------------


class FakeIndex(SemanticIndex):
    """Index qui répond une paire (tool, score) fixée, sans charger de modèle."""

    def __init__(self, tool: str, score: float) -> None:
        super().__init__(all_tools(), cache_path=None)
        self._fixed = (tool, score)
        self._runner_up = 0.0
        self._matrix = np.zeros((1, 1), dtype=np.float32)  # ready = True

    def query(self, text: str) -> tuple[str | None, float, str]:
        return self._fixed[0], self._fixed[1], "exemple"

    def query_with_runner_up(self, text: str) -> tuple[str | None, float, str, float]:
        return self._fixed[0], self._fixed[1], "exemple", self._runner_up


def test_level2_margin_too_small_defers_to_llm() -> None:
    index = FakeIndex("lock", 0.90)
    index._runner_up = 0.88
    router = Router(RouterConfig(semantic_threshold=0.82, semantic_margin=0.05), all_tools(), index)
    assert router.route("bloque la session").level == 3


def test_level2_above_threshold_without_required_params() -> None:
    router = Router(RouterConfig(semantic_threshold=0.82), all_tools(), FakeIndex("lock", 0.91))
    decision = router.route("je voudrais que tu bloques la session")
    assert decision.level == 2
    assert decision.tool is not None and decision.tool.name == "lock"
    assert decision.score == pytest.approx(0.91)


def test_level2_below_threshold_goes_to_llm() -> None:
    router = Router(RouterConfig(semantic_threshold=0.82), all_tools(), FakeIndex("lock", 0.6))
    assert router.route("bloque la session").level == 3


def test_level2_required_param_missing_defers_to_llm() -> None:
    # open_app exige « app » : sans pattern qui l'extrait, on laisse le LLM décider.
    router = Router(RouterConfig(semantic_threshold=0.82), all_tools(), FakeIndex("open_app", 0.95))
    assert router.route("je veux écouter de la musique").level == 3


def test_semantic_index_cache_roundtrip(tmp_path, monkeypatch) -> None:
    """Le cache est réutilisé quand l'empreinte des exemples est identique."""
    index = SemanticIndex(all_tools(), cache_path=tmp_path / "idx.npz")
    calls = {"n": 0}

    def fake_embed(texts: list[str]) -> np.ndarray:
        calls["n"] += 1
        vecs = np.random.default_rng(0).random((len(texts), 8)).astype(np.float32)
        return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)

    monkeypatch.setattr(index, "embed", fake_embed)
    index.build()
    assert calls["n"] == 1
    index2 = SemanticIndex(all_tools(), cache_path=tmp_path / "idx.npz")
    monkeypatch.setattr(index2, "embed", fake_embed)
    index2.build()
    assert calls["n"] == 1  # chargé depuis le cache
    assert index2.ready


def test_every_tool_has_examples_and_schema() -> None:
    for spec in all_tools():
        assert spec.examples, f"{spec.name} sans exemples"
        schema = spec.json_schema()
        assert schema["function"]["name"] == spec.name
        assert "parameters" in schema["function"]
    assert get_tool("shutdown") is not None and get_tool("shutdown").confirm
