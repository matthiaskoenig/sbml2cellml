# S4: BioModels release check - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run every manually curated SBML model of BioModels through the S3 pipeline with the roadrunner simulation as reference, commit the results and the report page, and provide the command and workflow for the release check.

**Architecture:** `sbml2cellml.testsuite` is generalized (cases without expected results, model names, parametrized report), `sbml2cellml.biomodels` adds the BioModels access (`models.py`), the case construction (`cases.py`), the runner and the command; a `workflow_dispatch` workflow regenerates the files and opens a pull request.

**Tech Stack:** python 3.13, requests, libsbml, the S3 harness (roadrunner and libopencor in worker processes), pytest.

**Spec:** `superpowers/specs/2026-09-17-s4-biomodels-design.md`

## Global Constraints

- roadrunner and libopencor only inside `SimulatorWorker` processes; never in the main process or in pytest.
- Library code logs, never prints (the CLI prints). Full annotations and google docstrings (tests exempt from `D`). ty `error-on-warning = true`, rule-specific ignores only where ty reports. Pristine test output.
- Tests never touch the network: `requests` is monkeypatched. The implementer may probe the live API by hand to confirm the endpoints; the spikes showed `https://www.biomodels.org/search?query=curationstatus%3A%22Manually%20curated%22%20AND%20modelformat%3A%22SBML%22&numResults=100&offset=0&format=json` returns `{"matches": 1075, "models": [{"id": "BIOMD...", "name": ..., "format": "SBML", ...}]}` (`numResults` below 10 is raised to 10), `https://www.biomodels.org/BIOMD0000000001?format=json` returns `name`, `publicationId`, `format.version`, `files.main[0].name`, and `https://www.biomodels.org/model/download/BIOMD0000000001?filename=BIOMD0000000001_url.xml` the SBML. `www.ebi.ac.uk/biomodels` rejects the quoted query, use `www.biomodels.org`.
- Generated files (`biomodels/models.json`, `biomodels/results.json`, `docs/biomodels.md`, and the rewritten `testsuite/results.json`) are produced only by the commands; no timestamps except the `date` of the model selection.
- No em dash anywhere. NO co-author trailer in commits. Branch `s4-biomodels` (checked out, stacked on `s3-testsuite`). `uv run <command>`. Commit after every task.
- Existing interfaces: `sbml2cellml.testsuite.cases.Case(id, case_dir, sbml_path, settings, expected, test_tags, component_tags, test_type)`, `Settings(start, duration, steps, variables, absolute, relative, amount, concentration)`, `skip_reason`, `PACKAGE_PREFIXES`, `cache_dir()`, `CACHE_ENV`; `testsuite.runner.run_case`, `run_suite(cases, work_dir, timeout, progress)`, `reference_selections`, `_message`, `_stage`; `testsuite.compare.compare/requested_frame/species_quantities/strip_brackets`; `testsuite.results.STAGES/StageResult/CaseResult/SuiteResult`; `testsuite.report.render_report(result)/write_report`; `testsuite.worker.frame`; `tests/sbml_models.py` `simple_model`, `write_sbml`; `tests/conftest.py` `MODELS_DIR`.

---

## File map

| Path | Responsibility | Task |
| --- | --- | --- |
| `src/sbml2cellml/testsuite/{cases,runner,results,report,cli}.py`, `testsuite/results.json`, tests | generalization | 1 |
| `src/sbml2cellml/biomodels/{__init__,models,cases}.py`, tests | BioModels access, case construction | 2 |
| `src/sbml2cellml/biomodels/{runner,cli}.py`, `pyproject.toml`, tests | runner, command | 3 |
| `biomodels/models.json`, `biomodels/results.json`, `docs/biomodels.md`, `.github/workflows/biomodels.yml`, docs, `CLAUDE.md`, `README.md`, release notes, `tests/test_biomodels_results.py` | full run, workflow, docs | 4 |
| pull request | 5 (main session) |

---

### Task 1: Generalize the test suite harness

