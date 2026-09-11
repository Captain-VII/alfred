"""Système de tools : décorateur ``@tool``, registre automatique, schéma JSON.

Un tool déclare en une seule fois :

- ``name`` / ``description`` → schéma JSON pour le tool calling du LLM (niveau 3) ;
- ``examples`` → phrases embarquées pour la similarité sémantique (niveau 2) ;
- ``patterns`` → expressions régulières pour le matcher exact (niveau 1),
  les groupes nommés deviennent des paramètres ;
- ``params`` → description humaine de chaque paramètre (pour le LLM) ;
- ``internal`` → paramètres remplis uniquement par les regex du niveau 1 et
  masqués dans le schéma JSON, pour ne pas égarer le LLM ;
- ``confirm`` → demande une confirmation vocale avant exécution.

Les types des paramètres sont déduits de la signature de la fonction et
les valeurs reçues (souvent des chaînes) sont converties automatiquement.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
import re
import types
import typing
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

ToolFunc = Callable[..., Awaitable[str]]


class ToolError(Exception):
    """Échec « propre » d'un tool : le message est lu à voix haute tel quel."""


@dataclass(slots=True)
class ToolParam:
    name: str
    annotation: Any
    description: str
    required: bool
    default: Any
    internal: bool = False  # rempli par les regex du niveau 1, masqué au LLM

    # ---- schéma JSON -------------------------------------------------
    def json_type(self) -> dict[str, Any]:
        base = _strip_optional(self.annotation)
        if base is bool:
            return {"type": "boolean"}
        if base is int:
            return {"type": "integer"}
        if base is float:
            return {"type": "number"}
        if base is list or typing.get_origin(base) is list:
            return {"type": "array", "items": {"type": "string"}}
        return {"type": "string"}

    # ---- conversion --------------------------------------------------
    def coerce(self, value: Any) -> Any:
        """Convertit une valeur reçue du LLM ou d'un regex vers le type annoté."""
        if value is None:
            return self.default if not self.required else None
        base = _strip_optional(self.annotation)
        try:
            if base is bool:
                if isinstance(value, bool):
                    return value
                return str(value).strip().lower() in {"1", "true", "oui", "vrai", "yes", "on"}
            if base is int:
                return int(float(str(value).replace(",", ".").strip()))
            if base is float:
                return float(str(value).replace(",", ".").strip())
            if base is str:
                return str(value).strip()
            if base is list or typing.get_origin(base) is list:
                if isinstance(value, list):
                    return value
                return [v.strip() for v in str(value).split(",") if v.strip()]
        except (TypeError, ValueError) as exc:
            raise ToolError(f"Paramètre « {self.name} » invalide : {value!r}") from exc
        return value


def _strip_optional(annotation: Any) -> Any:
    """``str | None`` → ``str``."""
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    func: ToolFunc
    examples: list[str] = field(default_factory=list)
    patterns: list[re.Pattern[str]] = field(default_factory=list)
    params: dict[str, ToolParam] = field(default_factory=dict)
    confirm: bool = False
    category: str = "général"

    # ---- niveau 1 ----------------------------------------------------
    def match(self, text: str) -> dict[str, Any] | None:
        """Retourne les paramètres extraits si un pattern correspond, sinon ``None``."""
        for pattern in self.patterns:
            m = pattern.fullmatch(text)
            if m:
                return {k: v for k, v in m.groupdict().items() if v is not None}
        return None

    # ---- niveau 3 ----------------------------------------------------
    def json_schema(self) -> dict[str, Any]:
        """Schéma au format attendu par l'API ``/api/chat`` d'Ollama (style OpenAI)."""
        properties: dict[str, Any] = {}
        required: list[str] = []
        for p in self.params.values():
            if p.internal:
                continue  # rempli par les regex du niveau 1, invisible pour le LLM
            properties[p.name] = {**p.json_type(), "description": p.description}
            if p.required:
                required.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": properties, "required": required},
            },
        }

    # ---- exécution ---------------------------------------------------
    async def invoke(self, **kwargs: Any) -> str:
        """Convertit les arguments puis appelle la coroutine du tool."""
        call: dict[str, Any] = {}
        for p in self.params.values():
            if p.name in kwargs:
                call[p.name] = p.coerce(kwargs[p.name])
            elif p.required:
                raise ToolError(f"Il me manque le paramètre « {p.name} ».")
        result = await self.func(**call)
        return result if isinstance(result, str) else str(result)


# ----------------------------------------------------------------------
# Registre
# ----------------------------------------------------------------------

REGISTRY: dict[str, ToolSpec] = {}


def tool(
    name: str,
    description: str,
    examples: list[str] | None = None,
    params: dict[str, str] | None = None,
    patterns: list[str] | None = None,
    internal: list[str] | None = None,
    confirm: bool = False,
    category: str = "général",
) -> Callable[[ToolFunc], ToolFunc]:
    """Décorateur d'enregistrement d'un tool.

    >>> @tool(name="lock", description="Verrouille la session",
    ...       examples=["verrouille", "verrouille l'écran"], patterns=[r"verrouille( l'écran| la session)?"])
    ... async def lock() -> str: ...
    """

    def decorator(func: ToolFunc) -> ToolFunc:
        if not inspect.iscoroutinefunction(func):
            raise TypeError(f"Le tool {name} doit être une coroutine (async def)")
        sig = inspect.signature(func)
        hints = typing.get_type_hints(func)
        tool_params: dict[str, ToolParam] = {}
        descriptions = params or {}
        for pname, param in sig.parameters.items():
            annotation = hints.get(pname, str)
            has_default = param.default is not inspect.Parameter.empty
            tool_params[pname] = ToolParam(
                name=pname,
                annotation=annotation,
                description=descriptions.get(pname, pname),
                required=not has_default,
                default=param.default if has_default else None,
                internal=pname in (internal or ()),
            )
        compiled = [re.compile(p, re.IGNORECASE) for p in (patterns or [])]
        spec = ToolSpec(
            name=name,
            description=description,
            func=func,
            examples=list(examples or []),
            patterns=compiled,
            params=tool_params,
            confirm=confirm,
            category=category,
        )
        if name in REGISTRY:
            log.warning("Tool %s redéfini", name)
        REGISTRY[name] = spec
        func.__tool_spec__ = spec  # type: ignore[attr-defined]
        return func

    return decorator


def get_tool(name: str) -> ToolSpec | None:
    return REGISTRY.get(name)


def all_tools() -> list[ToolSpec]:
    return list(REGISTRY.values())


def load_all_tools() -> int:
    """Importe tous les modules de ``alfred.tools`` pour déclencher les décorateurs."""
    import alfred.tools as package

    count = 0
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_") or info.name == "base":
            continue
        try:
            importlib.import_module(f"alfred.tools.{info.name}")
            count += 1
        except Exception:
            log.exception("Impossible de charger le module de tools %s", info.name)
    log.info("%d modules de tools chargés, %d tools", count, len(REGISTRY))
    return len(REGISTRY)
