"""Application principale : assemble configuration, audio, routeur, UI et hotkeys.

Modèle de threads :
- thread principal : boucle Qt (overlay, réglages, assistant) ;
- thread « alfred-loop » : boucle asyncio (STT, LLM, tools, TTS) ;
- threads gérés par ``keyboard`` (hooks) et ``pystray`` (icône).

Les passerelles entre threads sont explicites : signaux Qt vers le thread Qt,
``asyncio.run_coroutine_threadsafe`` vers la boucle asyncio.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from alfred import __version__
from alfred.audio.sounds import SoundPlayer
from alfred.audio.stt import SpeechToText, list_input_devices
from alfred.audio.tts import TextToSpeech
from alfred.config import AlfredConfig, ConfigManager, logs_dir
from alfred.core import services
from alfred.core.context import ConversationContext
from alfred.core.executor import Executor, is_no, is_yes
from alfred.core.llm import OllamaClient
from alfred.core.logging_setup import set_level
from alfred.core.notify import WindowsNotifier
from alfred.core.router import Router, SemanticIndex
from alfred.persona.responses import pick
from alfred.tools.base import all_tools, load_all_tools
from alfred.ui.overlay import Overlay
from alfred.ui.settings import SettingsDialog
from alfred.ui.tray import Tray
from alfred.ui.wizard import FirstRunWizard
from alfred.updater import ReleaseInfo, Updater

log = logging.getLogger(__name__)


class AlfredApp(QObject):
    """Objet vivant dans le thread Qt ; ses signaux permettent aux autres threads de le solliciter."""

    sig_invoke = pyqtSignal(str)  # "voice" | "text"
    sig_cancel = pyqtSignal()
    sig_open_settings = pyqtSignal()
    sig_open_wizard = pyqtSignal()
    sig_quit = pyqtSignal()
    sig_restart = pyqtSignal()
    sig_toggle_pause = pyqtSignal()
    sig_check_updates = pyqtSignal()

    def __init__(
        self, qt_app: QApplication, config: ConfigManager, start_minimized: bool = True
    ) -> None:
        super().__init__()
        self._qt = qt_app
        self._config = config
        cfg = config.current

        # ---- boucle asyncio dans son thread ----------------------------
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_loop, name="alfred-loop", daemon=True)

        # ---- composants --------------------------------------------------
        self._sounds = SoundPlayer(cfg.behavior.sound_feedback)
        self._stt = SpeechToText(cfg.stt)
        self._tts = TextToSpeech(cfg.tts)
        self._llm = OllamaClient(cfg.llm)
        self._context = ConversationContext(cfg.behavior.history_turns)
        load_all_tools()
        self._semantic = SemanticIndex(all_tools())
        self._router = Router(cfg.router, all_tools(), self._semantic)
        self._executor = Executor(
            cfg, self._router, self._llm, self._context, self._speak, self._confirm
        )
        self._updater = Updater(cfg.updates)
        self._notifier = WindowsNotifier(fallback=lambda msg, title: self._tray.notify(msg, title))

        # ---- UI ----------------------------------------------------------
        self._overlay = Overlay(
            on_submit=self._on_overlay_submit, on_cancel=lambda: self.sig_cancel.emit()
        )
        self._tray = Tray(
            on_toggle_pause=lambda: self.sig_toggle_pause.emit(),
            on_settings=lambda: self.sig_open_settings.emit(),
            on_logs=self._open_logs,
            on_check_updates=lambda: self.sig_check_updates.emit(),
            on_restart=lambda: self.sig_restart.emit(),
            on_quit=lambda: self.sig_quit.emit(),
            on_invoke=lambda: self.sig_invoke.emit("voice"),
        )
        self._settings_dialog: SettingsDialog | None = None

        # ---- état de session -------------------------------------------
        self._paused = False
        self._session: Future[Any] | None = None
        self._cancel_event = threading.Event()
        self._ptt_event = threading.Event()
        self._pending_text: asyncio.Future[str] | None = None
        self._last_source = "voice"
        self._hotkey_handles: list[Any] = []

        # ---- services partagés pour les tools --------------------------
        services.config_manager = config
        services.tts = self._tts
        services.llm = self._llm
        services.notifier = self._notifier
        services.overlay = self._overlay
        services.context = self._context

        # ---- câblage -----------------------------------------------------
        self.sig_invoke.connect(self._on_invoke)
        self.sig_cancel.connect(self._on_cancel)
        self.sig_open_settings.connect(self._open_settings)
        self.sig_open_wizard.connect(self._open_wizard)
        self.sig_quit.connect(self.quit)
        self.sig_restart.connect(self.restart)
        self.sig_toggle_pause.connect(self._toggle_pause)
        self.sig_check_updates.connect(lambda: self._submit(self._check_updates(manual=True)))
        config.subscribe(self._on_config_changed)
        self._start_minimized = start_minimized

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    def start(self) -> None:
        self._loop_thread.start()
        self._tray.start()
        self._register_hotkeys(self._config.current)
        self._config.start_watching()
        self._submit(self._boot())
        if not self._config.current.general.first_run_done:
            self.sig_open_wizard.emit()
        elif not self._start_minimized:
            self.sig_open_settings.emit()
        log.info("Alfred %s démarré", __version__)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro: Coroutine[Any, Any, Any]) -> Future[Any]:
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def _boot(self) -> None:
        """Préchargements parallèles : index sémantique, Whisper, Piper, Ollama, mises à jour."""

        async def safe(name: str, coro: Coroutine[Any, Any, Any]) -> None:
            try:
                await coro
            except Exception:
                log.exception("Initialisation de %s échouée", name)

        await asyncio.gather(
            safe("index sémantique", asyncio.to_thread(self._semantic.build)),
            safe("Whisper", self._stt.load_async()),
            safe("Piper", self._tts.load_async()),
            safe("Ollama", self._llm.warm_up()),
        )
        log.info(
            "Prêt : %d tools, LLM %s",
            len(all_tools()),
            "disponible" if self._llm.available else "absent",
        )
        if self._config.current.updates.auto_check:
            await safe("mises à jour", self._check_updates(manual=False))

    def quit(self) -> None:
        log.info("Arrêt d'Alfred")
        self._on_cancel()
        try:
            import keyboard

            keyboard.unhook_all()
        except Exception:
            pass
        self._config.stop_watching()
        self._tray.stop()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._qt.quit()

    def restart(self) -> None:
        log.info("Redémarrage d'Alfred")
        if getattr(sys, "frozen", False):
            args = [sys.executable, *sys.argv[1:]]
        else:
            args = [sys.executable, "-m", "alfred", *sys.argv[1:]]
        subprocess.Popen(args, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        self.quit()

    # ------------------------------------------------------------------
    # Hotkeys
    # ------------------------------------------------------------------
    def _register_hotkeys(self, cfg: AlfredConfig) -> None:
        try:
            import keyboard
        except ImportError:
            log.error("Bibliothèque keyboard absente : pas de raccourcis globaux")
            return
        for handle in self._hotkey_handles:
            try:
                keyboard.remove_hotkey(handle)
            except (KeyError, ValueError):
                pass
        self._hotkey_handles.clear()
        hk = cfg.hotkeys
        try:
            if hk.push_to_talk:
                self._hotkey_handles.append(
                    keyboard.add_hotkey(hk.invoke_voice, self._ptt_press, suppress=False)
                )
                self._hotkey_handles.append(
                    keyboard.add_hotkey(
                        hk.invoke_voice, self._ptt_release, suppress=False, trigger_on_release=True
                    )
                )
            else:
                self._hotkey_handles.append(
                    keyboard.add_hotkey(hk.invoke_voice, lambda: self.sig_invoke.emit("voice"))
                )
            self._hotkey_handles.append(
                keyboard.add_hotkey(hk.invoke_text, lambda: self.sig_invoke.emit("text"))
            )
            self._hotkey_handles.append(
                keyboard.add_hotkey(hk.cancel, lambda: self.sig_cancel.emit())
            )
            log.info(
                "Raccourcis : voix=%s texte=%s annuler=%s",
                hk.invoke_voice,
                hk.invoke_text,
                hk.cancel,
            )
        except (ValueError, KeyError) as exc:
            log.error("Raccourci invalide : %s", exc)

    def _ptt_press(self) -> None:
        if not self._ptt_event.is_set():
            self._ptt_event.set()
            self.sig_invoke.emit("voice")

    def _ptt_release(self) -> None:
        self._ptt_event.clear()

    # ------------------------------------------------------------------
    # Slots Qt
    # ------------------------------------------------------------------
    def _on_invoke(self, mode: str) -> None:
        if self._paused:
            return
        if self._session is not None and not self._session.done():
            self._on_cancel()
        self._cancel_event = threading.Event()
        self._last_source = mode
        self._overlay.show_mode(mode)
        if mode == "voice":
            self._sounds.play("listen")
            self._session = self._submit(self._voice_session())

    def _on_cancel(self) -> None:
        self._cancel_event.set()
        self._tts.stop()
        if self._pending_text is not None and not self._pending_text.done():
            self._loop.call_soon_threadsafe(self._resolve_pending, "")
        if self._session is not None and not self._session.done():
            self._session.cancel()
        if self._overlay.isVisible():
            self._sounds.play("cancel")
        self._overlay.hide_later(0)

    def _on_overlay_submit(self, text: str) -> None:
        if self._pending_text is not None and not self._pending_text.done():
            self._loop.call_soon_threadsafe(self._resolve_pending, text)
            return
        self._sounds.play("click")
        self._overlay.set_state("thinking", text)
        self._cancel_event = threading.Event()
        self._last_source = "text"
        self._session = self._submit(self._process(text))

    def _resolve_pending(self, text: str) -> None:
        if self._pending_text is not None and not self._pending_text.done():
            self._pending_text.set_result(text)

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self._tray.set_paused(self._paused)
        if self._paused:
            self._on_cancel()
        log.info("Alfred %s", "en pause" if self._paused else "repris")

    def _open_settings(self) -> None:
        if self._settings_dialog is not None and self._settings_dialog.isVisible():
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        try:
            devices = list_input_devices()
        except Exception:
            devices = []
        self._settings_dialog = SettingsDialog(
            self._config,
            on_test_voice=self._say_test,
            on_check_updates=lambda: self.sig_check_updates.emit(),
            input_devices=devices,
        )
        self._settings_dialog.show()

    def _open_wizard(self) -> None:
        wizard = FirstRunWizard(self._config, speak_test=self._say_test)
        wizard.exec()

    def _say_test(self, text: str) -> None:
        """Test de voix depuis les réglages / l'assistant (thread Qt → boucle asyncio)."""
        self._submit(self._tts.say(text, interrupt=True))

    def _open_logs(self) -> None:
        path = logs_dir() / "alfred.log"
        if sys.platform == "win32":
            os.startfile(path if path.exists() else logs_dir())

    # ------------------------------------------------------------------
    # Rechargement à chaud
    # ------------------------------------------------------------------
    def _on_config_changed(self, cfg: AlfredConfig) -> None:
        self._sounds.enabled = cfg.behavior.sound_feedback
        self._stt.apply(cfg.stt)
        self._tts.apply(cfg.tts)
        self._llm.apply(cfg.llm)
        self._router.apply(cfg.router)
        self._executor.apply(cfg)
        self._updater.apply(cfg.updates)
        set_level(cfg.behavior.log_level)
        self._register_hotkeys(cfg)
        self._submit(self._llm.warm_up())

    # ------------------------------------------------------------------
    # Sessions (thread asyncio)
    # ------------------------------------------------------------------
    def _persona(self, category: str, detail: str = "") -> str:
        p = self._config.current.persona
        return pick(category, p.mode, p.address, detail)

    async def _voice_session(self) -> None:
        cfg = self._config.current
        hold = self._ptt_event if cfg.hotkeys.push_to_talk else None
        try:
            tr = await self._stt.listen(self._cancel_event, hold)
        except Exception:
            log.exception("Écoute impossible")
            self._overlay.set_state("error", "Micro indisponible")
            await self._tts.say(self._persona("error", "le microphone est indisponible."))
            self._overlay.hide_later(2500)
            return
        if self._cancel_event.is_set():
            return
        log.info(
            "STT : « %s » (enreg. %.0f ms, transcription %.0f ms)",
            tr.text,
            tr.record_ms,
            tr.transcribe_ms,
        )
        if not tr.text.strip():
            spoken = self._persona("nothing_heard")
            self._overlay.set_state("idle", spoken)
            await self._tts.say(spoken)
            self._overlay.hide_later(1500)
            return
        self._sounds.play("click")
        self._overlay.set_state("thinking", tr.text)
        await self._process(tr.text)

    async def _process(self, text: str) -> None:
        result = await self._executor.handle(text)
        if result.cancelled and not result.spoken:
            return
        if self._config.current.behavior.show_metrics:
            self._overlay.set_metrics(result.metrics.as_text())
        self._overlay.hide_later(2500 if result.tool else 4000)

    async def _speak(self, text: str) -> None:
        """Callback de l'exécuteur : affiche puis prononce."""
        self._overlay.set_state("speaking", "")
        self._overlay.set_reply(text)
        await self._tts.say(text)

    async def _confirm(self, question: str) -> bool:
        """Callback de l'exécuteur : pose la question, attend oui/non (voix ou texte)."""
        self._overlay.set_state("confirm", question)
        await self._tts.say(question)
        if self._cancel_event.is_set():
            return False
        if self._last_source == "voice":
            self._sounds.play("listen")
            self._overlay.set_state("listening", question)
            try:
                tr = await self._stt.listen(self._cancel_event, None)
            except Exception:
                log.exception("Écoute de confirmation impossible")
                return False
            answer = tr.text
        else:
            self._pending_text = self._loop.create_future()
            self._overlay.set_state("input", "")
            try:
                answer = await asyncio.wait_for(self._pending_text, timeout=30)
            except TimeoutError:
                answer = ""
            finally:
                self._pending_text = None
        log.info("Confirmation : « %s »", answer)
        if is_no(answer) or not answer:
            return False
        return is_yes(answer)

    # ------------------------------------------------------------------
    # Mises à jour
    # ------------------------------------------------------------------
    async def _check_updates(self, manual: bool) -> None:
        release: ReleaseInfo | None = await self._updater.check()
        if release is None:
            if manual:
                self._notifier.notify(
                    "Alfred", f"Vous disposez de la dernière version ({__version__})."
                )
            return
        notes = release.notes.splitlines()[0][:120] if release.notes else ""
        cfg = self._config.current.updates
        if cfg.auto_install and release.installer_url:
            path = await self._updater.download(release)
            if path is not None:
                self._updater.schedule_install(path, release)
                self._notifier.notify(
                    "Alfred — mise à jour prête",
                    f"La version {release.version} sera installée au prochain redémarrage. {notes}",
                )
                return
        self._notifier.notify(
            "Alfred — mise à jour disponible", f"Version {release.version}. {notes}".strip()
        )
        if manual:
            self._updater.open_release_page(release)