**Files:**
- Modify: `src/sbml2cellml/testsuite/cases.py`, `runner.py`, `results.py`, `report.py`, `cli.py`, `testsuite/results.json`
- Test: `tests/test_testsuite_runner.py`, `tests/test_testsuite_results.py`, `tests/test_testsuite_report.py`

**Interfaces:**
- Produces: `Case.expected: pd.DataFrame | None`, `Case.name: str = ""`; `run_case` reference-as-expected mode; `CaseResult.name: str = ""`; `render_report(result, title="SBML test suite", intro=TESTSUITE_INTRO, command="sbml2cellml-testsuite", names=False)`, `report.TESTSUITE_INTRO`.

- [ ] **Step 1: Failing tests**

`tests/test_testsuite_runner.py`, add:

```python
def test_run_suite_without_expected_uses_reference(tmp_path: Path) -> None:
    """A case without expected results is compared against the reference."""
    import dataclasses

    case = load_cases(FIXTURES, ids=["00001"])[0]
    case = dataclasses.replace(case, expected=None, name="first case")
    result = run_suite([case], tmp_path)
    stages = result.cases["00001"].stages
    assert stages["reference"].status == "pass" and stages["reference"].max_excess is None
    for stage in ("sbml2cellml", "libopencor", "cellml2sbml", "roundtrip"):
        assert stages[stage].status == "pass", (stage, stages[stage].message)
    assert result.cases["00001"].name == "first case"


def test_run_suite_reference_failure_skips_simulations(tmp_path: Path) -> None:
    import dataclasses
    import shutil

    root = tmp_path / "semantic"
    shutil.copytree(FIXTURES / "00001", root / "00001")
    sbml = root / "00001" / "00001-sbml-l3v2.xml"
    # an algebraic rule roadrunner cannot handle, the conversion still runs
    text = sbml.read_text().replace(
        "<listOfReactions>",
        '<listOfRules><algebraicRule><math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<apply><minus/><ci>S1</ci><ci>S1</ci></apply></math></algebraicRule></listOfRules>"
        "<listOfReactions>",
        1,
    )
    sbml.write_text(text)
    case = dataclasses.replace(load_cases(root)[0], expected=None)
    result = run_suite([case], tmp_path / "work")
    stages = result.cases["00001"].stages
    assert stages["reference"].status == "fail"
    assert stages["libopencor"].status == "skip" and "reference failed" in stages["libopencor"].message
    assert stages["roundtrip"].status == "skip"
    assert stages["sbml2cellml"].status in ("pass", "fail")
```

`tests/test_testsuite_results.py`: in `test_json_roundtrip` also set `name="Repressilator"` on one case and assert it survives; add `test_from_json_without_name(tmp_path)` writing a JSON case dict without the `name` key and asserting `name == ""`.

`tests/test_testsuite_report.py`: add

```python
def test_render_report_parameters() -> None:
    result = sample()
    result.cases["00001"].name = "Edelstein1996 - EPSP ACh event"
    text = render_report(
        result, title="BioModels", intro="Curated models.", command="sbml2cellml-biomodels", names=True
    )
    assert text.startswith("<!-- generated by sbml2cellml-biomodels, do not edit -->")
    assert "# BioModels" in text and "Curated models." in text
    assert "| case | name | components |" in text
    assert "| 00001 | Edelstein1996 - EPSP ACh event | Compartment, Species |" in text
```

Run: `uv run pytest tests/test_testsuite_runner.py tests/test_testsuite_results.py tests/test_testsuite_report.py -n 0 -v`. Expected: the new tests fail (`TypeError` for the unknown fields and parameters).

- [ ] **Step 2: Implement**

- `cases.py`: `expected: pd.DataFrame | None`, `name: str = ""` (last field). Docstring updated.
- `results.py`: `CaseResult.name: str = ""`; `from_json` uses `case.get("name", "")`.
- `runner.py` `run_case`: the reference block becomes

