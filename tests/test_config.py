"""Configuration : fusion défaut/utilisateur, validation, rechargement, mise à jour."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from alfred import config as cfgmod


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(cfgmod, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfgmod, "user_config_path", lambda: tmp_path / "config.yaml")
    return tmp_path


def test_defaults_are_valid() -> None:
    cfg = cfgmod.AlfredConfig()
    assert cfg.llm.model == "qwen2.5:7b-instruct"
    assert cfg.router.semantic_threshold == 0.82
    assert cfg.persona.mode == "formal"


def test_default_yaml_loads_and_matches_model() -> None:
    data = yaml.safe_load(cfgmod.default_config_path().read_text(encoding="utf-8"))
    cfg = cfgmod.AlfredConfig(**data)
    assert cfg.hotkeys.invoke_voice == "ctrl+space"
    assert cfg.app_aliases["navigateur"] == "firefox.exe"


def test_user_override_merges(isolated: Path) -> None:
    (isolated / "config.yaml").write_text(
        "persona:\n  mode: concise\napp_aliases:\n  Jeux: steam.exe\n", encoding="utf-8"
    )
    cfg = cfgmod.load_config()
    assert cfg.persona.mode == "concise"
    assert cfg.llm.model == "qwen2.5:7b-instruct"  # défaut conservé
    assert cfg.app_aliases["jeux"] == "steam.exe"  # clé normalisée
    assert cfg.app_aliases["navigateur"] == "firefox.exe"  # défaut conservé


def test_invalid_user_config_falls_back(isolated: Path) -> None:
    (isolated / "config.yaml").write_text("router:\n  semantic_threshold: 3\n", encoding="utf-8")
    cfg = cfgmod.load_config()
    assert cfg.router.semantic_threshold == 0.82


def test_ensure_user_config_copies_default(isolated: Path) -> None:
    path = cfgmod.ensure_user_config()
    assert path.exists()
    assert "hotkeys" in path.read_text(encoding="utf-8")


def test_manager_update_persists_and_notifies(isolated: Path) -> None:
    manager = cfgmod.ConfigManager()
    seen: list[str] = []
    manager.subscribe(lambda c: seen.append(c.persona.address))
    manager.update(persona={"address": "madame"}, behavior={"history_turns": 3})
    assert seen == ["madame"]
    reloaded = yaml.safe_load((isolated / "config.yaml").read_text(encoding="utf-8"))
    assert reloaded["persona"]["address"] == "madame"
    assert reloaded["behavior"]["history_turns"] == 3
    assert manager.current.behavior.history_turns == 3


def test_manager_reload_is_silent_when_unchanged(isolated: Path) -> None:
    manager = cfgmod.ConfigManager()
    calls: list[int] = []
    manager.subscribe(lambda c: calls.append(1))
    manager.reload()
    assert calls == []
    (isolated / "config.yaml").write_text("persona:\n  mode: concise\n", encoding="utf-8")
    manager.reload()
    assert calls == [1]
    assert manager.current.persona.mode == "concise"


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALFRED__LLM__MODEL", "llama3:8b")
    assert cfgmod.AlfredConfig().llm.model == "llama3:8b"


def test_env_overrides_user_yaml(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (isolated / "config.yaml").write_text("llm:\n  model: from-yaml\n", encoding="utf-8")
    monkeypatch.setenv("ALFRED__LLM__MODEL", "from-env")
    assert cfgmod.load_config().llm.model == "from-env"
