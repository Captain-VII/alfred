"""Mises à jour automatiques via GitHub Releases.

- Vérification asynchrone au démarrage (non bloquante), comparaison semver.
- Téléchargement de l'installeur ``.exe`` dans le cache utilisateur.
- ``auto_install`` : l'installeur est lancé en silencieux (``/VERYSILENT``)
  au prochain redémarrage d'Alfred (un marqueur est déposé dans le cache).
- Le changelog de la release est affiché en notification.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from packaging.version import InvalidVersion, Version

from alfred import __version__
from alfred.config import UpdatesConfig, cache_dir

log = logging.getLogger(__name__)

_PENDING_FILE = "pending_update.json"


@dataclass(slots=True)
class ReleaseInfo:
    version: str
    tag: str
    notes: str
    installer_url: str | None
    installer_size: int
    url: str
    prerelease: bool

    def is_newer_than(self, current: str) -> bool:
        try:
            return Version(self.version) > Version(current)
        except InvalidVersion:
            return False


def _parse_release(data: dict[str, Any]) -> ReleaseInfo:
    tag = str(data.get("tag_name", ""))
    version = tag.lstrip("vV")
    installer_url: str | None = None
    size = 0
    for asset in data.get("assets", []):
        name = str(asset.get("name", "")).lower()
        if name.endswith(".exe") and "setup" in name:
            installer_url = asset.get("browser_download_url")
            size = int(asset.get("size", 0))
            break
    return ReleaseInfo(
        version=version,
        tag=tag,
        notes=str(data.get("body") or "").strip(),
        installer_url=installer_url,
        installer_size=size,
        url=str(data.get("html_url", "")),
        prerelease=bool(data.get("prerelease", False)),
    )


class Updater:
    def __init__(self, cfg: UpdatesConfig, current_version: str = __version__) -> None:
        self._cfg = cfg
        self._current = current_version
        self.latest: ReleaseInfo | None = None

    def apply(self, cfg: UpdatesConfig) -> None:
        self._cfg = cfg

    @property
    def current_version(self) -> str:
        return self._current

    # ---- vérification ------------------------------------------------
    async def check(self) -> ReleaseInfo | None:
        """Retourne la release la plus récente si elle est plus récente que la version courante."""
        url = f"https://api.github.com/repos/{self._cfg.repo}/releases"
        headers = {"Accept": "application/vnd.github+json", "User-Agent": f"alfred/{self._current}"}
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                r = await client.get(url, headers=headers, params={"per_page": 10})
                r.raise_for_status()
                releases = [_parse_release(d) for d in r.json() if not d.get("draft")]
        except (httpx.HTTPError, ValueError) as exc:
            log.info("Vérification des mises à jour impossible : %s", exc)
            return None
        if self._cfg.channel == "stable":
            releases = [rel for rel in releases if not rel.prerelease]
        candidates = [rel for rel in releases if rel.is_newer_than(self._current)]
        if not candidates:
            log.info("Alfred %s est à jour", self._current)
            return None
        candidates.sort(key=lambda rel: Version(rel.version), reverse=True)
        self.latest = candidates[0]
        log.info("Mise à jour disponible : %s", self.latest.version)
        return self.latest

    # ---- téléchargement ----------------------------------------------
    async def download(self, release: ReleaseInfo, progress: Any = None) -> Path | None:
        if not release.installer_url:
            return None
        target = cache_dir() / f"Alfred-Setup-{release.version}.exe"
        if target.exists() and (
            release.installer_size == 0 or target.stat().st_size == release.installer_size
        ):
            return target
        tmp = target.with_suffix(".part")
        try:
            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
                async with client.stream("GET", release.installer_url) as r:
                    r.raise_for_status()
                    done = 0
                    with tmp.open("wb") as fh:
                        async for chunk in r.aiter_bytes(65536):
                            fh.write(chunk)
                            done += len(chunk)
                            if progress:
                                progress(done, release.installer_size)
            tmp.replace(target)
        except (httpx.HTTPError, OSError) as exc:
            log.warning("Téléchargement de la mise à jour échoué : %s", exc)
            tmp.unlink(missing_ok=True)
            return None
        return target

    # ---- installation ------------------------------------------------
    def schedule_install(self, installer: Path, release: ReleaseInfo) -> None:
        """Dépose un marqueur : l'installation aura lieu au prochain démarrage d'Alfred."""
        pending = cache_dir() / _PENDING_FILE
        pending.write_text(
            json.dumps({"installer": str(installer), "version": release.version}), encoding="utf-8"
        )

    @staticmethod
    def pending_install() -> tuple[Path, str] | None:
        pending = cache_dir() / _PENDING_FILE
        if not pending.exists():
            return None
        try:
            data = json.loads(pending.read_text(encoding="utf-8"))
            installer = Path(data["installer"])
            if installer.exists():
                return installer, str(data.get("version", "?"))
        except (ValueError, KeyError, OSError):
            pass
        pending.unlink(missing_ok=True)
        return None

    @staticmethod
    def run_installer(installer: Path, silent: bool = True) -> None:
        """Lance l'installeur Inno Setup ; l'appelant doit quitter Alfred ensuite."""
        (cache_dir() / _PENDING_FILE).unlink(missing_ok=True)
        args = [str(installer)]
        if silent:
            args += [
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/CLOSEAPPLICATIONS",
                "/RESTARTAPPLICATIONS",
            ]
        if sys.platform == "win32":
            subprocess.Popen(
                args,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )

    @staticmethod
    def open_release_page(release: ReleaseInfo) -> None:
        import webbrowser

        webbrowser.open(release.url)