```python
    expected = case.expected
    try:
        result = roadrunner.call(...)  # unchanged arguments
        reference = strip_brackets(frame(result))
        if expected is None:
            expected = reference
            stages["reference"] = StageResult("pass")
        else:
            stages["reference"] = _stage(compare(reference, expected, settings))
    except Exception as err:
        stages["reference"] = StageResult("fail", _message(err))
```

and after the `sbml2cellml` stage, when `expected is None` (the reference failed and there were no expected results), `libopencor` and `roundtrip` become `StageResult("skip", "reference failed")` while `cellml2sbml` still runs; the two comparisons use `expected` instead of `case.expected`. Every `CaseResult(...)` construction passes `name=case.name`. Factor the three `CaseResult(case.id, list(case.test_tags), list(case.component_tags), stages, name=case.name)` calls into a local helper `_result(stages)`.

- `report.py`: module constants `TESTSUITE_INTRO` (the current intro paragraphs as one string) and the signature `render_report(result, title="SBML test suite", intro=TESTSUITE_INTRO, command="sbml2cellml-testsuite", names=False)`; header `f"<!-- generated by {command}, do not edit -->"`; `f"# {title}"`; the cases table header `| case | name | components | ...` and rows with `case.name` when `names` is set. `write_report` gets the same keyword parameters and passes them on. `testsuite/cli.py` unchanged in behaviour.
- Rewrite the committed results in the new format (no rerun): `uv run python -c "from pathlib import Path; from sbml2cellml.testsuite.results import SuiteResult; p = Path('testsuite/results.json'); SuiteResult.from_json(p).to_json(p)"`; `git diff --stat testsuite/results.json` shows only added `"name": ""` lines; `uv run sbml2cellml-testsuite report` leaves `docs/testsuite.md` unchanged (`git diff --quiet docs/testsuite.md`).

- [ ] **Step 3: Verify and commit**

`uv run pytest -n 0 tests/test_testsuite_runner.py tests/test_testsuite_results.py tests/test_testsuite_report.py -v`, full `uv run pytest`, `uv run ruff check && uv run ruff format && uv run ty check`.

```bash
git add src/sbml2cellml/testsuite tests testsuite/results.json
git commit -m "Generalize the test suite harness for cases without expected results"
```

---

### Task 2: BioModels access and cases

**Files:**
- Create: `src/sbml2cellml/biomodels/__init__.py`, `models.py`, `cases.py`
- Test: `tests/test_biomodels_models.py`, `tests/test_biomodels_cases.py`

**Interfaces:**
- Produces: `models.BIOMODELS_URL`, `SEARCH_QUERY`, `PAGE_SIZE`, `BioModelsError`, `ModelInfo(id, name, publication_id, format_version, main_file)`, `query_curated_ids() -> list[str]`, `model_info(model_id, cache=None) -> ModelInfo`, `download_model(model_id, cache=None) -> Path`, `Selection(date, query, models)`, `load_selection(path) -> Selection`, `write_selection(path, ids) -> Selection`, `packages(sbml_path) -> tuple[str, ...]`, `biomodels_cache(cache=None) -> Path` (`<cache>/biomodels`); `cases.DURATION`, `STEPS`, `ABSOLUTE`, `RELATIVE`, `constructs(model: libsbml.Model, text: str) -> tuple[str, ...]`, `biomodel_case(info, sbml_path, packages) -> Case`.

- [ ] **Step 1: Failing tests**

`tests/test_biomodels_models.py` (mock `requests.get` used by `models.py` via `monkeypatch.setattr(models.requests, "get", fake_get)`; `fake_get(url, params=None, stream=False, timeout=None)` returns an object with `raise_for_status()`, `json()`, `iter_content()`, context manager methods, dispatching on the url: `/search` returns a page of ids (`matches` 12, `PAGE_SIZE` monkeypatched to 5, so three pages are requested and the offsets asserted `0, 5, 10`), `/BIOMD...?format=json` returns the info dict, `/model/download/...` returns the bytes of `MODELS_DIR / "glimepiride_liver.xml"`):

