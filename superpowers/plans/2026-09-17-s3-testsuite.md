# S3: SBML test suite roundtrip harness - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run every runnable semantic case of the SBML test suite through roadrunner, `sbml2cellml`, libopencor, `cellml2sbml` and roadrunner again, compare each simulation with the expected results, commit the per-case status and a rendered report page, and fail CI on regressions.

**Architecture:** Subpackage `sbml2cellml.testsuite`: `cases.py` (download, cache, parse), `simulators.py` + `worker.py` (roadrunner and libopencor each in their own spawned process with timeouts), `compare.py` (suite tolerances, amount/concentration conversion), `results.py` (JSON, regressions), `runner.py` (pipeline), `report.py` (markdown), `cli.py` (`sbml2cellml-testsuite run|report`). The main process only converts.

**Tech Stack:** python 3.13, python-libsbml, libcellml, libopencor, libroadrunner (worker), pandas, numpy, requests, multiprocessing (spawn), pytest.

**Spec:** `superpowers/specs/2026-09-17-s3-testsuite-design.md`

## Global Constraints

- roadrunner is never imported in the main process of the harness or of pytest: only inside `sbml2cellml.testsuite.simulators` functions run by a `SimulatorWorker`. libopencor likewise only through `simulators.simulate_cellml` in a worker (the S1 tests keep using it in process; they never run roadrunner).
- Runtime dependencies unchanged; new extra `testsuite = ["sbml2cellml[simulate]", "libroadrunner>=2.10.0", "requests>=2.32"]`; `dev` lists `sbml2cellml[testsuite]` and no longer `libroadrunner` directly.
- Library code logs with lazy `%s`, never prints (the CLI and the progress callback print). Full annotations and google docstrings (tests exempt from `D`). ty `error-on-warning = true`; rule-specific ignores only where ty reports.
- `testsuite/results.json` and `docs/testsuite.md` are generated only by `sbml2cellml-testsuite run` and committed; no timestamps in either.
- Suite version `3.5.0`, URL `https://github.com/sbmlteam/sbml-test-suite/releases/download/3.5.0/semantic_tests_v3.5.0.zip`, cache `~/.cache/sbml2cellml/sbml-test-suite/3.5.0/semantic`.
- No em dash anywhere. NO co-author trailer in commits. Branch `s3-testsuite` (from `develop`, checked out). `uv run <command>`. Commit after every task.
- Interfaces from S1/S2: `sbml2cellml.convert_sbml2cellml(sbml_path, cellml_path=None, validate=True)`, `sbml2cellml.convert_cellml2sbml(cellml_path, sbml_path=None, validate=True)`, `sbml2cellml.simulate.run_timecourse(cellml_path, start, end, steps) -> (DataFrame, units)` with column `time` first, `sbml2cellml.sbml.document_to_string`, `sbml2cellml.log.enable_rich_logging`, `tests/conftest.py` `MODELS_DIR`, `TEST_MODEL_PATH`. The downloaded suite for local use is already at `/tmp/claude-1000/-home-mkoenig-git-sbml2cellml/cd30810e-7682-427b-aa26-9798000051f0/scratchpad/sts/semantic` (a spike copy; the harness must still download into the cache on its own).

---

## File map

| Path | Responsibility | Task |
| --- | --- | --- |
| `pyproject.toml`, `uv.lock`, `src/sbml2cellml/testsuite/__init__.py`, `cases.py`, `tests/data/testsuite/semantic/*`, `tests/test_testsuite_cases.py` | extras, suite download and parsing, fixtures | 1 |
| `src/sbml2cellml/simulate.py`, `testsuite/simulators.py`, `testsuite/worker.py`, `tests/test_testsuite_worker.py`, `tests/test_simulate.py` | constants columns, simulator functions, worker processes | 2 |
| `testsuite/compare.py`, `testsuite/results.py`, `tests/test_testsuite_compare.py`, `tests/test_testsuite_results.py` | comparison, results, regressions | 3 |
| `testsuite/runner.py`, `tests/test_testsuite_runner.py` | pipeline | 4 |
| `testsuite/report.py`, `testsuite/cli.py`, `tests/test_testsuite_report.py` | report, command | 5 |
| `testsuite/results.json`, `docs/testsuite.md`, `tests/test_testsuite_full.py`, `tox.ini`, `.github/workflows/ci-cd.yml`, docs, `CLAUDE.md`, `README.md`, release notes | full run, gating, documentation | 6 |
| pull request | 7 (main session) |

---

### Task 1: Extras, suite download and case parsing

**Files:**
- Modify: `pyproject.toml` (extras, script placeholder not yet, marker), `uv.lock`
- Create: `src/sbml2cellml/testsuite/__init__.py`, `src/sbml2cellml/testsuite/cases.py`, `tests/data/testsuite/semantic/<three cases>/`
- Test: `tests/test_testsuite_cases.py`

**Interfaces:**
- Produces: everything listed for `cases.py` in the spec section 1.

- [ ] **Step 1: Extras and marker**

In `pyproject.toml` `[project.optional-dependencies]` add before `dev`:

```toml
# the SBML test suite harness: roadrunner as reference simulator, requests for
# the download of the suite
testsuite = [
	"sbml2cellml[simulate]",
	"libroadrunner>=2.10.0",
	"requests>=2.32",
]
```

and in `dev` replace `"sbml2cellml[simulate]",` and the `"libroadrunner>=2.10.0",` line by `"sbml2cellml[testsuite]",`. In `[tool.pytest.ini_options]` add:

```toml
markers = [
	"testsuite: runs the complete SBML test suite, enabled with SBML2CELLML_TESTSUITE=1",
]
```

Run `uv sync --extra dev` (updates `uv.lock`; `uv run python -c "import requests, roadrunner"` must work).

- [ ] **Step 2: Fixture cases**

From the spike copy `/tmp/claude-1000/-home-mkoenig-git-sbml2cellml/cd30810e-7682-427b-aa26-9798000051f0/scratchpad/sts/semantic` (if missing, download the zip from the URL above into the scratchpad and unzip) copy the four files `<id>-sbml-l3v2.xml`, `<id>-settings.txt`, `<id>-results.csv`, `<id>-model.m` of three cases into `tests/data/testsuite/semantic/<id>/`:
- `00001`
- the lowest id whose `-model.m` has `EventNoDelay` in `testTags` and an L3V2 file (`grep -l "EventNoDelay" */*-model.m | head -1`)
- the lowest id whose `-model.m` has `FunctionDefinition` in `componentTags` and an L3V2 file

Record the two ids in `tests/test_testsuite_cases.py` as `EVENT_CASE` and `FUNCTION_CASE`.

- [ ] **Step 3: Write the failing tests**

`tests/test_testsuite_cases.py`:

```python
"""Tests of the test suite cases: download, cache, parsing."""

import io
import zipfile
from pathlib import Path

import pytest

from sbml2cellml.testsuite import cases
from sbml2cellml.testsuite.cases import (
    Case,
    Settings,
    TestSuiteError,
    ensure_suite,
    load_case,
    load_cases,
    parse_model_info,
    parse_settings,
    skip_reason,
)

FIXTURES = Path(__file__).parent / "data" / "testsuite" / "semantic"
EVENT_CASE = "<id from step 2>"
FUNCTION_CASE = "<id from step 2>"


def test_parse_settings() -> None:
    settings = parse_settings((FIXTURES / "00001" / "00001-settings.txt").read_text())
    assert settings == Settings(
        start=0.0,
        duration=5.0,
        steps=50,
        variables=("S1", "S2"),
        absolute=1e-7,
        relative=1e-4,
        amount=frozenset({"S1", "S2"}),
        concentration=frozenset(),
    )
    assert settings.end == 5.0


def test_parse_settings_missing_key_raises() -> None:
    with pytest.raises(TestSuiteError, match="duration"):
        parse_settings("start: 0\nsteps: 10\nvariables: S1\n")


def test_parse_model_info() -> None:
    info = parse_model_info((FIXTURES / "00001" / "00001-model.m").read_text())
    assert info["testType"] == ["TimeCourse"]
    assert "Amount" in info["testTags"]
    assert "Compartment" in info["componentTags"]


def test_load_case() -> None:
    case = load_case(FIXTURES / "00001")
    assert case.id == "00001"
    assert case.sbml_path == FIXTURES / "00001" / "00001-sbml-l3v2.xml"
    assert case.test_type == "TimeCourse"
    assert list(case.expected.columns) == ["time", "S1", "S2"]
    assert len(case.expected) == 51
    assert skip_reason(case) is None


def test_load_cases_sorted_and_filtered() -> None:
    all_cases = load_cases(FIXTURES)
    assert [c.id for c in all_cases] == sorted(["00001", EVENT_CASE, FUNCTION_CASE])
    assert [c.id for c in load_cases(FIXTURES, ids=[EVENT_CASE])] == [EVENT_CASE]
    assert "EventNoDelay" in next(c for c in all_cases if c.id == EVENT_CASE).test_tags
    assert "FunctionDefinition" in next(
        c for c in all_cases if c.id == FUNCTION_CASE
    ).component_tags


def test_skip_reasons(tmp_path: Path) -> None:
    import shutil

    src = FIXTURES / "00001"
    # no L3V2 file
    no_l3v2 = tmp_path / "10001"
    shutil.copytree(src, no_l3v2)
    for f in no_l3v2.iterdir():
        f.rename(no_l3v2 / f.name.replace("00001", "10001"))
    (no_l3v2 / "10001-sbml-l3v2.xml").unlink()
    assert skip_reason(load_case(no_l3v2)) == "no L3V2 file"
    # comp package
    comp = tmp_path / "10002"
    shutil.copytree(src, comp)
    for f in comp.iterdir():
        f.rename(comp / f.name.replace("00001", "10002"))
    m = comp / "10002-model.m"
    m.write_text(m.read_text().replace("componentTags: ", "componentTags: comp:Submodel, "))
    assert skip_reason(load_case(comp)) == "package comp"
    # other test type
    other = tmp_path / "10003"
    shutil.copytree(src, other)
    for f in other.iterdir():
        f.rename(other / f.name.replace("00001", "10003"))
    m = other / "10003-model.m"
    m.write_text(m.read_text().replace("testType:      TimeCourse", "testType: SteadyState"))
    assert skip_reason(load_case(other)) == "test type SteadyState"


def test_ensure_suite_downloads_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # a zip with the layout of the release: semantic/00001/...
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for f in (FIXTURES / "00001").iterdir():
            archive.write(f, f"semantic/00001/{f.name}")
    calls: list[str] = []

    class Response:
        def __init__(self) -> None:
            self.content = buffer.getvalue()

        def raise_for_status(self) -> None:
            pass

        def iter_content(self, chunk_size: int):  # noqa: ANN202
            yield self.content

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            pass

    def fake_get(url: str, stream: bool, timeout: float) -> Response:
        calls.append(url)
        return Response()

    monkeypatch.setattr(cases.requests, "get", fake_get)
    monkeypatch.setenv(cases.CACHE_ENV, str(tmp_path))
    semantic = ensure_suite()
    assert semantic == tmp_path / "sbml-test-suite" / cases.SUITE_VERSION / "semantic"
    assert (semantic / "00001" / "00001-settings.txt").is_file()
    assert calls == [cases.SUITE_URL.format(version=cases.SUITE_VERSION)]
    ensure_suite()
    assert len(calls) == 1
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/test_testsuite_cases.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sbml2cellml.testsuite'`.

