# Changelog

Toutes les évolutions notables de ce projet sont consignées ici.

Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et le
projet adhère au [Semantic Versioning](https://semver.org/lang/fr/).

## [Unreleased]

## [0.1.0] - 2026-09-11

Première version publique.

### Ajouté
- Routage à trois niveaux : regex (moins de 0,1 ms), similarité sémantique locale (fastembed, environ 1,3 ms), tool calling LLM via Ollama. Une commande courante n'atteint jamais le modèle de langage.
- Reconnaissance vocale locale avec faster-whisper (`small`, int8), détection de fin de phrase par webrtcvad, pré-roll et push-to-talk.
- Synthèse vocale Piper streamée phrase par phrase, voix `fr_FR-gilles-low` téléchargée au premier lancement, interruption immédiate par Échap.
- 35 tools : applications (résolution floue des noms), système (volume, luminosité, veille, verrouillage, arrêt, capture, ne-pas-déranger), média, web (DuckDuckGo, lecture de la page et résumé), fichiers (Everything ou parcours), fenêtres, presse-papier (lecture, traduction, résumé, réécriture), minuteurs.
- Décorateur `@tool` qui génère le schéma JSON du LLM, enregistre les exemples du niveau 2 et les regex du niveau 1 en une seule déclaration. `internal=[...]` masque au modèle les paramètres réservés aux regex.
- Overlay PyQt6 sans cadre sur l'écran du curseur, thème sombre ou clair suivant Windows, mode texte.
- Icône de barre système : pause, réglages, logs, mises à jour, redémarrage, quitter.
- Panneau de réglages complet et assistant de premier lancement : détection d'Ollama, téléchargement du modèle et de la voix, test du micro et des haut-parleurs, démarrage automatique.
- Rechargement à chaud de `config.yaml`, surchargeable par variables d'environnement `ALFRED__*`.
- Mises à jour automatiques via GitHub Releases : canaux stable et bêta, installation silencieuse optionnelle au redémarrage.
- Persona majordome : vouvoiement, concision, accusés de réception variés, modes `formal` et `concise`.
- Historique des cinq derniers tours, pour les anaphores du type « ferme-la ».
- Journalisation rotative sur sept jours, métriques de latence par étape dans l'overlay.
- Packaging PyInstaller et installeur Inno Setup, publiés automatiquement sur tag `v*`.

### Robustesse
- Un tool qui échoue devient une phrase parlée, jamais une exception qui remonte.
- Le mode hors ligne annonce clairement l'indisponibilité de la recherche web.
- Whisper bascule sur le processeur quand cuBLAS ou cuDNN manquent à côté de CUDA, au lieu d'échouer à la transcription.
- Les appels d'outil que certains modèles écrivent en JSON dans leur réponse sont récupérés, guillemets mal échappés compris. Un appel illisible n'est jamais prononcé.
- Une marge de confiance entre les deux meilleurs candidats du niveau 2 évite les confusions entre outils proches.
- 175 tests, dont aucun n'ouvre d'application ni ne modifie le volume. Benchmark de latence par étape. CI sur Python 3.11 et 3.12.

[Unreleased]: https://github.com/Captain-VII/alfred/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Captain-VII/alfred/releases/tag/v0.1.0
