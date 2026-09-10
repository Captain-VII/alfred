"""Panneau de réglages (PyQt6). Écrit dans ``config.yaml`` via ``ConfigManager.update``."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from alfred import __version__, startup
from alfred.audio.tts import KNOWN_VOICES
from alfred.config import ConfigManager
from alfred.ui.theme import dialog_stylesheet, label, palette

log = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    def __init__(
        self,
        config: ConfigManager,
        on_test_voice: Callable[[str], None],
        on_check_updates: Callable[[], None],
        input_devices: list[tuple[int, str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._on_test_voice = on_test_voice
        self._on_check_updates = on_check_updates
        self._input_devices = input_devices or []
        self.setWindowTitle(f"Alfred — Réglages (v{__version__})")
        self.setMinimumWidth(560)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setStyleSheet(dialog_stylesheet(palette()))

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_general(), "Général")
        self._tabs.addTab(self._build_hotkeys(), "Raccourcis")
        self._tabs.addTab(self._build_models(), "Modèles")
        self._tabs.addTab(self._build_voice(), "Voix")
        self._tabs.addTab(self._build_updates(), "Mises à jour")
        self._tabs.addTab(self._build_aliases(), "Alias")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        for std, text in (
            (QDialogButtonBox.StandardButton.Save, "Enregistrer"),
            (QDialogButtonBox.StandardButton.Cancel, "Annuler"),
        ):
            btn = buttons.button(std)
            if btn is not None:
                btn.setText(text)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._tabs)
        layout.addWidget(buttons)
        self._load()

    # ------------------------------------------------------------------
    # Construction des onglets
    # ------------------------------------------------------------------
    def _build_general(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.start_with_windows = QCheckBox("Lancer Alfred au démarrage de Windows")
        self.start_minimized = QCheckBox("Démarrer dans la barre système")
        self.persona_mode = QComboBox()
        self.persona_mode.addItem("Formel (phrases complètes)", "formal")
        self.persona_mode.addItem("Concis (un mot)", "concise")
        self.address = QLineEdit()
        self.address.setPlaceholderText("monsieur, madame, un prénom…")
        self.confirm_destructive = QCheckBox("Confirmer vocalement les actions irréversibles")
        self.sound_feedback = QCheckBox("Feedback sonore (clic à la capture)")
        self.show_metrics = QCheckBox("Afficher les latences dans l'overlay")
        self.log_level = QComboBox()
        for lvl in ("debug", "info", "warning", "error"):
            self.log_level.addItem(lvl, lvl)
        self.history_turns = QSpinBox()
        self.history_turns.setRange(0, 50)
        form.addRow(self.start_with_windows)
        form.addRow(self.start_minimized)
        form.addRow("Registre de réponse", self.persona_mode)
        form.addRow("Formule d'adresse", self.address)
        form.addRow(self.confirm_destructive)
        form.addRow(self.sound_feedback)
        form.addRow(self.show_metrics)
        form.addRow("Tours de contexte", self.history_turns)
        form.addRow("Niveau de log", self.log_level)
        return w

    def _build_hotkeys(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.hk_voice = QLineEdit()
        self.hk_text = QLineEdit()
        self.hk_cancel = QLineEdit()
        self.push_to_talk = QCheckBox("Push-to-talk : enregistrer tant que la touche est maintenue")
        hint = label(
            "Syntaxe : ctrl+space, ctrl+shift+space, alt+a, f9… (bibliothèque keyboard)", "hint"
        )
        form.addRow("Invocation vocale", self.hk_voice)
        form.addRow("Invocation texte", self.hk_text)
        form.addRow("Annulation", self.hk_cancel)
        form.addRow(self.push_to_talk)
        form.addRow(hint)
        return w

    def _build_models(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        llm_box = QGroupBox("LLM (Ollama)")
        llm_form = QFormLayout(llm_box)
        self.llm_model = QLineEdit()
        self.llm_fallback = QLineEdit()
        self.llm_host = QLineEdit()
        self.llm_temperature = QDoubleSpinBox()
        self.llm_temperature.setRange(0.0, 2.0)
        self.llm_temperature.setSingleStep(0.1)
        self.llm_timeout = QDoubleSpinBox()
        self.llm_timeout.setRange(1.0, 120.0)
        self.llm_timeout.setSuffix(" s")
        self.enable_llm = QCheckBox("Utiliser le LLM en dernier recours (niveau 3)")
        self.semantic_threshold = QDoubleSpinBox()
        self.semantic_threshold.setRange(0.5, 1.0)
        self.semantic_threshold.setSingleStep(0.01)
        self.semantic_threshold.setDecimals(2)
        llm_form.addRow("Modèle", self.llm_model)
        llm_form.addRow("Modèle de secours", self.llm_fallback)
        llm_form.addRow("Hôte", self.llm_host)
        llm_form.addRow("Température", self.llm_temperature)
        llm_form.addRow("Délai maximal", self.llm_timeout)
        llm_form.addRow(self.enable_llm)
        llm_form.addRow("Seuil sémantique", self.semantic_threshold)

        stt_box = QGroupBox("Reconnaissance vocale (faster-whisper)")
        stt_form = QFormLayout(stt_box)
        self.stt_model = QComboBox()
        for m in ("tiny", "base", "small", "medium", "large-v3"):
            self.stt_model.addItem(m, m)
        self.stt_device = QComboBox()
        for d in ("auto", "cuda", "cpu"):
            self.stt_device.addItem(d, d)
        self.stt_compute = QComboBox()
        for c in ("int8", "int8_float16", "float16", "float32"):
            self.stt_compute.addItem(c, c)
        self.vad = QSpinBox()
        self.vad.setRange(0, 3)
        self.max_recording = QDoubleSpinBox()
        self.max_recording.setRange(3.0, 60.0)
        self.max_recording.setSuffix(" s")
        self.silence_end = QSpinBox()
        self.silence_end.setRange(200, 3000)
        self.silence_end.setSuffix(" ms")
        self.input_device = QComboBox()
        self.input_device.addItem("Périphérique par défaut", None)
        for idx, name in self._input_devices:
            self.input_device.addItem(f"{idx} — {name}", idx)
        stt_form.addRow("Modèle", self.stt_model)
        stt_form.addRow("Périphérique de calcul", self.stt_device)
        stt_form.addRow("Précision", self.stt_compute)
        stt_form.addRow("Agressivité VAD", self.vad)
        stt_form.addRow("Durée max", self.max_recording)
        stt_form.addRow("Silence de fin", self.silence_end)
        stt_form.addRow("Microphone", self.input_device)

        layout.addWidget(llm_box)
        layout.addWidget(stt_box)
        layout.addStretch()
        return w

    def _build_voice(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.tts_enabled = QCheckBox("Réponses vocales activées")
        self.tts_voice = QComboBox()
        self.tts_voice.setEditable(True)
        for name in KNOWN_VOICES:
            self.tts_voice.addItem(name, name)
        self.length_scale = QDoubleSpinBox()
        self.length_scale.setRange(0.5, 2.0)
        self.length_scale.setSingleStep(0.02)
        self.noise_scale = QDoubleSpinBox()
        self.noise_scale.setRange(0.0, 2.0)
        self.noise_scale.setSingleStep(0.05)
        self.noise_scale.setDecimals(3)
        self.sentence_silence = QDoubleSpinBox()
        self.sentence_silence.setRange(0.0, 2.0)
        self.sentence_silence.setSingleStep(0.05)
        self.sentence_silence.setSuffix(" s")
        self.tts_volume = QDoubleSpinBox()
        self.tts_volume.setRange(0.0, 1.0)
        self.tts_volume.setSingleStep(0.05)
        test_row = QHBoxLayout()
        self.test_text = QLineEdit("Bonsoir, monsieur. Le dîner est servi.")
        test_btn = QPushButton("Écouter")
        test_btn.clicked.connect(lambda: self._on_test_voice(self.test_text.text()))
        test_row.addWidget(self.test_text)
        test_row.addWidget(test_btn)
        form.addRow(self.tts_enabled)
        form.addRow("Voix Piper", self.tts_voice)
        form.addRow("Débit (length_scale)", self.length_scale)
        form.addRow("Variabilité (noise_scale)", self.noise_scale)
        form.addRow("Pause entre phrases", self.sentence_silence)
        form.addRow("Volume", self.tts_volume)
        form.addRow("Test", test_row)
        form.addRow(
            label("Une nouvelle voix est téléchargée automatiquement à l'enregistrement.", "hint")
        )
        return w

    def _build_updates(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.auto_check = QCheckBox("Vérifier les mises à jour au démarrage")
        self.auto_install = QCheckBox("Installer silencieusement au prochain redémarrage")
        self.channel = QComboBox()
        self.channel.addItem("Stable", "stable")
        self.channel.addItem("Bêta", "beta")
        check_btn = QPushButton("Vérifier maintenant")
        check_btn.clicked.connect(lambda: self._on_check_updates())
        form.addRow(self.auto_check)
        form.addRow(self.auto_install)
        form.addRow("Canal", self.channel)
        form.addRow(check_btn)
        form.addRow(label(f"Version installée : {__version__}", "hint"))
        return w

    def _build_aliases(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(
            QLabel(
                "Un alias par ligne : nom parlé = exécutable (ex. « navigateur = firefox.exe »)."
            )
        )
        self.aliases = QPlainTextEdit()
        self.aliases.setMinimumHeight(220)
        layout.addWidget(self.aliases)
        return w

    # ------------------------------------------------------------------
    # Chargement / sauvegarde
    # ------------------------------------------------------------------
    @staticmethod
    def _select(combo: QComboBox, value: Any) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        elif combo.isEditable():
            combo.setEditText(str(value))

    def _load(self) -> None:
        c = self._config.current
        self.start_with_windows.setChecked(startup.is_enabled() or c.general.start_with_windows)
        self.start_minimized.setChecked(c.general.start_minimized)
        self._select(self.persona_mode, c.persona.mode)
        self.address.setText(c.persona.address)
        self.confirm_destructive.setChecked(c.behavior.confirm_destructive)
        self.sound_feedback.setChecked(c.behavior.sound_feedback)
        self.show_metrics.setChecked(c.behavior.show_metrics)
        self.history_turns.setValue(c.behavior.history_turns)
        self._select(self.log_level, c.behavior.log_level)

        self.hk_voice.setText(c.hotkeys.invoke_voice)
        self.hk_text.setText(c.hotkeys.invoke_text)
        self.hk_cancel.setText(c.hotkeys.cancel)
        self.push_to_talk.setChecked(c.hotkeys.push_to_talk)

        self.llm_model.setText(c.llm.model)
        self.llm_fallback.setText(c.llm.fallback_model or "")
        self.llm_host.setText(c.llm.host)
        self.llm_temperature.setValue(c.llm.temperature)
        self.llm_timeout.setValue(c.llm.timeout_s)
        self.enable_llm.setChecked(c.router.enable_llm_fallback)
        self.semantic_threshold.setValue(c.router.semantic_threshold)
        self._select(self.stt_model, c.stt.model)
        self._select(self.stt_device, c.stt.device)
        self._select(self.stt_compute, c.stt.compute_type)
        self.vad.setValue(c.stt.vad_aggressiveness)
        self.max_recording.setValue(c.stt.max_recording_s)
        self.silence_end.setValue(c.stt.silence_end_ms)
        self._select(self.input_device, c.stt.input_device)

        self.tts_enabled.setChecked(c.tts.enabled)
        self._select(self.tts_voice, c.tts.voice)
        self.length_scale.setValue(c.tts.length_scale)
        self.noise_scale.setValue(c.tts.noise_scale)
        self.sentence_silence.setValue(c.tts.sentence_silence)
        self.tts_volume.setValue(c.tts.volume)

        self.auto_check.setChecked(c.updates.auto_check)
        self.auto_install.setChecked(c.updates.auto_install)
        self._select(self.channel, c.updates.channel)

        self.aliases.setPlainText("\n".join(f"{k} = {v}" for k, v in c.app_aliases.items()))

    def _parse_aliases(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in self.aliases.toPlainText().splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                if key.strip() and value.strip():
                    result[key.strip().lower()] = value.strip()
        return result

    def _save(self) -> None:
        try:
            self._config.update(
                general={
                    "start_with_windows": self.start_with_windows.isChecked(),
                    "start_minimized": self.start_minimized.isChecked(),
                },
                hotkeys={
                    "invoke_voice": self.hk_voice.text().strip() or "ctrl+space",
                    "invoke_text": self.hk_text.text().strip() or "ctrl+shift+space",
                    "cancel": self.hk_cancel.text().strip() or "escape",
                    "push_to_talk": self.push_to_talk.isChecked(),
                },
                llm={
                    "model": self.llm_model.text().strip(),
                    "fallback_model": self.llm_fallback.text().strip() or None,
                    "host": self.llm_host.text().strip(),
                    "temperature": self.llm_temperature.value(),
                    "timeout_s": self.llm_timeout.value(),
                },
                stt={
                    "model": self.stt_model.currentData(),
                    "device": self.stt_device.currentData(),
                    "compute_type": self.stt_compute.currentData(),
                    "vad_aggressiveness": self.vad.value(),
                    "max_recording_s": self.max_recording.value(),
                    "silence_end_ms": self.silence_end.value(),
                    "input_device": self.input_device.currentData(),
                },
                tts={
                    "enabled": self.tts_enabled.isChecked(),
                    "voice": self.tts_voice.currentText().strip(),
                    "length_scale": self.length_scale.value(),
                    "noise_scale": self.noise_scale.value(),
                    "sentence_silence": self.sentence_silence.value(),
                    "volume": self.tts_volume.value(),
                },
                router={
                    "enable_llm_fallback": self.enable_llm.isChecked(),
                    "semantic_threshold": self.semantic_threshold.value(),
                },
                persona={
                    "mode": self.persona_mode.currentData(),
                    "address": self.address.text().strip() or "monsieur",
                },
                behavior={
                    "confirm_destructive": self.confirm_destructive.isChecked(),
                    "sound_feedback": self.sound_feedback.isChecked(),
                    "show_metrics": self.show_metrics.isChecked(),
                    "history_turns": self.history_turns.value(),
                    "log_level": self.log_level.currentData(),
                },
                updates={
                    "auto_check": self.auto_check.isChecked(),
                    "auto_install": self.auto_install.isChecked(),
                    "channel": self.channel.currentData(),
                },
                app_aliases=self._parse_aliases(),
            )
            startup.set_enabled(self.start_with_windows.isChecked())
        except Exception as exc:
            log.exception("Sauvegarde des réglages impossible")
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.critical(self, "Alfred", f"Impossible d'enregistrer les réglages :\n{exc}")
            return
        self.accept()
