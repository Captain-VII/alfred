"""Recherche web (DuckDuckGo, sans clé API) + lecture de la page + résumé par le LLM.

Hors ligne : le tool l'annonce clairement au lieu d'échouer silencieusement.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from urllib.parse import urlparse

import httpx

from alfred.core import services
from alfred.persona.prompt import SUMMARY_PROMPT
from alfred.tools.base import ToolError, tool

log = logging.getLogger(__name__)

MAX_PAGE_CHARS = 6000
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AlfredAssistant/0.1"


def is_online(timeout: float = 1.5) -> bool:
    """Test de connectivité rapide (DNS Cloudflare, port 53)."""
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=timeout):
            return True
    except OSError:
        return False


def _search(query: str, max_results: int = 3) -> list[dict[str, str]]:
    from duckduckgo_search import DDGS

    with DDGS() as ddgs:
        return list(
            ddgs.text(query, region="fr-fr", safesearch="moderate", max_results=max_results)
        )


async def _fetch_text(url: str) -> str:
    """Télécharge la page et en extrait le texte principal (trafilatura)."""
    async with httpx.AsyncClient(
        timeout=6.0, follow_redirects=True, headers={"User-Agent": _UA}
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        html = r.text
    try:
        import trafilatura

        text = await asyncio.to_thread(
            trafilatura.extract, html, include_comments=False, include_tables=False
        )
    except Exception:
        text = None
    if not text:
        # Repli minimal : suppression grossière des balises
        import re

        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
    return text[:MAX_PAGE_CHARS]


def _site_name(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host.removeprefix("www.")


@tool(
    name="web_search",
    description="Recherche une information sur le web, lit la page la plus pertinente et en donne un résumé parlé en deux ou trois phrases avec la source.",
    examples=[
        "cherche sur internet la météo à Lyon",
        "recherche qui a gagné le tour de France",
        "cherche sur le web le prix du bitcoin",
        "regarde sur internet les horaires de la poste",
        "fais une recherche sur la recette de la tarte tatin",
        "qu'est-ce que le protocole MCP",
    ],
    patterns=[
        r"(?:cherche|recherche|regarde|trouve|fais une recherche) (?:sur (?:internet|le web|le net|google|duckduckgo) )?(?P<query>.+)",
        r"(?:google|duckduckgo) (?P<query>.+)",
    ],
    params={"query": "La question ou les mots-clés à rechercher"},
    category="web",
)
async def web_search(query: str) -> str:
    query = query.strip()
    if not query:
        raise ToolError("que dois-je chercher ?")
    if not await asyncio.to_thread(is_online):
        raise ToolError("nous sommes hors ligne, la recherche est indisponible.")
    try:
        results = await asyncio.to_thread(_search, query, 3)
    except Exception as exc:
        log.warning("Recherche DuckDuckGo échouée : %s", exc)
        raise ToolError("le moteur de recherche ne répond pas.") from exc
    if not results:
        raise ToolError(f"aucun résultat pour « {query} ».")

    # On lit la première page lisible ; en cas d'échec, la suivante.
    page_text = ""
    source_url = ""
    for r in results:
        url = r.get("href") or r.get("url") or ""
        if not url:
            continue
        try:
            page_text = await _fetch_text(url)
            source_url = url
            if len(page_text) > 300:
                break
        except (httpx.HTTPError, ValueError):
            continue
    snippet = results[0].get("body", "")
    source = _site_name(source_url or results[0].get("href", ""))
    content = page_text if len(page_text) > 300 else snippet

    if services.llm is None:
        return f"{snippet[:300]} Source : {source}."
    try:
        summary = await services.llm.complete(
            SUMMARY_PROMPT,
            f"Question : {query}\nSource : {source}\nContenu :\n{content}",
            max_tokens=180,
        )
    except Exception as exc:
        log.warning("Résumé LLM impossible : %s", exc)
        return f"{snippet[:300]} Source : {source}."
    if "source" not in summary.lower():
        summary = f"{summary.rstrip()} Source : {source}."
    return summary