- [ ] **Step 5: Write the module**

`src/sbml2cellml/testsuite/__init__.py`:

```python
"""Harness running the SBML test suite through both converters."""
```

`src/sbml2cellml/testsuite/cases.py`:

```python
"""The semantic test cases of the SBML test suite.

A case is a directory `NNNNN` with the model in several SBML levels and
versions, `NNNNN-settings.txt` (simulation settings and tolerances),
`NNNNN-results.csv` (expected timecourse) and `NNNNN-model.m` (tags and the
test type). The suite is downloaded from its GitHub release into a cache on
first use.
"""

import logging
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

#: version of the SBML test suite
SUITE_VERSION = "3.5.0"
#: download url of the semantic test cases, formatted with the version
SUITE_URL = (
    "https://github.com/sbmlteam/sbml-test-suite/releases/download/"
    "{version}/semantic_tests_v{version}.zip"
)
#: environment variable overriding the cache root
CACHE_ENV = "SBML2CELLML_CACHE"
#: name of a case directory
CASE_ID = re.compile(r"^\d{5}$")
#: component tags of SBML packages, none of which the converters support
PACKAGE_PREFIXES = (
    "comp",
    "fbc",
    "qual",
    "multi",
    "distrib",
    "spatial",
    "groups",
    "layout",
    "render",
)
#: the only test type the harness runs
TIME_COURSE = "TimeCourse"


class TestSuiteError(RuntimeError):
    """The test suite cannot be obtained or a case cannot be read."""


def cache_dir() -> Path:
    """Root of the cache, `SBML2CELLML_CACHE` or `~/.cache/sbml2cellml`."""
    return Path(os.environ.get(CACHE_ENV, Path.home() / ".cache" / "sbml2cellml"))


def ensure_suite(version: str = SUITE_VERSION, cache: Path | None = None) -> Path:
    """Directory of the semantic cases, downloaded and unpacked on first use.

    Args:
        version: release of the test suite.
        cache: cache root, `cache_dir()` by default.

    Returns:
        The `semantic/` directory with one subdirectory per case.

    Raises:
        TestSuiteError: if the download fails or the archive has not the
            expected layout.
    """
    root = (cache or cache_dir()) / "sbml-test-suite" / version
    semantic = root / "semantic"
    if semantic.is_dir():
        return semantic
    root.mkdir(parents=True, exist_ok=True)
    url = SUITE_URL.format(version=version)
    zip_path = root / f"semantic_tests_v{version}.zip"
    logger.info("Downloading the SBML test suite %s from %s", version, url)
    try:
        with requests.get(url, stream=True, timeout=120) as response:
            response.raise_for_status()
            with zip_path.open("wb") as f_zip:
                for chunk in response.iter_content(1 << 16):
                    f_zip.write(chunk)
    except requests.RequestException as err:
        raise TestSuiteError(f"Download of {url} failed: {err}") from err
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(root)
    if not semantic.is_dir():
        raise TestSuiteError(f"No 'semantic' directory in {zip_path}")
    logger.info("SBML test suite unpacked to %s", semantic)
    return semantic


@dataclass(frozen=True)
class Settings:
    """Simulation settings of a case (`NNNNN-settings.txt`)."""

    start: float
    duration: float
    steps: int
    variables: tuple[str, ...]
    absolute: float
    relative: float
    amount: frozenset[str]
    concentration: frozenset[str]

    @property
    def end(self) -> float:
        """End time of the simulation."""
        return self.start + self.duration


def _key_values(text: str) -> dict[str, str]:
    """`key: value` lines of a settings or model file."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values


def _split(value: str) -> tuple[str, ...]:
    """Comma separated list, empty for an empty value."""
    return tuple(item.strip() for item in value.split(",") if item.strip())


def parse_settings(text: str) -> Settings:
    """Parse a settings file.

    Args:
        text: content of `NNNNN-settings.txt`.

    Returns:
        The settings.

    Raises:
        TestSuiteError: if `start`, `duration` or `steps` is missing.
    """
    values = _key_values(text)
    for key in ("start", "duration", "steps"):
        if key not in values:
            raise TestSuiteError(f"Settings without '{key}'.")
    return Settings(
        start=float(values["start"]),
        duration=float(values["duration"]),
        steps=int(values["steps"]),
        variables=_split(values.get("variables", "")),
        absolute=float(values.get("absolute", "0")),
        relative=float(values.get("relative", "0")),
        amount=frozenset(_split(values.get("amount", ""))),
        concentration=frozenset(_split(values.get("concentration", ""))),
    )


def parse_model_info(text: str) -> dict[str, list[str]]:
    """Parse the `key: values` lines of a `NNNNN-model.m` file.

    Args:
        text: content of the file.

    Returns:
        The values per key, e.g. `testTags`, `componentTags`, `testType`.
    """
    return {key: list(_split(value)) for key, value in _key_values(text).items()}


@dataclass(frozen=True)
class Case:
    """One semantic test case."""

    id: str
    case_dir: Path
    sbml_path: Path | None
    settings: Settings
    expected: pd.DataFrame
    test_tags: tuple[str, ...]
    component_tags: tuple[str, ...]
    test_type: str

    @property
    def packages(self) -> tuple[str, ...]:
        """SBML packages the case uses, from the component tags."""
        return tuple(
            sorted({tag.split(":")[0] for tag in self.component_tags if ":" in tag})
        )


def load_case(case_dir: Path) -> Case:
    """Read a case directory.

    Args:
        case_dir: directory `NNNNN`.

    Returns:
        The case; `sbml_path` is `None` when there is no L3V2 file.

    Raises:
        TestSuiteError: if the settings, results or model file is missing.
    """
    cid = case_dir.name
    for suffix in ("settings.txt", "results.csv", "model.m"):
        if not (case_dir / f"{cid}-{suffix}").is_file():
            raise TestSuiteError(f"Case {cid} has no {suffix}.")
    sbml_path: Path | None = case_dir / f"{cid}-sbml-l3v2.xml"
    if sbml_path is not None and not sbml_path.is_file():
        sbml_path = None
    info = parse_model_info((case_dir / f"{cid}-model.m").read_text(encoding="utf-8"))
    return Case(
        id=cid,
        case_dir=case_dir,
        sbml_path=sbml_path,
        settings=parse_settings((case_dir / f"{cid}-settings.txt").read_text(encoding="utf-8")),
        expected=pd.read_csv(case_dir / f"{cid}-results.csv"),
        test_tags=tuple(info.get("testTags", [])),
        component_tags=tuple(info.get("componentTags", [])),
        test_type=(info.get("testType") or [""])[0],
    )


def skip_reason(case: Case) -> str | None:
    """Why a case is not run, `None` if it is runnable."""
    if case.sbml_path is None:
        return "no L3V2 file"
    if case.test_type != TIME_COURSE:
        return f"test type {case.test_type}"
    for package in case.packages:
        if package in PACKAGE_PREFIXES:
            return f"package {package}"
    return None


def load_cases(root: Path, ids: list[str] | None = None) -> list[Case]:
    """Read the cases of a suite directory.

    Args:
        root: the `semantic/` directory.
        ids: case ids to read, all when `None`.

    Returns:
        The cases sorted by id.
    """
    wanted = set(ids) if ids is not None else None
    cases: list[Case] = []
    for case_dir in sorted(root.iterdir()):
        if not case_dir.is_dir() or not CASE_ID.match(case_dir.name):
            continue
        if wanted is not None and case_dir.name not in wanted:
            continue
        cases.append(load_case(case_dir))
    return cases
```

- [ ] **Step 6: Run the tests, lint, type check, commit**

