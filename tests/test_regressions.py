"""Non-régressions issues de la revue de code de la 0.1.0.

Chaque test reproduit un défaut constaté, pas une hypothèse.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest
from alfred import config as cfgmod
from alfred.config import AlfredConfig, RouterConfig
from alfred.core.context import ConversationContext
from alfred.core.executor import Executor
from alfred.core.router import Router
from alfred.tools.base import ToolError, all_tools

# ----------------------------------------------------------------------
# config : from_yaml était une variable de classe partagée entre threads
# ----------------------------------------------------------------------


def test_from_yaml_is_thread_safe() -> None:
    """Deux threads qui construisent une config ne doivent pas se voler leurs données.

    Avant correctif, le ``finally`` de l'un vidait la variable de classe pendant que
    l'autre construisait : ``update()`` produisait une config de pure valeurs par
    défaut, puis l'écrivait sur disque, effaçant les réglages de l'utilisateur.
    """
    results: dict[str, list[str]] = {"a": [], "b": []}
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def build(key: str, model: str) -> None:
        try:
            barrier.wait(timeout=5)
            for _ in range(60):
                cfg = AlfredConfig.from_yaml({"llm": {"model": model}})
                results[key].append(cfg.llm.model)
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=build, args=("a", "modele-a")),
        threading.Thread(target=build, args=("b", "modele-b")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert not errors, errors
    assert set(results["a"]) == {"modele-a"}, "le thread A a vu les données d'un autre thread"
    assert set(results["b"]) == {"modele-b"}, "le thread B a vu les données d'un autre thread"


def test_from_yaml_restores_previous_state() -> None:
    """Un appel imbriqué ne doit pas laisser le thread avec des données vides."""
    outer = {"llm": {"model": "externe"}}
    AlfredConfig._yaml_state.data = outer
    try:
        inner = AlfredConfig.from_yaml({"llm": {"model": "interne"}})
        assert inner.llm.model == "interne"
        assert AlfredConfig.yaml_data() == outer
    finally:
        AlfredConfig._yaml_state.data = None


def test_concurrent_update_and_reload_keep_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``update()`` ne doit jamais écrire une configuration vidée de ses réglages."""
    monkeypatch.setattr(cfgmod, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfgmod, "user_config_path", lambda: tmp_path / "config.yaml")
    manager = cfgmod.ConfigManager()
    manager.update(persona={"address": "madame"}, app_aliases={"jeux": "steam.exe"})

    stop = threading.Event()

    def reload_loop() -> None:
        while not stop.is_set():
            manager.reload()

    noise = threading.Thread(target=reload_loop, daemon=True)
    noise.start()
    try:
        for _ in range(25):
            cfg = manager.update(behavior={"history_turns": 7})
            assert cfg.persona.address == "madame", "réglage perdu pendant un rechargement"
            assert cfg.app_aliases.get("jeux") == "steam.exe", "alias perdu"
    finally:
        stop.set()
        noise.join(timeout=10)


# ----------------------------------------------------------------------
# executor : le shield empêchait d'annuler un tool destructeur
# ----------------------------------------------------------------------


