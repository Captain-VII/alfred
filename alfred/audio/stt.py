"""Reconnaissance vocale : capture micro + VAD (webrtcvad) + faster-whisper.

- Le modèle Whisper est chargé une seule fois en RAM (:meth:`SpeechToText.load`).
- L'enregistrement démarre à la première parole détectée et s'arrête après
  ``silence_end_ms`` de silence, ou à ``max_recording_s``.
- Tout le traitement bloquant tourne dans un thread ; l'API est ``async``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from alfred.config import STTConfig

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 480 échantillons
PRE_ROLL_FRAMES = 10  # ~300 ms conservés avant la détection de parole


_CUDA_FAILURE_MARKERS = ("cublas", "cudnn", "cuda", "libcu", "gpu")


def _is_cuda_failure(exc: BaseException) -> bool:
    """Vrai si l'exception provient d'une pile CUDA absente ou incomplète."""
    return any(marker in str(exc).lower() for marker in _CUDA_FAILURE_MARKERS)


@dataclass(slots=True)
class Transcription:
    text: str
    record_ms: float
    transcribe_ms: float
    language_prob: float = 0.0


class SpeechToText:
    def __init__(self, cfg: STTConfig) -> None:
        self._cfg = cfg
        self._model: Any = None
        self._vad: Any = None
        self._forced_device: str | None = None  # « cpu » après un échec CUDA
        self._lock = threading.Lock()

    # ---- cycle de vie ------------------------------------------------
    def apply(self, cfg: STTConfig) -> None:
        """Rechargement à chaud : le modèle n'est rechargé que s'il change."""
        reload_needed = (cfg.model, cfg.device, cfg.compute_type) != (
            self._cfg.model,
            self._cfg.device,
            self._cfg.compute_type,
        )
        self._cfg = cfg
        self._vad = None
        if reload_needed:
            self._forced_device = None
        if reload_needed and self._model is not None:
            self._model = None
            threading.Thread(target=self.load, daemon=True, name="stt-reload").start()

    def _resolve_device(self) -> tuple[str, str]:
        device, compute = self._cfg.device, self._cfg.compute_type
        if self._forced_device:
            return self._forced_device, "int8"
        if device == "auto":
            try:
                import ctranslate2

                device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
            except Exception:
                device = "cpu"
        if device == "cpu" and compute in ("float16", "int8_float16"):
            compute = "int8"
        return device, compute

    def load(self) -> None:
        """Charge le modèle Whisper (bloquant, ~2-5 s ; appelé au boot dans un thread)."""
        with self._lock:
            if self._model is not None:
                return
            from faster_whisper import WhisperModel

            device, compute = self._resolve_device()
            started = time.perf_counter()
            self._model = WhisperModel(
                self._cfg.model,
                device=device,
                compute_type=compute,
                cpu_threads=4,
                num_workers=1,
            )
            log.info(
                "Whisper %s chargé sur %s/%s en %.1f s",
                self._cfg.model,
                device,
                compute,
                time.perf_counter() - started,
            )

    @property
    def ready(self) -> bool:
        return self._model is not None

    async def load_async(self) -> None:
        await asyncio.to_thread(self.load)

    # ---- VAD ---------------------------------------------------------
    def _get_vad(self) -> Any:
        if self._vad is None:
            import webrtcvad

            self._vad = webrtcvad.Vad(self._cfg.vad_aggressiveness)
        return self._vad

    # ---- capture -----------------------------------------------------
    def _open_stream(self) -> Any:
        import sounddevice as sd

        device = self._cfg.input_device
        if isinstance(device, str) and device.strip():
            device = _find_input_device(device)
        return sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SAMPLES,
            device=device if device not in ("", None) else None,
        )

    def record(self, cancel: threading.Event, hold: threading.Event | None = None) -> np.ndarray:
        """Enregistre jusqu'à la fin de phrase (VAD) ou l'annulation.

        ``hold`` (push-to-talk) : si fourni, on enregistre tant qu'il est levé,
        sans se fier au VAD pour la fin.
        """
        vad = self._get_vad()
        frames: list[bytes] = []
        pre_roll: deque[bytes] = deque(maxlen=PRE_ROLL_FRAMES)
        speech_started = False
        silence_frames_needed = max(1, self._cfg.silence_end_ms // FRAME_MS)
        silence_run = 0
        max_frames = int(self._cfg.max_recording_s * 1000 // FRAME_MS)
        no_speech_timeout_frames = int(4000 // FRAME_MS)  # 4 s sans parole → on abandonne
        total = 0

        with self._open_stream() as stream:
            while not cancel.is_set() and total < max_frames:
                data, _overflow = stream.read(FRAME_SAMPLES)
                chunk = bytes(data)
                total += 1
                if hold is not None:
                    frames.append(chunk)
                    if not hold.is_set():
                        break
                    continue
                is_speech = vad.is_speech(chunk, SAMPLE_RATE)
                if not speech_started:
                    pre_roll.append(chunk)
                    if is_speech:
                        speech_started = True
                        frames.extend(pre_roll)
                    elif total >= no_speech_timeout_frames:
                        break
                    continue
                frames.append(chunk)
                if is_speech:
                    silence_run = 0
                else:
                    silence_run += 1
                    if silence_run >= silence_frames_needed:
                        break
        if not frames:
            return np.zeros(0, dtype=np.float32)
        audio = np.frombuffer(b"".join(frames), dtype=np.int16).astype(np.float32) / 32768.0
        return audio

    # ---- transcription -----------------------------------------------
    def _transcribe_once(self, audio: np.ndarray) -> tuple[str, float]:
        segments, info = self._model.transcribe(
            audio,
            language="fr",
            beam_size=1,
            best_of=1,
            temperature=0.0,
            vad_filter=False,
            without_timestamps=True,
            condition_on_previous_text=False,
            initial_prompt="Commande vocale à un assistant : ouvre, ferme, monte le son, rappelle-moi.",
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return text, float(getattr(info, "language_probability", 0.0))

    def fall_back_to_cpu(self) -> None:
        """Recharge le modèle sur le processeur après un échec CUDA."""
        from faster_whisper import WhisperModel

        with self._lock:
            self._forced_device = "cpu"
            self._model = WhisperModel(
                self._cfg.model, device="cpu", compute_type="int8", cpu_threads=4, num_workers=1
            )
        log.warning("Whisper bascule sur le processeur : les bibliothèques CUDA sont incomplètes")

    def transcribe(self, audio: np.ndarray) -> tuple[str, float]:
        """Transcrit un tampon float32 16 kHz. Retourne ``(texte, prob_langue)``.

        Une installation CUDA incomplète (cuBLAS ou cuDNN manquants) ne se manifeste
        qu'à la première transcription : dans ce cas on rebascule sur le processeur
        plutôt que d'échouer, définitivement pour la durée de la session.
        """
        if self._model is None:
            self.load()
        if audio.size < SAMPLE_RATE // 4:  # < 250 ms : rien d'exploitable
            return "", 0.0
        try:
            return self._transcribe_once(audio)
        except Exception as exc:
            if self._forced_device == "cpu" or not _is_cuda_failure(exc):
                raise
            self.fall_back_to_cpu()
            return self._transcribe_once(audio)

    async def listen(
        self, cancel: threading.Event, hold: threading.Event | None = None
    ) -> Transcription:
        """Enregistre puis transcrit, sans bloquer la boucle asyncio."""
        t0 = time.perf_counter()
        audio = await asyncio.to_thread(self.record, cancel, hold)
        t1 = time.perf_counter()
        if cancel.is_set():
            return Transcription(text="", record_ms=(t1 - t0) * 1000, transcribe_ms=0.0)
        text, prob = await asyncio.to_thread(self.transcribe, audio)
        t2 = time.perf_counter()
        return Transcription(
            text=text,
            record_ms=(t1 - t0) * 1000,
            transcribe_ms=(t2 - t1) * 1000,
            language_prob=prob,
        )


# ----------------------------------------------------------------------
# Périphériques
# ----------------------------------------------------------------------


def list_input_devices() -> list[tuple[int, str]]:
    """``(index, nom)`` des périphériques d'entrée disponibles."""
    import sounddevice as sd

    result: list[tuple[int, str]] = []
    for idx, dev in enumerate(sd.query_devices()):
        if int(dev.get("max_input_channels", 0)) > 0:
            result.append((idx, str(dev.get("name", f"Périphérique {idx}"))))
    return result


def _find_input_device(name: str) -> int | None:
    name = name.lower()
    for idx, dev_name in list_input_devices():
        if name in dev_name.lower():
            return idx
    log.warning("Micro « %s » introuvable, périphérique par défaut utilisé", name)
    return None


def mic_level(duration_s: float = 1.0, device: int | str | None = None) -> float:
    """Niveau RMS du micro sur ``duration_s`` (pour le test de l'assistant de premier lancement)."""
    import sounddevice as sd

    if isinstance(device, str):
        device = _find_input_device(device)
    data = sd.rec(
        int(duration_s * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        device=device,
    )
    sd.wait()
    return float(np.sqrt(np.mean(np.square(data))))