Run: `uv run pytest tests/test_testsuite_cases.py -v`
Expected: all pass. The `test_skip_reasons` replacements assume the exact spacing of the fixture's `-model.m` (`testType:      TimeCourse`); if the file differs, adjust the replaced string in the test, not the parser.

```bash
uv run ruff check && uv run ruff format && uv run ty check
git add pyproject.toml uv.lock src/sbml2cellml/testsuite tests/data/testsuite tests/test_testsuite_cases.py
git commit -m "Add the SBML test suite download and case parsing"
```

---

### Task 2: Constants in the timecourse, simulator functions and workers

**Files:**
- Modify: `src/sbml2cellml/simulate.py`, `tests/test_simulate.py`
- Create: `src/sbml2cellml/testsuite/simulators.py`, `src/sbml2cellml/testsuite/worker.py`
- Test: `tests/test_testsuite_worker.py`

**Interfaces:**
- Produces: `run_timecourse` columns include the constants and computed constants; `simulators.simulate_sbml(sbml, selections, start, end, steps) -> dict`, `simulators.simulate_cellml(cellml_path, start, end, steps) -> dict`, `simulators.sleep(seconds) -> dict`; `worker.SimulatorWorker(name, timeout=60.0)` with `start()`, `call(function, **kwargs) -> dict`, `stop()`, context manager; `worker.SimulationFailure`, `worker.SimulationTimeout`; `worker.frame(result: dict) -> pd.DataFrame`.

- [ ] **Step 1: Constants in `run_timecourse`**

In `src/sbml2cellml/simulate.py` `run_timecourse`, after the algebraic variables loop, add the constants and computed constants as columns with the value repeated for every row:

```python
    rows = len(task.voi)
    for k in range(task.constant_count):
        name = _variable_name(task.constant_name(k))
        data[name] = [float(task.constant(k))] * rows
        units[name] = task.constant_unit(k)
    for k in range(task.computed_constant_count):
        name = _variable_name(task.computed_constant_name(k))
        data[name] = [float(task.computed_constant(k))] * rows
        units[name] = task.computed_constant_unit(k)
```

Check with `uv run python -c "import libopencor; ..."` that `task.constant(k)` returns a number (the spike listed `constant`, `constant_count`, `constant_name`, `constant_unit`, `computed_constant*` on the task); if it returns a list, take its first element. Update the docstring ("followed by the states, the algebraic variables, the constants and the computed constants") and `docs/simulation.md` one sentence accordingly. In `tests/test_simulate.py` `test_run_timecourse_test_model` change the columns assertion to `["t", "m", "alpha"]`, add `assert (df["alpha"] == 0.05).all()` and `units["alpha"] == "per_second"`; in `test_run_timecourse_liver` keep `set(units) == set(df.columns)` (compartments now present: assert `"Vli" in df.columns` if that is a compartment id of the liver model, else the first compartment id printed by libsbml).

Run: `uv run pytest tests/test_simulate.py -v` (all pass).

- [ ] **Step 2: Write the failing worker tests**

`tests/test_testsuite_worker.py`:

```python
"""Tests of the simulator workers (roadrunner and libopencor in own processes)."""

from pathlib import Path

import pytest

from sbml2cellml.testsuite.worker import (
    SimulationFailure,
    SimulationTimeout,
    SimulatorWorker,
    frame,
)
from tests.conftest import TEST_MODEL_PATH

FIXTURES = Path(__file__).parent / "data" / "testsuite" / "semantic"


def test_simulate_sbml_in_worker() -> None:
    sbml = (FIXTURES / "00001" / "00001-sbml-l3v2.xml").read_text()
    with SimulatorWorker("roadrunner") as worker:
        result = worker.call(
            "simulate_sbml", sbml=sbml, selections=["S1", "S2"], start=0.0, end=5.0, steps=50
        )
    df = frame(result)
    assert list(df.columns) == ["time", "S1", "S2"]
    assert len(df) == 51
    assert df["time"].iloc[-1] == pytest.approx(5.0)
    assert df["S1"].iloc[0] == pytest.approx(1.5e-4)


def test_simulate_cellml_in_worker() -> None:
    with SimulatorWorker("libopencor") as worker:
        result = worker.call(
            "simulate_cellml", cellml_path=str(TEST_MODEL_PATH), start=0.0, end=10.0, steps=5
        )
    df = frame(result)
    assert list(df.columns) == ["t", "m", "alpha"]
    assert len(df) == 6


def test_worker_error_is_raised() -> None:
    with SimulatorWorker("roadrunner") as worker:
        with pytest.raises(SimulationFailure, match="RuntimeError|Exception"):
            worker.call("simulate_sbml", sbml="<sbml/>", selections=[], start=0.0, end=1.0, steps=1)
        # the worker survives an error
        sbml = (FIXTURES / "00001" / "00001-sbml-l3v2.xml").read_text()
        assert frame(worker.call("simulate_sbml", sbml=sbml, selections=["S1"], start=0.0, end=1.0, steps=1)).shape == (2, 2)


def test_worker_timeout_restarts() -> None:
    with SimulatorWorker("sleeper", timeout=0.5) as worker:
        with pytest.raises(SimulationTimeout):
            worker.call("sleep", seconds=5.0)
        # restarted and usable again
        assert worker.call("sleep", seconds=0.0) == {"slept": 0.0}


def test_two_workers_side_by_side() -> None:
    sbml = (FIXTURES / "00001" / "00001-sbml-l3v2.xml").read_text()
    with SimulatorWorker("roadrunner") as rr, SimulatorWorker("libopencor") as oc:
        for _ in range(2):
            rr.call("simulate_sbml", sbml=sbml, selections=["S1"], start=0.0, end=1.0, steps=2)
            oc.call("simulate_cellml", cellml_path=str(TEST_MODEL_PATH), start=0.0, end=1.0, steps=2)


def test_unknown_function() -> None:
    with SimulatorWorker("x") as worker, pytest.raises(SimulationFailure, match="nope"):
        worker.call("nope")
```

Run: `uv run pytest tests/test_testsuite_worker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sbml2cellml.testsuite.worker'`.

- [ ] **Step 3: Write the modules**

`src/sbml2cellml/testsuite/simulators.py`:

```python
"""Simulator functions run inside a `SimulatorWorker`.

Every function imports its simulator lazily, so a worker process loads only
the simulator it is used for: roadrunner and libopencor bundle different LLVM
versions and crash once both have compiled in the same process. Results are
plain dictionaries (`columns`, `rows`) so they can be sent between processes.
"""

import time
from pathlib import Path
from typing import Any


def simulate_sbml(
    sbml: str, selections: list[str], start: float, end: float, steps: int
) -> dict[str, Any]:
    """Uniform timecourse of an SBML model with roadrunner.

    Args:
        sbml: SBML document as string.
        selections: roadrunner selections after `time`, e.g. `S1`, `[S1]`.
        start: start time.
        end: end time.
        steps: number of intervals, the result has `steps + 1` rows.

    Returns:
        `columns` (the selections with `time` first) and `rows`.
    """
    import roadrunner

    roadrunner.Logger.setLevel(roadrunner.Logger.LOG_ERROR)
    rr = roadrunner.RoadRunner(sbml)
    rr.timeCourseSelections = ["time", *selections]
    result = rr.simulate(start, end, steps + 1)
    return {
        "columns": list(result.colnames),
        "rows": [[float(value) for value in row] for row in result],
    }


def simulate_cellml(cellml_path: str, start: float, end: float, steps: int) -> dict[str, Any]:
    """Uniform timecourse of a CellML model with libopencor.

    Args:
        cellml_path: path of the CellML file.
        start: start time.
        end: end time.
        steps: number of intervals.

    Returns:
        `columns` (`time` first, then every variable) and `rows`.
    """
    from sbml2cellml.simulate import run_timecourse

    df, _ = run_timecourse(Path(cellml_path), start=start, end=end, steps=steps)
    return {"columns": list(df.columns), "rows": df.to_numpy().tolist()}


def sleep(seconds: float) -> dict[str, Any]:
    """Sleep, for the timeout tests of the worker.

    Args:
        seconds: how long.

    Returns:
        `slept` with the seconds.
    """
    time.sleep(seconds)
    return {"slept": seconds}
```

`src/sbml2cellml/testsuite/worker.py`:

