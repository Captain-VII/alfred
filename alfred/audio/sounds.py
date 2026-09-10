"""Feedbacks sonores courts (clic de capture, confirmation, erreur).

Les sons sont synthétisés en mémoire au démarrage (aucun fichier requis) et
joués de façon non bloquante. Le « clic » est joué dès que l'entrée est
captée, avant même l'exécution : la latence perçue compte autant que la réelle.
Si des fichiers ``assets/sounds/<nom>.wav`` existent, ils sont utilisés à la place.
"""

from __future__ import annotations

import logging
import threading
import wave
from pathlib import Path

import numpy as np

from alfred.config import assets_dir

log = logging.getLogger(__name__)

SAMPLE_RATE = 44_100


def _tone(
    freq: float,
    duration_s: float,
    volume: float = 0.3,
    attack_s: float = 0.003,
    decay_s: float = 0.04,
) -> np.ndarray:
    n = int(SAMPLE_RATE * duration_s)
    t = np.linspace(0, duration_s, n, endpoint=False)
    wave_ = np.sin(2 * np.pi * freq * t)
    env = np.ones(n)
    a = int(SAMPLE_RATE * attack_s)
    d = int(SAMPLE_RATE * decay_s)
    if a:
        env[:a] = np.linspace(0, 1, a)
    if d and d < n:
        env[-d:] = np.linspace(1, 0, d)
    return (wave_ * env * volume).astype(np.float32)


def _silence(duration_s: float) -> np.ndarray:
    return np.zeros(int(SAMPLE_RATE * duration_s), dtype=np.float32)


def _build_sounds() -> dict[str, np.ndarray]:
    return {
        # Clic discret : très court, aigu, faible
        "click": _tone(1800, 0.035, volume=0.18, decay_s=0.02),
        # Début d'écoute : deux notes montantes
        "listen": np.concatenate([_tone(660, 0.07, 0.2), _silence(0.02), _tone(880, 0.09, 0.2)]),
        # Confirmation : note douce
        "ok": _tone(987, 0.12, 0.2, decay_s=0.08),
        # Erreur : note grave descendante
        "error": np.concatenate([_tone(330, 0.1, 0.22), _silence(0.02), _tone(247, 0.16, 0.22)]),
        # Annulation : note courte grave
        "cancel": _tone(392, 0.08, 0.18),
        # Minuteur : trois notes
        "timer": np.concatenate(
            [
                _tone(880, 0.12, 0.3),
                _silence(0.05),
                _tone(880, 0.12, 0.3),
                _silence(0.05),
                _tone(1175, 0.25, 0.3),
            ]
        ),
    }


def _load_wav(path: Path) -> np.ndarray | None:
    try:
        with wave.open(str(path), "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            width = wf.getsampwidth()
            channels = wf.getnchannels()
        if width != 2:
            return None
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            data = data.reshape(-1, channels).mean(axis=1)
        return data
    except (OSError, wave.Error):
        return None


class SoundPlayer:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._sounds = _build_sounds()
        folder = assets_dir() / "sounds"
        for name in list(self._sounds):
            custom = folder / f"{name}.wav"
            if custom.exists():
                data = _load_wav(custom)
                if data is not None:
                    self._sounds[name] = data

    def play(self, name: str) -> None:
        """Joue un son sans bloquer. Ignoré si désactivé ou inconnu."""
        if not self.enabled:
            return
        data = self._sounds.get(name)
        if data is None:
            return
        threading.Thread(
            target=self._play_blocking, args=(data,), daemon=True, name=f"sound-{name}"
        ).start()

    @staticmethod
    def _play_blocking(data: np.ndarray) -> None:
        try:
            import sounddevice as sd

            sd.play(data, SAMPLE_RATE, blocking=True)
        except Exception:
            log.debug("Impossible de jouer le son", exc_info=True)

    def export(self, folder: Path) -> None:
        """Écrit les sons générés en WAV (utile pour personnaliser les assets)."""
        folder.mkdir(parents=True, exist_ok=True)
        for name, data in self._sounds.items():
            with wave.open(str(folder / f"{name}.wav"), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes((data * 32767).astype(np.int16).tobytes())
