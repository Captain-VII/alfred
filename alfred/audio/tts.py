"""Synthèse vocale Piper, streamée phrase par phrase.

- La voix (ONNX) est chargée une fois en mémoire dans ce processus : aucun
  spawn de ``piper.exe`` par phrase.
- ``say()`` découpe le texte en phrases ; un thread synthétise la phrase N+1
  pendant que la phrase N est jouée.
- ``stop()`` interrompt immédiatement synthèse et lecture (touche Échap).
- Téléchargement automatique de la voix depuis Hugging Face au premier usage.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import re
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from alfred.config import TTSConfig, voices_dir

log = logging.getLogger(__name__)

_HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…;:])\s+")
_SENTINEL = object()

# Voix connues : nom → chemin relatif sur Hugging Face
KNOWN_VOICES: dict[str, str] = {
    "fr_FR-gilles-low": "fr/fr_FR/gilles/low",
    "fr_FR-tom-medium": "fr/fr_FR/tom/medium",
    "fr_FR-siwis-medium": "fr/fr_FR/siwis/medium",
    "fr_FR-upmc-medium": "fr/fr_FR/upmc/medium",
}


def voice_paths(name: str) -> tuple[Path, Path]:
    folder = voices_dir()
    return folder / f"{name}.onnx", folder / f"{name}.onnx.json"


def voice_installed(name: str) -> bool:
    onnx, cfg = voice_paths(name)
    return onnx.exists() and cfg.exists() and onnx.stat().st_size > 1_000_000


def download_voice(name: str, progress: Any = None) -> tuple[Path, Path]:
    """Télécharge ``.onnx`` + ``.onnx.json`` (bloquant). ``progress(done_bytes, total_bytes)`` optionnel."""
    import httpx

    rel = KNOWN_VOICES.get(name)
    if rel is None:
        # fr_FR-xxx-quality → fr/fr_FR/xxx/quality
        try:
            lang, speaker, quality = name.split("-")
            rel = f"{lang.split('_')[0]}/{lang}/{speaker}/{quality}"
        except ValueError as exc:
            raise ValueError(f"Nom de voix inconnu : {name}") from exc
    onnx_path, cfg_path = voice_paths(name)
    for url, target in (
        (f"{_HF_BASE}/{rel}/{name}.onnx.json", cfg_path),
        (f"{_HF_BASE}/{rel}/{name}.onnx", onnx_path),
    ):
        tmp = target.with_suffix(target.suffix + ".part")
        log.info("Téléchargement de %s", url)
        with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            done = 0
            with tmp.open("wb") as fh:
                for chunk in r.iter_bytes(65536):
                    fh.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        tmp.replace(target)
    return onnx_path, cfg_path


def split_sentences(text: str) -> list[str]:
    """Découpe un texte en phrases prononçables, sans fragments vides."""
    text = text.replace("\n", " ").strip()
    if not text:
        return []
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


class TextToSpeech:
    """Moteur TTS persistant. Implémente ``services.Speaker``."""

    def __init__(self, cfg: TTSConfig) -> None:
        self._cfg = cfg
        self._voice: Any = None
        self._sample_rate = 22050
        self._lock = threading.Lock()
        self._stop_flag = threading.Event()
        self._playing = threading.Event()
        self._current_thread: threading.Thread | None = None

    # ---- cycle de vie ------------------------------------------------
    def apply(self, cfg: TTSConfig) -> None:
        reload_needed = cfg.voice != self._cfg.voice
        self._cfg = cfg
        if reload_needed:
            self._voice = None
            threading.Thread(target=self.load, daemon=True, name="tts-reload").start()

    def load(self) -> None:
        """Charge la voix Piper (télécharge si nécessaire). Bloquant, à appeler au boot."""
        with self._lock:
            if self._voice is not None:
                return
            name = self._cfg.voice
            if not voice_installed(name):
                download_voice(name)
            onnx_path, cfg_path = voice_paths(name)
            from piper.voice import PiperVoice

            started = time.perf_counter()
            self._voice = PiperVoice.load(str(onnx_path), config_path=str(cfg_path))
            self._sample_rate = int(self._voice.config.sample_rate)
            log.info("Voix %s chargée en %.0f ms", name, (time.perf_counter() - started) * 1000)

    async def load_async(self) -> None:
        await asyncio.to_thread(self.load)

    @property
    def ready(self) -> bool:
        return self._voice is not None

    @property
    def speaking(self) -> bool:
        return self._playing.is_set()

    # ---- synthèse ----------------------------------------------------
    def _synthesize(self, sentence: str) -> Iterator[np.ndarray]:
        """Génère des blocs int16 pour une phrase (compatible piper-tts 1.2 et 1.3+)."""
        voice = self._voice
        c = self._cfg
        if hasattr(voice, "synthesize_stream_raw"):  # piper-tts ≤ 1.2
            for raw in voice.synthesize_stream_raw(
                sentence,
                length_scale=c.length_scale,
                noise_scale=c.noise_scale,
                noise_w=c.noise_w,
                sentence_silence=c.sentence_silence,
            ):
                yield np.frombuffer(raw, dtype=np.int16)
        else:  # piper-tts ≥ 1.3
            from piper.config import SynthesisConfig

            syn = SynthesisConfig(
                length_scale=c.length_scale,
                noise_scale=c.noise_scale,
                noise_w_scale=c.noise_w,
                volume=1.0,
            )
            for chunk in voice.synthesize(sentence, syn_config=syn):
                yield np.frombuffer(chunk.audio_int16_bytes, dtype=np.int16)
            pause = int(self._sample_rate * c.sentence_silence)
            if pause > 0:
                yield np.zeros(pause, dtype=np.int16)

    def synthesize_to_array(self, text: str) -> np.ndarray:
        """Synthèse complète en mémoire (tests / assistant de premier lancement)."""
        if self._voice is None:
            self.load()
        parts = [blk for s in split_sentences(text) for blk in self._synthesize(s)]
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.int16)

    # ---- lecture -----------------------------------------------------
    def _output_device(self) -> int | None:
        dev = self._cfg.output_device
        if isinstance(dev, int):
            return dev
        if isinstance(dev, str) and dev.strip():
            import sounddevice as sd

            for idx, d in enumerate(sd.query_devices()):
                if (
                    dev.lower() in str(d.get("name", "")).lower()
                    and int(d.get("max_output_channels", 0)) > 0
                ):
                    return idx
        return None

    def _speak_blocking(self, text: str) -> None:
        """Pipeline synthèse → file → lecture, dans le thread courant."""
        import sounddevice as sd

        sentences = split_sentences(text)
        if not sentences or self._voice is None:
            return
        q: queue.Queue[Any] = queue.Queue(maxsize=8)
        stop = self._stop_flag

        def producer() -> None:
            try:
                for sentence in sentences:
                    if stop.is_set():
                        break
                    for block in self._synthesize(sentence):
                        if stop.is_set():
                            break
                        q.put(block)
            except Exception:
                log.exception("Erreur de synthèse Piper")
            finally:
                q.put(_SENTINEL)

        threading.Thread(target=producer, daemon=True, name="tts-producer").start()
        gain = float(self._cfg.volume)
        self._playing.set()
        try:
            with sd.OutputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="int16",
                device=self._output_device(),
            ) as stream:
                while True:
                    block = q.get()
                    if block is _SENTINEL or stop.is_set():
                        break
                    if gain < 0.999:
                        block = (block.astype(np.float32) * gain).astype(np.int16)
                    stream.write(block.reshape(-1, 1))
                if stop.is_set():
                    stream.abort()
        except Exception:
            log.exception("Erreur de lecture audio")
        finally:
            self._playing.clear()
            # Vide la file pour libérer le producteur s'il bloque sur put()
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break

    async def say(self, text: str, interrupt: bool = False) -> None:
        """Prononce ``text``. Attend la fin de la lecture (ou l'interruption)."""
        if not self._cfg.enabled or not text.strip():
            return
        if self._voice is None:
            try:
                await self.load_async()
            except Exception:
                log.exception("Voix indisponible")
                return
        if interrupt:
            self.stop()
        # Sérialise les énoncés : un seul thread de lecture à la fois.
        prev = self._current_thread
        if prev is not None and prev.is_alive():
            await asyncio.to_thread(prev.join)
        self._stop_flag.clear()
        thread = threading.Thread(
            target=self._speak_blocking, args=(text,), daemon=True, name="tts-play"
        )
        self._current_thread = thread
        thread.start()
        await asyncio.to_thread(thread.join)

    def stop(self) -> None:
        """Interrompt immédiatement la parole en cours."""
        self._stop_flag.set()
