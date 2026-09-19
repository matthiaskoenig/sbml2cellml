# CLAUDE.md

This file provides guidance when working with code in this repository.

## Project

`sbml2cellml` converts SBML models to CellML 2.0 and CellML models to SBML
L3V2 with libsbml and libcellml and simulates the result with libopencor.
Python 3.13 and 3.14 (`.python-version` is 3.14), packaged with
hatchling (version in `src/sbml2cellml/__init__.py`). Runtime dependencies:
`python-libsbml`, `libcellml`, `rich`. The `simulate` extra adds `pandas`
and `matplotlib`; libopencor itself is not on PyPI and comes from a uv flat
index on its GitHub release (`[tool.uv.index]` in `pyproject.toml`), it is
part of the `dev` extra, which also has `libroadrunner`.

## Commands

```bash
uv sync --extra dev             # environment, includes libopencor
uv run pre-commit install

pytest                          # all tests (parallel, pytest-xdist)
pytest tests/test_sbml2cellml.py::test_simple_model_initial_values
tox r -e py3.14                 # tests from uv.lock via tox-uv (also py3.13)
tox r -e ty                     # type check
tox run-parallel

ruff check
ruff format
uvx ty check

uv run zensical build --clean --strict   # docs into site/
uv run python scripts/llms_txt.py
uv run zensical serve

sbml2cellml model.xml -o model.cellml
cellml2sbml model.cellml -o model.xml

uv run sbml2cellml-testsuite run        # full SBML test suite, writes testsuite/results.json, docs/testsuite.md and docs/images/testsuite*.svg
tox r -e testsuite                      # gating test against the committed results (SBML2CELLML_TESTSUITE=1)

# local only, not in CI (about 20 minutes, the models are cached in ~/.cache/sbml2cellml/biomodels)
uv run sbml2cellml-biomodels run        # curated BioModels selection, writes biomodels/results.json, docs/biomodels.md and docs/images/biomodels*.svg
uv run sbml2cellml-biomodels update     # refresh the committed selection biomodels/models.json
uv run sbml2cellml-biomodels report     # rerender docs/biomodels.md and the figures from the results file
```

`develop` is the default branch and takes every change through a pull request;
the rulesets in `.github/rulesets/` (applied with `apply.sh`) require the
`tests`, `ruff`, `ty` and `docs` checks. `main` tracks the latest release and
is fast-forwarded by the `sync-main` job of the release workflow. Release
steps are in `docs/development.md`: release branch,
`uvx bump-my-version bump [major|minor|patch]` (updates `__init__.py` and
`CITATION.cff`, no tag), release notes in `docs/release-notes/`, pull request, tag
on `develop` after the merge.

## Architecture

- `sbml2cellml.py`: `convert_sbml2cellml(sbml_path, cellml_path=None, validate=True)`.
  One CellML component `sbml`, one variable per compartment, parameter and
  species plus `time`. `_variable_units` gives the variables their units when
  the unit annotation of the SBML model is complete (all or nothing: unset
  SBML units are unknown, not dimensionless), else all are `dimensionless`
  with a warning. The calls of function definitions
  are expanded first with libsbml's `expandFunctionDefinitions` conversion and
  the initial assignments evaluated to initial values with
  `expandInitialAssignments` (both skipped with a warning when a function is
  recursive, libsbml crashes on it when read from a file). libsbml evaluates
  formulas `_without_rate_rules` in the model (initial assignments, algebraic
  rules at the start): it takes the rate rule of a variable without a value
  yet for its value and crashes when the rate depends on the variable.
  Assignment rules
  become equations
  (their targets get no initial value), rate rules and kinetic laws
  differential equations; a concentration species
  gets its reaction terms divided by the compartment. The local parameters of
  a kinetic law become variables `<reaction>_<parameter>` (`unique_sid`).
  Kinetic laws are multiplied with the stoichiometry (no factor for 1) and do
  not change boundary species, the sum is multiplied with the conversion
  factor of the species or model; a
  species reference with an id is a variable of its stoichiometry, a reaction
  whose id a formula uses a variable of its rate. A model without rate rules,
  reactions and uses of time gets no `time` variable (CellML knows the
  variable of integration only from a differential equation); `simulate`
  runs such an algebraic model as a steady state. `_collect_formulas` gathers
  all formulas before the initial assignments are evaluated (they do not
  depend on initial values) and replaces `rateOf(x)` by the right-hand side
  of the equation of `x`, also in the initial assignments. An algebraic rule
  becomes `0 = formula`: `_match_algebraic_rules` finds the variable it
  determines, `_solve_algebraic_rules` solves it at the start (libsbml
  evaluates, secant method) for the solver guess and compartment sizes, and
  `_constants_of_algebraic_rules` turns the other initial values of the rule
  into equations, since libcellml takes any variable with an initial value in
  an implicit equation for its unknown. An infinite or NaN value of
  a variable which is not a state becomes an equation. Events, algebraic
  rules, unevaluated initial assignments and unset initial values (set to 1.0)
  are logged as warnings. The generated CellML is a fixed contract: tests compare the
  structure and the validity of the example models.
- `cellmlunits.py`: `CellMLUnits` converts every unit definition to CellML
  units (scale to prefix, a power of ten multiplier too, any other multiplier
  `m` to `m^exponent`: CellML applies the exponent to the prefix only; `item`
  as new base units, `avogadro` as dimensionless units) and finds the units of
  compartments, parameters, species (substance per size for a concentration,
  the identical unit definition of the model or new `a_per_b` units) and
  reaction rates (extent per time), with the built-in units of level 1 and 2.
