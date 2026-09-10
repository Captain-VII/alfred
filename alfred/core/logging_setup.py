"""Journalisation : fichier rotatif quotidien conservé 7 jours + console en développement."""

from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from alfred.config import logs_dir

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(level: str = "info") -> Path:
    """Configure le logger racine. Retourne le chemin du fichier courant."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    path = logs_dir() / "alfred.log"
    file_handler = TimedRotatingFileHandler(path, when="midnight", backupCount=7, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(file_handler)

    if not getattr(sys, "frozen", False) and sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(console)

    # Bibliothèques bavardes
    for noisy in (
        "httpx",
        "httpcore",
        "faster_whisper",
        "urllib3",
        "comtypes",
        "PIL",
        "huggingface_hub",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # Piper signale un phonème nasal absent de la table de gilles-low à chaque phrase : sans effet audible
    logging.getLogger("piper.phoneme_ids").setLevel(logging.ERROR)
    return path


def set_level(level: str) -> None:
    logging.getLogger().setLevel(getattr(logging, level.upper(), logging.INFO))
