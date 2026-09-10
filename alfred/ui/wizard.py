"""Assistant de premier lancement.

Étapes : Ollama → modèle LLM → voix Piper → micro & haut-parleurs → démarrage auto.
Les opérations longues (téléchargements) tournent dans des ``QThread`` et
remontent leur progression par signaux, l'interface reste fluide.
"""

from __future__ import annotations

import json
import logging
import shutil
import webbrowser
from collections.abc import Callable

import httpx
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from alfred import startup
from alfred.audio.tts import download_voice, voice_installed
from alfred.config import ConfigManager
from alfred.ui.theme import dialog_stylesheet, label, palette

log = logging.getLogger(__name__)

OLLAMA_DOWNLOAD_URL = "https://ollama.com/download/windows"


# ----------------------------------------------------------------------
# Threads de travail
# ----------------------------------------------------------------------


class _PullModelThread(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(bool, str)

    def __init__(self, host: str, model: str) -> None:
        super().__init__()
        self._host = host
        self._model = model

    def run(self) -> None:
        try:
            with httpx.stream(
                "POST", f"{self._host}/api/pull", json={"name": self._model}, timeout=None
            ) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line.strip():
                        continue
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    status = str(ev.get("status", ""))
                    total = int(ev.get("total", 0) or 0)
                    done = int(ev.get("completed", 0) or 0)
                    pct = int(done * 100 / total) if total else (100 if status == "success" else 0)
                    self.progress.emit(pct, status)
                    if "error" in ev:
                        self.finished_ok.emit(False, str(ev["error"]))
                        return
            self.finished_ok.emit(True, "")
        except Exception as exc:
            self.finished_ok.emit(False, str(exc))


class _DownloadVoiceThread(QThread):
    progress = pyqtSignal(int)
    finished_ok = pyqtSignal(bool, str)

    def __init__(self, voice: str) -> None:
        super().__init__()
        self._voice = voice

    def run(self) -> None:
        try:
            download_voice(
                self._voice,
                lambda done, total: self.progress.emit(int(done * 100 / total) if total else 0),
            )
            self.finished_ok.emit(True, "")
        except Exception as exc:
            self.finished_ok.emit(False, str(exc))


class _MicLevelThread(QThread):
    level = pyqtSignal(float)

    def __init__(self, device: int | str | None) -> None:
        super().__init__()
        self._device = device
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        from alfred.audio.stt import mic_level

        while self._running:
            try:
                self.level.emit(mic_level(0.2, self._device))
            except Exception:
                self.level.emit(-1.0)
                self.msleep(500)


# ----------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------


class _WelcomePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Bienvenue")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Alfred est un majordome vocal entièrement local.\n\n"
                "Cet assistant va vérifier Ollama, télécharger le modèle de langage et la voix,\n"
                "puis tester votre micro et vos haut-parleurs. Comptez quelques minutes,\n"
                "selon votre connexion."
            )
        )
        layout.addStretch()


class _OllamaPage(QWizardPage):
    def __init__(self, host: str) -> None:
        super().__init__()
        self._host = host
        self._ok = False
        self.setTitle("Ollama")
        layout = QVBoxLayout(self)
        self._status = QLabel("Vérification…")
        self._status.setWordWrap(True)
        btn_row = QVBoxLayout()
        self._download_btn = QPushButton("Ouvrir la page de téléchargement d'Ollama")
        self._download_btn.clicked.connect(lambda: webbrowser.open(OLLAMA_DOWNLOAD_URL))
        self._retry_btn = QPushButton("Revérifier")
        self._retry_btn.clicked.connect(self._check)
        btn_row.addWidget(self._download_btn)
        btn_row.addWidget(self._retry_btn)
        layout.addWidget(self._status)
        layout.addLayout(btn_row)
        layout.addWidget(
            label("Ollama doit être installé et lancé (icône dans la barre système).", "hint")
        )
        layout.addStretch()

    def initializePage(self) -> None:
        self._check()

    def _check(self) -> None:
        installed = shutil.which("ollama") is not None
        try:
            r = httpx.get(f"{self._host}/api/tags", timeout=2.0)
            running = r.status_code == 200
        except httpx.HTTPError:
            running = False
        self._ok = running
        if running:
            self._status.setText("✔ Ollama est installé et répond. Vous pouvez continuer.")
        elif installed:
            self._status.setText(
                "Ollama est installé mais ne répond pas. Lancez-le (menu Démarrer → Ollama), puis revérifiez."
            )
        else:
            self._status.setText(
                "Ollama n'est pas détecté. Téléchargez-le, installez-le, puis revérifiez."
            )
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._ok


