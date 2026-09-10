"""Configuration d'ALFRED.

- Modèles pydantic validés, une section par bloc du ``config.yaml``.
- Chargement : ``config.default.yaml`` (embarqué) surchargé par
  ``%APPDATA%\\Alfred\\config.yaml`` (créé au premier lancement).
- Rechargement à chaud : un observateur ``watchdog`` surveille le fichier
  utilisateur et notifie les abonnés à chaque modification valide.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Chemins
# ----------------------------------------------------------------------


def resource_root() -> Path:
    """Racine des ressources embarquées (source ou bundle PyInstaller)."""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    """Dossier de données utilisateur : ``%APPDATA%\\Alfred``."""
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    path = Path(base) / "Alfred"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_config_path() -> Path:
    return user_data_dir() / "config.yaml"


def default_config_path() -> Path:
    return resource_root() / "config.default.yaml"


def assets_dir() -> Path:
    return resource_root() / "assets"


def cache_dir() -> Path:
    path = user_data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = user_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def voices_dir() -> Path:
    """Les voix Piper sont téléchargées dans le dossier utilisateur (pas dans le bundle)."""
    path = user_data_dir() / "voices"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ----------------------------------------------------------------------
# Sections
# ----------------------------------------------------------------------


class GeneralConfig(BaseModel):
    language: str = "fr"
    start_with_windows: bool = True
    start_minimized: bool = True
    first_run_done: bool = False


class HotkeysConfig(BaseModel):
    invoke_voice: str = "ctrl+space"
    invoke_text: str = "ctrl+shift+space"
    cancel: str = "escape"
    push_to_talk: bool = False


class LLMConfig(BaseModel):
    provider: Literal["ollama"] = "ollama"
    model: str = "llama3.1:latest"
    host: str = "http://localhost:11434"
    keep_alive: int | str = -1
    temperature: float = Field(0.3, ge=0.0, le=2.0)
    timeout_s: float = Field(12.0, gt=0)
    fallback_model: str | None = "llama3.2:3b"


class STTConfig(BaseModel):
    model: str = "small"
    device: Literal["auto", "cuda", "cpu"] = "auto"
    compute_type: Literal["int8", "int8_float16", "float16", "float32"] = "int8"
    vad_aggressiveness: int = Field(2, ge=0, le=3)
    max_recording_s: float = Field(15.0, gt=0, le=60)
    silence_end_ms: int = Field(700, ge=200, le=3000)
    input_device: int | str | None = None


class TTSConfig(BaseModel):
    voice: str = "fr_FR-gilles-low"
    length_scale: float = Field(1.08, gt=0.3, lt=3.0)
    noise_scale: float = Field(0.667, ge=0.0, le=2.0)
    noise_w: float = Field(0.8, ge=0.0, le=2.0)
    sentence_silence: float = Field(0.35, ge=0.0, le=2.0)
    volume: float = Field(0.9, ge=0.0, le=1.0)
    enabled: bool = True
    output_device: int | str | None = None


class RouterConfig(BaseModel):
    semantic_threshold: float = Field(0.82, ge=0.0, le=1.0)
    semantic_margin: float = Field(0.05, ge=0.0, le=0.5)
    enable_llm_fallback: bool = True


class PersonaConfig(BaseModel):
    mode: Literal["formal", "concise"] = "formal"
    address: str = "monsieur"


class BehaviorConfig(BaseModel):
    confirm_destructive: bool = True
    sound_feedback: bool = True
    history_turns: int = Field(5, ge=0, le=50)
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    show_metrics: bool = False


class UpdatesConfig(BaseModel):
    auto_check: bool = True
    channel: Literal["stable", "beta"] = "stable"
    auto_install: bool = False
    repo: str = "dorian-dubosc/alfred"


class AlfredConfig(BaseSettings):
    """Configuration complète. Les variables d'env ``ALFRED__LLM__MODEL`` etc. surchargent le YAML."""

    model_config = SettingsConfigDict(
        env_prefix="ALFRED__", env_nested_delimiter="__", extra="ignore"
    )

    # Données YAML fusionnées (défaut + utilisateur), injectées comme source de priorité basse
    _yaml_data: ClassVar[dict[str, Any]] = {}

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Priorité : arguments explicites > variables d'environnement > YAML."""
        return (init_settings, env_settings, _YamlSource(settings_cls))

    @classmethod
    def from_yaml(cls, data: dict[str, Any]) -> AlfredConfig:
        """Construit la config depuis un mapping YAML, en laissant l'environnement surcharger."""
        cls._yaml_data = data
        try:
            return cls()
        finally:
            cls._yaml_data = {}

    general: GeneralConfig = Field(default_factory=GeneralConfig)
    hotkeys: HotkeysConfig = Field(default_factory=HotkeysConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    router: RouterConfig = Field(default_factory=RouterConfig)
    persona: PersonaConfig = Field(default_factory=PersonaConfig)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    updates: UpdatesConfig = Field(default_factory=UpdatesConfig)
    app_aliases: dict[str, str] = Field(default_factory=dict)

    @field_validator("app_aliases", mode="before")
    @classmethod
    def _normalize_aliases(cls, value: Any) -> dict[str, str]:
        if value is None:
            return {}
        return {str(k).strip().lower(): str(v).strip() for k, v in dict(value).items()}


class _YamlSource(PydanticBaseSettingsSource):
    """Source pydantic-settings alimentée par ``AlfredConfig._yaml_data``."""

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return AlfredConfig._yaml_data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return dict(AlfredConfig._yaml_data)


# ----------------------------------------------------------------------
# Chargement / sauvegarde
# ----------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Fusion récursive : ``override`` gagne, les dicts sont fusionnés clé par clé."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} : le document YAML doit être un mapping")
    return data


def ensure_user_config() -> Path:
    """Copie le fichier par défaut vers le dossier utilisateur s'il n'existe pas."""
    target = user_config_path()
    if not target.exists():
        default = default_config_path()
        if default.exists():
            shutil.copy(default, target)
        else:
            # Bundle sans fichier par défaut : on sérialise le modèle.
            save_config(AlfredConfig(), target)
    return target


def load_config() -> AlfredConfig:
    """Charge défaut + utilisateur. En cas d'erreur de validation, retombe sur le défaut."""
    merged = _deep_merge(_read_yaml(default_config_path()), _read_yaml(ensure_user_config()))
    try:
        return AlfredConfig.from_yaml(merged)
    except ValidationError as exc:
        log.error("config.yaml invalide, valeurs par défaut utilisées :\n%s", exc)
        return AlfredConfig.from_yaml(_read_yaml(default_config_path()))


def save_config(cfg: AlfredConfig, path: Path | None = None) -> None:
    """Écrit la configuration en YAML (les commentaires du fichier original sont perdus)."""
    path = path or user_config_path()
    data = cfg.model_dump(mode="json")
    with path.open("w", encoding="utf-8") as fh:
        fh.write("# Configuration ALFRED — rechargée à chaud à chaque sauvegarde.\n")
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)


