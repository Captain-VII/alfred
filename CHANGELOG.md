# Changelog

Toutes les évolutions notables de ce projet sont consignées ici.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le
projet adhère au [Semantic Versioning](https://semver.org/lang/fr/).

## [Unreleased]

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