- `test_query_curated_ids_pages`: ids sorted, offsets as expected, `params` carry `SEARCH_QUERY`, `format=json`.
- `test_model_info_cached(tmp_path, monkeypatch)`: with `CACHE_ENV` set to `tmp_path`, `model_info("BIOMD0000000001")` returns `ModelInfo("BIOMD0000000001", "Edelstein1996 - EPSP ACh event", "BIOMD0000000001", "L2V4", "BIOMD0000000001_url.xml")`, writes `tmp_path/biomodels/BIOMD0000000001/info.json`, and a second call does not hit the network (count the calls).
- `test_download_model_cached`: file path `tmp_path/biomodels/BIOMD0000000001/BIOMD0000000001_url.xml` exists with the fixture content, second call no network.
- `test_download_failure_raises`: `raise_for_status` raising `requests.HTTPError` yields `BioModelsError` mentioning the id.
- `test_selection_roundtrip(tmp_path)`: `write_selection(path, ["BIOMD0000000002", "BIOMD0000000001"])` writes sorted ids, `query`, a `date` of the form `YYYY-MM-DD`; `load_selection` returns them.
- `test_packages(tmp_path)`: an SBML root with `xmlns:comp="http://www.sbml.org/sbml/level3/version1/comp/version1"` and `xmlns:fbc="http://www.sbml.org/sbml/level3/version1/fbc/version2"` gives `("comp", "fbc")`; the glimepiride liver model gives `()`.

`tests/test_biomodels_cases.py`:

- `test_constructs_liver`: `constructs(model, text)` of the liver model contains `Reactions` and `AssignmentRules` (check the model; adjust to what it really contains, printing the result first) and not `Events`.
- `test_constructs_events(tmp_path)`: `simple_model` plus an event (see `tests/test_sbml2cellml.py` for building one) contains `Events`.
- `test_biomodel_case`: `biomodel_case(ModelInfo(...), liver_path, ())` gives `settings.start == 0`, `duration == 100`, `steps == 100`, `variables` = the species ids of the model in document order, `amount`/`concentration` split by `hasOnlySubstanceUnits`, `absolute == 1e-6`, `relative == 1e-3`, `expected is None`, `test_type == "TimeCourse"`, `component_tags == constructs`, `name == info.name`, `sbml_path == liver_path`, `id == info.id`; with `packages=("comp",)` the component tags contain `"comp:package"` and `skip_reason(case) == "package comp"`.

Run and see them fail with `ModuleNotFoundError`.

- [ ] **Step 2: Implement**

`src/sbml2cellml/biomodels/__init__.py`: `"""BioModels release check: the curated models through both converters."""`

`models.py` (google docstrings, logging, `requests` at module level so tests can monkeypatch `models.requests.get`):

```python
BIOMODELS_URL = "https://www.biomodels.org"
SEARCH_QUERY = 'curationstatus:"Manually curated" AND modelformat:"SBML"'
PAGE_SIZE = 100
TIMEOUT = 60.0


class BioModelsError(RuntimeError): ...

@dataclass(frozen=True)
class ModelInfo: id: str; name: str; publication_id: str; format_version: str; main_file: str

@dataclass(frozen=True)
class Selection: date: str; query: str; models: tuple[str, ...]

def biomodels_cache(cache: Path | None = None) -> Path: return (cache or cache_dir()) / "biomodels"

def _get_json(url, params=None) -> dict: response = requests.get(url, params=params, timeout=TIMEOUT); raise_for_status; return response.json()  (wrap RequestException into BioModelsError)

def query_curated_ids() -> list[str]:
    offset = 0; ids = []; matches = None
    while matches is None or offset < matches:
        data = _get_json(f"{BIOMODELS_URL}/search", {"query": SEARCH_QUERY, "numResults": PAGE_SIZE, "offset": offset, "format": "json"})
        matches = int(data["matches"]); ids.extend(m["id"] for m in data["models"]); offset += PAGE_SIZE
    return sorted(set(ids))

def model_info(model_id, cache=None) -> ModelInfo: info.json cache; fields as in the spec; a model without `files.main` raises BioModelsError.

def download_model(model_id, cache=None) -> Path: info = model_info(...); path = biomodels_cache(cache)/model_id/info.main_file; if exists return; stream `requests.get(url, params={"filename": info.main_file}, stream=True, timeout=TIMEOUT)` to a temporary file then rename; return path.

def load_selection(path) -> Selection; def write_selection(path, ids) -> Selection (date = date.today().isoformat(), sorted unique ids, json indent 1).

_XMLNS = re.compile(r'xmlns:(\w+)="http://www\.sbml\.org/sbml/level3/version\d+/(\w+)/version\d+"')
def packages(sbml_path) -> tuple[str, ...]: sorted set of the package names in the first 8 kB of the file.
```

