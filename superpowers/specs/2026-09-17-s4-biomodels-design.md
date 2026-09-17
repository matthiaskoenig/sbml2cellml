# S4: BioModels release check

Date: 2026-09-17
Status: approved design, implementation pending

## Context

S3 measures the converters against the SBML test suite (expected results
exist per case). S4 runs the same pipeline over the manually curated models
of BioModels, real-world models without expected results: the roadrunner
simulation of the original model over a generic timecourse is the reference
the CellML simulation and the roundtrip are compared with. The check runs
before a release (manually or through a `workflow_dispatch` workflow), its
results are committed and rendered on the site.

## Decisions

| Question | Decision |
|----------|----------|
| What is checked | Conversion plus self-consistency: `sbml2cellml`, `cellml2sbml` with validation, and the `libopencor` and `roundtrip` simulations compared against the roadrunner `reference` over a generic timecourse. |
| When | Release gate, not per pull request: `sbml2cellml-biomodels run` locally or `biomodels.yml` (`workflow_dispatch`) which opens a pull request with the regenerated files. |
| Model set | All manually curated SBML models (about 1075), ids snapshotted in the committed `biomodels/models.json`; `sbml2cellml-biomodels update` refreshes the snapshot. Models with SBML packages are skipped with the reason. |
| Reuse | `sbml2cellml.testsuite` runner, workers, comparison, results and report, generalized for cases without expected results and for a title, intro and model name. |

## Section 1: generalization of `sbml2cellml.testsuite`

- `cases.Case.expected: pd.DataFrame | None` and `cases.Case.name: str = ""`.
- `runner.run_case`: when `case.expected is None`, the `reference` stage is `pass` when the roadrunner simulation runs and its frame (brackets stripped) becomes the expected results for `libopencor` and `roundtrip`; when it fails, `libopencor` and `roundtrip` are `skip` with `reference failed` (the conversions still run). `max_excess` of `reference` is `None` in that mode.
- `results.CaseResult.name: str = ""` (`from_json` tolerates its absence); `run_case` copies `case.name`. `SuiteResult.suite` is any string (`"3.5.0"` for the test suite, `"biomodels"` here).
- `report.render_report(result, title="SBML test suite", intro=TESTSUITE_INTRO, command="sbml2cellml-testsuite", names=False)`: the header names the command, the page the title, the intro text is a parameter, the cases table gets a `name` column when `names` is set. `testsuite.cli` passes the defaults; the committed `testsuite/results.json` is rewritten in the new format (`name` field) without a rerun.

## Section 2: `sbml2cellml.biomodels`

