<p align="center">
  <img src="assets/icons/alfred.png" width="96" alt="Alfred">
</p>

<h1 align="center">ALFRED</h1>

<p align="center">
  <em>Majordome vocal local pour Windows 11. Il comprend le français, agit sur votre machine<br>et répond d'une voix posée. Rien ne quitte votre PC.</em>
</p>

<p align="center">
  <a href="https://github.com/Captain-VII/alfred/actions/workflows/ci.yml"><img src="https://github.com/Captain-VII/alfred/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/Captain-VII/alfred/releases/latest"><img src="https://img.shields.io/github/v/release/Captain-VII/alfred?include_prereleases&label=version" alt="Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-MIT-green.svg" alt="Licence MIT"></a>
  <img src="https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/plateforme-Windows%2011-0078d4.svg" alt="Windows 11">
</p>

<p align="center">
  <img src="docs/overlay.svg" width="640" alt="Overlay Alfred : « ouvre spotify et monte le son » puis « Spotify est ouvert. Volume à soixante pour cent. »">
</p>

---

- **Local, point.** Le modèle de langage (Ollama), la reconnaissance vocale (faster-whisper) et la synthèse (Piper) tournent sur votre machine. Pas de compte, pas de clé d'API, pas de cloud.
- **Rapide.** Un routeur à trois niveaux évite le modèle de langage quand il est inutile : moins de 400 ms entre la fin de la phrase et l'action pour les commandes courantes.
- **Un majordome, pas un robot de dialogue.** Vouvoiement, une phrase, deux au maximum. « C'est fait. » Jamais « Bien sûr ! Je serais ravi de vous aider ! ».

## Installation

