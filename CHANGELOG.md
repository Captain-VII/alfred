# Changelog

Toutes les évolutions notables de ce projet sont consignées ici.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le
projet adhère au [Semantic Versioning](https://semver.org/lang/fr/).

## [Unreleased]

### Modifié
- Modèle LLM par défaut : `llama3.1:latest` (secours `llama3.2:3b`), tous deux avec tool calling natif dans Ollama.
- Le décorateur `@tool` accepte `internal=[...]` : les paramètres destinés aux regex du niveau 1 sont retirés du schéma envoyé au LLM.
- Prompt de résumé web recentré sur la réponse à la question.

### Corrigé
- Volume et luminosité : compatibilité avec pycaw 2024 (`AudioDevice.EndpointVolume`).
- Les appels d'outil écrits en JSON dans le texte de la réponse sont récupérés, y compris avec des guillemets mal échappés ; un appel illisible n'est jamais prononcé.
- « un quart du volume » réglait le son à 90 % : les drapeaux internes de `set_volume` induisaient le modèle en erreur.
- Plus de ponctuation doublée dans les accusés de réception (« Volume à trente pour cent., monsieur. »).
- Les variables d'environnement `ALFRED__*` l'emportent désormais sur le `config.yaml`.
- Whisper bascule automatiquement sur le processeur quand cuBLAS ou cuDNN manquent, au lieu d'échouer à la transcription.
- « affiche mon bureau » activait la mise au premier plan d'une application.
- Construction PyInstaller réparée : hook `webrtcvad` compatible avec `webrtcvad-wheels`, et collecte de `fastembed` sans import.
- Le benchmark ne plante plus sur les consoles en cp1252 et distingue le cache chaud du calcul complet.

## [0.1.0] - 2026-09-11

### Ajouté
- Routage à trois niveaux : regex (~0 ms), similarité sémantique (fastembed, ~15 ms), tool calling LLM (Ollama).
- Reconnaissance vocale locale avec faster-whisper (`small`, int8) et détection de fin de phrase (webrtcvad).
- Synthèse vocale Piper streamée phrase par phrase, voix `fr_FR-gilles-low` téléchargée au premier lancement.
- 35 tools : applications (résolution floue), système (volume, luminosité, veille, verrouillage, arrêt, capture, ne-pas-déranger), média, web (DuckDuckGo + lecture de page + résumé), fichiers (Everything ou parcours), fenêtres, presse-papier (lecture, traduction, résumé, réécriture), minuteurs.
- Overlay PyQt6 frameless sur l'écran du curseur, thème sombre/clair suivant Windows, mode texte.
- Icône de barre système : pause, réglages, logs, mises à jour, redémarrage, quitter.
- Panneau de réglages complet et assistant de premier lancement (Ollama, modèle, voix, micro, haut-parleurs, démarrage auto).
- Rechargement à chaud de `config.yaml`.
- Mises à jour automatiques via GitHub Releases (canaux stable / bêta, installation silencieuse optionnelle).
- Persona majordome : vouvoiement, concision, accusés de réception variés, modes `formal` et `concise`.
- Historique court (5 tours) pour les anaphores (« ferme-la »).
- Journalisation rotative sur 7 jours, métriques de latence par étape.
- Suite de tests (routeur, tools mockés, exécuteur, configuration, updater) et benchmark de latence.
- Packaging PyInstaller + installeur Inno Setup, workflows CI et release.

[Unreleased]: https://github.com/dorian-dubosc/alfred/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/dorian-dubosc/alfred/releases/tag/v0.1.0