- `mathml.py`: libsbml renders formulas as MathML documents; the helpers strip
  the declaration and `math` element, map `sbml:units` to `cellml:units` with
  the CellML name of the units (`units` callable),
  make every number a real with units (`dimensionless` when it has none),
  replace the time symbol by the variable `time` and avogadro by its value
  (`normalize_math`) and wrap the equations into the component math.
- `cellml.py`: libcellml `Parser`, `Printer`, `Validator` and `Analyser`
  wrappers; issues are returned, `errors()` filters level `ERROR`,
  `CellMLValidationError`.
- `simulate.py`: libopencor timecourse; the library is imported inside
  `run_timecourse` so the package works without it. The settings are applied
  to `document.simulations[0]`. Results drop the `component/` prefix of the
  variable names. Issues raise `SimulationError`.
- `cellml2sbml.py`: `convert_cellml2sbml(cellml_path, sbml_path=None, validate=True)`,
  analyser driven: parameters by variable type, rules by equation type, initial
  assignments for computed constants and variable-referenced initial values,
  implicit (NLA) equations as algebraic rules,
  resets as events with `eq` trigger and `-order` priority, imports flattened
  with `Importer`.
- `variables.py`: `VariableIds` gives one SBML id per equivalence set, a
  component prefix on name clashes; `unique_sid` adds a numeric suffix for
  colliding ids (parameters, unit definitions, the model id and event ids);
  `VariableIds.reserve` reserves an id outside the variables (model, events).
- `sbmlmath.py`: analyser AST to libsbml AST, nested piecewise flattened,
  `mathml_to_sbml` for reset maths. The analyser AST has no units of numbers:
  `NumberUnits` reads them from the MathML of the components and finds the
  equation of an AST by its variables and numbers (in order, else by value).
- `units.py`: CellML to SBML: standard units by name, custom units expanded to
  base kinds (prefix to scale, multiplier `m` to `m^(1/exponent)`), the factor
  of a reference to custom units folded into the first unit, new base units
  `item` as the unit kind.
- `sbml.py`: libsbml helpers, `validate_document` returns error messages, unit
  problems are warnings.
- `cli.py`: argparse, `[project.scripts]` entry point.
- `console.py`, `log.py`: rich console for scripts and the CLI, opt-in rich
  logging. Library code logs with `logging.getLogger(__name__)` and lazy `%s`
  formatting (ruff `G`), it never prints.
- `testsuite/`: `sbml2cellml-testsuite run|report` runs the SBML test suite
  through both converters and both simulators. `cases.py` downloads and reads
  the cases; `compare.py` checks a simulation against the expected results;
  `simulators.py` has the plain roadrunner and libopencor functions run
  inside `worker.py`'s `SimulatorWorker` processes (one process per
  simulator for the whole run, roadrunner and libopencor bundle different
  LLVM versions); `runner.py` is the five-stage pipeline
  (`reference`/`sbml2cellml`/`libopencor`/`cellml2sbml`/`roundtrip`) per
  case; `results.py` is `SuiteResult` (JSON) with `regressions`/
  `improvements`; `report.py` renders `docs/testsuite.md`; `figure.py` its
  bar diagram `docs/images/testsuite.svg` and `testsuite_dark.svg` (also in
  `README.md`); `cli.py` is the
  `sbml2cellml-testsuite` entry point.
- `biomodels/` (run locally, never in CI; see `biomodels/README.md`):
  `sbml2cellml-biomodels run|update|report` runs the manually
  curated SBML models of BioModels through the same pipeline. `models.py`
  queries and downloads the models through the BioModels REST API, cached on
  disk, and reads/writes the selection `biomodels/models.json`; `cases.py`
  builds a case for a downloaded model with the generic timecourse (0 to 100
  time units, 100 steps); `runner.py` turns a list of ids into cases (skipping
  a failed download or a model without variables) and calls
  `sbml2cellml.testsuite.runner.run_suite`, whose `reference` stage uses the
  roadrunner simulation of the original model as the expected results since
  BioModels has none; `cli.py` is the `sbml2cellml-biomodels` entry point,
  which renders the report `docs/biomodels.md` with the report and figure
  code of the test suite.

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
- Known conversion issues are documented in `docs/conversion-issues.md` and encoded in the
  tests (`delay_model` in `tests/test_sbml2cellml.py`, the kidney model in
  `tests/test_simulate.py`); fixing a gap means removing its test, not
  weakening the assertion.
- No em dash in any text, use `-`.
- Release notes go in `docs/release-notes/x.y.z.md` as part of a release
  commit, with an entry in the nav of `zensical.toml` and in the overview
  `docs/release-notes/index.md` (`tests/test_package.py` checks both); the
  release workflow uses the file as body of the GitHub release.
- `references/` holds the CellML specification and libopencor notes, it is not
  part of the documentation site.
- Test models built with libcellml live in `tests/cellml_models.py`;
  `tests/data/` holds the import fixtures.
- roadrunner and libopencor bundle different LLVM versions and crash in one
  process, so the roundtrip tests run roadrunner in a subprocess
  (`tests/simulators.py`).
- `testsuite/results.json`, `docs/testsuite.md` and `docs/images/testsuite*.svg`
  are generated by `sbml2cellml-testsuite run` (or `report`) and committed;
  the full-suite test (`tests/test_testsuite_full.py`) fails on regressions
  against them; accept improvements by regenerating them.
- `biomodels/models.json`, `biomodels/results.json`, `docs/biomodels.md` and
  `docs/images/biomodels*.svg` are generated (`update` and `run`) and
  committed. The check runs locally only, there is no workflow and no gating
  test for it: rerun it after converter changes, review the regressions it
  prints and commit the regenerated files.