- `models.py`: `BIOMODELS_URL = "https://www.biomodels.org"`, `SEARCH_QUERY = 'curationstatus:"Manually curated" AND modelformat:"SBML"'`, `PAGE_SIZE = 100`; `query_curated_ids() -> list[str]` (paged `/search?format=json`, sorted ids); `ModelInfo(id, name, publication_id, format_version, main_file)` from `/{id}?format=json` (`name`, `publicationId`, `format.version`, first entry of `files.main`); `model_info(model_id, cache) -> ModelInfo` cached as `<cache>/biomodels/<id>/info.json`; `download_model(model_id, cache) -> Path` (`/model/download/{id}?filename={main_file}` into `<cache>/biomodels/<id>/<main_file>`, cached); `Selection(date, models)`, `load_selection(path)`, `write_selection(path, ids)` for `biomodels/models.json` (`{"date": "YYYY-MM-DD", "query": SEARCH_QUERY, "models": [...]}`); `packages(sbml_path) -> tuple[str, ...]` from the `xmlns` declarations of the root element (`http://www.sbml.org/sbml/level3/version1/<pkg>/version<n>`); `BioModelsError`. Downloads go through `requests` with a 60 s timeout; a failed download or info request is a skipped model with reason `download failed: <Type>`.
- `cases.py`: `DURATION = 100.0`, `STEPS = 100`, `ABSOLUTE = 1e-6`, `RELATIVE = 1e-3`; `constructs(model) -> tuple[str, ...]` (`Events`, `FunctionDefinitions`, `AlgebraicRules`, `RateRules`, `AssignmentRules`, `InitialAssignments`, `Constraints`, `Delay` when a `csymbol` delay occurs in the file text, `Reactions`, plus `<pkg>:package` per package); `biomodel_case(info, sbml_path, packages) -> Case` with settings start 0, duration 100, steps 100, `variables` = species ids (empty variables make the case skipped with `no species`), `amount` = species with `hasOnlySubstanceUnits`, `concentration` = the others, `expected = None`, `test_tags = ()`, `component_tags = constructs`, `test_type = "TimeCourse"`, `name = info.name`.
- `runner.py`: `run_biomodels(ids, cache=None, work_dir, timeout=60.0, progress=None) -> SuiteResult` (`suite = "biomodels"`): info and download per id (skipped on failure), `packages` (skipped `package <pkg>` via `skip_reason`), `run_suite`.
- `cli.py`: `sbml2cellml-biomodels run [--models biomodels/models.json] [--ids ID,ID] [--count N] [--work-dir biomodels/work] [--results biomodels/results.json] [--report docs/biomodels.md] [--timeout 60] [-v]`, `update [--models biomodels/models.json] [--count N]`, `report [--results] [--output]`. Script `sbml2cellml-biomodels = "sbml2cellml.biomodels.cli:main"`. The `testsuite` extra covers the dependencies.

## Section 3: workflow, tests, docs

- `.github/workflows/biomodels.yml`: `workflow_dispatch`; ubuntu; python dev files; `uv sync --extra dev`; `actions/cache` of `~/.cache/sbml2cellml/biomodels` keyed by `hashFiles('biomodels/models.json')`; `uv run sbml2cellml-biomodels run`; `peter-evans/create-pull-request@v8` (branch `biomodels-results`, base `develop`, title "Update the BioModels results", body with the summary lines) with `permissions: contents: write, pull-requests: write`; `timeout-minutes: 120`.
- Tests: `tests/test_biomodels_models.py` (search paging, model info, download and caching, selection file, packages; HTTP mocked through `requests.Session`/`requests.get` monkeypatching), `tests/test_biomodels_cases.py` (`constructs` and the settings on the glimepiride liver model and on `tests/sbml_models.py` `simple_model`), `tests/test_biomodels_runner.py` (`run_biomodels` with `download_model`/`model_info` monkeypatched to local files: the five stages present, `reference` pass, `expected` derived; a package model skipped; a download failure skipped), `tests/test_testsuite_runner.py` extended for `expected is None` (a fixture case with `expected=None` passes all five stages), `tests/test_biomodels_results.py` (the committed `biomodels/results.json` loads and every case has the five stages, skipped when absent).
- Initial run locally: `sbml2cellml-biomodels update` then `run`; commit `biomodels/models.json`, `biomodels/results.json`, `docs/biomodels.md`.
- Docs: `docs/biomodels.md` generated (title "BioModels", intro naming the curated set, the generic timecourse and tolerances, that `reference` failures mean roadrunner cannot simulate the model); nav "BioModels" after "SBML test suite"; `docs/development.md` sections "BioModels check" (run, update, the workflow, the release step: run before a release, review the regressions in the PR, merge before tagging); `docs/api/biomodels.*.md`; `CLAUDE.md`, `README.md`, `release-notes/0.1.0.md`, `docs/roadmap.md` item 3 done.
- Branch `s4-biomodels`, stacked on `s3-testsuite` (PR #4 open); PR into `develop` after #4 merges (rebase first).

## Out of scope

- SED-ML of the BioModels archives (the generic timecourse is used instead).
- Non-SBML curated models, models with SBML packages.
- Fixing converter gaps (S5).