# ----------------------------------------------------------------------
# Gestionnaire avec rechargement à chaud
# ----------------------------------------------------------------------

ConfigListener = Callable[[AlfredConfig], None]


class ConfigManager:
    """Détient la config courante et notifie les abonnés lors d'un rechargement.

    Utilisation :
        cfg = ConfigManager()
        cfg.subscribe(lambda c: tts.apply(c.tts))
        cfg.start_watching()
        cfg.current.llm.model
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._config = load_config()
        self._listeners: list[ConfigListener] = []
        self._observer: Any = None

    @property
    def current(self) -> AlfredConfig:
        with self._lock:
            return self._config

    def subscribe(self, listener: ConfigListener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def reload(self) -> AlfredConfig:
        """Recharge depuis le disque et notifie. Silencieux si rien n'a changé."""
        new = load_config()
        with self._lock:
            if new.model_dump() == self._config.model_dump():
                return self._config
            self._config = new
            listeners = list(self._listeners)
        log.info("Configuration rechargée")
        for listener in listeners:
            try:
                listener(new)
            except Exception:
                log.exception("Erreur dans un abonné de configuration")
        return new

    def update(self, **sections: Any) -> AlfredConfig:
        """Modifie des sections en mémoire, sauvegarde et notifie.

        Exemple : ``cfg.update(persona={"mode": "concise"})``.
        """
        with self._lock:
            data = self._config.model_dump()
            for name, patch in sections.items():
                if isinstance(patch, dict) and isinstance(data.get(name), dict):
                    data[name] = _deep_merge(data[name], patch)
                else:
                    data[name] = patch
            new = AlfredConfig.from_yaml(data)
            self._config = new
            listeners = list(self._listeners)
        save_config(new)
        for listener in listeners:
            try:
                listener(new)
            except Exception:
                log.exception("Erreur dans un abonné de configuration")
        return new

    def start_watching(self) -> None:
        """Démarre l'observateur watchdog sur le dossier de configuration."""
        try:
            from watchdog.events import FileSystemEvent, FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            log.warning("watchdog absent : pas de rechargement à chaud")
            return

        manager = self
        target = user_config_path()

        class _Handler(FileSystemEventHandler):
            def on_modified(self, event: FileSystemEvent) -> None:
                if Path(str(event.src_path)).name == target.name:
                    # Certains éditeurs écrivent en deux temps : on laisse retomber la poussière.
                    threading.Timer(0.25, manager.reload).start()

            on_created = on_modified
            on_moved = on_modified

        self._observer = Observer()
        self._observer.schedule(_Handler(), str(target.parent), recursive=False)
        self._observer.daemon = True
        self._observer.start()
        log.debug("Surveillance de %s", target)

    def stop_watching(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None
