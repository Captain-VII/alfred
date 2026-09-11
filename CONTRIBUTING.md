# Contribuer à ALFRED

Merci de votre intérêt. Voici comment travailler proprement sur le projet.

## Mise en place

```bash
git clone https://github.com/Captain-VII/alfred.git
cd alfred
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

Ollama doit tourner localement (`ollama serve`) pour le niveau 3 ; les tests
n'en ont pas besoin.

## Vérifications avant une PR

```bash
ruff check alfred tests scripts
ruff format --check alfred tests scripts
mypy alfred
pytest
```

La CI exécute exactement ces commandes. Une PR qui les casse ne sera pas relue.

## Règles du code

- Python 3.11+, type hints partout, `async def` pour tous les tools.
- Commentaires et docstrings en français ; identifiants en anglais.
- Aucun appel système direct dans un tool : passez par `alfred/tools/_win.py`,
  c'est ce module que les tests remplacent.
- Un tool qui échoue lève `ToolError("message parlé")` — jamais un crash.
- Une action irréversible est déclarée `confirm=True`.
- Pas de `print`, utilisez `logging`.

## Ajouter un tool

Voir la section « Ajouter un tool » du README. Ajoutez au minimum :

1. des `examples` (niveau 2) et, si la formulation est prévisible, des `patterns` (niveau 1) ;
2. un test dans `tests/` qui vérifie le routage et l'exécution avec le système simulé ;
3. une ligne dans le tableau des commandes du README.

## Commits et versions

- Messages de commit à l'impératif, en français ou en anglais, concis.
- Mettez à jour `CHANGELOG.md` (section *Unreleased*) dans la même PR.
- Les releases sont créées par tag `vX.Y.Z` ; le workflow `release.yml` construit et publie l'installeur.