async def test_cancelling_a_slow_tool_cancels_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Échap pendant la fenêtre d'accusé de réception doit arrêter le tool.

    Avant correctif, ``asyncio.shield`` absorbait l'annulation : l'arrêt du PC
    confirmé puis annulé 100 ms plus tard s'exécutait quand même.
    """
    from alfred.core import executor as ex
    from alfred.tools.base import REGISTRY, ToolSpec

    started = asyncio.Event()
    completed = False

    async def slow_tool() -> str:
        nonlocal completed
        started.set()
        await asyncio.sleep(5)
        completed = True
        return "effet de bord"

    spec = ToolSpec(name="tool_lent", description="Tool lent", func=slow_tool)
    monkeypatch.setitem(REGISTRY, "tool_lent", spec)
    monkeypatch.setattr(ex, "ACK_DELAY_S", 10)  # on reste dans la fenêtre shieldée

    async def speak(_: str) -> None:
        return None

    async def confirm(_: str) -> bool:
        return True

    executor = Executor(
        AlfredConfig(),
        Router(RouterConfig(), all_tools(), semantic=None),
        None,
        ConversationContext(),
        speak,
        confirm,
    )
    task = asyncio.ensure_future(executor._run_tool("test", spec, {}, ex.Metrics()))
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.05)
    assert not completed, "le tool a poursuivi ses effets de bord après l'annulation"


# ----------------------------------------------------------------------
# web : la source citée ne correspondait pas toujours au texte résumé
# ----------------------------------------------------------------------


async def test_web_search_cites_the_site_it_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Quand la page lue est trop maigre, on cite la source de l'extrait réellement utilisé."""
    from alfred.core import services
    from alfred.tools import web

    results = [
        {"href": "https://premier.fr/a", "body": "Extrait du premier résultat."},
        {"href": "https://second.fr/b", "body": "Extrait du second."},
    ]
    monkeypatch.setattr(web, "is_online", lambda timeout=1.5: True)
    monkeypatch.setattr(web, "_search", lambda q, n=3: results)

    async def fake_fetch(url: str) -> str:
        if "premier" in url:
            raise ValueError("page illisible")
        return "trop court"  # moins de 300 caractères

    monkeypatch.setattr(web, "_fetch_text", fake_fetch)
    monkeypatch.setattr(services, "llm", None)

    answer = await web.web_search("une question")
    assert "premier.fr" in answer, "la source doit être celle de l'extrait cité"
    assert "second.fr" not in answer, "on cite un site dont le texte n'est pas utilisé"


async def test_web_search_cites_the_page_it_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Quand une page substantielle est lue, c'est elle qui est citée."""
    from alfred.core import services
    from alfred.tools import web

    results = [
        {"href": "https://premier.fr/a", "body": "Extrait du premier."},
        {"href": "https://second.fr/b", "body": "Extrait du second."},
    ]
    monkeypatch.setattr(web, "is_online", lambda timeout=1.5: True)
    monkeypatch.setattr(web, "_search", lambda q, n=3: results)

    async def fake_fetch(url: str) -> str:
        if "premier" in url:
            raise ValueError("page illisible")
        return "contenu substantiel " * 40

    monkeypatch.setattr(web, "_fetch_text", fake_fetch)

    class FakeLLM:
        async def complete(self, system: str, user: str, max_tokens: int = 200) -> str:
            assert "second.fr" in user
            return "La réponse."

    monkeypatch.setattr(services, "llm", FakeLLM())
    answer = await web.web_search("une question")
    assert "second.fr" in answer


# ----------------------------------------------------------------------
# files : la recherche plantait si un fichier disparaissait pendant le tri
# ----------------------------------------------------------------------


def test_search_walk_survives_vanished_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Un fichier supprimé pendant le tri ne doit pas faire échouer la recherche entière."""
    from alfred.tools import files

    present = tmp_path / "budget 2024.txt"
    present.write_text("x", encoding="utf-8")
    ghost = tmp_path / "budget fantome.txt"
    ghost.write_text("x", encoding="utf-8")

    monkeypatch.setattr(files, "_user_folders", lambda: [tmp_path])
    real_stat = Path.stat

    def flaky_stat(self: Path, *args: object, **kwargs: object) -> object:
        if self.name == "budget fantome.txt":
            raise FileNotFoundError(self)
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", flaky_stat)
    found = files._search_walk("budget")
    assert present in found, "les autres résultats doivent survivre"


def test_find_file_reports_missing_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Aucun résultat donne une ToolError parlée, jamais une exception brute."""
    from alfred.tools import files

    monkeypatch.setattr(files, "_everything_dll", lambda: None)
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(files, "_user_folders", lambda: [tmp_path])
    with pytest.raises(ToolError):
        asyncio.get_event_loop_policy()
        asyncio.run(files.find_file("introuvable-xyz"))
