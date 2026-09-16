# CLAUDE.md

This file provides guidance when working with code in this repository.

## Project

`sbml2cellml` converts SBML models to CellML 2.0 with libsbml and libcellml and
simulates the result with libopencor. Python 3.13 only (libcellml has no wheel
for 3.14 yet), packaged with hatchling (version in `src/sbml2cellml/__init__.py`).
Runtime dependencies: `python-libsbml`, `libcellml`, `rich`. The
`simulate` extra adds `pandas` and `matplotlib`; libopencor itself is not on
PyPI and comes from a uv flat index on its GitHub release (`[tool.uv.index]`
in `pyproject.toml`), it is part of the `dev` extra.

## Commands

```bash
uv sync --extra dev             # environment, includes libopencor
uv run pre-commit install

pytest                          # all tests (parallel, pytest-xdist)
pytest tests/test_sbml2cellml.py::test_simple_model_initial_values
tox r -e py3.13                 # tests from uv.lock via tox-uv
tox r -e ty                     # type check
tox run-parallel

ruff check
ruff format
uvx ty check

uv run zensical build --clean   # docs into site/
uv run python scripts/llms_txt.py
uv run zensical serve

sbml2cellml model.xml -o model.cellml
```

`develop` is the default branch and takes every change through a pull request;
the rulesets in `.github/rulesets/` (applied with `apply.sh`) require the
`tests`, `ruff`, `ty` and `docs` checks. `main` tracks the latest release and
is fast-forwarded by the `sync-main` job of the release workflow. Release
steps are in `docs/development.md`: release branch,
`uvx bump-my-version bump [major|minor|patch]` (updates `__init__.py` and
`CITATION.cff`, no tag), release notes in `release-notes/`, pull request, tag
on `develop` after the merge.

## Architecture

- `sbml2cellml.py`: `convert_sbml2cellml(sbml_path, cellml_path=None, validate=True)`.
  One CellML component `sbml`, one variable per compartment, parameter and
  species plus `time`, all `dimensionless`. Assignment rules become equations,
  rate rules and kinetic laws differential equations; a concentration species
  gets its reaction terms divided by the compartment. Events, initial
  assignments, algebraic rules and unset initial values (set to 1.0) are logged
  as warnings. The generated CellML is a fixed contract: tests compare the
  structure and the validity of the example models.
- `mathml.py`: libsbml renders formulas as MathML documents; the helpers strip
  the declaration and `math` element, map `sbml:units` to `cellml:units` and
  wrap the equations into the component math.
- `cellml.py`: libcellml `Parser`, `Printer`, `Validator` and `Analyser`
  wrappers; issues are returned, `errors()` filters level `ERROR`,
  `CellMLValidationError`.
- `simulate.py`: libopencor timecourse; the library is imported inside
  `run_timecourse` so the package works without it. The settings are applied
  to `document.simulations[0]`. Results drop the `component/` prefix of the
  variable names. Issues raise `SimulationError`.
- `cli.py`: argparse, `[project.scripts]` entry point.
- `console.py`, `log.py`: rich console for scripts and the CLI, opt-in rich
  logging. Library code logs with `logging.getLogger(__name__)` and lazy `%s`
  formatting (ruff `G`), it never prints.

## Conventions

- ty with `error-on-warning = true`: zero diagnostics, rule specific
  `# ty: ignore[rule-name]` only.
- Full type annotations and google-style docstrings on every module, class and
  function (ruff `D`; `examples/` and `tests/` exempt).
- `examples/` at the top level holds the runnable examples and
  `examples/models/` the glimepiride SBML models and `test_model.cellml`; the
  tests read the models via `MODELS_DIR` in `tests/conftest.py`. Generated
  CellML goes to the gitignored `examples/results/`. Small fixtures created
  for a test go to `tests/data/`.
- Known conversion gaps are documented in `docs/roadmap.md` and encoded in the
  tests (`INVALID_MODELS` in `tests/test_sbml2cellml.py`, the kidney model in
  `tests/test_simulate.py`); fixing a gap means removing the model from the
  list, not weakening the assertion.
- No em dash in any text, use `-`.
- Release notes go in `release-notes/` as part of a release commit.
- `references/` holds the CellML specification and libopencor notes, it is not
  part of the documentation site.
