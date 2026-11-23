# Development

Contributions are welcome. The repository is [matthiaskoenig/sbml2cellml](https://github.com/matthiaskoenig/sbml2cellml); development happens against the `develop` branch via pull requests.

## Branch model

Two branches are permanent:

- **`develop`** is the default branch and the branch everything is integrated
  into. The documentation on
  [matthiaskoenig.github.io/sbml2cellml](https://matthiaskoenig.github.io/sbml2cellml)
  is published from it.
- **`main`** tracks the latest published release. It is fast-forwarded to the
  released commit by the `sync-main` job of the `CI-CD` workflow after the
  package went to pypi, so `main` and the newest version on pypi always agree.
  Nothing is developed on `main` and nothing is merged into it by hand.

Work happens on short lived branches off `develop`, which GitHub deletes after
the merge. Releases are tagged on `develop`, see [Release](#release).

## Pull requests

Neither branch accepts a direct push, every change goes through a pull request
against `develop`. This includes the maintainer, there is no bypass.

A pull request can only be merged once the four required checks are green:

| check   | workflow      | content                                                             |
| ------- | ------------- | --------------------------------------------------------------------|
| `tests` | `ci-cd.yml`   | the test matrix, python 3.14 on linux, macos and windows            |
| `ruff`  | `ruff.yml`    | `ruff check` and `ruff format --check`                              |
| `ty`    | `ty.yml`      | `tox r -e ty`                                                       |
| `docs`  | `docs.yml`    | the zensical build including the api reference and the agent files  |

`tests` aggregates the test matrix into a single job, so the name of the required check stays the same when the matrix changes. The CI runs the standalone interpreters of uv (`UV_PYTHON_PREFERENCE=only-managed`). The linux jobs run on `ubuntu-24.04` and not on `ubuntu-latest`: the wheels of libcellml link `libxml2.so.2` and ubuntu 26.04 ships libxml2 2.15 as `libxml2-16`, which provides `libxml2.so.16` only.

Continuous integration is kept small: every workflow cancels its running build when a newer commit of the same branch or pull request arrives, uv caches the packages and the interpreters between runs, dependabot proposes its updates once a month, and the matrix runs python 3.14, the only supported version.

Further rules of a pull request:

- conversations have to be resolved before the merge
- an approval is dismissed when new commits are pushed
- the history stays linear, i.e., a pull request is merged with squash or
  rebase; merge commits are disabled
- the maintainer is the code owner of the repository (`.github/CODEOWNERS`) and
  is requested for review on every pull request. A pull request of a contributor
  is therefore reviewed and merged by the maintainer, who has the only write
  access. The rulesets themselves do not require an approval: on a personal
  repository a ruleset cannot ask for an approval only from somebody else, and
  requiring one would block the pull requests of the maintainer, who cannot
  approve their own. Once a second person has write access, a ruleset requiring
  an approving review of a code owner can be added

[Auto-merge](https://docs.github.com/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/automatically-merging-a-pull-request)
is enabled for the repository, so a pull request can be queued and is merged as
soon as the checks pass and the required approval is there.

### Repository policies { #repository-policies }

The protection is implemented with
[repository rulesets](https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets).
They are part of the repository in `.github/rulesets/` instead of only living in
the web interface, so a change to a policy is reviewed like any other change:

| ruleset                 | applies to | rules                                                                                                                                       |
| ----------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `develop.json`          | `develop`  | pull request required, the four checks above, resolved conversations, linear history, no force push, no deletion. **No bypass, for anybody.** |
| `main.json`             | `main`     | linear history, no force push, no deletion, no bypass. The fast-forward of the release workflow needs none, only a force push or a merge commit would be rejected |
| `tags.json`             | all tags   | a tag cannot be deleted or moved, so a release tag keeps pointing at what was released                                                       |

Changing a policy means changing the json and applying it:

```bash
.github/rulesets/apply.sh
```

The script is idempotent: it updates the rulesets which exist and creates the
missing ones. It also sets the merge settings of the repository, i.e.,
auto-merge, delete branch on merge, and squash and rebase as the only merge
methods, and it allows `develop` to deploy to the `github-pages` environment:
enabling GitHub Pages creates that environment with a deployment policy for the
default branch of that moment only, which rejects the deployments of the
documentation workflow from `develop`. It needs the
[github cli](https://cli.github.com) authenticated as a user with admin
permission on the repository.

## Setup development environment

Development needs [uv](https://docs.astral.sh/uv/), a [rust toolchain](https://rustup.rs) for the module `sbml2cellml._rust` (the version is pinned by `rust-toolchain.toml`, which rustup reads on the first `cargo` call) and a checkout of the repository:

```bash
git clone https://github.com/matthiaskoenig/sbml2cellml.git
cd sbml2cellml
```

A single sync creates the virtual environment in `.venv`, builds the rust module, installs `sbml2cellml` into it in editable mode and adds the complete tooling:

```bash
uv sync --extra dev
```

The `dev` extra contains everything used below, i.e., pytest, ruff, ty, tox, pre-commit, zensical and bump-my-version, together with the `simulate` extra (libopencor, sbmlsim-core, pandas, matplotlib). The python version is taken from `.python-version` (3.14, the only supported version).

The tools are then run either with `uv run <command>`, which uses the environment without activating it, or from the activated environment:

```bash
source .venv/bin/activate        # Linux and macOS
.venv\Scripts\activate           # Windows
```

The commands in this document are written without the `uv run` prefix; prepend it if the environment is not activated.

The last step installs the git hook:

```bash
uv run pre-commit install          # install the hook, once per checkout
uv run pre-commit run --all-files  # check the current state of the repository
```

From now on every commit is checked with ruff (lint and format) and ty, i.e., the same checks that run in continuous integration. On a commit only the changed files are looked at, `--all-files` checks the whole repository and is what a newly added hook should be tried with.

## Testing

The tests are written with pytest, tox runs them against the supported python versions.

The tox environments are `py3.14` and `ty` (see `envlist` in `tox.ini`); a test environment is run with
```bash
tox r -e py3.14
```
and all environments, in parallel, with
```bash
tox run-parallel
```

The tox environments are created from `uv.lock` by tox-uv (`runner = uv-venv-lock-runner` in `tox.ini`).

This needs the interpreter to be available, which uv installs with `uv python install 3.14`. It is the complete test and is run before a pull request is opened: continuous integration runs `py3.14` on linux, macos and windows, as `uvx --with tox-uv tox -e py3.14 -- --durations=15`, which lists the 15 slowest tests so that a test which becomes slow is seen. The tests run in parallel on every core (pytest-xdist, `addopts = "-n auto"`).

To run the tests directly against the development environment use

```bash
pytest                                                       # the full suite
pytest tests/test_cellml.py                                  # a single module
pytest tests/test_cellml.py::test_read_model                 # a single test
```

The simulation tests and the examples need libopencor and are skipped without it; with `uv sync --extra dev` it is installed.

The roundtrip tests (`tests/test_roundtrip.py`) simulate the SBML side with sbmlsim-core (`tests/simulators.py`) and the CellML side with libopencor; both are installed with `uv sync --extra dev` and the tests are skipped without them.

## Linting and formatting

Linting and formatting use [ruff](https://docs.astral.sh/ruff/):

```bash
ruff check     # lint
ruff format    # format
```

## Type checking

Type checking is performed with [ty](https://docs.astral.sh/ty/):

```bash
tox r -e ty
```
Or directly in the working tree:
```bash
uvx ty check
```

The configuration lives in `[tool.ty]` in `pyproject.toml`. Warnings are treated as errors, so the codebase is kept free of diagnostics. Suppress an unavoidable diagnostic with a rule specific `# ty: ignore[rule-name]` rather than a blanket comment.

## Documentation

The documentation is built with [Zensical](https://zensical.org/), the static site generator of the Material for MkDocs authors. The sources are markdown files in `docs/`, the site is configured in `zensical.toml` in the repository root. Nothing rendered is committed: the site is built by the `documentation` workflow on every push and published to [matthiaskoenig.github.io/sbml2cellml](https://matthiaskoenig.github.io/sbml2cellml) from the `develop` branch. The workflow builds with `--strict`, so a warning such as a broken link fails the `docs` check.

Build the site into `site/`:

```bash
uv run zensical build --clean
```

For writing, the preview rebuilds on save:

```bash
uv run zensical serve
```

The [online converter](index.md#online-converter) of the landing page needs the
WebAssembly module of the crate `crates/wasm`, which is not committed. The
script builds it with cargo and copies it to `docs/converter/`, where the site
build picks it up; the `documentation` workflow runs it before the build:

```bash
uv run python scripts/build_wasm.py
```

Without the module every other part of the page works and the converter says
that it is not available.

The API reference is rendered from the docstrings by [mkdocstrings](https://mkdocstrings.github.io/); a page in `docs/api/` only contains the module directive:

```markdown
# cellml

::: sbml2cellml.cellml
```

Docstrings are therefore the place to document functions and classes, the markdown files provide the narrative around them. Adding a module to the reference means adding such a page and an entry to `nav` in `zensical.toml`.

### Logo and favicon

The logo is `docs/images/sbml2cellml-logo.png` (512 px, transparent outside of its frame). The README and the release notes are also shown on GitHub and PyPI and reference it by its absolute URL on `develop`; `tests/test_package.py` checks that the README and every release notes page start with it.

The favicon is drawn after the logo in `docs/images/favicon/favicon.svg`, which is also the logo in the header of the site. `favicon.ico` (16, 32 and 48 px) and the opaque `apple-touch-icon.png` (180 px, without the frame, which iOS draws itself) are rendered from it. The ICO is the `favicon` of the theme, the SVG and the apple touch icon are linked in `overrides/main.html` (`custom_dir`).

### Files for agents { #files-for-agents }

Agents and language models read markdown, not rendered html. `scripts/llms_txt.py` writes the files of the [llms.txt convention](https://llmstxt.org/) into the built site, i.e., [llms.txt](https://matthiaskoenig.github.io/sbml2cellml/llms.txt) as an annotated index of all pages, [llms-full.txt](https://matthiaskoenig.github.io/sbml2cellml/llms-full.txt) with the complete documentation in a single file, and the markdown of every page next to its html (`/conversion-issues.md` for `/conversion-issues/`). The markdown of the API reference is generated from the docstrings with `inspect`, since the pages themselves only contain the mkdocstrings directive.

```bash
uv run zensical build --clean
uv run python scripts/llms_txt.py
```

The `documentation` workflow runs both steps, so the files are regenerated with every push. `docs/robots.txt` points crawlers at the sitemap and at these files. Zensical will provide agent context files itself at some point, then this script can go.

## Repository setup { #repository-setup }

The one-time setup of the GitHub repository, for the record:

1. `develop` is created from `main` and made the default branch: `gh repo edit matthiaskoenig/sbml2cellml --default-branch develop`
2. the GitHub Pages source is set to GitHub Actions: `gh api -X POST repos/matthiaskoenig/sbml2cellml/pages -f build_type=workflow`
3. the merge settings, the rulesets and the deployment branch of the documentation are applied: `.github/rulesets/apply.sh`
4. the PyPI trusted publisher is registered on [pypi.org](https://pypi.org/manage/account/publishing/) for the project `sbml2cellml`, owner `matthiaskoenig`, repository `sbml2cellml`, workflow `ci-cd.yml`, environment `pypi` (as a pending publisher before the first release)
5. the repository is enabled in the [Zenodo GitHub integration](https://zenodo.org/account/settings/github/), so that a GitHub release is archived with a DOI

## SBML test suite { #sbml-test-suite }

`sbml2cellml.testsuite` runs the [SBML test suite](https://github.com/sbmlteam/sbml-test-suite) through both converters and both simulators, so that every conversion gap is measured against a real corpus instead of a handful of examples. Each runnable case goes through five stages: the original SBML is simulated with sbmlsim-core (`sbmlsim`), converted to CellML (`sbml2cellml`), the CellML is simulated with libopencor (`libopencor`), converted back to SBML (`cellml2sbml`) and the roundtrip SBML is simulated again with sbmlsim-core (`roundtrip`); every simulation is compared with the expected results of the case. A value passes when `|value - expected| <= absolute + relative * |expected|` at every time point, with the absolute and the relative tolerance of the settings of the case (`NNNNN-settings.txt`; the relative tolerance is `1e-4` for most cases, the absolute tolerance between `1e-9` and `0.15`). Cases with an SBML package the converters do not support, without a level 3 version 2 file or of a test type other than `TimeCourse` are skipped.

```bash
uv run sbml2cellml-testsuite run
```

fetches the cases of the pinned commit of the suite into `~/.cache/sbml2cellml` on first use (`SUITE_COMMIT` of `sbml2cellml.testsuite.cases`, a partial `git` clone of `cases/semantic`; `SBML2CELLML_CACHE` overrides the cache root), runs the pipeline and writes `testsuite/results.json`, `docs/testsuite.md`, its bar diagram `docs/images/testsuite.svg` (`testsuite_dark.svg` for dark backgrounds, also shown in `README.md`) and the timings `docs/images/testsuite_timings.svg` (`testsuite_timings_dark.svg`), the wall time of the libopencor simulation of every case against the wall time of its sbmlsim-core simulation. The report lists the median setup and the total, median, 95th percentile and slowest integration of every stage: the time is measured inside the simulator wrapper in the worker process, so it separates what a simulator does with the model before it integrates (reading and converting the file, compiling the model, building the instance) from the integration itself and holds no overhead of the harness. The figure and the comparison of the two simulators use the integration time of the cases whose CellML model reproduces the expected results, where both of them integrate the same dynamics. `--cases 00001,00002` restricts the run to a subset of case ids and `--suite-dir` points at a local copy of the `semantic/` directory instead of downloading. The tolerances of the comparison are not the tolerances of the solver: every sbmlsim-core and libopencor simulation integrates with tight solver tolerances (`1e-9` relative, `1e-12` absolute), so the comparison measures the conversion rather than the default integrator tolerances, an amendment to the original harness design. CVODE gives up on some models with tolerances this tight (`CV_TOO_MUCH_WORK`, `CV_CONV_FAILURE`, `CV_ERR_FAILURE`); only then the simulation is repeated with `1e-8`/`1e-10` and `1e-7`/`1e-9` (`SOLVER_SETTINGS` of `sbml2cellml.testsuite.runner`), and the failure with the tight tolerances is reported when the model integrates with none. Looser tolerances for every simulation are no alternative: with `1e-8`/`1e-10` 4 cases of the test suite and 22 stages of the BioModels check which pass would fail, with `1e-6`/`1e-8` 78 and 123. Both simulators may take 100000 internal steps between two time points; the 500 steps of libopencor ended the integration of 147 curated models of BioModels. Both of them scale the absolute tolerance with the smallest initial value of a state of their own model when it is below one, so that the tolerance stays below the states of a model whose values are small: the states of the SBML model are amounts, the states of the CellML model the variables of its components.

`testsuite/results.json`, `docs/testsuite.md` and the figures `docs/images/testsuite*.svg` are generated and committed. `tests/test_testsuite_full.py` (enabled with `SBML2CELLML_TESTSUITE=1`, run with `tox r -e testsuite` and in the linux CI job of python 3.14; the pipeline runs with python 3.14 only, the unit tests with every supported python) reruns the full suite and fails if any case regresses against the committed results or if the rendered report no longer matches `docs/testsuite.md`. The failure reasons of the report list every failing case with its complete error: the message of a stage in `testsuite/results.json` is the full text of the exception with all its lines, only absolute paths are reduced to the file name and the long decimals of a CVODE diagnostic rounded, so that the committed files do not depend on the machine. To accept an improvement, rerun `uv run sbml2cellml-testsuite run` and commit the updated `testsuite/results.json`, `docs/testsuite.md` and figures together in the same pull request. `uv run sbml2cellml-testsuite report` rerenders the report and the figures from the committed results, e.g., after a change of the report itself.

The harness runs each simulator in a worker process of its own (`sbml2cellml.testsuite.worker`) for the whole run, instead of starting a subprocess per call: a call has a timeout and a simulator which hangs or crashes the process costs one case instead of the run.

## BioModels { #biomodels }

`sbml2cellml.biomodels` runs the manually curated SBML models of [BioModels](https://www.biomodels.org) (about 1075) through the pipeline of the SBML test suite, reusing `sbml2cellml.testsuite`, so the converters are measured against published models in addition to the test cases. These models have no expected results: the `sbmlsim` stage simulates the original SBML with sbmlsim-core over a generic timecourse (0 to 100 time units, 100 steps), and its result is what the `libopencor` and `roundtrip` simulations are compared with, using the comparison of the test suite with a relative tolerance of `1e-3` and an absolute tolerance of `1e-6` (`RELATIVE` and `ABSOLUTE` of `sbml2cellml.biomodels.cases`); the solver settings are the ones of the test suite (`1e-9`/`1e-12`, relaxed only when CVODE fails). An `sbmlsim` failure means sbmlsim-core cannot simulate the model, it says nothing about the converters; models with an SBML package or without a variable (no species and no target of a rate rule or assignment rule) are skipped.

```bash
uv run sbml2cellml-biomodels run
```

downloads every model into `~/.cache/sbml2cellml/biomodels` on first use (cached for later runs), runs the pipeline, prints the regressions and improvements against the committed results and writes `biomodels/results.json`, the page [BioModels](biomodels.md) (`docs/biomodels.md`) and its bar diagram `docs/images/biomodels.svg` (`biomodels_dark.svg` for dark backgrounds, also shown in `README.md`). `--ids BIOMD0000000001,BIOMD0000000012` and `--count N` restrict the run to a subset or the first N ids of the selection, for a quick check; give such a run its own `--results` and `--report`. `uv run sbml2cellml-biomodels report` rerenders the report and the figures from the results file.

The check is run locally and not in continuous integration: it takes about 20 minutes and depends on the BioModels web service. `tox r -e biomodels` runs it in the locked environment with python 3.14, the only python the pipeline runs with; arguments follow `--`, e.g., `tox r -e biomodels -- --count 10 --results /tmp/results.json --report /tmp/report.md`. The generated files are committed; rerun the check after changes of the converters, review the regressions and commit the regenerated files with the change.

`uv run sbml2cellml-biomodels update` refreshes the committed selection `biomodels/models.json` (the date, the search query and the sorted ids) from the current BioModels search; it is run occasionally, not with every check.

## Physiome { #physiome }

`sbml2cellml.physiome` runs a curated selection of the CellML models of the [Physiome Model Repository](https://models.physiomeproject.org) through the same pipeline, in the order of a CellML model (`CELLML_STAGES` of `sbml2cellml.testsuite.results`): libopencor simulates the published model (`libopencor`), `cellml2sbml` converts it to SBML (`cellml2sbml`), sbmlsim-core simulates that model (`sbmlsim`), `sbml2cellml` converts it back to CellML (`sbml2cellml`) and libopencor simulates the roundtrip (`roundtrip`). The models are real world models of many components, most of them CellML 1.0 and 1.1 documents which libcellml reads in its permissive mode, so the check measures the converters on models which were not written for them.

The repository has no expected results, so the libopencor simulation of the published model over a generic timecourse (0 to 100 time units, 1000 steps: the models are stiff and many of them switch their right-hand side hard, where the two solvers step over the switch differently on a coarse output grid, so the comparison would measure the grid instead of the conversion) is what the `sbmlsim` and `roundtrip` simulations are compared with, with a relative tolerance of `1e-3` and an absolute tolerance of `1e-6` (`RELATIVE` and `ABSOLUTE` of `sbml2cellml.physiome.cases`) and the solver settings of the test suite (`1e-9`/`1e-12`, relaxed only when CVODE fails). A `libopencor` failure means libopencor cannot simulate the published model, it says nothing about the converters. The CellML simulation names a variable by its name, or by `component/variable` when more than one variable of the model has that name, while the SBML simulation names it by the id of its equivalence set: the case carries the map between them (`PhysiomeCase.columns`), built from the ids of `sbml2cellml.variables.VariableIds`, so every comparison runs on the same columns. A model which libcellml cannot read or analyse is skipped with its error.

```bash
uv run sbml2cellml-physiome run
```

clones the workspace of every model at the commit of its exposure into `~/.cache/sbml2cellml/physiome` on first use (cached for later runs, so a model which imports other files of its workspace has them all on disk), runs the pipeline, prints the regressions and improvements against the committed results and writes `physiome/results.json`, the page [Physiome Model Repository](physiome.md) (`docs/physiome.md`), its bar diagram `docs/images/physiome.svg` (`physiome_dark.svg` for dark backgrounds) and the timings `docs/images/physiome_timings.svg`. `--ids 5f,2c` and `--count N` restrict the run to single exposures or the first N models of the selection; give such a run its own `--results` and `--report`. `uv run sbml2cellml-physiome report` rerenders the report and the figures from the results file.

The check is run locally and not in continuous integration: it clones about a hundred git repositories and depends on the repository web service. `tox r -e physiome` runs it in the locked environment with python 3.14; arguments follow `--`, e.g., `tox r -e physiome -- --count 5 --results /tmp/results.json --report /tmp/report.md`. The generated files are committed; rerun the check after changes of the converters, review the regressions and commit the regenerated files with the change.

`uv run sbml2cellml-physiome update` refreshes the committed selection `physiome/models.json` from the current exposures of the repository: it reads the listing of every exposure, keeps the ones which publish a CellML file (the exposure of a workspace which was published again counts once) and writes the first 100 of them by exposure id, each with the workspace, the commit and the file, so that a run of the check is reproducible. It is run occasionally, not with every check.

## Models and benchmarks { #overview }

`sbml2cellml.overview` renders the two pages across the checks from their committed results, it runs no simulation: [Models](models.md) (`docs/models.md`), which models of the three checks the converters handle, and [Benchmarks](benchmarks.md) (`docs/benchmarks.md`), the wall time of the two simulators over the models both of them run.

```bash
uv run sbml2cellml-overview
```

reads `testsuite/results.json`, `biomodels/results.json` and `physiome/results.json` (a missing file is logged and left out) and writes the two pages and four figures, each of them for light and for dark backgrounds: the wall time of libopencor against the wall time of sbmlsim-core per model for the setup of the simulator (`docs/images/benchmarks_setup.svg`), for the integration (`benchmarks.svg`, also shown in `README.md`) and for the two together (`benchmarks_total.svg`), and the median of all three phases per check (`benchmarks_medians.svg`). The setup is everything a simulator does with a model before it integrates, reading and converting the file, generating and compiling the code of the model and building the instance, and it takes longer than the integration for the median model of every check; the total is what a simulator costs for a model which is simulated once. The model page gives every check the same five roles, whatever the order of its stages is: the source model is simulated, converted to the other language, the converted model reproduces the simulation of the source model, it is converted back and the roundtrip model reproduces it again; a model works when every one of these stages passes. Every model of BioModels and of the Physiome Model Repository is listed with a link to its page in the repository, the status of its stages and whether it works, and the models which do not run at all with the reason.

The two pages are generated and committed, and they are rendered from the results files alone: `tests/test_overview.py` renders both of them from the committed `results.json` files and fails when they differ from `docs/benchmarks.md` and `docs/models.md`, so a check which ran without the overview being rerun is caught by the unit tests. Rerun the command after any check wrote new results, and commit the pages and the figures with them.

## Rust workspace { #rust }

[Issue #68](https://github.com/matthiaskoenig/sbml2cellml/issues/68) moves the reader and the converter to rust, so that a conversion is fast and runs in a browser next to [sbmlsim-core](https://matthiaskoenig.github.io/sbmlsim-core/), whose compiler takes SBML text and whose engine is WebAssembly: a CellML model converted to SBML in the browser is simulated there without a server. The reader and the conversion of CellML to SBML are there, and the python package converts with them: `sbml2cellml._rust` is the module of `crates/python`, which maturin builds into the wheel, and `convert_cellml2sbml` takes the engine to use (`auto` by default, see [Conversion](conversion.md#engines)). libcellml stays for what the rust converter does not do - the metadata of the elements, the hierarchical conversion and the imports of a document, which it flattens before the rust converter reads it - and libsbml reads the SBML text the conversion writes, validates it and writes the file.

`crates/cellml` reads a document of CellML 2.0, 1.1 or 1.0 and gives the model with its unit definitions, its components with their variables and their mathematics, its connections, its encapsulation and its imports. A document of CellML 1.0 is read as it is written, with its `public_interface` and its groups of the relationship `encapsulation`, and gives the same model as the document of CellML 2.0 of the same system, so what reads the model afterwards does not know the version; the built in units CellML 2.0 renamed (`meter`, `liter`) are read as `metre` and `litre` unless the model defines units of that name, as libcellml reads them. The crate validates nothing and resolves nothing: an import keeps its `href`, there is no file system and no network access, and the crate builds for `wasm32-unknown-unknown`. `equivalence_sets` gives the variables a chain of connections makes one quantity, which the conversion to SBML needs. The crate writes a document as well: `Model::to_xml` writes the model as CellML 2.0, whatever version it was read from, so a model which is read and written again is the same model and the conversion of an SBML model has a writer. A document of CellML 1.0 or 1.1 moves to the later version as it is written: the two interface directions of a variable become its `interface`, a unit definition inside a component becomes one of the model, `base_units="yes"` becomes a `<units>` element without a `<unit>` child, and the `offset` of a unit is dropped, which CellML 2.0 has none of. A number carries `dimensionless` when the document gives it no units, a number which needs an exponent is written in the `e-notation` of MathML (`<cn type="e-notation">1.5<sep/>-7</cn>`; the text `1.5e-7` is no number of CellML), and an infinity and a value which is no number are written as the elements of MathML, which a `<cn>` cannot hold. The metadata of a document (`cmeta:id`, RDF) is not written, as CellML 2.0 has no place for it. `crates/cli` is the command `cellml-info`, which prints what the reader reads of a document as JSON.

`crates/sbml` holds the SBML level 3 version 2 document the conversion writes - unit definitions, parameters, initial assignments and rules, since a CellML model has no reactions - and its XML, which it writes itself: there is no libsbml in the rust workspace. `crates/convert` is the conversion. It reads the equations of the model where the python converter asks the analyser of libcellml: every equivalence set of variables becomes one parameter, named after the variable the equation of the quantity is written next to, else one with an initial value, else the first of the set, which is the variable the analyser of libcellml takes, so that both converters give a quantity the same id; a derivative on one side of an equation makes the other side the rate of a state, an equation with a single variable on one side determines that variable, an equation which determines no single variable becomes an algebraic rule, and a variable which an equation computes from constants only becomes an initial assignment. The custom units become unit definitions of the base units of SBML, and the mathematics keeps its operators, with the variable of integration written as the time of SBML and a derivative inside an expression as its `rateOf`. An equation whose variable its own right hand side uses, and a pair of equations which compute each other, are implicit and become algebraic rules, which is what SBML needs: an assignment rule must not depend on itself. An operator which SBML does not have, units which the model does not define, an imported component or imported units are refused, so that nothing is written which a simulator reads as something else. `crates/cli` holds the three commands: `cellml-info`, which prints what the reader reads of a document as JSON, `cellml-convert`, which writes the SBML of a document, and `cellml-write`, which writes the document again as CellML 2.0.

`crates/tocellml` is the other direction, the conversion of an SBML model to CellML, which [issue #82](https://github.com/matthiaskoenig/sbml2cellml/issues/82) builds in stages. The SBML document is read by `sbmlsim-sbml` of [sbmlsim-core](https://github.com/matthiaskoenig/sbmlsim-core), which reads every level and version of SBML core into the model of level 3, so the conversion never sees a level and no document has to be converted first. `units.rs` is the units of the model: every unit definition becomes CellML units of the same name, where the scale and a multiplier which is a power of ten become the prefix (`(1000 gram)^-1` is `kilo gram^-1`) and any other multiplier its power (`(60 second)^-1` is `1/60 second^-1`), the unit kind `item` becomes new base units and `avogadro` the dimensionless units of its value. The elements which become variables get their units from it as well: a compartment, a parameter and a species with only substance units reference their units, a species in concentration is the substance per the size of its compartment, and the rate of a reaction the extent per time; for such a quotient the unit definition of the model which is identical to it is taken, else units `numerator_per_denominator` are added. The units which level 1 and 2 have built in are the kinds they stand for (`volume` is `litre`), and a model which has nothing but them states no units at all, so its variables are all `dimensionless`, as in the python converter.

`math.rs` writes a formula of SBML as the mathematics of CellML. Both are content MathML, so an operator keeps its element, and what the conversion changes is what CellML states differently or does not have: every number carries the CellML name of its units and `dimensionless` when the formula gives it none, an infinity and a NaN become the elements of MathML, the time symbol becomes the variable of integration and the avogadro symbol the number SBML defines for it. `quotient(a, b)` becomes `floor(a / b)` and `implies(a, b)` becomes `not a or b`, the two operators CellML does not have; a relation of more than two arguments becomes the conjunction of its pairs (`a < b < c` is `and(a < b, b < c)`) and an n-ary operator of less than two arguments its value (`plus()` is 0, `times(a)` is `a`). CellML has no functions, so `Functions` expands every call of a function definition, the arguments of a call and the body of a definition included; a definition which is part of a cycle of calls, a call of the wrong arity, a call of a function the model does not define and a definition without a lambda are refused, as are `delay` and a `rateOf` which the conversion did not replace.

`model.rs` builds the CellML model, the structure which `sbml2cellml.py` writes in python: one component `sbml` holds one variable per compartment, parameter and species, the local parameters of a kinetic law as `<reaction>_<parameter>`, one variable per reaction with its rate and one per species reference which has an id with its stoichiometry. An assignment rule becomes an equation, a rate rule and the reaction terms of a species a differential equation, where the terms of a species in concentration are divided by its compartment, and a species in a compartment which changes in time gets its `<species>_amount` with the terms and the equation `species = amount / compartment`, since SBML keeps the amount when the size changes. `time` is the variable of integration, a model which uses time without a differential equation gets the state `time_state` with `d time_state / d time = 1`, and an algebraic model gets no `time` at all, as CellML knows the variable of integration from a differential equation only. `Formulas` holds the formulas of the model and expands `rateOf` to the right hand side of the equation of its variable, and the variables get their units when the unit annotation of the model is complete, else all of them are `dimensionless`, as in the python converter. The stages of [issue #82](https://github.com/matthiaskoenig/sbml2cellml/issues/82) which follow convert what the conversion refuses so far: an algebraic rule, an event, and a model which needs a package.

`eval.rs` evaluates the formulas of the model at the start, which CellML needs as numbers, since it has no initial assignment. The value of a quantity is the value of its initial assignment, else of its assignment rule, else the value the model states, where the value of a reaction is its rate and the value of a species the quantity a formula of SBML means, its concentration unless it has only substance units, converted with the size of its compartment when the model states the other quantity. The evaluation is the one of the simulator of SBML: a value which is no boolean is true when it is not zero, `plus()` is 0 and `times()` is 1, a relation of more than two arguments holds when it holds for every pair, and `quotient` and `rem` are the integer division of the OpenMath dictionary which the MathML of SBML follows, which truncates towards zero and gives the remainder the sign of the dividend. libsbml, which the python converter has evaluate, takes a number as a condition only when it is 1 and divides with a floor.

The conversion evaluates every initial assignment to the value of its quantity and gives every compartment its size at the start, which converts the initial values of its species; an initial assignment which cannot be evaluated, a delay or a value which needs itself, is not converted, with a warning, as in the python converter, and a value which is infinite or NaN becomes an equation when the variable is no state.

`crates/python` is the module `sbml2cellml._rust`, built with [pyo3](https://pyo3.rs) and the stable ABI of python 3.14 (`abi3-py314`), which gives the package the conversion in the process; `sbml2cellml.rust` wraps it, `src/sbml2cellml/_rust.pyi` is its signature for the type checker. maturin is the build backend of the package (`[tool.maturin]` of `pyproject.toml`), so `uv sync` and `uv build` compile the crates and put the module next to the python code. The crate is no default member of the workspace: a test binary of it would have to link libpython, so `cargo test` leaves it out and the `rust` workflow lints it on its own.

```bash
cargo test                  # the rust tests, over the CellML fixtures of the repository
cargo clippy --all-targets  # the lints, denied in the workspace
cargo clippy -p sbml2cellml-python   # the lints of the python module
cargo fmt --check           # the formatting
cargo build --release       # the cellml-info, cellml-convert, cellml-write and sbml-convert commands in target/release
cargo build --target wasm32-unknown-unknown -p sbml2cellml-cellml -p sbml2cellml-convert

target/release/cellml-convert model.cellml            # writes model.xml
target/release/cellml-convert -o - model.cellml       # to the standard output
target/release/sbml-convert model.xml                 # writes model.cellml

uv sync --extra dev         # builds sbml2cellml._rust as well
uv build                    # the wheel with the module and the sdist
```

The `rust` workflow runs these in continuous integration. `scripts/cellml_parity.py` measures the reader against libcellml over the models of the Physiome selection and the CellML files of the repository, which is run locally like the checks of BioModels and of the Physiome repository:

```bash
cargo build --release
uv run python scripts/cellml_parity.py        # the reader against libcellml
uv run python scripts/cellml_write_parity.py  # the writer against libcellml
uv run python scripts/cellml2sbml_parity.py   # the converter against the python converter
uv run python scripts/sbml2cellml_parity.py   # the forward converter against the python converter
uv run python scripts/cellml_parity.py --count 10 -v
```

Of the 101 documents of the corpus, 96 are read identically (the version, the components with their variables, the units of a variable, its initial value and what it exposes, the encapsulation and the equivalence sets), 4 are read by the rust reader alone, since libcellml refuses them (a non whitespace text in a component, a namespace URI which is not absolute), and 1 differs in what a variable exposes: the permissive parser of libcellml reads the interface of a
variable of CellML 1.0 from the presence of the attributes `public_interface` and `private_interface`
and not from their values, so a variable which declares `private_interface="none"` is given a private
interface ([cellml/libcellml#1528](https://github.com/cellml/libcellml/issues/1528)); the reader takes
the value, as the specification defines it.

`scripts/cellml_write_parity.py` measures the writer over the same corpus: every document is written again as CellML 2.0, the validator of libcellml validates the result, and what libcellml reads of the written document is compared with what it reads of the original (the components with their variables, the encapsulation and the equivalence sets; not the version, which the writer always writes as 2.0). Of the 102 documents, 97 are written identically, 4 are left out, since libcellml does not read the original either, and 1 differs in what a variable exposes, the same reading of `private_interface="none"` as above. No written document holds an error of the validator which the original does not hold as well.

`scripts/cellml2sbml_parity.py` measures the conversion against the python converter over the same corpus: it converts every document with both, validates the SBML of the rust converter with libsbml and compares the parameters with their value, their units and whether they are constant, the rules by kind and target, the initial assignments and the formula of every rule, which `libsbml.formulaToL3String` writes for both sides.

Of the 102 documents of the corpus, the rust converter converts 92, and libsbml validates every one of those without an error. 68 documents are converted by both: 38 give the same SBML model and 30 differ in the notation of a formula or in the nesting of its sums and products only, nothing in what an equation computes. The notation differs where the rust converter writes the mathematics as the CellML model has it, a square root without the degree two and the exponent of a number as the model writes it, while the python converter writes the tree of the analyser of libcellml; the nesting differs because the rust converter keeps the `a + b + c` of the model and the analyser of libcellml gives it as the binary tree `a + (b + c)`, which is the same sum in another association. The ids are the same for every document, since both converters name a quantity after the variable the equation of the quantity is written next to. 24 documents are converted by the rust converter alone, since the analyser of libcellml refuses the model; 1 by the python converter alone, the fixture with an import, which the rust converter does not resolve yet; 9 by neither.

The resets of a model become the events of SBML, as they do in the python converter: the trigger is the equality of the test variable and the test value, or the condition of a test variable which is `piecewise(1, condition, 0)`, which is how the conversion of an SBML event writes it, and the priority is the negated order.

What the rust converter does not do yet: resolve the imports of a document, write the metadata of the CellML elements and write a hierarchical model. The python engine converts such a model, and the imports are flattened with libcellml before the rust converter reads the document.

`scripts/convert_benchmark.py` measures the two engines over the same corpus, three runs per model and engine, the fastest of the three:

```bash
uv run python scripts/convert_benchmark.py      # writes docs/images/convert_benchmark*.svg
uv run python scripts/convert_benchmark.py --count 10 --repeats 5
```

Of the 102 documents, 68 are converted by both engines. The python engine takes 129 ms for the median model and 16.9 s for all of them, the rust engine 2.3 ms and 0.37 s, and the rust conversion alone, without the libsbml document the python API returns, 0.4 ms and 0.07 s. The rust engine is 48 times faster for the median model and between 13 and 193 times faster over the corpus; the conversion alone is 288 times faster. The largest model of the selection, `Schoeberl_EichlerJonsson_Gilles_Muller_2002` with 228 components, takes 2.3 s with the python engine and 12 ms with the rust engine.

## Release

A release is made from `develop`. Since `develop` only accepts pull requests,
the release is prepared on a branch and tagged once that pull request is merged:

1. branch off `develop`: `git switch -c release/x.y.z develop`
2. write the release notes for the version in `docs/release-notes/x.y.z.md`, with the logo below the heading as in the earlier notes, and add the page to the `Release notes` section of `nav` in `zensical.toml` and to the overview `docs/release-notes/index.md`, newest first. The notes are part of the [documentation](release-notes/index.md) and the body of the GitHub release; `tests/test_package.py` fails when the current version has no notes or a page is missing in the navigation or the overview
3. make sure everything passes: `tox run-parallel`, `ruff check`, `tox r -e ty`
4. check the version bump: `uvx bump-my-version bump [major|minor|patch] --dry-run -vv`
5. bump the version: `uvx bump-my-version bump [major|minor|patch]`, which updates `pyproject.toml` (the version of the wheel, which maturin reads), `src/sbml2cellml/__init__.py` and `CITATION.cff` and commits. It does not create the tag; a squash or rebase merge would rewrite the commit and leave the tag behind on a commit which is not part of `develop`
6. push the branch, open the pull request against `develop` and merge it once the checks are green
7. tag the merged commit on `develop` and push the tag:

    ```bash
    git switch develop
    git pull
    git tag x.y.z
    git push origin x.y.z
    ```

    This starts the `CI-CD` workflow, which runs the test matrix, builds the
    wheels of linux (x86_64, aarch64), macOS (universal2) and windows with
    [maturin](https://www.maturin.rs) and the source distribution, publishes
    them to [pypi](https://pypi.org/project/sbml2cellml/), creates the GitHub
    release from `docs/release-notes/x.y.z.md` and fast-forwards `main` to the
    tagged commit.
    Check the version before pushing, a tag cannot be moved or deleted
    afterwards.

8. test the installation from pypi in a fresh environment:

    ```bash
    uv venv --python 3.14
    uv pip install sbml2cellml
    ```

9. once Zenodo has archived the release, update the citation information, i.e., `date-released` in `CITATION.cff` and the version, date and version DOI of the release in the citation of `README.md` and `docs/index.md`. `bump-my-version` only updates the version, not the date and the DOI, which are only known after the release. These changes go in through a pull request like everything else

`scripts/sbml2cellml_parity.py` measures the conversion of an SBML model against the python converter, over the models of `examples/models`, the cases of the SBML test suite and the models of the BioModels cache (`--corpus models|suite|biomodels|all`). It converts every model with both converters, validates the CellML of the rust converter with libcellml and compares the variables with their units and their initial value and the equations by the variable they determine, where a formula is written as a canonical expression. The units of a variable and of a number are compared by what they are and not by the name they carry, since both converters take a unit definition of the SBML model for the units of a concentration and pick a different one when the model states the same units in two ways; an initial value is compared to twelve significant digits, since libcellml writes fifteen of them and the rust writer every digit of the double.

Of the 1692 cases of the SBML test suite, 998 are converted by both converters and 997 of them give the same CellML model. 569 are refused by the rust converter, which are the stages of issue #82 that follow, and 125 need the `comp` package, whose submodels the python converter flattens with libsbml first. Of the 1075 models of the BioModels cache, 896 are converted by both and 895 of them give the same model.

The two models which differ differ because the rust converter is right and the python converter follows libsbml. Case `01282` of the test suite has a number as the condition of a `piecewise`, which libsbml takes as true only when it is 1, where every simulator and the rust converter take a value which is not zero as true; the expected result of the case is the value of the rust converter. `BIOMD0000000040` of BioModels holds the `<stoichiometryMath>` of a species reference, which the rust path converts, since the reader of SBML writes it as an assignment rule of the id it gives the reference, while the python converter takes the stoichiometry as it stands ([issue #86](https://github.com/matthiaskoenig/sbml2cellml/issues/86)).
