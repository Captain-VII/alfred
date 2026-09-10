"""Variantes d'accusés de réception, tirées au hasard pour éviter l'effet robot.

Chaque catégorie possède une liste ``formal`` et une liste ``concise``.
Les chaînes peuvent contenir ``{address}`` (« monsieur ») et ``{detail}``.
"""

from __future__ import annotations

import random

_RESPONSES: dict[str, dict[str, list[str]]] = {
    # Action réussie, sans détail particulier
    "done": {
        "formal": [
            "C'est fait.",
            "C'est fait, {address}.",
            "Voilà qui est fait.",
            "Bien, {address}.",
            "À vos ordres.",
            "Comme vous voudrez.",
        ],
        "concise": ["Fait.", "Voilà.", "Bien."],
    },
    # Action réussie avec un détail : « Spotify est ouvert. »
    "done_detail": {
        "formal": ["{detail}", "{detail}, {address}.", "Voilà. {detail}"],
        "concise": ["{detail}"],
    },
    # Écoute en cours (affiché, pas toujours prononcé)
    "listening": {
        "formal": ["Je vous écoute.", "Oui, {address} ?", "{address} ?", "Je suis à vous."],
        "concise": ["Oui ?", "J'écoute."],
    },
    # Demande de confirmation d'une action destructrice
    "confirm": {
        "formal": [
            "Vous confirmez, {address} : {detail} ?",
            "Dois-je vraiment procéder ? {detail}.",
            "{detail}. Vous en êtes certain, {address} ?",
        ],
        "concise": ["{detail} ? Confirmez."],
    },
    # Confirmation refusée / annulation
    "cancelled": {
        "formal": [
            "Très bien, je n'en ferai rien.",
            "Annulé, {address}.",
            "Comme vous voudrez, j'y renonce.",
        ],
        "concise": ["Annulé."],
    },
    # Commande incomprise
    "unknown": {
        "formal": [
            "Je crains de ne pas avoir saisi, {address}.",
            "Pardonnez-moi, je n'ai pas compris.",
            "Pourriez-vous reformuler, {address} ?",
        ],
        "concise": ["Pardon ?", "Je n'ai pas compris."],
    },
    # Échec d'un tool avec une raison : « Cette application n'est pas installée. »
    "error": {
        "formal": [
            "Je crains que ce ne soit pas possible : {detail}",
            "Il semble y avoir un contretemps : {detail}",
            "Hélas, {detail}",
        ],
        "concise": ["Échec : {detail}"],
    },
    # Aucun texte reconnu au micro
    "nothing_heard": {
        "formal": [
            "Je n'ai rien entendu, {address}.",
            "Le silence, {address}. Je reste à disposition.",
        ],
        "concise": ["Rien entendu."],
    },
    # LLM indisponible
    "llm_down": {
        "formal": [
            "Mon jugement me fait défaut : le modèle de langage ne répond pas.",
            "Je ne puis raisonner pour l'instant, {address} ; Ollama semble absent.",
        ],
        "concise": ["Modèle indisponible."],
    },
    # Hors ligne (tool web)
    "offline": {
        "formal": [
            "Nous sommes sans connexion, {address} ; la recherche attendra.",
            "Internet nous fait défaut pour l'instant.",
        ],
        "concise": ["Hors ligne."],
    },
    # Tool lent : prononcé pendant l'exécution
    "wait": {
        "formal": ["Un instant, {address}.", "Je m'en occupe.", "Tout de suite."],
        "concise": ["Un instant."],
    },
    # Salutations
    "greeting": {
        "formal": ["Bonjour, {address}.", "{address}.", "Bonjour. Que puis-je pour vous ?"],
        "concise": ["Bonjour."],
    },
}


def pick(category: str, mode: str = "formal", address: str = "monsieur", detail: str = "") -> str:
    """Tire une variante au hasard et la formate.

    Le mode inconnu retombe sur ``formal`` ; la catégorie inconnue retombe sur ``done``.
    L'adresse est capitalisée lorsqu'elle ouvre la phrase.
    """
    variants = _RESPONSES.get(category, _RESPONSES["done"])
    pool = variants.get(mode) or variants["formal"]
    text = random.choice(pool).format(address=address, detail=detail)
    text = text.strip()
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def categories() -> list[str]:
    return list(_RESPONSES)
