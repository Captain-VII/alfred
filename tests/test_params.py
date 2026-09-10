"""Parsing des paramètres : niveaux (volume), durées (minuteurs), conversion de types."""

from __future__ import annotations

import pytest
from alfred.tools.base import ToolError, ToolParam, get_tool
from alfred.tools.system import parse_level
from alfred.tools.timer import humanize, parse_duration


@pytest.mark.parametrize(
    ("raw", "current", "expected"),
    [
        ("30", 50, 30),
        ("30 %", 50, 30),
        ("30 pour cent", 50, 30),
        ("+10", 50, 60),
        ("-20", 50, 30),
        ("+ 5", 98, 100),
        ("-70", 50, 0),
        ("plus", 50, 60),
        ("moins", 5, 0),
        ("cinquante", 10, 50),
        ("fond", 10, 100),
        ("maximum", 10, 100),
        ("150", 10, 100),
    ],
)
def test_parse_level(raw: str, current: int, expected: int) -> None:
    assert parse_level(raw, current) == expected


def test_parse_level_invalid() -> None:
    with pytest.raises(ToolError):
        parse_level("beaucoup", 50)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("20 minutes", 1200),
        ("5 min", 300),
        ("une heure", 3600),
        ("une heure et demie", 5400),
        ("1 h 30", 5400),
        ("1h30", 5400),
        ("90 secondes", 90),
        ("un quart d'heure", 900),
        ("une demi-heure", 1800),
        ("deux heures 15 minutes", 8100),
        ("trois minutes", 180),
        ("2,5 minutes", 150),
    ],
)
def test_parse_duration(raw: str, expected: float) -> None:
    assert parse_duration(raw) == pytest.approx(expected)


def test_parse_duration_invalid() -> None:
    with pytest.raises(ToolError):
        parse_duration("bientôt")


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (60, "1 minute"),
        (1200, "20 minutes"),
        (3600, "1 heure"),
        (5400, "1 heure et 30 minutes"),
        (45, "45 secondes"),
    ],
)
def test_humanize(seconds: int, expected: str) -> None:
    assert humanize(seconds) == expected


def test_tool_param_coercion() -> None:
    assert ToolParam("n", int, "", True, None).coerce("42") == 42
    assert ToolParam("n", int, "", True, None).coerce("42.0") == 42
    assert ToolParam("f", float, "", True, None).coerce("1,5") == 1.5
    assert ToolParam("b", bool, "", True, None).coerce("oui") is True
    assert ToolParam("b", bool, "", True, None).coerce("non") is False
    assert ToolParam("s", str | None, "", False, None).coerce(None) is None
    assert ToolParam("l", list[str], "", True, None).coerce("a, b ,c") == ["a", "b", "c"]
    with pytest.raises(ToolError):
        ToolParam("n", int, "", True, None).coerce("abc")


async def test_invoke_missing_required_param() -> None:
    spec = get_tool("open_app")
    assert spec is not None
    with pytest.raises(ToolError):
        await spec.invoke()


def test_json_schema_types() -> None:
    spec = get_tool("set_timer")
    assert spec is not None
    props = spec.json_schema()["function"]["parameters"]["properties"]
    assert props["duration"]["type"] == "string"
    assert "label" in props
    assert spec.json_schema()["function"]["parameters"]["required"] == ["duration"]
