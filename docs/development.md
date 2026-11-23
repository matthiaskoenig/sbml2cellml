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

Development needs [uv](https://docs.astral.sh/uv/) and a checkout of the repository:

```bash
git clone https://github.com/matthiaskoenig/sbml2cellml.git
cd sbml2cellml
```

A single sync creates the virtual environment in `.venv`, installs `sbml2cellml` into it in editable mode and adds the complete tooling:

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

## Release

A release is made from `develop`. Since `develop` only accepts pull requests,
the release is prepared on a branch and tagged once that pull request is merged:

1. branch off `develop`: `git switch -c release/x.y.z develop`
2. write the release notes for the version in `docs/release-notes/x.y.z.md`, with the logo below the heading as in the earlier notes, and add the page to the `Release notes` section of `nav` in `zensical.toml` and to the overview `docs/release-notes/index.md`, newest first. The notes are part of the [documentation](release-notes/index.md) and the body of the GitHub release; `tests/test_package.py` fails when the current version has no notes or a page is missing in the navigation or the overview
3. make sure everything passes: `tox run-parallel`, `ruff check`, `tox r -e ty`
4. check the version bump: `uvx bump-my-version bump [major|minor|patch] --dry-run -vv`
5. bump the version: `uvx bump-my-version bump [major|minor|patch]`, which updates `src/sbml2cellml/__init__.py` and `CITATION.cff` and commits. It does not create the tag; a squash or rebase merge would rewrite the commit and leave the tag behind on a commit which is not part of `develop`
6. push the branch, open the pull request against `develop` and merge it once the checks are green
7. tag the merged commit on `develop` and push the tag:

    ```bash
    git switch develop
    git pull
    git tag x.y.z
    git push origin x.y.z
    ```

    This starts the `CI-CD` workflow, which runs the test matrix, publishes to
    [pypi](https://pypi.org/project/sbml2cellml/), creates the GitHub release
    from `docs/release-notes/x.y.z.md` and fast-forwards `main` to the tagged commit.
    Check the version before pushing, a tag cannot be moved or deleted
    afterwards.

8. test the installation from pypi in a fresh environment:

    ```bash
    uv venv --python 3.14
    uv pip install sbml2cellml
    ```

9. once Zenodo has archived the release, update the citation information, i.e., `date-released` in `CITATION.cff` and the version, date and version DOI of the release in the citation of `README.md` and `docs/index.md`. `bump-my-version` only updates the version, not the date and the DOI, which are only known after the release. These changes go in through a pull request like everything else
