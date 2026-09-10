"""Tools système / média / fenêtres / presse-papier / minuteurs, avec système simulé."""

from __future__ import annotations

import asyncio

import pytest
from alfred.tools import _win
from alfred.tools.base import ToolError, get_tool


async def _run(tool_name: str, **kwargs: object) -> str:
    spec = get_tool(tool_name)
    assert spec is not None, tool_name
    return await spec.invoke(**kwargs)


async def test_volume_relative(system) -> None:
    assert await _run("set_volume", up="monte") == "Volume à 60 pour cent."
    assert system.volume == 60
    assert await _run("set_volume", down="baisse", delta="25") == "Volume à 35 pour cent."


async def test_volume_absolute_and_clamp(system) -> None:
    await _run("set_volume", level="30 %")
    assert system.volume == 30
    await _run("set_volume", level="+90")
    assert system.volume == 100


async def test_volume_requires_level(system) -> None:
    with pytest.raises(ToolError):
        await _run("set_volume")


async def test_mute_toggle(system) -> None:
    assert await _run("mute") == "Son coupé."
    assert system.muted is True
    assert await _run("mute") == "Son rétabli."
    assert await _run("mute", muted="true") == "Son coupé."


async def test_brightness(system) -> None:
    await _run("set_brightness", level="40")
    assert system.brightness == 40
    await _run("set_brightness", up="plus")
    assert system.brightness == 50


async def test_lock_sleep_shutdown(system) -> None:
    await _run("lock")
    await _run("sleep")
    await _run("shutdown")
    await _run("abort_shutdown")
    names = [n for n, _ in system.calls]
    assert names == ["lock", "sleep", "shutdown", "abort_shutdown"]


async def test_screenshot_path(system, monkeypatch) -> None:
    result = await _run("screenshot")
    assert "Images" in result
    (path,) = system.called("screenshot")[0]
    assert path.endswith(".png")


async def test_do_not_disturb(system) -> None:
    assert "activé" in await _run("do_not_disturb")
    assert system.dnd is True
    assert "rétablies" in await _run("do_not_disturb", enabled="false")


async def test_media_keys(system) -> None:
    await _run("media_play_pause")
    await _run("media_next")
    await _run("media_previous")
    await _run("media_stop")
    assert [a[0] for a in system.called("press_vk")] == [
        _win.VK_MEDIA_PLAY_PAUSE,
        _win.VK_MEDIA_NEXT_TRACK,
        _win.VK_MEDIA_PREV_TRACK,
        _win.VK_MEDIA_STOP,
    ]


async def test_window_minimize_active(system) -> None:
    await _run("minimize_window")
    assert system.called("show_window") == [(102, "minimize")]


async def test_window_maximize_named(system) -> None:
    await _run("maximize_window", target="spotify")
    assert system.called("show_window") == [(101, "maximize")]


async def test_snap_windows(system) -> None:
    result = await _run("snap_windows")
    assert result == "Fenêtres côte à côte."
    moves = system.called("move_window")
    assert moves[0] == (102, 0, 0, 960, 1040)
    assert moves[1][0] == 101 and moves[1][1] == 960


async def test_snap_windows_named(system) -> None:
    await _run("snap_windows", left="code", right="firefox")
    moves = system.called("move_window")
    assert moves[0][0] == 103 and moves[1][0] == 102


async def test_show_desktop(system) -> None:
    await _run("show_desktop")
    assert system.called("minimize_all") == [()]


async def test_read_clipboard(system) -> None:
    assert await _run("read_clipboard") == "Bonjour le monde."
    system.clipboard = ""
    with pytest.raises(ToolError):
        await _run("read_clipboard")


async def test_translate_clipboard_with_fake_llm(system, monkeypatch) -> None:
    from alfred.core import services

    class FakeLLM:
        async def complete(self, system_prompt: str, user: str, max_tokens: int = 200) -> str:
            assert "espagnol" in user
            return "Hola mundo."

    monkeypatch.setattr(services, "llm", FakeLLM())
    result = await _run("translate_clipboard", language="espagnol")
    assert "espagnol" in result
    assert system.clipboard == "Hola mundo."


async def test_clipboard_without_llm(system, monkeypatch) -> None:
    from alfred.core import services

    monkeypatch.setattr(services, "llm", None)
    with pytest.raises(ToolError):
        await _run("summarize_clipboard")


async def test_timer_lifecycle(system, monkeypatch) -> None:
    from alfred.tools import timer as timer_mod

    timer_mod._timers.clear()
    result = await _run("set_timer", duration="20 minutes", label="de sortir le gâteau")
    assert result == "Rappel dans 20 minutes pour sortir le gâteau."
    assert len(timer_mod.active_timers()) == 1
    listing = await _run("list_timers")
    assert "sortir le gâteau" in listing
    assert await _run("cancel_timer") == "Rappel pour sortir le gâteau annulé."
    assert timer_mod.active_timers() == []
    with pytest.raises(ToolError):
        await _run("cancel_timer")


async def test_timer_rings(system, monkeypatch) -> None:
    from alfred.core import services
    from alfred.tools import timer as timer_mod

    timer_mod._timers.clear()
    spoken: list[str] = []
    notified: list[tuple[str, str]] = []

    class FakeTTS:
        async def say(self, text: str, interrupt: bool = False) -> None:
            spoken.append(text)

    class FakeNotifier:
        def notify(self, title: str, message: str) -> None:
            notified.append((title, message))

    monkeypatch.setattr(services, "tts", FakeTTS())
    monkeypatch.setattr(services, "notifier", FakeNotifier())
    monkeypatch.setattr(timer_mod, "parse_duration", lambda text: 0.01)
    await _run("set_timer", duration="tout de suite", label="vérifier le four")
    await asyncio.sleep(0.2)
    assert spoken and "vérifier le four" in spoken[0]
    assert notified and "vérifier le four" in notified[0][1].lower()
    assert timer_mod.active_timers() == []


async def test_find_and_open_file(system, monkeypatch, tmp_path) -> None:
    from alfred.tools import files

    target = tmp_path / "budget 2024.xlsx"
    target.write_text("x")
    monkeypatch.setattr(files, "_everything_dll", lambda: None)
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(files, "_user_folders", lambda: [tmp_path])
    result = await _run("find_file", name="budget")
    assert "budget 2024.xlsx" in result
    await _run("open_file")
    assert system.called("open_path") == [(str(target),)]
    await _run("reveal_file", name="budget")
    assert system.called("reveal") == [(str(target),)]


async def test_web_search_offline(monkeypatch) -> None:
    from alfred.tools import web

    monkeypatch.setattr(web, "is_online", lambda timeout=1.5: False)
    with pytest.raises(ToolError, match="hors ligne"):
        await _run("web_search", query="météo")
