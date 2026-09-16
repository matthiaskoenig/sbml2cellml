# S1: package and infrastructure baseline

Date: 2026-09-16
Status: approved design, implementation pending

## Context

`sbml2cellml` was migrated out of `sbmlutils.converters.cellml` in two commits.
The code converts SBML models to CellML 2.0 with `libcellml` and simulates the
result with `libopencor`. The repository is not yet a package: the
`pyproject.toml` is a stub, the examples import `sbmlutils.converters.cellml`,
there are no tests, no CI, no documentation and no release process.

The update of the repository is decomposed into five sub-projects, each with
its own design and implementation plan:

- **S1 (this document):** package and infrastructure baseline. The converter
  keeps its current behaviour, the repository becomes releasable and follows
  the conventions of `pymetadata` and `sbmlsim`.
- **S2:** CellML to SBML converter (`cellml2sbml`).
- **S3:** SBML test suite roundtrip harness (libroadrunner simulation of the
  SBML, conversion to CellML, libopencor simulation, back conversion, comparison
  against the expected results) with a status page in the documentation.
  Gated on regressions against a committed expected-status manifest, not on
  all cases passing.
- **S4:** curated BioModels conversion check before a release.
- **S5:** converter features driven by S3 failures: units, events, initial
  assignments, function definitions, algebraic rules.

## Decisions

| Question | Decision |
|----------|----------|
| Scope of S1 | Infrastructure and package restructure only; converter semantics unchanged. |
| Python versions | `>=3.13`. `libcellml` 0.6.3 ships wheels up to cp313; 3.14 is added when a cp314 wheel exists. |
| Branch model | `develop` default branch, all changes via pull request, `main` tracks the latest release and is fast-forwarded by the release workflow (as `pymetadata`). |
| `libopencor` | Not on PyPI, prebuilt wheels on GitHub releases. Pinned in the `dev` extra through a uv flat index; the `simulate` extra only carries `pandas` and `matplotlib`; end users install the wheel from the release URL. Simulation tests skip when `libopencor` is not importable. |
| CLI | `sbml2cellml` entry point in S1 (argparse, no extra dependency). |

## Section 1: package layout and API

```
src/sbml2cellml/
  __init__.py        __version__, re-exports convert_sbml2cellml
  sbml2cellml.py     SBML -> CellML converter (the existing code, moved from cellml2sbml.py)
  cellml.py          libcellml helpers: read, write, validate, analyse, issues
  mathml.py          MathML helpers: process_mathml_for_cellml, mathml_for_diff, mathml_for_assignment
  simulate.py        libopencor timecourse and plot, lazy import of libopencor
  cli.py             argparse entry point of the `sbml2cellml` command
  console.py         rich console (existing)
  log.py             NullHandler on the package logger, enable_rich_logging() opt-in (as pymetadata)
examples/            top level, not packaged: glimepiride_example.py, cellml_example.py, models/
tests/               test_sbml2cellml.py, test_mathml.py, test_cellml.py, test_simulate.py,
                     test_cli.py, test_examples.py, data/
references/          cellml_2_0_1_normative_specification.pdf, libopencor.ipynb,
                     cellml_reset_example.py (kept out of the documentation site)
docs/                zensical sources (see section 5)
scripts/             llms_txt.py
```

`src/__init__.py` is removed (it makes `src` a package by accident). The
`models/` directory moves to `examples/models/` (the five glimepiride SBML
files, 640 kB, and `test_model.cellml`). The tests use these files through a
`MODELS_DIR` constant in `tests/conftest.py` instead of a second copy in
`tests/data/`; `tests/data/` only holds small fixtures created for a test. The
converted `.cellml` files are not committed; tests and examples generate them.

### API

- `sbml2cellml.convert_sbml2cellml(sbml_path: Path, cellml_path: Path | None = None, validate: bool = True) -> libcellml.Model`
  reads the SBML file, builds the CellML model and writes it to `cellml_path`
  when given. With `validate=True` the model is checked with the `libcellml`
  `Validator` and `Analyser` and a `CellMLValidationError` is raised when an
  issue of level `ERROR` exists. `SBML2CellMLConversionError` is raised when
  the document has no model.
- `sbml2cellml.cellml`: `read_model(path) -> libcellml.Model`,
  `write_model(model, path) -> None`, `model_to_string(model) -> str`,
  `validate_model(model) -> list[libcellml.Issue]` (validator and analyser
  issues, no printing), `errors(issues) -> list[libcellml.Issue]` (the
  issues of level `ERROR`), `format_issue(issue) -> str`,
  `CellMLValidationError`.