`cases.py`:

```python
DURATION = 100.0; STEPS = 100; ABSOLUTE = 1e-6; RELATIVE = 1e-3

def constructs(model: libsbml.Model, text: str) -> tuple[str, ...]:
    tags = []
    if model.getNumReactions(): tags.append("Reactions")
    if model.getNumEvents(): tags.append("Events")
    if model.getNumFunctionDefinitions(): tags.append("FunctionDefinitions")
    if model.getNumInitialAssignments(): tags.append("InitialAssignments")
    if model.getNumConstraints(): tags.append("Constraints")
    rules = [model.getRule(k) for k in range(model.getNumRules())]
    if any(r.isAlgebraic() for r in rules): tags.append("AlgebraicRules")
    if any(r.isAssignment() for r in rules): tags.append("AssignmentRules")
    if any(r.isRate() for r in rules): tags.append("RateRules")
    if "symbols/delay" in text: tags.append("Delay")
    return tuple(tags)

def biomodel_case(info: ModelInfo, sbml_path: Path, packages: tuple[str, ...]) -> Case:
    doc = libsbml.readSBMLFromFile(str(sbml_path)); model = doc.getModel()
    if model is None: raise BioModelsError(f"{info.id}: no model in {sbml_path.name}")
    species = list(model.getListOfSpecies())
    settings = Settings(start=0.0, duration=DURATION, steps=STEPS, variables=tuple(s.getId() for s in species), absolute=ABSOLUTE, relative=RELATIVE, amount=frozenset(s.getId() for s in species if s.getHasOnlySubstanceUnits()), concentration=frozenset(s.getId() for s in species if not s.getHasOnlySubstanceUnits()))
    tags = constructs(model, sbml_path.read_text(encoding="utf-8")) + tuple(f"{p}:package" for p in packages)
    return Case(id=info.id, case_dir=sbml_path.parent, sbml_path=sbml_path, settings=settings, expected=None, test_tags=(), component_tags=tags, test_type="TimeCourse", name=info.name)
```

- [ ] **Step 3: Verify and commit**

Tests green, `uv run ruff check && uv run ruff format && uv run ty check`, one manual live probe allowed (`uv run python -c "from sbml2cellml.biomodels.models import query_curated_ids; ids = query_curated_ids(); print(len(ids), ids[:3])"`, expect about 1075 and `BIOMD0000000001` first); put the output in the report.

```bash
git add src/sbml2cellml/biomodels tests/test_biomodels_models.py tests/test_biomodels_cases.py
git commit -m "Add the BioModels access and case construction"
```

---

### Task 3: Runner and command

**Files:**
- Create: `src/sbml2cellml/biomodels/runner.py`, `src/sbml2cellml/biomodels/cli.py`
- Modify: `pyproject.toml` (`[project.scripts] sbml2cellml-biomodels = "sbml2cellml.biomodels.cli:main"`), `uv.lock` if changed
- Test: `tests/test_biomodels_runner.py`, `tests/test_biomodels_cli.py`