1. Installez [Ollama](https://ollama.com/download/windows) et lancez-le. Une icône apparaît dans la barre système.
2. Téléchargez `Alfred-Setup-x.y.z.exe` depuis la [dernière version publiée](https://github.com/Captain-VII/alfred/releases/latest) et exécutez-le.
3. Suivez l'assistant de premier lancement : il télécharge le modèle de langage (`llama3.1`, environ 4,9 Go) et la voix (environ 60 Mo), puis teste votre micro et vos haut-parleurs.

Alfred s'installe ensuite dans la barre système.

| Raccourci | Effet |
|---|---|
| <kbd>Ctrl</kbd> + <kbd>Espace</kbd> | Parler |
| <kbd>Ctrl</kbd> + <kbd>Maj</kbd> + <kbd>Espace</kbd> | Taper une commande |
| <kbd>Échap</kbd> | Tout annuler, y compris la voix en cours |

<details>
<summary><strong>Installation depuis les sources</strong></summary>

```bash
git clone https://github.com/Captain-VII/alfred.git
cd alfred
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python -m alfred
```

Pour essayer une commande sans interface ni micro :

```bash
python -m alfred --cli "rappelle-moi dans 20 minutes de sortir le gâteau" --no-tts
```

</details>

## Commandes

Les formulations ci-dessous sont reconnues instantanément. Les variantes proches sont rattrapées par la similarité sémantique, et le reste par le modèle de langage, questions ouvertes comprises.

| Domaine | Exemples | Remarques |
|---|---|---|
| **Applications** | « ouvre Spotify », « lance le navigateur », « ferme-la », « bascule sur VS Code » | Résolution approximative des noms : « spotifaille », « mon éditeur de code ». Alias configurables. |
| **Volume** | « monte le son », « baisse le volume de 20 », « volume à 30 % », « coupe le son » | Valeur absolue, relative, mots-clés, nombres en toutes lettres. |
| **Luminosité** | « baisse la luminosité », « luminosité à 40 % », « écran plus lumineux » | Écrans compatibles DDC/CI, et portables. |
| **Session** | « verrouille l'écran », « mets en veille », « éteins l'ordinateur », « redémarre le PC » | L'arrêt et le redémarrage demandent confirmation. |
| **Écran** | « capture d'écran », « ne pas déranger », « remets les notifications » | Les captures vont dans `Images\Alfred`. |
| **Média** | « pause », « suivant », « piste précédente », « arrête la musique » | Touches média : Spotify, YouTube, VLC. |
| **Web** | « cherche sur internet la météo à Lyon », « qu'est-ce que le protocole MCP » | DuckDuckGo, lecture de la page, réponse en deux ou trois phrases, source citée. |
| **Fichiers** | « cherche le fichier budget 2024 », « ouvre-le », « montre-le dans l'explorateur » | Everything s'il est installé, sinon parcours des dossiers utilisateur. |
| **Fenêtres** | « réduis la fenêtre », « plein écran », « côte à côte », « montre le bureau » | |
| **Presse-papier** | « lis le presse-papier », « traduis-le en anglais », « corrige les fautes » | Le résultat remplace le contenu du presse-papier. |
| **Minuteurs** | « rappelle-moi dans 20 minutes de sortir le gâteau », « annule le rappel » | Notification Windows, annonce vocale et son. |
| **Contexte** | « ouvre Spotify » puis « ferme-la » | Les cinq derniers échanges sont conservés. |

## Comment ça marche

```
Entrée (voix via faster-whisper, ou texte)
   │  clic sonore immédiat
   ├─► Niveau 1 — expressions régulières déclarées par les tools   « monte le son »
   ├─► Niveau 2 — embeddings locaux des exemples                   « je veux plus de volume »
   └─► Niveau 3 — Ollama, appel d'outil                            formulation libre, questions
                       │
              exécution asynchrone ──► réponse Piper, phrase par phrase
```

Mesures de `python scripts/benchmark.py`, modèles préchargés :

| Étape | Médiane |
|---|---|
| Niveau 1, routage et exécution | 0,1 ms |
| Niveau 2, embedding et recherche | 1,3 ms |
| Niveau 3, action simple | 0,5 s |
| Niveau 3 avec recherche web | 2,1 s |
| Piper, une phrase courte | 22 ms |

Le démarrage paie seul les chargements : index sémantique une seconde, puis deux millisecondes depuis le cache disque, voix Piper et modèle Whisper une seconde chacun. Ensuite, plus rien n'est rechargé. Ollama reste en mémoire grâce à `keep_alive: -1`, les tools sont asynchrones, et la voix commence à parler pendant que les tools lents travaillent.

## Ajouter un tool

Un tool est une coroutine décorée. Le décorateur produit le schéma destiné au modèle de langage, enregistre les exemples et les expressions régulières. Déposez un fichier dans `alfred/tools/` : il est découvert au démarrage.

```python
from alfred.tools.base import ToolError, tool

@tool(
    name="set_lights",
    description="Allume ou éteint les lumières du bureau.",
    examples=["allume la lumière", "éteins les lumières", "lumière du bureau"],
    patterns=[r"(?P<state>allume|éteins) (?:la |les )?lumières?(?: du bureau)?"],
    params={"state": "« allume » ou « éteins »"},
    confirm=False,          # True demande une confirmation vocale
)
async def set_lights(state: str) -> str:
    if not await ma_domotique.set("bureau", state.startswith("allume")):
        raise ToolError("le pont domotique ne répond pas.")   # lu à voix haute, jamais de plantage
    return "Lumières allumées."                               # accusé de réception parlé
```

Quatre règles suffisent à s'en sortir.

- **`examples` est obligatoire.** Cinq à dix formulations naturelles et variées : c'est ce qui alimente la reconnaissance sémantique.
- **Les groupes nommés des `patterns` deviennent des paramètres**, convertis automatiquement selon les annotations de la signature.
- **`internal=[...]` cache au modèle les paramètres réservés aux expressions régulières.** Sans cela il s'en empare et invente des valeurs.
- **Aucun appel système direct** : passez par `alfred/tools/_win.py`, que les tests remplacent, et exécutez le bloquant via `_win.run_blocking(...)`.

Le détail, les services partagés et les conventions de test sont dans [CONTRIBUTING.md](CONTRIBUTING.md).

## Configuration

`%APPDATA%\Alfred\config.yaml` est créé au premier lancement à partir de [`config.default.yaml`](config.default.yaml), qui documente chaque clé. Le fichier est **rechargé à chaud** à chaque sauvegarde, et le panneau de réglages modifie le même fichier.

Les réglages les plus souvent touchés :

```yaml
hotkeys:
  invoke_voice: ctrl+space
  push_to_talk: false        # true : enregistre tant que la touche est maintenue

llm:
  model: llama3.1:latest     # tout modèle Ollama sachant appeler des outils
  fallback_model: llama3.2:3b

stt:
  model: small               # tiny | base | small | medium | large-v3
  device: auto               # cuda si disponible

tts:
  voice: fr_FR-gilles-low    # ou fr_FR-tom-medium
  length_scale: 1.08         # au-dessus de 1, le débit ralentit

router:
  semantic_threshold: 0.82   # plus bas, plus permissif, plus de faux positifs

persona:
  mode: formal               # formal | concise
  address: monsieur

app_aliases:
  navigateur: firefox.exe
```

Toute clé se surcharge aussi par variable d'environnement : `ALFRED__LLM__MODEL=llama3.2:3b`.

Deux voix masculines françaises sont proposées. `fr_FR-gilles-low` est la plus posée et la plus rapide, `fr_FR-tom-medium` est plus riche mais un peu plus lente. Changez `tts.voice` : la nouvelle voix est téléchargée automatiquement dans `%APPDATA%\Alfred\voices`.

## Dépannage

| Symptôme | Cause probable | Remède |
|---|---|---|
| « Mon jugement me fait défaut… » | Ollama est arrêté ou le modèle est absent | Lancez Ollama, puis `ollama pull llama3.1`. |
| Alfred n'entend rien | Mauvais micro sélectionné | Réglages, onglet Modèles, Microphone. Vérifiez aussi que Windows autorise le micro pour les applications de bureau. |
| Le raccourci ne répond pas | Une autre application capture <kbd>Ctrl</kbd> + <kbd>Espace</kbd> | Changez `hotkeys.invoke_voice`, par exemple `alt+space` ou `f9`. |
| Première réponse très lente | Modèle en cours de chargement | Normal au premier appel. `keep_alive: -1` le garde ensuite en mémoire. |
| Réponses lentes en général | Whisper sur processeur, ou modèle 8B sans carte graphique | Passez à `stt.model: base` et `llm.model: llama3.2:3b`. |
| « Whisper bascule sur le processeur » | cuBLAS ou cuDNN manquent à côté de CUDA | Alfred continue sans vous déranger. Pour retrouver la carte graphique, installez cuBLAS et cuDNN 9. |
| « Cette application n'est pas installée » | Nom trop éloigné, ou absent du menu Démarrer | Ajoutez un alias dans `app_aliases`. |
| Aucune icône au lancement | Une instance tourne déjà | Gestionnaire des tâches, `Alfred.exe`. Ou barre système, Redémarrer. |

Les journaux sont dans `%APPDATA%\Alfred\logs\alfred.log`, accessibles depuis la barre système et conservés sept jours. `behavior.log_level: debug` et `behavior.show_metrics: true` affichent la latence de chaque étape dans l'overlay.

## Développement

```bash
pip install -e ".[dev]"
pytest                      # 183 tests, aucun appel système réel
ruff check . && mypy alfred
python scripts/benchmark.py # latence par étape
python scripts/build.py     # dist/Alfred/ puis installer/Output/Alfred-Setup-x.y.z.exe
```

```
alfred/
├── core/       router (trois niveaux), llm (Ollama), executor, context, services
├── audio/      stt (faster-whisper et VAD), tts (Piper), sounds
├── tools/      base (@tool), puis apps, system, media, web, files, window, clipboard, timer
├── ui/         overlay, tray, settings, wizard, theme
├── persona/    prompt système, variantes de réponses
├── app.py      assemblage : Qt, boucle asyncio, raccourcis globaux
└── updater.py  GitHub Releases, installation silencieuse
```

Voir [CONTRIBUTING.md](CONTRIBUTING.md) et [CHANGELOG.md](CHANGELOG.md).

## Licence

[MIT](LICENSE). Les voix Piper relèvent de leurs licences respectives, voir [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices).
