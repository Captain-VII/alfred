# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller (onedir) pour ALFRED. Utilisé par scripts/build.py."""

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

ROOT = Path(SPECPATH)

datas = [
    (str(ROOT / "config.default.yaml"), "."),
    (str(ROOT / "assets" / "icons"), "assets/icons"),
    (str(ROOT / "assets" / "sounds"), "assets/sounds"),
    (str(ROOT / "LICENSE"), "."),
]
binaries = []
hiddenimports = [
    "alfred.tools.apps",
    "alfred.tools.clipboard",
    "alfred.tools.files",
    "alfred.tools.media",
    "alfred.tools.system",
    "alfred.tools.timer",
    "alfred.tools.web",
    "alfred.tools.window",
    "comtypes.gen",
    "pycaw",
    "win32com.client",
    "win32timezone",
]

# Bibliothèques avec données/dll à embarquer intégralement.
for pkg in ("piper", "faster_whisper", "ctranslate2", "onnxruntime", "webrtcvad", "sounddevice", "windows_toasts", "trafilatura", "duckduckgo_search"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:  # noqa: BLE001 — package optionnel absent
        pass

# fastembed et tokenizers embarquent des extensions natives dont l'import fait
# planter le sous-processus isolé de collect_all (violation d'accès). On collecte
# donc leurs données et leurs DLL sans jamais les importer, et on déclare
# explicitement les modules utilisés par alfred/core/router.py.
for pkg in ("fastembed", "tokenizers", "py_rust_stemmers", "huggingface_hub"):
    try:
        datas += collect_data_files(pkg)
        binaries += collect_dynamic_libs(pkg)
    except Exception:  # noqa: BLE001
        pass
hiddenimports += [
    "fastembed",
    "fastembed.text",
    "fastembed.text.text_embedding",
    "fastembed.common",
    "fastembed.common.model_management",
    "huggingface_hub",
    "py_rust_stemmers",
    "tokenizers",
]

datas += collect_data_files("screen_brightness_control")
hiddenimports += collect_submodules("pystray")

a = Analysis(
    [str(ROOT / "alfred" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(ROOT / "installer" / "hooks")],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "IPython", "jupyter", "notebook", "torch", "torchvision", "torchaudio"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Alfred",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "assets" / "icons" / "alfred.ico"),
    version=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Alfred",
)