- `sbml2cellml.mathml`: the three existing helpers, unchanged behaviour, typed
  and documented. The MathML prefix handling stays string based in S1.
- `sbml2cellml.simulate`: `run_timecourse(cellml_path, start=0.0, end=100.0, steps=100) -> tuple[pd.DataFrame, dict[str, str]]`
  and `plot_timecourse(df, units, show=True) -> Figure`. `libopencor` is
  imported inside `run_timecourse`; an `ImportError` is re-raised with the
  install instruction. `pandas` and `matplotlib` are imported at module level,
  the module is part of the `simulate` extra. The timecourse settings are
  applied to the `SedUniformTimeCourse` which `libopencor` creates for the
  file (`document.simulations[0]`), which fixes the "cannot set start, end,
  steps" issue of the old code (it created a second, unused simulation). The
  data frame holds the variable of integration, the states and the algebraic
  variables; the columns are the variable names without the `component/`
  prefix `libopencor` reports (the converter puts everything in one
  component). A `libopencor` issue on the file, document or instance raises
  `SimulationError` with the descriptions of the issues.
- `sbml2cellml.cli.main(argv: list[str] | None = None) -> int`:
  `sbml2cellml INPUT.xml [-o OUTPUT.cellml] [--no-validate] [-v]`. Without
  `-o` the output is written next to the input with the `.cellml` suffix.
  `-v` enables rich logging at `INFO`. Returns 0 on success, 1 on a missing
  input, a conversion error or a validation error, with the message on stderr.

### Behaviour changes in S1

- Library code logs instead of printing: the verbose output of the converter
  becomes `logger.info`, "not converted" events and initial assignments become
  `logger.warning`, the NaN initial value fallback becomes `logger.warning`.
  The `verbose` parameter is dropped; scripts enable logging with
  `log.enable_rich_logging()`.
- `validate_cellml` no longer prints and returns a list of issues.
- The TODO and FIXME lists of the module docstring move to `docs/roadmap.md`.
- Everything else, in particular the generated CellML, is unchanged.

## Section 2: packaging and dependencies

`pyproject.toml` follows `sbmlsim`:

- hatchling build backend, `dynamic = ["version"]` read from
  `src/sbml2cellml/__init__.py`, `[tool.hatch.build.targets.wheel] packages = ["src/sbml2cellml"]`.
- `requires-python = ">=3.13"`, classifier for 3.13 only, `Development Status :: 3 - Alpha`.
- `dependencies`: `python-libsbml>=5.21.1`, `libcellml>=0.6.3`, `numpy>=2.5.3`, `rich>=15.0.0`.
- `[project.optional-dependencies]`:
  - `simulate = ["pandas>=3.0.5", "matplotlib>=3.11.1"]`
  - `dev = ["sbml2cellml[simulate]", "libopencor==1.20260803.0", "bump-my-version>=1.5.1", "ruff>=0.16.6", "pre-commit>=4.6.2", "ty>=0.0.79", "tox>=4.61.2", "tox-uv", "pytest>=9.1.1", "pytest-xdist>=3.8", "zensical>=0.0.60", "mkdocstrings-python>=2.0.8"]`
- `[[tool.uv.index]] name = "libopencor"`, `format = "flat"`,
  `url = "https://github.com/opencor/libopencor/releases/expanded_assets/v1.20260803.0"`,
  `explicit = true`, and `[tool.uv.sources] libopencor = { index = "libopencor" }`.
  Bumping `libopencor` changes the version in two places. If the
  `expanded_assets` page does not work as a flat index, the fallback is one
  `{ url = "<wheel url>", marker = "<platform and python marker>" }` entry per
  supported wheel (linux x86_64, linux aarch64, macOS arm64, macOS x86_64,
  windows amd64) for cp313.
- `[project.scripts] sbml2cellml = "sbml2cellml.cli:main"`.
- `[project.urls]` Homepage and Documentation `https://matthiaskoenig.github.io/sbml2cellml`,
  Repository, Issues, Changelog (`release-notes` on `develop`), Download (PyPI).
