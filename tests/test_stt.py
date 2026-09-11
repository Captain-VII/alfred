"""Reconnaissance vocale : repli sur le processeur quand CUDA est incomplet.

Aucun modèle réel n'est chargé : ``WhisperModel`` et la transcription sont simulés.
"""

from __future__ import annotations

import numpy as np
import pytest
from alfred.audio.stt import SAMPLE_RATE, SpeechToText, _is_cuda_failure
from alfred.config import STTConfig


def _audio(seconds: float = 1.0) -> np.ndarray:
    return np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)


@pytest.mark.parametrize(
    "message",
    [
        "Library cublas64_12.dll is not found or cannot be loaded",
        "Could not load library cudnn_ops_infer64_8.dll",
        "CUDA driver version is insufficient",
        "no GPU detected",
    ],
)
def test_is_cuda_failure_detects_stack_problems(message: str) -> None:
    assert _is_cuda_failure(RuntimeError(message))


def test_is_cuda_failure_ignores_unrelated_errors() -> None:
    assert not _is_cuda_failure(ValueError("fichier audio corrompu"))
    assert not _is_cuda_failure(MemoryError("mémoire insuffisante"))


class _FakeInfo:
    language_probability = 0.98


class _FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModel:
    """Modèle simulé : échoue tant qu'il tourne sur CUDA."""

    def __init__(self, device: str, fail_on_cuda: bool = True) -> None:
        self.device = device
        self._fail_on_cuda = fail_on_cuda
        self.calls = 0

    def transcribe(self, audio, **kwargs):
        self.calls += 1
        if self.device == "cuda" and self._fail_on_cuda:
            raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
        return [_FakeSegment("monte le son")], _FakeInfo()


def test_transcribe_falls_back_to_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    stt = SpeechToText(STTConfig(device="cuda"))
    created: list[str] = []

    def fake_whisper_model(model: str, device: str = "cpu", **kwargs):
        created.append(device)
        return _FakeModel(device)

    monkeypatch.setattr("faster_whisper.WhisperModel", fake_whisper_model)
    stt.load()
    assert created == ["cuda"]

    text, prob = stt.transcribe(_audio())
    assert text == "monte le son"
    assert prob == pytest.approx(0.98)
    assert created == ["cuda", "cpu"], "le modèle doit être rechargé sur le processeur"


def test_cpu_fallback_is_sticky(monkeypatch: pytest.MonkeyPatch) -> None:
    """Une fois basculé, on ne retente pas CUDA à chaque phrase."""
    stt = SpeechToText(STTConfig(device="cuda"))
    created: list[str] = []

    def fake_whisper_model(model: str, device: str = "cpu", **kwargs):
        created.append(device)
        return _FakeModel(device)

    monkeypatch.setattr("faster_whisper.WhisperModel", fake_whisper_model)
    stt.load()
    stt.transcribe(_audio())
    stt.transcribe(_audio())
    stt.transcribe(_audio())
    assert created == ["cuda", "cpu"]


def test_non_cuda_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    stt = SpeechToText(STTConfig(device="cpu"))

    class Boom:
        def transcribe(self, audio, **kwargs):
            raise ValueError("audio illisible")

    monkeypatch.setattr("faster_whisper.WhisperModel", lambda *a, **k: Boom())
    stt.load()
    with pytest.raises(ValueError, match="audio illisible"):
        stt.transcribe(_audio())


def test_short_audio_is_not_transcribed(monkeypatch: pytest.MonkeyPatch) -> None:
    stt = SpeechToText(STTConfig())
    model = _FakeModel("cpu")
    monkeypatch.setattr("faster_whisper.WhisperModel", lambda *a, **k: model)
    stt.load()
    assert stt.transcribe(_audio(0.1)) == ("", 0.0)
    assert model.calls == 0


def test_cpu_compute_type_is_downgraded() -> None:
    """float16 n'existe pas sur processeur : on retombe sur int8."""
    stt = SpeechToText(STTConfig(device="cpu", compute_type="float16"))
    assert stt._resolve_device() == ("cpu", "int8")
