"""Benchmark de latence : mesure chaque étape et affiche un tableau.

Usage :
    python scripts/benchmark.py            # routeur + tools mockés + (si dispo) embeddings, Piper, Whisper, Ollama
    python scripts/benchmark.py --quick    # routeur et tools uniquement, aucun modèle chargé

Les appels système sont neutralisés : rien n'est ouvert, aucun volume modifié.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# La console Windows est en cp1252 dès que la sortie est redirigée : les flèches
# et les accents doivent malgré tout s'afficher.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from alfred.config import AlfredConfig
from alfred.core.context import ConversationContext
from alfred.core.executor import Executor
from alfred.core.router import Router, SemanticIndex
from alfred.tools import _win
from alfred.tools.base import all_tools, load_all_tools

COMMANDS_L1 = [
    "monte le son",
    "ouvre spotify",
    "pause",
    "verrouille l'écran",
    "rappelle-moi dans 10 minutes",
]
COMMANDS_L2 = [
    "bloque la session",
    "je veux plus de volume",
    "mets la chanson d'après",
    "affiche mon bureau",
]
COMMANDS_L3 = [
    "quelle est la capitale de l'australie",
    "baisse un peu la lumière de l'écran si tu veux bien",
]


def _neutralize_system() -> None:
    """Remplace tous les appels système par des no-op instantanés."""
    for name in dir(_win):
        attr = getattr(_win, name)
        if callable(attr) and not name.startswith("_") and name not in {"run_blocking"}:
            if name in ("get_volume", "get_brightness"):
                setattr(_win, name, lambda: 50)
            elif name in ("is_muted", "get_do_not_disturb"):
                setattr(_win, name, lambda: False)
            elif name == "list_windows":
                setattr(
                    _win,
                    name,
                    lambda: [(1, "Spotify", "Spotify.exe"), (2, "Firefox", "firefox.exe")],
                )
            elif name == "foreground_window":
                setattr(_win, name, lambda: 1)
            elif name == "work_area":
                setattr(_win, name, lambda: (0, 0, 1920, 1040))
            elif name == "running_process_names":
                setattr(_win, name, lambda: {"spotify.exe"})
            elif name == "clipboard_read":
                setattr(_win, name, lambda: "texte")
            elif name == "kill_process_by_name":
                setattr(_win, name, lambda n: 1)
            elif name == "screenshot":
                setattr(_win, name, lambda p: p)
            elif name.startswith(("IS_", "VK_", "KEYEVENTF")):
                continue
            else:
                setattr(_win, name, lambda *a, **k: None)


def _timeit(fn, repeat: int = 20) -> tuple[float, float]:
    samples = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples), max(samples)


async def _atimeit(coro_factory, repeat: int = 10) -> tuple[float, float]:
    samples = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        await coro_factory()
        samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples), max(samples)


def _print_table(rows: list[tuple[str, str, float, float]]) -> None:
    w = max(len(r[0]) for r in rows) + 2
    print(f"\n{'Étape':<{w}} {'Détail':<40} {'médiane':>10} {'max':>10}")
    print("-" * (w + 63))
    for name, detail, med, mx in rows:
        print(f"{name:<{w}} {detail:<40} {med:>8.1f} ms {mx:>8.1f} ms")
    print()


async def main(quick: bool) -> None:
    _neutralize_system()
    load_all_tools()
    tools = all_tools()
    rows: list[tuple[str, str, float, float]] = []

    # ---- Niveau 1 --------------------------------------------------------
    router_l1 = Router(AlfredConfig().router, tools, semantic=None)
    for cmd in COMMANDS_L1:
        med, mx = _timeit(lambda c=cmd: router_l1.route(c), repeat=200)
        rows.append(("routage niveau 1", cmd, med, mx))

    # ---- Exécution tool (mocké) -------------------------------------------
    spoken: list[str] = []

    async def speak(t: str) -> None:
        spoken.append(t)

    async def confirm(_: str) -> bool:
        return True

    executor = Executor(AlfredConfig(), router_l1, None, ConversationContext(), speak, confirm)
    for cmd in COMMANDS_L1:
        med, mx = await _atimeit(lambda c=cmd: executor.handle(c), repeat=30)
        rows.append(("routage + exécution", cmd, med, mx))

    if quick:
        _print_table(rows)
        return

    # ---- Niveau 2 : embeddings ------------------------------------------
    try:
        index = SemanticIndex(tools)
        t0 = time.perf_counter()
        index.build()
        origin = "cache disque" if index.loaded_from_cache else "calcul complet"
        rows.append(
            (
                "index sémantique (boot)",
                f"{sum(len(t.examples) for t in tools)} exemples, {origin}",
                (time.perf_counter() - t0) * 1000,
                0,
            )
        )
        router_l2 = Router(AlfredConfig().router, tools, index)
        for cmd in COMMANDS_L2:
            d = router_l2.route(cmd)
            med, mx = _timeit(lambda c=cmd: router_l2.route(c), repeat=20)
            label = f"{cmd} → {d.tool.name if d.tool else 'LLM'} ({d.score:.2f})"
            rows.append((f"routage niveau {d.level}", label[:40], med, mx))
    except Exception as exc:
        print(f"[niveau 2 ignoré : {exc}]")

    # ---- TTS Piper ---------------------------------------------------------
    try:
        from alfred.audio.tts import TextToSpeech, voice_installed

        cfg = AlfredConfig().tts
        if voice_installed(cfg.voice):
            tts = TextToSpeech(cfg)
            t0 = time.perf_counter()
            tts.load()
            rows.append(("Piper (chargement)", cfg.voice, (time.perf_counter() - t0) * 1000, 0))
            med, mx = _timeit(lambda: tts.synthesize_to_array("C'est fait, monsieur."), repeat=5)
            rows.append(("Piper (synthèse)", "« C'est fait, monsieur. »", med, mx))
        else:
            print(f"[Piper ignoré : voix {cfg.voice} non téléchargée]")
    except Exception as exc:
        print(f"[Piper ignoré : {exc}]")

    # ---- STT Whisper ---------------------------------------------------------
    try:
        from alfred.audio.stt import SAMPLE_RATE, SpeechToText

        stt = SpeechToText(AlfredConfig().stt)
        t0 = time.perf_counter()
        stt.load()
        rows.append(
            ("Whisper (chargement)", AlfredConfig().stt.model, (time.perf_counter() - t0) * 1000, 0)
        )
        audio = (np.random.default_rng(0).standard_normal(SAMPLE_RATE * 2) * 0.01).astype(
            np.float32
        )
        stt.transcribe(audio)  # warm-up
        med, mx = _timeit(lambda: stt.transcribe(audio), repeat=3)
        rows.append(("Whisper (2 s de bruit)", "transcription", med, mx))
    except Exception as exc:
        print(f"[Whisper ignoré : {exc}]")

    # ---- LLM Ollama ------------------------------------------------------------
    try:
        from alfred.core.llm import OllamaClient

        llm = OllamaClient(AlfredConfig().llm)
        if await llm.ping():
            await llm.warm_up()
            executor_l3 = Executor(
                AlfredConfig(), router_l1, llm, ConversationContext(), speak, confirm
            )
            for cmd in COMMANDS_L3:
                t0 = time.perf_counter()
                res = await executor_l3.handle(cmd)
                rows.append(
                    (
                        "niveau 3 (LLM)",
                        f"{cmd[:25]} → {res.tool or 'texte'}",
                        (time.perf_counter() - t0) * 1000,
                        0,
                    )
                )
        else:
            print("[Ollama ignoré : injoignable]")
        await llm.close()
    except Exception as exc:
        print(f"[Ollama ignoré : {exc}]")

    _print_table(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="routeur et tools uniquement")
    asyncio.run(main(parser.parse_args().quick))
