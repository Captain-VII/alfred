"""Résolution floue des noms d'applications, sans toucher au système."""

from __future__ import annotations

import pytest
from alfred.tools.apps import INDEX, AppEntry, AppIndex, _normalize


@pytest.fixture
def index(monkeypatch: pytest.MonkeyPatch) -> AppIndex:
    idx = AppIndex()
    idx._entries = [
        AppEntry("Spotify", r"C:\Apps\Spotify.lnk", "spotify.exe"),
        AppEntry("Mozilla Firefox", r"C:\Apps\Firefox.lnk", "firefox.exe"),
        AppEntry("Visual Studio Code", r"C:\Apps\Code.lnk", "code.exe"),
        AppEntry("Discord", r"C:\Apps\Discord.lnk", "discord.exe"),
        AppEntry("Calculatrice", r"C:\Apps\calc.lnk", "calc.exe"),
        AppEntry("Windows Terminal", r"C:\Apps\wt.lnk", "wt.exe"),
    ]
    idx._built = True
    monkeypatch.setattr("alfred.tools.apps._app_paths_lookup", lambda exe: None)
    monkeypatch.setattr("shutil.which", lambda name: None)
    return idx


@pytest.mark.parametrize(
    ("spoken", "expected_exe"),
    [
        ("spotify", "spotify.exe"),
        ("spotifaille", "spotify.exe"),
        ("Spotifi", "spotify.exe"),
        ("le navigateur", "firefox.exe"),
        ("firefox", "firefox.exe"),
        ("mon éditeur de code", "code.exe"),
        ("vs code", "code.exe"),
        ("visual studio", "code.exe"),
        ("discorde", "discord.exe"),
        ("la calculatrice", "calc.exe"),
        ("le terminal", "wt.exe"),
    ],
)
def test_fuzzy_resolution(index: AppIndex, spoken: str, expected_exe: str) -> None:
    entry = index.resolve(spoken)
    assert entry is not None, f"« {spoken} » non résolu"
    assert entry.exe == expected_exe


def test_user_alias_wins(index: AppIndex) -> None:
    entry = index.resolve("musique", {"musique": "discord.exe"})
    assert entry is not None and entry.exe == "discord.exe"


def test_unknown_app(index: AppIndex) -> None:
    assert index.resolve("xylophone quantique") is None


def test_normalize_strips_articles() -> None:
    assert _normalize("L'application Spotify") == "spotify"
    assert _normalize("mon Éditeur de code") == "editeur de code"


# ----------------------------------------------------------------------
# Tools (via le registre), avec système simulé
# ----------------------------------------------------------------------


async def test_open_app_tool(system, index: AppIndex, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("alfred.tools.apps.INDEX", index)
    from alfred.tools.base import get_tool

    spec = get_tool("open_app")
    assert spec is not None
    result = await spec.invoke(app="spotifaille")
    assert "Spotify" in result
    assert system.called("start_process") == [(r"C:\Apps\Spotify.lnk",)]


async def test_close_app_uses_windows_first(
    system, index: AppIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alfred.tools.apps.INDEX", index)
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    from alfred.tools.base import get_tool

    spec = get_tool("close_app")
    assert spec is not None
    result = await spec.invoke(app="spotify")
    assert "fermé" in result
    assert system.called("close_window") == [(101,)]
    assert system.called("kill") == []


async def test_close_app_anaphora(system, index: AppIndex, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("alfred.tools.apps.INDEX", index)
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    from alfred.core import services
    from alfred.core.context import ConversationContext
    from alfred.tools.base import get_tool

    ctx = ConversationContext()
    ctx.add("ouvre firefox", "Firefox est ouvert.", "open_app", {"app": "firefox"})
    monkeypatch.setattr(services, "context", ctx)
    spec = get_tool("close_app")
    assert spec is not None
    result = await spec.invoke(app="")
    assert "Firefox" in result
    assert system.called("close_window") == [(102,)]


async def test_close_app_not_running(
    system, index: AppIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alfred.tools.apps.INDEX", index)
    system.windows = []
    system.processes = set()
    from alfred.tools.base import ToolError, get_tool

    spec = get_tool("close_app")
    assert spec is not None
    with pytest.raises(ToolError):
        await spec.invoke(app="discord")


async def test_focus_app(system, index: AppIndex, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("alfred.tools.apps.INDEX", index)
    from alfred.tools.base import get_tool

    spec = get_tool("focus_app")
    assert spec is not None
    result = await spec.invoke(app="vs code")
    assert "premier plan" in result
    assert system.called("focus") == [(103,)]


async def _no_sleep(_: float) -> None:
    return None


def test_global_index_object_exists() -> None:
    assert isinstance(INDEX, AppIndex)
