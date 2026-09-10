"""Point d'entrée : ``python -m alfred`` ou ``alfred.exe``.

Options :
  --minimized      démarre sans ouvrir de fenêtre (utilisé par le démarrage Windows)
  --cli "texte"    traite une commande en ligne de commande, sans interface (tests, scripts)
  --version        affiche la version
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from alfred import __version__


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="alfred", description="ALFRED — majordome vocal local pour Windows"
    )
    parser.add_argument("--minimized", action="store_true", help="démarrer dans la barre système")
    parser.add_argument("--cli", metavar="TEXTE", help="exécuter une commande texte sans interface")
    parser.add_argument("--no-tts", action="store_true", help="avec --cli : ne pas parler")
    parser.add_argument("--version", action="version", version=f"alfred {__version__}")
    return parser.parse_args(argv)


def _ensure_single_instance() -> bool:
    """Mutex Windows nommé : une seule instance d'Alfred à la fois."""
    if sys.platform != "win32":
        return True
    import ctypes

    ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\AlfredAssistantSingleton")
    return bool(ctypes.windll.kernel32.GetLastError() != 183)  # ERROR_ALREADY_EXISTS


async def _run_cli(text: str, speak: bool) -> int:
    """Mode ligne de commande : route + exécute + affiche, sans Qt."""
    from alfred.audio.tts import TextToSpeech
    from alfred.config import ConfigManager
    from alfred.core import services
    from alfred.core.context import ConversationContext
    from alfred.core.executor import Executor
    from alfred.core.llm import OllamaClient
    from alfred.core.router import Router, SemanticIndex
    from alfred.tools.base import all_tools, load_all_tools

    config = ConfigManager()
    cfg = config.current
    load_all_tools()
    semantic = SemanticIndex(all_tools())
    await asyncio.to_thread(semantic.build)
    llm = OllamaClient(cfg.llm)
    tts = TextToSpeech(cfg.tts) if speak else None
    context = ConversationContext()
    services.config_manager = config
    services.llm = llm
    services.tts = tts
    services.context = context

    async def _speak(msg: str) -> None:
        print(f"Alfred : {msg}")
        if tts is not None:
            await tts.say(msg)

    async def _confirm(question: str) -> bool:
        print(f"Alfred : {question}")
        answer = await asyncio.to_thread(input, "Vous (oui/non) : ")
        return answer.strip().lower() in {"oui", "o", "yes", "y"}

    executor = Executor(
        cfg, Router(cfg.router, all_tools(), semantic), llm, context, _speak, _confirm
    )
    result = await executor.handle(text)
    print(f"[{result.metrics.as_text()}]")
    await llm.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    from alfred.config import ConfigManager, ensure_user_config
    from alfred.core.logging_setup import setup_logging

    ensure_user_config()
    config = ConfigManager()
    setup_logging(config.current.behavior.log_level)
    log = logging.getLogger("alfred")

    if args.cli:
        return asyncio.run(_run_cli(args.cli, speak=not args.no_tts))

    # Mise à jour en attente (déposée par l'updater au tour précédent)
    from alfred.updater import Updater

    pending = Updater.pending_install()
    if pending is not None and config.current.updates.auto_install:
        installer, version = pending
        log.info("Installation de la mise à jour %s", version)
        Updater.run_installer(installer, silent=True)
        return 0

    if not _ensure_single_instance():
        log.warning("Alfred est déjà lancé")
        return 0

    from PyQt6.QtWidgets import QApplication

    from alfred.app import AlfredApp

    qt_app = QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)
    qt_app.setApplicationName("Alfred")
    qt_app.setApplicationVersion(__version__)

    app = AlfredApp(
        qt_app, config, start_minimized=args.minimized or config.current.general.start_minimized
    )
    try:
        app.start()
    except Exception:
        log.exception("Démarrage impossible")
        return 1
    return qt_app.exec()


if __name__ == "__main__":
    sys.exit(main())