```python
"""Simulators in their own processes.

`SimulatorWorker` starts a process (spawn context, so nothing of the parent
is inherited) which runs the functions of `sbml2cellml.testsuite.simulators`
on request. Every call has a timeout; a worker which times out or dies is
replaced, so one bad case never takes the suite down.
"""

import logging
import multiprocessing
from multiprocessing.connection import Connection
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class SimulationFailure(RuntimeError):
    """The simulator raised or the worker died."""


class SimulationTimeout(SimulationFailure):
    """The simulator did not answer within the timeout."""


def _serve(connection: Connection) -> None:
    """Loop of the worker process: run the requested functions."""
    from sbml2cellml.testsuite import simulators

    while True:
        message = connection.recv()
        if message is None:
            break
        function, kwargs = message
        try:
            result = getattr(simulators, function)(**kwargs)
            connection.send({"result": result})
        except Exception as err:  # noqa: BLE001 - every error is reported to the parent
            connection.send({"error": f"{type(err).__name__}: {err}"})


class SimulatorWorker:
    """A simulator running in its own process."""

    def __init__(self, name: str, timeout: float = 60.0) -> None:
        """Create the worker, not started yet.

        Args:
            name: name for the logs, e.g. `roadrunner`.
            timeout: seconds a call may take before the worker is replaced.
        """
        self.name = name
        self.timeout = timeout
        self._context = multiprocessing.get_context("spawn")
        self._process: Any = None
        self._connection: Connection | None = None

    def start(self) -> None:
        """Start the process."""
        parent, child = self._context.Pipe()
        self._process = self._context.Process(target=_serve, args=(child,), daemon=True)
        self._process.start()
        child.close()
        self._connection = parent
        logger.info("%s worker started (pid %d)", self.name, self._process.pid)

    def stop(self) -> None:
        """Stop the process."""
        if self._process is None:
            return
        try:
            if self._connection is not None and self._process.is_alive():
                self._connection.send(None)
                self._process.join(timeout=5.0)
        except (BrokenPipeError, OSError):
            pass
        if self._process.is_alive():
            self._process.kill()
            self._process.join()
        if self._connection is not None:
            self._connection.close()
        self._process = None
        self._connection = None

    def _restart(self) -> None:
        """Replace a dead or hanging process."""
        logger.warning("%s worker replaced", self.name)
        self.stop()
        self.start()

    def call(self, function: str, **kwargs: Any) -> dict[str, Any]:
        """Run a function of `sbml2cellml.testsuite.simulators` in the worker.

        Args:
            function: name of the function.
            **kwargs: its arguments, picklable.

        Returns:
            The result dictionary of the function.

        Raises:
            SimulationTimeout: if the call exceeds the timeout; the worker is
                replaced.
            SimulationFailure: if the function raised, does not exist, or
                the worker died; a dead worker is replaced.
        """
        if self._connection is None or self._process is None or not self._process.is_alive():
            self._restart()
        assert self._connection is not None
        try:
            self._connection.send((function, kwargs))
            if not self._connection.poll(self.timeout):
                self._restart()
                raise SimulationTimeout(f"{self.name}: {function} exceeded {self.timeout} s")
            reply = self._connection.recv()
        except (EOFError, BrokenPipeError, OSError) as err:
            self._restart()
            raise SimulationFailure(f"{self.name}: worker died during {function}") from err
        if "error" in reply:
            raise SimulationFailure(f"{self.name}: {reply['error']}")
        return reply["result"]

    def __enter__(self) -> "SimulatorWorker":
        """Start the worker."""
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        """Stop the worker."""
        self.stop()


def frame(result: dict[str, Any]) -> pd.DataFrame:
    """Data frame of a simulator result.

    Args:
        result: `columns` and `rows` as returned by the simulator functions.

    Returns:
        The rows as data frame.
    """
    return pd.DataFrame(result["rows"], columns=result["columns"])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_testsuite_worker.py -v` then `uv run pytest tests/test_testsuite_worker.py -v -n 0`.
Expected: all pass in both modes. Notes: `test_worker_error_is_raised` expects the roadrunner error type in the message (`RuntimeError` for a broken document; if roadrunner raises another type, widen the `match`). A `ResourceWarning` about a connection is a finding; close connections in `stop`. Test output must be pristine.

- [ ] **Step 5: Full suite, lint, type check, commit**

```bash
uv run pytest
uv run ruff check && uv run ruff format && uv run ty check
git add src/sbml2cellml/simulate.py src/sbml2cellml/testsuite/simulators.py src/sbml2cellml/testsuite/worker.py tests/test_simulate.py tests/test_testsuite_worker.py docs/simulation.md
git commit -m "Add the simulator workers and the constants of a libopencor timecourse"
```

---

### Task 3: Comparison and results

**Files:**
- Create: `src/sbml2cellml/testsuite/compare.py`, `src/sbml2cellml/testsuite/results.py`
- Test: `tests/test_testsuite_compare.py`, `tests/test_testsuite_results.py`

**Interfaces:**
- Produces: `compare.compare(result, expected, settings) -> Comparison`, `compare.Comparison(variables, passed, message)` with property `max_excess`, `compare.VariableComparison(variable, max_error, max_excess, passed)`, `compare.species_quantities(model_sbml) -> dict[str, tuple[bool, str]]`, `compare.requested_frame(df, quantities, settings) -> pd.DataFrame`, `compare.strip_brackets(df) -> pd.DataFrame`; `results.STAGES`, `StageResult`, `CaseResult`, `SuiteResult` (`to_json`, `from_json`, `counts`), `regressions`, `improvements`.

- [ ] **Step 1: Write the failing tests**

`tests/test_testsuite_compare.py`:

```python
"""Tests of the comparison with the expected results."""

import libsbml
import numpy as np
import pandas as pd
import pytest

from sbml2cellml.testsuite.cases import Settings
from sbml2cellml.testsuite.compare import (
    compare,
    requested_frame,
    species_quantities,
    strip_brackets,
)

SETTINGS = Settings(
    start=0.0,
    duration=1.0,
    steps=2,
    variables=("S1", "S2"),
    absolute=1e-3,
    relative=1e-2,
    amount=frozenset({"S1"}),
    concentration=frozenset({"S2"}),
)


def expected() -> pd.DataFrame:
    return pd.DataFrame({"time": [0.0, 0.5, 1.0], "S1": [1.0, 0.5, 0.25], "S2": [0.0, 0.5, 0.75]})


def test_compare_pass() -> None:
    result = expected().copy()
    result["S1"] += 0.004  # within 1e-3 + 1e-2 * |e| for e >= 0.3, S1 min is 0.25 -> tol 0.0035
    result.loc[2, "S1"] = 0.25 + 0.003
    comparison = compare(result, expected(), SETTINGS)
    assert comparison.passed, comparison.message
    assert comparison.max_excess <= 0
    assert {v.variable for v in comparison.variables} == {"S1", "S2"}


def test_compare_fail_by_tolerance() -> None:
    result = expected().copy()
    result.loc[2, "S2"] = 0.75 + 0.02
    comparison = compare(result, expected(), SETTINGS)
    assert not comparison.passed
    assert "S2" in comparison.message
    s2 = next(v for v in comparison.variables if v.variable == "S2")
    assert s2.max_error == pytest.approx(0.02)
    assert s2.max_excess > 0


def test_compare_missing_variable_and_rows() -> None:
    result = expected().drop(columns=["S2"])
    comparison = compare(result, expected(), SETTINGS)
    assert not comparison.passed and "S2" in comparison.message and "missing" in comparison.message
    comparison = compare(expected().iloc[:2], expected(), SETTINGS)
    assert not comparison.passed and "rows" in comparison.message
    shifted = expected()
    shifted["time"] = shifted["time"] + 0.1
    comparison = compare(shifted, expected(), SETTINGS)
    assert not comparison.passed and "time" in comparison.message


def test_compare_nan_fails() -> None:
    result = expected()
    result.loc[1, "S1"] = np.nan
    assert not compare(result, expected(), SETTINGS).passed


def test_species_quantities_and_requested_frame() -> None:
    doc = libsbml.SBMLDocument(3, 2)
    model = doc.createModel()
    c = model.createCompartment()
    c.setId("cell")
    c.setSize(2.0)
    c.setConstant(True)
    for sid, amount in [("S1", True), ("S2", False)]:
        s = model.createSpecies()
        s.setId(sid)
        s.setCompartment("cell")
        s.setHasOnlySubstanceUnits(amount)
        s.setConstant(False)
        s.setBoundaryCondition(False)
    quantities = species_quantities(model)
    assert quantities == {"S1": (True, "cell"), "S2": (False, "cell")}

    df = pd.DataFrame({"time": [0.0, 1.0], "S1": [4.0, 2.0], "S2": [1.0, 3.0], "cell": [2.0, 2.0]})
    # S1 is an amount variable requested as amount, S2 a concentration variable requested as concentration
    same = requested_frame(df, quantities, SETTINGS)
    assert list(same.columns) == ["time", "S1", "S2"]
    assert same["S1"].tolist() == [4.0, 2.0] and same["S2"].tolist() == [1.0, 3.0]
    # swapped requests convert with the compartment
    swapped = Settings(0.0, 1.0, 1, ("S1", "S2"), 0, 0, frozenset({"S2"}), frozenset({"S1"}))
    converted = requested_frame(df, quantities, swapped)
    assert converted["S1"].tolist() == [2.0, 1.0]
    assert converted["S2"].tolist() == [2.0, 6.0]


def test_strip_brackets() -> None:
    df = pd.DataFrame({"time": [0.0], "[S1]": [1.0], "k": [2.0]})
    assert list(strip_brackets(df).columns) == ["time", "S1", "k"]
```

`tests/test_testsuite_results.py`:

```python
"""Tests of the suite results and the regression detection."""

from pathlib import Path

from sbml2cellml.testsuite.results import (
    STAGES,
    CaseResult,
    StageResult,
    SuiteResult,
    improvements,
    regressions,
)


def suite(status_00001: str, message: str = "") -> SuiteResult:
    stages = {stage: StageResult("pass") for stage in STAGES}
    stages["roundtrip"] = StageResult(status_00001, message, 0.5 if status_00001 == "fail" else None)
    return SuiteResult(
        suite="3.5.0",
        version="0.1.0",
        cases={
            "00001": CaseResult("00001", ["Amount"], ["Compartment", "Species"], stages),
            "00002": CaseResult("00002", [], [], {stage: StageResult("skip", "x") for stage in STAGES}),
        },
        skipped={"00003": "package comp"},
    )


def test_json_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    original = suite("fail", "S1 exceeds the tolerance")
    original.to_json(path)
    text = path.read_text()
    assert text.startswith("{")
    assert '"00001"' in text and "timestamp" not in text
    loaded = SuiteResult.from_json(path)
    assert loaded == original
    original.to_json(path)
    assert path.read_text() == text  # deterministic


def test_counts() -> None:
    result = suite("fail")
    assert result.counts("roundtrip") == {"pass": 0, "fail": 1, "skip": 1}
    assert result.counts("reference") == {"pass": 1, "fail": 0, "skip": 1}


def test_regressions_and_improvements() -> None:
    old = suite("pass")
    new = suite("fail", "S1 exceeds the tolerance")
    assert regressions(old, new) == ["00001 roundtrip: pass -> fail (S1 exceeds the tolerance)"]
    assert regressions(new, old) == []
    assert improvements(new, old) == ["00001 roundtrip: fail -> pass"]
    missing = suite("pass")
    del missing.cases["00002"]
    assert regressions(old, missing) == ["00002: missing"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_testsuite_compare.py tests/test_testsuite_results.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the modules**

`src/sbml2cellml/testsuite/compare.py`:

```python
"""Comparison of a simulation with the expected results of a case.

The SBML test suite accepts a value when
`|value - expected| <= absolute + relative * |expected|` at every time point,
with the tolerances of the case. Species are expected either as amounts or
as concentrations (the `amount` and `concentration` lists of the settings);
a converted model carries every species in one quantity, so the columns are
converted with the compartment before the comparison.
"""

from dataclasses import dataclass

import libsbml
import numpy as np
import pandas as pd
import pytest

from sbml2cellml.testsuite.cases import Settings

TIME = "time"


@dataclass(frozen=True)
class VariableComparison:
    """Result of one variable."""

    variable: str
    max_error: float
    max_excess: float
    passed: bool


@dataclass(frozen=True)
class Comparison:
    """Result of a case: every variable and the verdict."""

    variables: tuple[VariableComparison, ...]
    passed: bool
    message: str

    @property
    def max_excess(self) -> float:
        """Largest excess over the tolerance, negative when everything passes."""
        return max((v.max_excess for v in self.variables), default=float("nan"))


def _failed(message: str) -> Comparison:
    return Comparison(variables=(), passed=False, message=message)


def compare(result: pd.DataFrame, expected: pd.DataFrame, settings: Settings) -> Comparison:
    """Compare a simulation with the expected results.

    Args:
        result: timecourse with a `time` column and the settings variables.
        expected: expected timecourse of the case.
        settings: settings of the case (variables and tolerances).

    Returns:
        The comparison; `passed` when every variable is within the tolerance
        at every time point.
    """
    if len(result) != len(expected):
        return _failed(f"{len(result)} rows instead of {len(expected)}")
    if TIME not in result.columns:
        return _failed("no time column")
    if not np.allclose(result[TIME].to_numpy(), expected[TIME].to_numpy(), rtol=1e-6, atol=1e-9):
        return _failed("time points differ from the expected results")

    comparisons: list[VariableComparison] = []
    failures: list[str] = []
    for variable in settings.variables:
        if variable not in result.columns:
            return _failed(f"variable {variable} missing in the result")
        if variable not in expected.columns:
            return _failed(f"variable {variable} missing in the expected results")
        values = result[variable].to_numpy(dtype=float)
        target = expected[variable].to_numpy(dtype=float)
        error = np.abs(values - target)
        error = np.where(np.isnan(error), np.inf, error)
        tolerance = settings.absolute + settings.relative * np.abs(target)
        excess = float(np.max(error - tolerance))
        passed = excess <= 0
        comparisons.append(VariableComparison(variable, float(np.max(error)), excess, passed))
        if not passed:
            failures.append(f"{variable} exceeds the tolerance by {excess:.3g}")
    return Comparison(tuple(comparisons), not failures, "; ".join(failures))


def species_quantities(model: libsbml.Model) -> dict[str, tuple[bool, str]]:
    """Quantity of the species variables of a converted model.

    Args:
        model: the original SBML model.

    Returns:
        Species id to `(has only substance units, compartment id)`: the
        converted variable is an amount when the flag is set, else a
        concentration.
    """
    return {
        species.getId(): (bool(species.getHasOnlySubstanceUnits()), species.getCompartment())
        for species in model.getListOfSpecies()
    }


def requested_frame(
    df: pd.DataFrame, quantities: dict[str, tuple[bool, str]], settings: Settings
) -> pd.DataFrame:
    """The settings variables in the quantity the case expects.

    Args:
        df: timecourse of a converted model (every variable a column,
            including the compartments).
        quantities: result of `species_quantities`.
        settings: settings of the case.

    Returns:
        `time` and the settings variables, species converted between amount
        and concentration with their compartment column when needed. A
        variable missing in `df` is left out (the comparison reports it).
    """
    out = pd.DataFrame({TIME: df[TIME]})
    for variable in settings.variables:
        if variable not in df.columns:
            continue
        values = df[variable]
        if variable in quantities:
            in_amount, compartment = quantities[variable]
            want_amount = variable in settings.amount
            if compartment in df.columns:
                size = df[compartment]
                if in_amount and not want_amount:
                    values = values / size
                elif not in_amount and want_amount:
                    values = values * size
        out[variable] = values.to_numpy()
    return out


def strip_brackets(df: pd.DataFrame) -> pd.DataFrame:
    """Rename roadrunner's `[S]` concentration columns to `S`."""
    return df.rename(columns={c: c[1:-1] for c in df.columns if c.startswith("[") and c.endswith("]")})
```

`src/sbml2cellml/testsuite/results.py`:

```python
"""Results of a suite run: per case and stage, JSON, regressions."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

#: the stages of the pipeline, in order
STAGES = ("reference", "sbml2cellml", "libopencor", "cellml2sbml", "roundtrip")
#: possible statuses of a stage
STATUSES = ("pass", "fail", "skip")


@dataclass
class StageResult:
    """Outcome of one stage of one case."""

    status: str
    message: str = ""
    max_excess: float | None = None


@dataclass
class CaseResult:
    """Outcome of one case."""

    id: str
    test_tags: list[str]
    component_tags: list[str]
    stages: dict[str, StageResult]


@dataclass
class SuiteResult:
    """Outcome of a suite run."""

    suite: str
    version: str
    cases: dict[str, CaseResult] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)

    def counts(self, stage: str) -> dict[str, int]:
        """Number of cases per status of a stage."""
        counts = dict.fromkeys(STATUSES, 0)
        for case in self.cases.values():
            counts[case.stages[stage].status] += 1
        return counts

    def to_json(self, path: Path) -> None:
        """Write the result as JSON, sorted and indented (deterministic)."""
        data: dict[str, Any] = {
            "suite": self.suite,
            "version": self.version,
            "cases": {cid: asdict(case) for cid, case in sorted(self.cases.items())},
            "skipped": dict(sorted(self.skipped.items())),
        }
        Path(path).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    @classmethod
    def from_json(cls, path: Path) -> "SuiteResult":
        """Read a result written by `to_json`."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        cases = {
            cid: CaseResult(
                id=case["id"],
                test_tags=list(case["test_tags"]),
                component_tags=list(case["component_tags"]),
                stages={name: StageResult(**stage) for name, stage in case["stages"].items()},
            )
            for cid, case in data["cases"].items()
        }
        return cls(suite=data["suite"], version=data["version"], cases=cases, skipped=dict(data["skipped"]))


def regressions(old: SuiteResult, new: SuiteResult) -> list[str]:
    """Stages which passed before and do not pass now, and missing cases.

    Args:
        old: committed result.
        new: current result.

    Returns:
        One line per regression, e.g. `00001 roundtrip: pass -> fail (message)`.
    """
    lines: list[str] = []
    for cid, case in sorted(old.cases.items()):
        if cid not in new.cases:
            lines.append(f"{cid}: missing")
            continue
        for stage in STAGES:
            before = case.stages[stage].status
            after = new.cases[cid].stages[stage]
            if before == "pass" and after.status != "pass":
                lines.append(f"{cid} {stage}: pass -> {after.status} ({after.message})")
    return lines


def improvements(old: SuiteResult, new: SuiteResult) -> list[str]:
    """Stages which did not pass before and pass now."""
    lines: list[str] = []
    for cid, case in sorted(new.cases.items()):
        if cid not in old.cases:
            lines.append(f"{cid}: new")
            continue
        for stage in STAGES:
            before = old.cases[cid].stages[stage].status
            if before != "pass" and case.stages[stage].status == "pass":
                lines.append(f"{cid} {stage}: {before} -> pass")
    return lines
```

- [ ] **Step 4: Run the tests, lint, type check, commit**

Run: `uv run pytest tests/test_testsuite_compare.py tests/test_testsuite_results.py -v` (all pass; fix the placeholder assertion in the compare test as noted).

```bash
uv run ruff check && uv run ruff format && uv run ty check
git add src/sbml2cellml/testsuite/compare.py src/sbml2cellml/testsuite/results.py tests/test_testsuite_compare.py tests/test_testsuite_results.py
git commit -m "Add the comparison with the expected results and the suite results"
```

---

### Task 4: The pipeline

**Files:**
- Create: `src/sbml2cellml/testsuite/runner.py`
- Test: `tests/test_testsuite_runner.py`

**Interfaces:**
- Produces: `runner.run_case(case, work_dir, roadrunner, libopencor) -> CaseResult`, `runner.run_suite(cases, work_dir, timeout=60.0, progress=None) -> SuiteResult`, `runner.reference_selections(case, model) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_testsuite_runner.py`:

```python
"""Tests of the pipeline on the fixture cases."""

from pathlib import Path

import libsbml

from sbml2cellml import __version__
from sbml2cellml.testsuite.cases import SUITE_VERSION, load_cases
from sbml2cellml.testsuite.results import STAGES, STATUSES, SuiteResult
from sbml2cellml.testsuite.runner import reference_selections, run_suite

