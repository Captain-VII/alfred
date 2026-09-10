"""Construit l'exécutable (PyInstaller onedir) puis l'installeur (Inno Setup).

Usage :
    python scripts/build.py                  # exe + installeur
    python scripts/build.py --skip-installer # exe seulement (CI)

Prérequis : `pip install -e ".[dev]"` ; Inno Setup 6 pour l'installeur
(chemin détecté automatiquement, ou variable d'environnement ISCC).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def ensure_assets() -> None:
    """Génère icônes et sons par défaut s'ils manquent (ils ne sont pas versionnés en binaire)."""
    from alfred.audio.sounds import SoundPlayer
    from alfred.ui.tray import save_default_icons

    icons = ROOT / "assets" / "icons"
    if not (icons / "alfred.ico").exists():
        save_default_icons(icons)
        print(f"Icônes générées dans {icons}")
    sounds = ROOT / "assets" / "sounds"
    if not any(sounds.glob("*.wav")):
        SoundPlayer(True).export(sounds)
        print(f"Sons générés dans {sounds}")


def build_exe() -> Path:
    for folder in ("build", "dist"):
        shutil.rmtree(ROOT / folder, ignore_errors=True)
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(ROOT / "alfred.spec")],
        check=True,
        cwd=ROOT,
    )
    exe = ROOT / "dist" / "Alfred" / "Alfred.exe"
    if not exe.exists():
        raise SystemExit("PyInstaller n'a pas produit dist/Alfred/Alfred.exe")
    print(f"Exécutable : {exe}")
    return exe


def find_iscc() -> Path | None:
    env = os.environ.get("ISCC")
    if env and Path(env).exists():
        return Path(env)
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Inno Setup 6"
        / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    ]
    found = shutil.which("ISCC")
    if found:
        candidates.insert(0, Path(found))
    return next((c for c in candidates if c.exists()), None)


def build_installer() -> Path:
    from alfred import __version__

    iscc = find_iscc()
    if iscc is None:
        raise SystemExit("Inno Setup 6 introuvable (définissez ISCC=chemin\\ISCC.exe)")
    subprocess.run(
        [str(iscc), f"/DAppVersion={__version__}", str(ROOT / "installer" / "alfred.iss")],
        check=True,
        cwd=ROOT,
    )
    out = ROOT / "installer" / "Output" / f"Alfred-Setup-{__version__}.exe"
    print(f"Installeur : {out}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-installer", action="store_true")
    args = parser.parse_args()
    ensure_assets()
    build_exe()
    if not args.skip_installer:
        build_installer()


if __name__ == "__main__":
    main()