- keywords: modeling, standardization, COMBINE, SBML, CellML, converter.
- `[tool.pytest.ini_options] testpaths = ["tests"]`, `addopts = "-n auto"`.
- `[tool.ty]` as `sbmlsim`: `root = ["./src", "."]`, `include = ["src", "tests", "examples", "scripts"]`, `error-on-warning = true`.
- `.ruff.toml`: the `sbmlsim` configuration (includes the `G` logging rules and
  google-style `D` docstring rules).
- `.python-version` stays `3.13`.
- `tox.ini`: `envlist = ty, py3.13`, `tox-uv` with `uv_sync = true` so the
  `[tool.uv]` sources and the lockfile are honoured; the `ty` env runs `ty check`.
- `uv.lock` is committed.
- `.pre-commit-config.yaml`: the `pymetadata` hooks (pre-commit-hooks, ruff
  check and format, ty).
- `.bumpversion.toml`: updates `src/sbml2cellml/__init__.py` and
  `CITATION.cff`, `tag = false`, `commit = true`.
- `.gitignore`: standard python plus `site/`, `.tox/`, `.venv/`, `.cache/`,
  `.ruff_cache/`, `.pytest_cache/`, `*.egg-info/`, `dist/`, and the generated
  `examples/models/*.cellml`.

## Section 3: tests

The five glimepiride SBML models (`glimepiride_body.xml`,
`glimepiride_body_flat.xml`, `glimepiride_intestine.xml`,
`glimepiride_kidney.xml`, `glimepiride_liver.xml`) and `test_model.cellml` are
read from `examples/models/` via `MODELS_DIR` in `tests/conftest.py`. Small
SBML fixtures are built in test code with `libsbml` where that is cheaper than
a file; files created for a test go to `tests/data/`.

- `test_sbml2cellml.py`: every glimepiride model converts with
  `validate=False`; the model has one component `sbml`; the variable count
  equals compartments + parameters + species + 1 (time); the written file is
  parsed back by `libcellml.Parser` without issues. `Validator` and `Analyser`
  report no errors for `glimepiride_liver` and `glimepiride_kidney`; the
  other three models have known conversion gaps of the current converter
  (`glimepiride_intestine`: a function definition and units on `cn`
  elements; `glimepiride_body` and `glimepiride_body_flat`: units on `cn`
  elements) and their validity test is `xfail(strict=True)` with that reason,
  so S5 flips them by removing the marker. A document without a model raises
  `SBML2CellMLConversionError`. `convert_sbml2cellml(validate=True)` raises
  `CellMLValidationError` for `glimepiride_body`. An event or an initial
  assignment logs a warning (`caplog`). A NaN initial value is set to 1.0 with
  a warning. The initial value arithmetic for species in amount and in
  concentration is covered by a small fixture.
- `test_mathml.py`: `process_mathml_for_cellml` strips the xml header and the
  math element, maps `sbml:units` to `cellml:units`; `mathml_for_diff` and
  `mathml_for_assignment` produce the expected structure.
- `test_cellml.py`: read and write roundtrip of `test_model.cellml`,
  `validate_model` returns no issues for it and returns the issues of an
  invalid model (a component whose math references an unknown variable),
  `read_model` raises `CellMLValidationError` on unparsable text.
- `test_simulate.py`: `pytest.importorskip("libopencor")`. The timecourse of
  `test_model.cellml` with `end=50.0, steps=10` returns a data frame with 11
  rows, columns `t` and `m`, `t` ending at 50.0, `m` starting at 10.0 and
  decaying monotonically, and units `{"t": "second", "m": "kilogram"}`.
  `glimepiride_liver` simulates without error and its columns include `time`
  and every species id. `glimepiride_kidney` is underconstrained for
  `libopencor` (`egfr_healthy`, `f_renal_function`, `egfr`, a conversion gap
  for S5) and raises `SimulationError`; the test asserts that and is not an
  xfail, since the behaviour is deterministic.
- `test_cli.py`: `main(["in.xml", "-o", "out.cellml"])` writes the file and
  returns 0; a missing input file returns 1; the default output path is next
  to the input.
- `test_examples.py`: each example script runs via `runpy` in a temporary
  working directory without exception, with the matplotlib `Agg` backend
  (`MPLBACKEND=Agg`); the examples convert with `validate=False`, report
  the issues, and only simulate the models which `libopencor` can run
  (`test_model`, `glimepiride_liver`). Skipped when `libopencor` is missing.

Tests run in parallel with `pytest-xdist`, need no network, and the coverage is
not gated.