FIXTURES = Path(__file__).parent / "data" / "testsuite" / "semantic"


def test_reference_selections() -> None:
    case = load_cases(FIXTURES, ids=["00001"])[0]
    model = libsbml.readSBMLFromFile(str(case.sbml_path)).getModel()
    # 00001 expects amounts
    assert reference_selections(case, model) == ["S1", "S2"]
    concentration = case.settings.__class__(
        **{**case.settings.__dict__, "amount": frozenset(), "concentration": frozenset({"S1", "S2"})}
    )
    case_c = case.__class__(**{**case.__dict__, "settings": concentration})
    assert reference_selections(case_c, model) == ["[S1]", "[S2]"]


def test_run_suite_on_fixtures(tmp_path: Path) -> None:
    cases = load_cases(FIXTURES)
    seen: list[str] = []
    result = run_suite(cases, tmp_path, timeout=60.0, progress=seen.append)
    assert result.suite == SUITE_VERSION
    assert result.version == __version__
    assert set(result.cases) == {c.id for c in cases}
    assert result.skipped == {}
    assert len(seen) == len(cases)
    for case in result.cases.values():
        assert set(case.stages) == set(STAGES)
        for stage in case.stages.values():
            assert stage.status in STATUSES
    first = result.cases["00001"].stages
    assert first["reference"].status == "pass", first["reference"].message
    assert first["sbml2cellml"].status == "pass", first["sbml2cellml"].message
    assert (tmp_path / "00001.cellml").is_file()
    # a stage after a failed conversion is skipped, never run
    for case in result.cases.values():
        if case.stages["sbml2cellml"].status == "fail":
            assert case.stages["libopencor"].status == "skip"
            assert case.stages["cellml2sbml"].status == "skip"
            assert case.stages["roundtrip"].status == "skip"
    path = tmp_path / "results.json"
    result.to_json(path)
    assert SuiteResult.from_json(path) == result