class _ModelPage(QWizardPage):
    def __init__(self, host: str, model: str) -> None:
        super().__init__()
        self._host = host
        self._model = model
        self._done = False
        self._thread: _PullModelThread | None = None
        self.setTitle("Modèle de langage")
        layout = QVBoxLayout(self)
        self._status = QLabel(f"Téléchargement de {model} (plusieurs Go la première fois).")
        self._status.setWordWrap(True)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._btn = QPushButton("Télécharger")
        self._btn.clicked.connect(self._start)
        layout.addWidget(self._status)
        layout.addWidget(self._bar)
        layout.addWidget(self._btn)
        layout.addStretch()

    def initializePage(self) -> None:
        try:
            r = httpx.get(f"{self._host}/api/tags", timeout=2.0)
            names = [m["name"] for m in r.json().get("models", [])]
            if self._model in names or self._model.split(":")[0] in {
                n.split(":")[0] for n in names
            }:
                self._done = True
                self._bar.setValue(100)
                self._status.setText(f"✔ {self._model} est déjà présent.")
                self._btn.setEnabled(False)
                self.completeChanged.emit()
        except (httpx.HTTPError, ValueError, KeyError):
            pass

    def _start(self) -> None:
        self._btn.setEnabled(False)
        self._thread = _PullModelThread(self._host, self._model)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished_ok.connect(self._on_finished)
        self._thread.start()

    def _on_progress(self, pct: int, status: str) -> None:
        self._bar.setValue(pct)
        self._status.setText(f"{status} — {pct} %")

    def _on_finished(self, ok: bool, error: str) -> None:
        self._done = ok
        self._btn.setEnabled(not ok)
        self._status.setText(f"✔ {self._model} est prêt." if ok else f"Échec : {error}")
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._done


class _VoicePage(QWizardPage):
    def __init__(self, voice: str) -> None:
        super().__init__()
        self._voice = voice
        self._done = False
        self._thread: _DownloadVoiceThread | None = None
        self.setTitle("Voix du majordome")
        layout = QVBoxLayout(self)
        self._status = QLabel(f"Téléchargement de la voix {voice} (~60 Mo).")
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._btn = QPushButton("Télécharger")
        self._btn.clicked.connect(self._start)
        layout.addWidget(self._status)
        layout.addWidget(self._bar)
        layout.addWidget(self._btn)
        layout.addStretch()

    def initializePage(self) -> None:
        if voice_installed(self._voice):
            self._done = True
            self._bar.setValue(100)
            self._status.setText(f"✔ La voix {self._voice} est déjà installée.")
            self._btn.setEnabled(False)
            self.completeChanged.emit()

    def _start(self) -> None:
        self._btn.setEnabled(False)
        self._thread = _DownloadVoiceThread(self._voice)
        self._thread.progress.connect(self._bar.setValue)
        self._thread.finished_ok.connect(self._on_finished)
        self._thread.start()

    def _on_finished(self, ok: bool, error: str) -> None:
        self._done = ok
        self._btn.setEnabled(not ok)
        self._status.setText("✔ Voix prête." if ok else f"Échec : {error}")
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self._done


