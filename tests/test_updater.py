"""Updater : parsing des releases GitHub, comparaison semver, canal bêta."""

from __future__ import annotations

import httpx
import pytest
from alfred.config import UpdatesConfig
from alfred.updater import Updater, _parse_release


def _release(tag: str, prerelease: bool = False, with_asset: bool = True) -> dict:
    assets = (
        [
            {
                "name": f"Alfred-Setup-{tag.lstrip('v')}.exe",
                "browser_download_url": f"https://x/{tag}.exe",
                "size": 123,
            }
        ]
        if with_asset
        else []
    )
    return {
        "tag_name": tag,
        "body": "## Nouveautés\n- truc",
        "assets": assets,
        "html_url": f"https://gh/{tag}",
        "prerelease": prerelease,
        "draft": False,
    }


def test_parse_release() -> None:
    rel = _parse_release(_release("v1.2.3"))
    assert rel.version == "1.2.3"
    assert rel.installer_url == "https://x/v1.2.3.exe"
    assert rel.is_newer_than("1.2.2")
    assert not rel.is_newer_than("1.2.3")
    assert not rel.is_newer_than("2.0.0")


def test_parse_release_without_installer() -> None:
    rel = _parse_release(_release("v1.0.0", with_asset=False))
    assert rel.installer_url is None


@pytest.fixture
def mock_github(monkeypatch: pytest.MonkeyPatch):
    releases = [_release("v0.2.0-beta.1", prerelease=True), _release("v0.1.5"), _release("v0.1.0")]

    def handler(request: httpx.Request) -> httpx.Response:
        assert "releases" in request.url.path
        return httpx.Response(200, json=releases)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    class PatchedClient(real_client):  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", PatchedClient)
    return releases


async def test_check_stable_channel(mock_github) -> None:
    updater = Updater(UpdatesConfig(channel="stable"), current_version="0.1.0")
    rel = await updater.check()
    assert rel is not None and rel.version == "0.1.5"


async def test_check_beta_channel(mock_github) -> None:
    updater = Updater(UpdatesConfig(channel="beta"), current_version="0.1.5")
    rel = await updater.check()
    assert rel is not None and rel.version == "0.2.0-beta.1"


async def test_check_up_to_date(mock_github) -> None:
    updater = Updater(UpdatesConfig(channel="stable"), current_version="0.1.5")
    assert await updater.check() is None


async def test_check_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    class PatchedClient(real_client):  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", PatchedClient)
    updater = Updater(UpdatesConfig(), current_version="0.1.0")
    assert await updater.check() is None


def test_pending_install_roundtrip(monkeypatch, tmp_path) -> None:
    from alfred import updater as upd

    monkeypatch.setattr(upd, "cache_dir", lambda: tmp_path)
    assert Updater.pending_install() is None
    installer = tmp_path / "Alfred-Setup-9.9.9.exe"
    installer.write_bytes(b"MZ")
    rel = _parse_release(_release("v9.9.9"))
    Updater(UpdatesConfig()).schedule_install(installer, rel)
    pending = Updater.pending_install()
    assert pending == (installer, "9.9.9")
    installer.unlink()
    assert Updater.pending_install() is None  # marqueur nettoyé