def test_run_suite_skips_unrunnable(tmp_path: Path) -> None:
    import shutil

    root = tmp_path / "semantic"
    shutil.copytree(FIXTURES / "00001", root / "00001")
    (root / "00001" / "00001-sbml-l3v2.xml").unlink()
    result = run_suite(load_cases(root), tmp_path / "work")
    assert result.cases == {}
    assert result.skipped == {"00001": "no L3V2 file"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_testsuite_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sbml2cellml.testsuite.runner'`.

- [ ] **Step 3: Write the module**

`src/sbml2cellml/testsuite/runner.py`:

```python
"""The pipeline of the harness.

Every runnable case goes through five stages: the reference simulation of
the original SBML with roadrunner, the conversion to CellML, the libopencor
simulation of the CellML, the conversion back to SBML and the roadrunner
simulation of the roundtrip SBML. Every simulation is compared with the
expected results of the case. The simulators run in worker processes, the
conversions in this process.
"""

import logging
from collections.abc import Callable
from pathlib import Path

import libsbml

from sbml2cellml import __version__, convert_cellml2sbml, convert_sbml2cellml
from sbml2cellml.testsuite.cases import SUITE_VERSION, Case, skip_reason
from sbml2cellml.testsuite.compare import (
    Comparison,
    compare,
    requested_frame,
    species_quantities,
    strip_brackets,
)
from sbml2cellml.testsuite.results import CaseResult, StageResult, SuiteResult
from sbml2cellml.testsuite.worker import SimulatorWorker, frame

logger = logging.getLogger(__name__)

#: length of a failure message
MESSAGE_LENGTH = 200


def _message(err: BaseException) -> str:
    """Type and first line of an exception, shortened."""
    first = str(err).strip().splitlines()[0] if str(err).strip() else ""
    return f"{type(err).__name__}: {first}"[:MESSAGE_LENGTH]


def _stage(comparison: Comparison) -> StageResult:
    """Stage result of a comparison."""
    return StageResult(
        "pass" if comparison.passed else "fail",
        comparison.message[:MESSAGE_LENGTH],
        None if not comparison.variables else comparison.max_excess,
    )


def reference_selections(case: Case, model: libsbml.Model) -> list[str]:
    """Roadrunner selections of the settings variables of the original model.

    A species expected as concentration is selected as `[id]`, everything
    else by id.
    """
    species = {s.getId() for s in model.getListOfSpecies()}
    return [
        f"[{v}]" if v in species and v in case.settings.concentration else v
        for v in case.settings.variables
    ]


def run_case(
    case: Case, work_dir: Path, roadrunner: SimulatorWorker, libopencor: SimulatorWorker
) -> CaseResult:
    """Run the five stages of a case.

    Args:
        case: a runnable case.
        work_dir: directory for the converted files.
        roadrunner: worker for the SBML simulations.
        libopencor: worker for the CellML simulation.

    Returns:
        The stage results; a stage whose input stage failed is `skip`.
    """
    assert case.sbml_path is not None
    settings = case.settings
    stages: dict[str, StageResult] = {}
    model = libsbml.readSBMLFromFile(str(case.sbml_path)).getModel()
    quantities = species_quantities(model)
    compartments = [c.getId() for c in model.getListOfCompartments()]

    # reference
    try:
        result = roadrunner.call(
            "simulate_sbml",
            sbml=case.sbml_path.read_text(encoding="utf-8"),
            selections=reference_selections(case, model),
            start=settings.start,
            end=settings.end,
            steps=settings.steps,
        )
        stages["reference"] = _stage(compare(strip_brackets(frame(result)), case.expected, settings))
    except Exception as err:  # noqa: BLE001 - every failure is a stage result
        stages["reference"] = StageResult("fail", _message(err))

    # sbml2cellml
    cellml_path = work_dir / f"{case.id}.cellml"
    try:
        convert_sbml2cellml(case.sbml_path, cellml_path=cellml_path, validate=True)
        stages["sbml2cellml"] = StageResult("pass")
    except Exception as err:  # noqa: BLE001
        stages["sbml2cellml"] = StageResult("fail", _message(err))
        for stage in ("libopencor", "cellml2sbml", "roundtrip"):
            stages[stage] = StageResult("skip", "sbml2cellml failed")
        return CaseResult(case.id, list(case.test_tags), list(case.component_tags), stages)

    # libopencor
    try:
        result = libopencor.call(
            "simulate_cellml",
            cellml_path=str(cellml_path),
            start=settings.start,
            end=settings.end,
            steps=settings.steps,
        )
        df = requested_frame(frame(result), quantities, settings)
        stages["libopencor"] = _stage(compare(df, case.expected, settings))
    except Exception as err:  # noqa: BLE001
        stages["libopencor"] = StageResult("fail", _message(err))

    # cellml2sbml
    roundtrip_path = work_dir / f"{case.id}-roundtrip.xml"
    try:
        convert_cellml2sbml(cellml_path, sbml_path=roundtrip_path, validate=True)
        stages["cellml2sbml"] = StageResult("pass")
    except Exception as err:  # noqa: BLE001
        stages["cellml2sbml"] = StageResult("fail", _message(err))
        stages["roundtrip"] = StageResult("skip", "cellml2sbml failed")
        return CaseResult(case.id, list(case.test_tags), list(case.component_tags), stages)

    # roundtrip
    try:
        selections = list(dict.fromkeys([*settings.variables, *compartments]))
        result = roadrunner.call(
            "simulate_sbml",
            sbml=roundtrip_path.read_text(encoding="utf-8"),
            selections=selections,
            start=settings.start,
            end=settings.end,
            steps=settings.steps,
        )
        df = requested_frame(frame(result), quantities, settings)
        stages["roundtrip"] = _stage(compare(df, case.expected, settings))
    except Exception as err:  # noqa: BLE001
        stages["roundtrip"] = StageResult("fail", _message(err))

    return CaseResult(case.id, list(case.test_tags), list(case.component_tags), stages)


def run_suite(
    cases: list[Case],
    work_dir: Path,
    timeout: float = 60.0,
    progress: Callable[[str], None] | None = None,
) -> SuiteResult:
    """Run the pipeline for every runnable case.

    Args:
        cases: the cases; unrunnable ones are recorded as skipped.
        work_dir: directory for the converted files, created if needed.
        timeout: seconds per simulator call.
        progress: called with the case id after every runnable case.

    Returns:
        The suite result.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    result = SuiteResult(suite=SUITE_VERSION, version=__version__)
    runnable = []
    for case in cases:
        reason = skip_reason(case)
        if reason is None:
            runnable.append(case)
        else:
            result.skipped[case.id] = reason
    if not runnable:
        return result
    with SimulatorWorker("roadrunner", timeout) as roadrunner, SimulatorWorker("libopencor", timeout) as libopencor:
        for case in runnable:
            logger.info("case %s", case.id)
            result.cases[case.id] = run_case(case, work_dir, roadrunner, libopencor)
            if progress is not None:
                progress(case.id)
    return result
```

- [ ] **Step 4: Run the tests, lint, type check, commit**

Run: `uv run pytest tests/test_testsuite_runner.py -v` and `-n 0`. Expected: all pass. If `reference` fails for `00001` print the message: roadrunner's default tolerances reproduce case 00001 (checked in a spike with error 1.7e-7 against tolerance 1e-7 + 1e-4 * value; if the comparison fails on this margin, set in `simulators.simulate_sbml` `rr.integrator.setValue("absolute_tolerance", 1e-10)` and `rr.integrator.setValue("relative_tolerance", 1e-8)` before simulating, and note it in the report). The libopencor stage of 00001 may fail for the same reason; that is a result, not a test failure.

```bash
uv run ruff check && uv run ruff format && uv run ty check
git add src/sbml2cellml/testsuite/runner.py tests/test_testsuite_runner.py
git commit -m "Add the test suite pipeline"
```

---

### Task 5: Report and command

**Files:**
- Create: `src/sbml2cellml/testsuite/report.py`, `src/sbml2cellml/testsuite/cli.py`
- Modify: `pyproject.toml` (`[project.scripts]`), `uv.lock`
- Test: `tests/test_testsuite_report.py`

**Interfaces:**
- Produces: `report.render_report(result) -> str`, `report.write_report(result, path)`, `cli.main(argv) -> int`, script `sbml2cellml-testsuite`.

- [ ] **Step 1: Write the failing tests**

`tests/test_testsuite_report.py`:

```python
"""Tests of the report and the command line."""

from pathlib import Path

import pytest

from sbml2cellml.testsuite.cli import main
from sbml2cellml.testsuite.report import render_report, write_report
from sbml2cellml.testsuite.results import STAGES, CaseResult, StageResult, SuiteResult

FIXTURES = Path(__file__).parent / "data" / "testsuite" / "semantic"


def sample() -> SuiteResult:
    ok = {stage: StageResult("pass") for stage in STAGES}
    bad = dict(ok)
    bad["libopencor"] = StageResult("fail", "S1 exceeds the tolerance by 0.5", 0.5)
    bad["roundtrip"] = StageResult("fail", "SimulationFailure: roadrunner: RuntimeError: x", None)
    return SuiteResult(
        "3.5.0",
        "0.1.0",
        {
            "00001": CaseResult("00001", ["Amount"], ["Compartment", "Species"], ok),
            "00002": CaseResult("00002", ["Amount"], ["Compartment"], bad),
        },
        {"00003": "package comp", "00004": "package comp", "00005": "no L3V2 file"},
    )


def test_render_report() -> None:
    text = render_report(sample())
    assert text.startswith("<!-- generated by sbml2cellml-testsuite, do not edit -->")
    assert "# SBML test suite" in text
    assert "3.5.0" in text and "0.1.0" in text
    assert "| libopencor | 1 | 1 | 0 |" in text
    assert "S1 exceeds the tolerance" in text
    assert "SimulationFailure: roadrunner: RuntimeError: x" in text
    assert "| package comp | 2 |" in text
    assert "| 00002 | Compartment | pass | pass | fail | pass | fail |" in text
    assert "—" not in text


def test_write_report(tmp_path: Path) -> None:
    path = tmp_path / "testsuite.md"
    write_report(sample(), path)
    assert path.read_text() == render_report(sample())


def test_cli_run_and_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    results = tmp_path / "results.json"
    report = tmp_path / "testsuite.md"
    code = main(
        [
            "run",
            "--suite-dir",
            str(FIXTURES),
            "--cases",
            "00001",
            "--work-dir",
            str(tmp_path / "work"),
            "--results",
            str(results),
            "--report",
            str(report),
        ]
    )
    assert code == 0
    assert results.is_file() and report.is_file()
    out = capsys.readouterr().out
    assert "00001" in out and "reference" in out
    report.unlink()
    assert main(["report", "--results", str(results), "--output", str(report)]) == 0
    assert report.is_file()


def test_cli_missing_results(tmp_path: Path) -> None:
    assert main(["report", "--results", str(tmp_path / "nope.json"), "--output", str(tmp_path / "r.md")]) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_testsuite_report.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the modules**

`src/sbml2cellml/testsuite/report.py`:

```python
"""Markdown report of a suite run, the page `docs/testsuite.md`."""

from collections import Counter, defaultdict
from pathlib import Path

from sbml2cellml.testsuite.results import STAGES, SuiteResult

HEADER = "<!-- generated by sbml2cellml-testsuite, do not edit -->"
#: case ids listed per failure reason
CASES_PER_REASON = 10


def _reason(message: str) -> str:
    """Group key of a failure message: the text before the first digit run or `by`."""
    cut = message.split(" by ")[0]
    return cut.split(" exceeds")[0] + (" exceeds the tolerance" if " exceeds" in message else "")


def render_report(result: SuiteResult) -> str:
    """Render the report.

    Args:
        result: a suite run.

    Returns:
        The markdown page.
    """
    lines: list[str] = [
        HEADER,
        "# SBML test suite",
        "",
        f"Semantic test cases of the [SBML test suite](https://github.com/sbmlteam/sbml-test-suite) "
        f"{result.suite}, run with sbml2cellml {result.version}. Every case is simulated with "
        "roadrunner (`reference`), converted to CellML (`sbml2cellml`), simulated with libopencor "
        "(`libopencor`), converted back to SBML (`cellml2sbml`) and simulated with roadrunner again "
        "(`roundtrip`); every simulation is compared with the expected results using the tolerances "
        "of the case. See [Development](development.md#sbml-test-suite) for how to run it.",
        "",
        "## Summary",
        "",
        f"{len(result.cases)} cases run, {len(result.skipped)} skipped.",
        "",
        "| stage | pass | fail | skip | pass rate |",
        "| --- | --- | --- | --- | --- |",
    ]
    for stage in STAGES:
        counts = result.counts(stage)
        total = len(result.cases) or 1
        lines.append(
            f"| {stage} | {counts['pass']} | {counts['fail']} | {counts['skip']} | "
            f"{100 * counts['pass'] / total:.1f}% |"
        )

    lines += ["", "## Failure reasons", ""]
    for stage in STAGES:
        groups: dict[str, list[str]] = defaultdict(list)
        for cid, case in sorted(result.cases.items()):
            stage_result = case.stages[stage]
            if stage_result.status == "fail":
                groups[_reason(stage_result.message)].append(cid)
        if not groups:
            continue
        lines += [f"### {stage}", "", "| reason | cases | examples |", "| --- | --- | --- |"]
        for reason, ids in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
            examples = ", ".join(ids[:CASES_PER_REASON])
            more = f", ... ({len(ids)} in total)" if len(ids) > CASES_PER_REASON else ""
            lines.append(f"| {reason} | {len(ids)} | {examples}{more} |")
        lines.append("")

    lines += ["## Skipped cases", "", "| reason | cases |", "| --- | --- |"]
    for reason, count in sorted(Counter(result.skipped.values()).items()):
        lines.append(f"| {reason} | {count} |")

    lines += [
        "",
        "## Cases",
        "",
        "| case | components | " + " | ".join(STAGES) + " |",
        "| --- | --- | " + " | ".join("---" for _ in STAGES) + " |",
    ]
    for cid, case in sorted(result.cases.items()):
        statuses = " | ".join(case.stages[stage].status for stage in STAGES)
        lines.append(f"| {cid} | {', '.join(case.component_tags)} | {statuses} |")
    lines.append("")
    return "\n".join(lines)


def write_report(result: SuiteResult, path: Path) -> None:
    """Write the report.

    Args:
        result: a suite run.
        path: markdown file, overwritten.
    """
    Path(path).write_text(render_report(result), encoding="utf-8")
```

`src/sbml2cellml/testsuite/cli.py`:

```python
"""The `sbml2cellml-testsuite` command.

    sbml2cellml-testsuite run [--cases 00001,00002] [--suite-dir DIR] [--work-dir DIR]
                              [--results FILE] [--report FILE] [--timeout SECONDS] [-v]
    sbml2cellml-testsuite report --results FILE --output FILE

`run` downloads the suite when no `--suite-dir` is given, runs the pipeline,
writes the results and the report. `report` renders a results file.
"""

import argparse
import logging
import sys
from pathlib import Path

from sbml2cellml import __version__, log
from sbml2cellml.testsuite.cases import TestSuiteError, ensure_suite, load_cases
from sbml2cellml.testsuite.report import write_report
from sbml2cellml.testsuite.results import STAGES, SuiteResult
from sbml2cellml.testsuite.runner import run_suite

DEFAULT_RESULTS = Path("testsuite") / "results.json"
DEFAULT_REPORT = Path("docs") / "testsuite.md"


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        The parser with the `run` and `report` subcommands.
    """
    parser = argparse.ArgumentParser(
        prog="sbml2cellml-testsuite",
        description="Run the SBML test suite through sbml2cellml and cellml2sbml.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run the suite, write results and report")
    run.add_argument("--cases", help="comma separated case ids, all by default")
    run.add_argument("--suite-dir", help="semantic directory of the suite, downloaded by default")
    run.add_argument("--work-dir", default="testsuite/work", help="directory for the converted files")
    run.add_argument("--results", default=str(DEFAULT_RESULTS), help="results file (json)")
    run.add_argument("--report", default=str(DEFAULT_REPORT), help="report file (markdown)")
    run.add_argument("--timeout", type=float, default=60.0, help="seconds per simulation")
    run.add_argument("-v", "--verbose", action="store_true", help="log the steps")

    report = subparsers.add_parser("report", help="render a results file")
    report.add_argument("--results", default=str(DEFAULT_RESULTS), help="results file (json)")
    report.add_argument("--output", default=str(DEFAULT_REPORT), help="report file (markdown)")
    return parser


def _run(args: argparse.Namespace) -> int:
    """The `run` subcommand."""
    if args.verbose:
        log.enable_rich_logging(logging.INFO)
    try:
        root = Path(args.suite_dir) if args.suite_dir else ensure_suite()
    except TestSuiteError as err:
        print(str(err), file=sys.stderr)
        return 1
    ids = [cid.strip() for cid in args.cases.split(",")] if args.cases else None
    cases = load_cases(root, ids)
    if not cases:
        print(f"No cases found in '{root}'", file=sys.stderr)
        return 1

    result = run_suite(cases, Path(args.work_dir), timeout=args.timeout, progress=print)
    for cid, case in result.cases.items():
        statuses = " ".join(f"{stage}={case.stages[stage].status}" for stage in STAGES)
        print(f"{cid} {statuses}")
    for stage in STAGES:
        counts = result.counts(stage)
        print(f"{stage}: {counts['pass']} pass, {counts['fail']} fail, {counts['skip']} skip")
    print(f"{len(result.skipped)} cases skipped")

    results_path = Path(args.results)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_json(results_path)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_report(result, report_path)
    print(f"{results_path}\n{report_path}")
    return 0


def _report(args: argparse.Namespace) -> int:
    """The `report` subcommand."""
    results_path = Path(args.results)
    if not results_path.is_file():
        print(f"Results file does not exist: '{results_path}'", file=sys.stderr)
        return 1
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_report(SuiteResult.from_json(results_path), output)
    print(output)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the command.

    Args:
        argv: arguments without the program name, `sys.argv[1:]` by default.

    Returns:
        0 on success, 1 on a missing suite or results file.
    """
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return _run(args)
    return _report(args)


if __name__ == "__main__":
    sys.exit(main())
```

`pyproject.toml` `[project.scripts]`: add `sbml2cellml-testsuite = "sbml2cellml.testsuite.cli:main"`; `uv sync --extra dev`.

- [ ] **Step 4: Run the tests, lint, type check, commit**

Run: `uv run pytest tests/test_testsuite_report.py -v` (all pass), `uv run sbml2cellml-testsuite --version`.

```bash
uv run ruff check && uv run ruff format && uv run ty check
git add src/sbml2cellml/testsuite/report.py src/sbml2cellml/testsuite/cli.py tests/test_testsuite_report.py pyproject.toml uv.lock
git commit -m "Add the test suite report and the sbml2cellml-testsuite command"
```

---

### Task 6: Full run, gating test, CI, documentation

**Files:**
- Create: `testsuite/results.json`, `docs/testsuite.md`, `tests/test_testsuite_full.py`, `docs/api/testsuite.*.md`
- Modify: `tox.ini`, `.github/workflows/ci-cd.yml`, `.gitignore` (`testsuite/work/`), `zensical.toml`, `docs/api/index.md`, `docs/development.md`, `docs/roadmap.md`, `docs/index.md`, `README.md`, `CLAUDE.md`, `release-notes/0.1.0.md`

- [ ] **Step 1: The gating test**

`tests/test_testsuite_full.py`:

```python
"""The complete SBML test suite, gated on regressions.

Enabled with `SBML2CELLML_TESTSUITE=1` (the linux CI job, `tox -e testsuite`).
Downloads the suite into the cache, runs every runnable case and compares
with the committed `testsuite/results.json`; the rendered report must equal
the committed `docs/testsuite.md`. Improvements are printed: rerun
`sbml2cellml-testsuite run` and commit both files to accept them.
"""

import os
from pathlib import Path

import pytest

from sbml2cellml.testsuite.cases import ensure_suite, load_cases
from sbml2cellml.testsuite.report import render_report
from sbml2cellml.testsuite.results import SuiteResult, improvements, regressions
from sbml2cellml.testsuite.runner import run_suite

REPO = Path(__file__).parent.parent
RESULTS = REPO / "testsuite" / "results.json"
REPORT = REPO / "docs" / "testsuite.md"

pytestmark = pytest.mark.testsuite


@pytest.mark.skipif(os.environ.get("SBML2CELLML_TESTSUITE") != "1", reason="SBML2CELLML_TESTSUITE=1 not set")
def test_full_suite_no_regression(tmp_path: Path) -> None:
    committed = SuiteResult.from_json(RESULTS)
    result = run_suite(load_cases(ensure_suite()), tmp_path / "work")
    better = improvements(committed, result)
    if better:
        print("improvements, rerun `sbml2cellml-testsuite run` and commit:\n" + "\n".join(better))
    worse = regressions(committed, result)
    assert worse == [], "regressions:\n" + "\n".join(worse)
    assert render_report(result) == REPORT.read_text(encoding="utf-8"), (
        "docs/testsuite.md is stale, rerun `sbml2cellml-testsuite run`"
    )
```

- [ ] **Step 2: tox, CI, gitignore**

`tox.ini`: add to `[testenv]` `passenv =\n    SBML2CELLML_TESTSUITE\n    SBML2CELLML_CACHE` (merge with the existing `passenv` of the `ty` env if present; keep `TY_OUTPUT_FORMAT` there) and a new env:

```ini
[testenv:testsuite]
runner = uv-venv-lock-runner
extras =
    dev
setenv =
    SBML2CELLML_TESTSUITE = 1
passenv =
    SBML2CELLML_CACHE
commands =
    pytest -n 0 -m testsuite tests/test_testsuite_full.py
```

`.github/workflows/ci-cd.yml` `test` job: before "Test with tox" add

```yaml
    - name: Cache the SBML test suite
      uses: actions/cache@v4
      with:
        path: ~/.cache/sbml2cellml
        key: sbml-test-suite-3.5.0
```

and give the "Test with tox" step

```yaml
      env:
        # the complete SBML test suite runs on linux only
        SBML2CELLML_TESTSUITE: ${{ runner.os == 'Linux' && '1' || '' }}
```

(`actions/cache@v4` is the current major; check `gh api repos/actions/cache/releases/latest --jq .tag_name` and use the latest major.) `.gitignore`: add `testsuite/work/` under the examples results entry.

- [ ] **Step 3: Run the full suite and commit the results**

```bash
uv run sbml2cellml-testsuite run -v 2>&1 | tail -12
ls -la testsuite/results.json docs/testsuite.md
uv run tox r -e testsuite 2>&1 | tail -3
```

Expected: the run finishes (minutes), writes both files, the `testsuite` tox env passes (no regression against the just written results, report equal). Put the summary lines (per stage pass/fail/skip) in the task report. If the run aborts, fix the harness; if single cases hang beyond the timeout they are recorded as `fail timeout`.

- [ ] **Step 4: Documentation**

- `docs/api/testsuite.cases.md` ... one page per module (`cases`, `compare`, `results`, `runner`, `report`, `worker`, `simulators`, `cli`) with `::: sbml2cellml.testsuite.<module>`; `docs/api/index.md` gains a section "sbml2cellml.testsuite" with a table of these modules; `zensical.toml` nav: `{ "SBML test suite" = "testsuite.md" }` after Roadmap, and under "API reference" a `{ "sbml2cellml.testsuite" = [ ... ] }` list.
- `docs/development.md`: section `## SBML test suite { #sbml-test-suite }` before "Release": what the harness does (one paragraph, the five stages), `uv run sbml2cellml-testsuite run` (downloads to `~/.cache/sbml2cellml`, `SBML2CELLML_CACHE` overrides, `--cases` for a subset, `--suite-dir` for a local copy), the committed files, the gating test (`tox -e testsuite`, `SBML2CELLML_TESTSUITE=1`, linux CI), how to accept improvements (rerun, commit `testsuite/results.json` and `docs/testsuite.md` in the same pull request), the process rule (roadrunner and libopencor in separate worker processes because of their LLVM versions; the S2 sentence can point here).
- `docs/roadmap.md`: item 2 "SBML test suite roundtrip: done, see [SBML test suite](testsuite.md)"; under conversion gaps add one sentence pointing to the failure reasons of the report as the work list of S5.
- `docs/index.md` and `README.md`: feature bullet "- the SBML test suite harness: every semantic case through both converters and both simulators, results on the [SBML test suite](https://matthiaskoenig.github.io/sbml2cellml/testsuite/) page" (README uses the absolute URL, index the relative link); mention the `testsuite` extra in `docs/installation.md` (one paragraph: `pip install "sbml2cellml[testsuite]"` plus the libopencor wheel).
- `CLAUDE.md`: commands (`uv run sbml2cellml-testsuite run`, `tox r -e testsuite`), architecture entry for `testsuite/` (modules and the process model), conventions: "`testsuite/results.json` and `docs/testsuite.md` are generated by the command and committed; the full-suite test fails on regressions against them; accept improvements by regenerating both".
- `release-notes/0.1.0.md`: feature line for the harness and the `sbml2cellml-testsuite` command.

Build: `uv run zensical build --clean --strict && uv run python scripts/llms_txt.py` (zero warnings; the large generated page must build), `grep -rn "—" docs/*.md README.md CLAUDE.md` nothing.

- [ ] **Step 5: Full checks and commits**

```bash
uv run pytest
uv run ruff check && uv run ruff format --check && uv run ty check
uv run pre-commit run --all-files
git add tests/test_testsuite_full.py tox.ini .github/workflows/ci-cd.yml .gitignore
git commit -m "Gate the SBML test suite on regressions in CI"
git add testsuite/results.json docs/testsuite.md
git commit -m "Add the SBML test suite results"
git add docs zensical.toml README.md CLAUDE.md release-notes/0.1.0.md
git commit -m "Document the SBML test suite harness"
```

`pre-commit`'s `check-added-large-files` (500 kB) may reject `testsuite/results.json` or `docs/testsuite.md`; if so, raise `--maxkb` in `.pre-commit-config.yaml` to `2000` with a comment naming the two generated files, and include that in the results commit.

---

### Task 7: Pull request

Run by the main session: full verification, push, `gh pr create --base develop`, watch the checks (the linux job now downloads and runs the suite; note its duration in the PR).