class _AudioTestPage(QWizardPage):
    def __init__(self, config: ConfigManager, speak_test: Callable[[str], None]) -> None:
        super().__init__()
        self._config = config
        self._speak_test = speak_test
        self._mic_thread: _MicLevelThread | None = None
        self.setTitle("Micro et haut-parleurs")
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Parlez : la barre doit bouger. Choisissez un autre micro si besoin.")
        )
        self._devices = QComboBox()
        self._devices.addItem("Périphérique par défaut", None)
        try:
            from alfred.audio.stt import list_input_devices

            for idx, name in list_input_devices():
                self._devices.addItem(f"{idx} — {name}", idx)
        except Exception:
            log.debug("Liste des micros indisponible", exc_info=True)
        self._devices.currentIndexChanged.connect(self._restart_mic)
        self._level = QProgressBar()
        self._level.setRange(0, 100)
        self._level.setTextVisible(False)
        speak_btn = QPushButton("Tester les haut-parleurs (Alfred parle)")
        speak_btn.clicked.connect(lambda: self._speak_test("Bonsoir. Alfred, à votre service."))
        layout.addWidget(self._devices)
        layout.addWidget(self._level)
        layout.addWidget(speak_btn)
        layout.addStretch()

    def initializePage(self) -> None:
        self._restart_mic()

    def cleanupPage(self) -> None:
        self._stop_mic()

    def validatePage(self) -> bool:
        self._stop_mic()
        self._config.update(stt={"input_device": self._devices.currentData()})
        return True

    def _restart_mic(self) -> None:
        self._stop_mic()
        self._mic_thread = _MicLevelThread(self._devices.currentData())
        self._mic_thread.level.connect(self._on_level)
        self._mic_thread.start()

    def _stop_mic(self) -> None:
        if self._mic_thread is not None:
            self._mic_thread.stop()
            self._mic_thread.wait(1500)
            self._mic_thread = None

    def _on_level(self, rms: float) -> None:
        if rms < 0:
            self._level.setValue(0)
            return
        self._level.setValue(max(0, min(100, int(rms * 800))))


class _FinishPage(QWizardPage):
    def __init__(self, config: ConfigManager) -> None:
        super().__init__()
        self._config = config
        self.setTitle("Terminé")
        layout = QVBoxLayout(self)
        self.autostart = QCheckBox("Lancer Alfred au démarrage de Windows")
        self.autostart.setChecked(config.current.general.start_with_windows)
        hk = config.current.hotkeys
        layout.addWidget(self.autostart)
        layout.addWidget(
            QLabel(
                f"Invocation vocale : {hk.invoke_voice}\nInvocation texte : {hk.invoke_text}\nAnnulation : {hk.cancel}"
            )
        )
        layout.addWidget(
            label("Alfred se tient à votre disposition dans la barre système.", "hint")
        )
        layout.addStretch()

    def validatePage(self) -> bool:
        enabled = self.autostart.isChecked()
        self._config.update(general={"start_with_windows": enabled, "first_run_done": True})
        try:
            startup.set_enabled(enabled)
        except OSError:
            log.exception("Impossible de modifier le démarrage automatique")
        return True


# ----------------------------------------------------------------------
# Assistant
# ----------------------------------------------------------------------


class FirstRunWizard(QWizard):
    def __init__(self, config: ConfigManager, speak_test: Callable[[str], None]) -> None:
        super().__init__()
        self.setWindowTitle("Alfred — Premier lancement")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setStyleSheet(dialog_stylesheet(palette()))
        self.setMinimumSize(560, 400)
        self.setButtonText(QWizard.WizardButton.NextButton, "Suivant")
        self.setButtonText(QWizard.WizardButton.BackButton, "Précédent")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Terminer")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Annuler")
        c = config.current
        self.addPage(_WelcomePage())
        self.addPage(_OllamaPage(c.llm.host))
        self.addPage(_ModelPage(c.llm.host, c.llm.model))
        self.addPage(_VoicePage(c.tts.voice))
        self.addPage(_AudioTestPage(config, speak_test))
        self.addPage(_FinishPage(config))
        # Assure l'affichage au premier plan même lancé depuis une session minimisée
        QTimer.singleShot(0, self.raise_)
