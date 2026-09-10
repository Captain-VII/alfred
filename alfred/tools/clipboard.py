"""Presse-papier : lire à voix haute, traduire, résumer, réécrire.

Les transformations (traduction, résumé, réécriture) passent par le LLM et
remettent le résultat dans le presse-papier ; Alfred n'énonce qu'un court accusé.
"""

from __future__ import annotations

from alfred.core import services
from alfred.persona.prompt import REWRITE_PROMPT, SUMMARY_PROMPT, TRANSLATE_PROMPT
from alfred.tools import _win
from alfred.tools.base import ToolError, tool

MAX_SPOKEN_CHARS = 600
MAX_LLM_CHARS = 8000

_LANGUAGES = {
    "anglais": "anglais",
    "english": "anglais",
    "français": "français",
    "francais": "français",
    "espagnol": "espagnol",
    "allemand": "allemand",
    "italien": "italien",
    "portugais": "portugais",
    "néerlandais": "néerlandais",
    "japonais": "japonais",
    "chinois": "chinois",
    "russe": "russe",
    "arabe": "arabe",
}


async def _read_or_fail() -> str:
    text = (await _win.run_blocking(_win.clipboard_read)).strip()
    if not text:
        raise ToolError("le presse-papier est vide.")
    return text


async def _llm_or_fail() -> services.Summarizer:
    if services.llm is None:
        raise ToolError("le modèle de langage est indisponible.")
    return services.llm


@tool(
    name="read_clipboard",
    description="Lit à voix haute le contenu texte du presse-papier.",
    examples=[
        "lis le presse-papier",
        "lis ce que j'ai copié",
        "qu'est-ce qu'il y a dans le presse-papier",
        "lis-moi le presse-papier",
    ],
    patterns=[
        r"lis(?:-moi)? (?:le |mon )?presse[- ]papiers?",
        r"lis(?:-moi)? ce que j'ai copié",
        r"(?:qu'est-ce qu'il y a|qu'y a-t-il|que contient) (?:dans )?(?:le |mon )?presse[- ]papiers?",
    ],
    category="presse-papier",
)
async def read_clipboard() -> str:
    text = await _read_or_fail()
    if len(text) > MAX_SPOKEN_CHARS:
        return text[:MAX_SPOKEN_CHARS].rsplit(" ", 1)[0] + "… Le reste est trop long pour être lu."
    return text


@tool(
    name="translate_clipboard",
    description="Traduit le texte du presse-papier vers une langue (anglais par défaut) et remplace le presse-papier par la traduction.",
    examples=[
        "traduis le presse-papier",
        "traduis ce que j'ai copié en anglais",
        "traduis le presse-papier en espagnol",
        "traduction en allemand du presse-papier",
    ],
    patterns=[
        r"traduis(?:-moi)? (?:le |mon )?(?:presse[- ]papiers?|texte copié|ce que j'ai copié)(?: en (?P<language>\w+))?",
        r"traduis(?:-moi)? (?:ça|cela)(?: en (?P<language>\w+))?",
    ],
    params={"language": "Langue cible (anglais, espagnol, allemand…) ; défaut : anglais"},
    category="presse-papier",
)
async def translate_clipboard(language: str = "anglais") -> str:
    text = await _read_or_fail()
    llm = await _llm_or_fail()
    lang = _LANGUAGES.get(language.strip().lower(), language.strip() or "anglais")
    result = await llm.complete(
        TRANSLATE_PROMPT,
        f"Langue cible : {lang}\n\nTexte :\n{text[:MAX_LLM_CHARS]}",
        max_tokens=600,
    )
    if not result:
        raise ToolError("la traduction a échoué.")
    await _win.run_blocking(_win.clipboard_write, result)
    return f"Traduction en {lang} copiée dans le presse-papier."


@tool(
    name="summarize_clipboard",
    description="Résume le texte du presse-papier en deux ou trois phrases, à voix haute, et copie le résumé.",
    examples=[
        "résume le presse-papier",
        "résume ce que j'ai copié",
        "fais-moi un résumé du texte copié",
        "résume le texte que j'ai copié",
    ],
    patterns=[
        r"résume(?:-moi)? (?:le |mon )?(?:presse[- ]papiers?|texte copié|ce que j'ai copié|ça|cela)",
        r"fais(?:-moi)? un résumé (?:du |de ce )?(?:presse[- ]papiers?|texte copié|que j'ai copié)",
    ],
    category="presse-papier",
)
async def summarize_clipboard() -> str:
    text = await _read_or_fail()
    llm = await _llm_or_fail()
    prompt = SUMMARY_PROMPT.replace(
        "Termine par la source sous la forme « Source : nom du site. »", "Ne cite aucune source."
    )
    result = await llm.complete(prompt, text[:MAX_LLM_CHARS], max_tokens=200)
    if not result:
        raise ToolError("le résumé a échoué.")
    await _win.run_blocking(_win.clipboard_write, result)
    return result


@tool(
    name="rewrite_clipboard",
    description="Réécrit / corrige le texte du presse-papier (orthographe, clarté, fluidité) et remplace le presse-papier.",
    examples=[
        "réécris le presse-papier",
        "corrige ce que j'ai copié",
        "améliore le texte copié",
        "reformule le presse-papier",
        "corrige les fautes du presse-papier",
    ],
    patterns=[
        r"(?:réécris|corrige|améliore|reformule|peaufine)(?:-moi)? (?:le |mon |les fautes du )?(?:presse[- ]papiers?|texte copié|ce que j'ai copié|ça|cela)",
    ],
    category="presse-papier",
)
async def rewrite_clipboard() -> str:
    text = await _read_or_fail()
    llm = await _llm_or_fail()
    result = await llm.complete(REWRITE_PROMPT, text[:MAX_LLM_CHARS], max_tokens=800)
    if not result:
        raise ToolError("la réécriture a échoué.")
    await _win.run_blocking(_win.clipboard_write, result)
    return "Texte réécrit et copié dans le presse-papier."