**Interfaces:**
- Produces: `runner.run_biomodels(ids, cache=None, work_dir=Path("biomodels/work"), timeout=60.0, progress=None) -> SuiteResult`, `runner.prepare_cases(ids, cache) -> tuple[list[Case], dict[str, str]]`; `cli.main(argv) -> int`.

- [ ] **Step 1: Failing tests**

`tests/test_biomodels_runner.py`: monkeypatch `sbml2cellml.biomodels.runner.model_info` and `download_model` to serve local files: `BIOMD_A` -> `MODELS_DIR / "glimepiride_liver.xml"` with a `ModelInfo`, `BIOMD_B` -> a tmp SBML file with a `comp` namespace declaration, `BIOMD_C` -> `model_info` raising `BioModelsError("boom")`.

- `test_prepare_cases`: two cases returned (A and B; B's tags contain `comp:package`), skipped `{"BIOMD_C": "download failed: BioModelsError"}`.
- `test_run_biomodels(tmp_path)`: `run_biomodels(["BIOMD_A", "BIOMD_B", "BIOMD_C"], work_dir=tmp_path)`: `result.suite == "biomodels"`, `result.skipped == {"BIOMD_B": "package comp", "BIOMD_C": "download failed: BioModelsError"}`, `result.cases["BIOMD_A"].name` is the info name, the five stages present, `reference` pass, `sbml2cellml` pass (the liver model converts), `libopencor` and `roundtrip` have a status in `pass`/`fail` (the liver model has no dose, so both pass on constant zero trajectories; assert `pass` and note it), `expected` handled without error.

`tests/test_biomodels_cli.py`: with the same monkeypatches applied to `sbml2cellml.biomodels.runner`:
- `test_cli_run_with_ids(tmp_path, capsys)`: `main(["run", "--ids", "BIOMD_A", "--work-dir", ..., "--results", ..., "--report", ...])` returns 0, both files written, stdout has the status line and the summary.
- `test_cli_run_with_models_file(tmp_path)`: `write_selection(models_path, ["BIOMD_A"])`, `main(["run", "--models", str(models_path), ...])` returns 0; with `--count 0`... skip that; `--count 1` on a two-id selection runs one case.
- `test_cli_update(tmp_path, monkeypatch)`: monkeypatch `sbml2cellml.biomodels.cli.query_curated_ids` to return three ids; `main(["update", "--models", path])` writes the selection with the three ids; `--count 2` keeps the first two.
- `test_cli_report(tmp_path)`: after a run, `main(["report", "--results", ..., "--output", ...])` rewrites the report.
- `test_cli_missing_models_file(tmp_path)`: returns 1 with a message on stderr.

- [ ] **Step 2: Implement**

`runner.py`:

```python
def prepare_cases(ids, cache=None) -> tuple[list[Case], dict[str, str]]:
    cases, skipped = [], {}
    for model_id in ids:
        try:
            info = model_info(model_id, cache); path = download_model(model_id, cache)
            cases.append(biomodel_case(info, path, packages(path)))
        except Exception as err:
            logger.warning("%s skipped: %s", model_id, err)
            skipped[model_id] = f"download failed: {type(err).__name__}"
    return cases, skipped

def run_biomodels(ids, cache=None, work_dir=Path("biomodels/work"), timeout=60.0, progress=None) -> SuiteResult:
    cases, skipped = prepare_cases(ids, cache)
    result = run_suite(cases, work_dir, timeout=timeout, progress=progress)
    result.suite = "biomodels"
    result.skipped.update(skipped)
    return result
```

(`model_info`, `download_model`, `packages` imported into `runner.py` by name so the tests can monkeypatch them there.)

`cli.py` mirrors `testsuite/cli.py`: subcommands `run` (`--models` default `biomodels/models.json`, `--ids`, `--count`, `--work-dir` default `biomodels/work`, `--results` default `biomodels/results.json`, `--report` default `docs/biomodels.md`, `--timeout`, `-v`), `update` (`--models`, `--count`), `report` (`--results`, `--output`). `run` without `--ids` loads the selection (error 1 when the file is missing), applies `--count`, runs with `progress=print`, prints the per-stage summary and the skipped count, writes the results and the report with `write_report(result, path, title="BioModels", intro=BIOMODELS_INTRO, command="sbml2cellml-biomodels", names=True)`. `BIOMODELS_INTRO` (module constant in `cli.py` or `runner.py`): "Manually curated SBML models of [BioModels](https://www.biomodels.org) (the ids in `biomodels/models.json`). Every model is simulated with roadrunner over 0 to 100 time units in 100 steps (`reference`), converted to CellML (`sbml2cellml`), simulated with libopencor (`libopencor`), converted back to SBML (`cellml2sbml`) and simulated with roadrunner again (`roundtrip`); the two later simulations are compared with the reference for every species with a relative tolerance of 1e-3 and an absolute tolerance of 1e-6. A `reference` failure means roadrunner cannot simulate the model, it says nothing about the converters. See [Development](development.md#biomodels-check) for how to run it." `update` writes the selection from `query_curated_ids()` (`--count` limits). The gitignore gets `biomodels/work/`.

- [ ] **Step 3: Verify and commit**

`uv run pytest tests/test_biomodels_*.py -n 0 -v`, full suite, ruff/format/ty, `uv sync --extra dev` and `uv run sbml2cellml-biomodels --version`.

```bash
git add src/sbml2cellml/biomodels pyproject.toml uv.lock .gitignore tests/test_biomodels_runner.py tests/test_biomodels_cli.py
git commit -m "Add the BioModels runner and the sbml2cellml-biomodels command"
```

---

### Task 4: Full run, workflow, documentation

**Files:**
- Create: `biomodels/models.json`, `biomodels/results.json`, `docs/biomodels.md`, `.github/workflows/biomodels.yml`, `tests/test_biomodels_results.py`, `docs/api/biomodels.{models,cases,runner,cli}.md`
- Modify: `zensical.toml`, `docs/api/index.md`, `docs/development.md`, `docs/roadmap.md`, `docs/index.md`, `README.md`, `CLAUDE.md`, `release-notes/0.1.0.md`, `.pre-commit-config.yaml` if the results exceed the large-file limit

- [ ] **Step 1: Selection and full run**

```bash
uv run sbml2cellml-biomodels update          # biomodels/models.json, about 1075 ids
uv run sbml2cellml-biomodels run -v 2>&1 | tail -12
```

The first run downloads every model (about 1075 small files, minutes) and simulates; models that hang beyond the timeout are `fail` with `SimulationTimeout`. Record the per-stage summary and the wall time. If the run crashes, fix the harness minimally and rerun. Then `uv run sbml2cellml-biomodels report` must leave `docs/biomodels.md` unchanged (deterministic), and a rerun of `run` must leave both files unchanged (`git diff --stat`); if not, find the nondeterminism (e.g. dict ordering, floating point in messages) and fix it.

`tests/test_biomodels_results.py`:

```python
"""The committed BioModels results have the expected shape."""

from pathlib import Path

import pytest

from sbml2cellml.testsuite.results import STAGES, SuiteResult

RESULTS = Path(__file__).parent.parent / "biomodels" / "results.json"


@pytest.mark.skipif(not RESULTS.is_file(), reason="no committed BioModels results")
def test_committed_results() -> None:
    result = SuiteResult.from_json(RESULTS)
    assert result.suite == "biomodels"
    assert result.cases
    for case in result.cases.values():
        assert set(case.stages) == set(STAGES)
        assert case.name
```

- [ ] **Step 2: Workflow**

`.github/workflows/biomodels.yml`:

```yaml
name: biomodels

on:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  biomodels:
    name: biomodels
    runs-on: ubuntu-latest
    timeout-minutes: 120
    permissions:
      contents: write       # push the results branch
      pull-requests: write  # open the pull request
    steps:
      - uses: actions/checkout@v7
        with:
          persist-credentials: false
      - name: Install the python dev files
        # the extension of libroadrunner links against libpython, which the
        # standalone interpreters do not put on the library search path
        run: |
          sudo add-apt-repository -y ppa:deadsnakes/ppa
          sudo apt-get update
          sudo apt-get install -y python3.13-dev
      - name: Install uv and set the python version
        uses: astral-sh/setup-uv@v10.0.1
        with:
          python-version: "3.13"
          enable-cache: true
      - name: Cache the BioModels downloads
        uses: actions/cache@v6
        with:
          path: ~/.cache/sbml2cellml/biomodels
          key: biomodels-${{ hashFiles('biomodels/models.json') }}
      - name: Install dependencies
        run: uv sync --extra dev
      - name: Run the BioModels check
        run: uv run sbml2cellml-biomodels run | tail -8
      - name: Open a pull request with the results
        uses: peter-evans/create-pull-request@v8
        with:
          branch: biomodels-results
          base: develop
          title: "Update the BioModels results"
          commit-message: "Update the BioModels results"
          body: |
            Regenerated by the `biomodels` workflow with `sbml2cellml-biomodels run`.
            Review the changes of `docs/biomodels.md` for regressions before merging.
          add-paths: |
            biomodels/results.json
            docs/biomodels.md
```

Use the exact `actions/checkout` and `astral-sh/setup-uv` versions of `ci-cd.yml`. Validate the yaml.

- [ ] **Step 3: Documentation**

- `docs/api/biomodels.models.md`, `biomodels.cases.md`, `biomodels.runner.md`, `biomodels.cli.md` (`::: sbml2cellml.biomodels.<module>`); nav: "BioModels" (`biomodels.md`) after "SBML test suite", API section "sbml2cellml.biomodels" after the testsuite section; `docs/api/index.md` table.
- `docs/development.md`: section `## BioModels check { #biomodels-check }` after the test suite section: what it checks (reference from roadrunner, generic timecourse, tolerances), `uv run sbml2cellml-biomodels run` (cache, `--ids`, `--count` for a quick local run), `update` and the committed selection, the workflow (Actions tab, "biomodels", "Run workflow"; it opens a pull request with the regenerated files), and the release step: run the check or trigger the workflow before a release, review the `docs/biomodels.md` diff for regressions, merge before tagging. Add the step to the numbered release list (after the release notes step).
- `docs/roadmap.md`: item 3 done, link `biomodels.md`; `docs/index.md` and `README.md`: feature bullet "BioModels check: the curated models through both converters, results on the BioModels page"; `CLAUDE.md`: commands (`uv run sbml2cellml-biomodels run|update|report`), architecture entry for `biomodels/` (models access with cache, case construction with the generic timecourse, runner reusing the test suite pipeline with the reference as expected results, the workflow), conventions: the three generated files and the release step; `release-notes/0.1.0.md`: feature line.
- Build: `uv run zensical build --clean --strict && uv run python scripts/llms_txt.py` (zero warnings), `grep -rn "—" docs/*.md README.md CLAUDE.md` (nothing).

- [ ] **Step 4: Verify and commit**

`uv run pytest` (zero warnings), `uv run ruff check && uv run ruff format --check && uv run ty check`, `uv run pre-commit run --all-files` (raise `--maxkb` with a comment if `biomodels/results.json` exceeds the limit).

```bash
git add biomodels/models.json biomodels/results.json docs/biomodels.md tests/test_biomodels_results.py .pre-commit-config.yaml
git commit -m "Add the BioModels selection and results"
git add .github/workflows/biomodels.yml
git commit -m "Add the biomodels workflow"
git add docs zensical.toml README.md CLAUDE.md release-notes/0.1.0.md
git commit -m "Document the BioModels check"
```

---

### Task 5: Pull request

Run by the main session: full verification, push, PR into `develop` (stacked on `s3-testsuite`; rebase after #4 merges), watch the checks.