## Section 4: CI, rulesets, branch and release setup

Workflows are copied from `sbmlsim` and adapted:

- `ci-cd.yml`: test matrix ubuntu, windows and macOS on 3.13, no deadsnakes
  step (no libroadrunner in S1), `uvx --with tox-uv tox -e py3.13`; the
  aggregate job `tests`; the `release` job on a tag builds with `hatch`,
  checks with `twine`, publishes to PyPI through trusted publishing
  (environment `pypi`) and creates the GitHub release from
  `release-notes/<tag>.md`; the `sync-main` job fast-forwards `main`.
- `ruff.yml` and `ty.yml`: unchanged, job names `ruff` and `ty`.
- `docs.yml`: `uv sync --extra dev`, `zensical build --clean`,
  `scripts/llms_txt.py`, Pages deployment from `develop`; job name `docs`.
- `.github/rulesets/develop.json`, `main.json`, `tags.json` and `apply.sh`
  (default repository `matthiaskoenig/sbml2cellml`) with the required checks
  `tests`, `ruff`, `ty` and `docs`.

One-time repository steps, documented in `docs/development.md`:

1. Create `develop` from `main`, push it and make it the default branch (`gh`).
2. Run `.github/rulesets/apply.sh` for the merge settings and rulesets. From
   then on every change, including the rest of S1, goes through a pull request
   into `develop`.
3. Set the GitHub Pages source to GitHub Actions (`gh api`).
4. Register the PyPI trusted publisher for `sbml2cellml` (repository
   `matthiaskoenig/sbml2cellml`, workflow `ci-cd.yml`, environment `pypi`).
   Manual step on pypi.org by the maintainer; a pending publisher works before
   the first release.
5. Enable the Zenodo GitHub integration for the repository. Manual step by the
   maintainer.

The release flow is the `pymetadata` one: release branch,
`uvx bump-my-version bump [major|minor|patch]`, the release note file, pull
request into `develop`, tag on `develop` after the merge, which triggers the
release workflow.

## Section 5: documentation, README and metadata files

Zensical site with `zensical.toml` from `pymetadata` (`site_name = "sbml2cellml"`,
teal palette, edit uri on `develop`, copyright 2025-2026). Pages:

- `index.md`: purpose, a short python example, and a table of SBML constructs
  with their conversion status (compartments, parameters, species, assignment
  rules, rate rules and reactions are supported; unit definitions, units on
  numbers in formulas, events, initial assignments, function definitions and
  algebraic rules are not yet).
- `installation.md`: `pip install sbml2cellml`, the `simulate` extra, and the
  `libopencor` wheel installation from the GitHub release with the URL pattern.
- `conversion.md`: user guide for the python API and the CLI, what `validate`
  checks.
- `simulation.md`: timecourse with `libopencor` and plotting.
- `roadmap.md`: the S2 to S5 items, replaces the TODO list in the code.
- `development.md`: uv setup, tests, tox, ty, docs build, branch model,
  release steps and the one-time repository setup of section 4.
- `api/`: one `::: sbml2cellml.<module>` page per module plus an overview.
- `scripts/llms_txt.py` copied from `pymetadata`.
- No logo exists yet. The site and the README have no logo and no favicon
  until one is supplied.

Metadata files:

- `README.md`: the `pymetadata` layout with badges for CI, documentation,
  PyPI version, python versions, license and Zenodo DOI. The DOI badge and the
  citation block are filled in with the first release; until then they carry
  the text "DOI available with the first release".
- `CITATION.cff`: version `0.1.0`, `date-released` and `doi` set with the
  first release, affiliation and ORCID as in `pymetadata`.
- `.zenodo.json`: the description link is corrected from `pymetadata` to
  `sbml2cellml`, keywords and funding text kept.
- `LICENSE`: MIT, copyright `2025-2026 Matthias König`.
- `release-notes/0.1.0.md`: first release, features and limitations.
- `CLAUDE.md`: project summary, commands, architecture per module,
  conventions (ty with `error-on-warning`, docstrings, logging not printing,
  examples and models not packaged, small fixtures in `tests/data/`), the `libopencor`
  installation and the roadmap pointer.

## Out of scope for S1

- Any change to the generated CellML (units, events, initial assignments,
  function definitions).
- The CellML to SBML direction (S2).
- The SBML test suite and BioModels checks (S3, S4).
- A logo.
