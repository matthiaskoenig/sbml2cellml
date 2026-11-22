"""Tests of the pipeline on the fixture cases."""

import dataclasses
import shutil
from pathlib import Path
from typing import Any, cast

import libsbml
import pytest

from sbml2cellml import __version__
from sbml2cellml.testsuite.cases import SUITE_VERSION, load_cases
from sbml2cellml.testsuite.results import STAGES, STATUSES, SuiteResult
from sbml2cellml.testsuite.runner import (
    SOLVER_SETTINGS,
    _message,
    _simulate,
    run_suite,
    selections,
)
from sbml2cellml.testsuite.worker import SimulationFailure, SimulatorWorker
from tests.sbml_models import simple_model, write_sbml

FIXTURES = Path(__file__).parent / "data" / "testsuite" / "semantic"


def test_message_keeps_every_line() -> None:
    # the report shows the complete error, e.g. every issue of a validation
    class CellMLValidationError(Exception):
        pass

    err = CellMLValidationError(
        "CellML model 'x' converted from '/some/path' has 2 errors:\n"
        "[ERROR] the first issue  \n"
        "[ERROR] the second issue\n"
    )
    assert _message(err) == (
        "CellMLValidationError: CellML model 'x' converted from 'path' has 2 errors:\n"
        "[ERROR] the first issue\n"
        "[ERROR] the second issue"
    )


def test_message_is_not_shortened() -> None:
    text = "the variable " + ", ".join(f"S{k}" for k in range(500)) + " is missing"
    assert _message(ValueError(text)) == f"ValueError: {text}"


def test_message_single_line_unchanged() -> None:
    err = ValueError("no time column")
    assert _message(err) == "ValueError: no time column"


def test_message_reduces_absolute_paths_to_basename() -> None:
    # the message must not depend on $HOME or where the suite was checked
    # out, or the committed docs/testsuite.md would differ across machines
    err = ValueError("model '/home/x/y/z/case.xml' is invalid")
    message = _message(err)
    assert "'case.xml'" in message
    assert "/home/" not in message


def test_message_rounds_long_decimals() -> None:
    # a solver diagnostic (e.g. CVODE) prints full machine precision, which
    # is an artifact of the solver and the machine it ran on and would churn
    # the committed message across machines; rounded to 3 significant digits
    err = RuntimeError("CVODE: at t = 0.0827801454102412, mxstep steps taken")
    message = _message(err)
    assert "0.0827801454102412" not in message
    assert "0.0828" in message


def test_message_keeps_long_decimals_outside_integrator_failures() -> None:
    # a constant of the model in the code a compiler error points at is no
    # artifact of the machine, and rounding it would shift the marker below
    text = "Compiler: expression is not assignable:\n  1 | x = --0.00166112956810631;"
    assert _message(RuntimeError(text)) == f"RuntimeError: {text}"


def test_selections() -> None:
    case = load_cases(FIXTURES, ids=["00001"])[0]
    model = libsbml.readSBMLFromFile(str(case.sbml_path)).getModel()
    # 00001 expects amounts
    assert selections(case, model) == ["S1", "S2"]
    concentration = dataclasses.replace(
        case.settings, amount=frozenset(), concentration=frozenset({"S1", "S2"})
    )
    case_c = dataclasses.replace(case, settings=concentration)
    assert selections(case_c, model) == ["[S1]", "[S2]"]


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
    assert first["sbmlsim"].status == "pass", first["sbmlsim"].message
    assert first["sbml2cellml"].status == "pass", first["sbml2cellml"].message
    # the simulated stages are timed, the conversions are not
    for stage in ("sbmlsim", "libopencor", "roundtrip"):
        seconds = first[stage].seconds
        assert seconds is not None and seconds > 0.0
    assert first["sbml2cellml"].seconds is None
    assert first["cellml2sbml"].seconds is None
    assert (tmp_path / "00001.cellml").is_file()
    # a stage after a failed conversion is skipped, never run
    for case in result.cases.values():
        if case.stages["sbml2cellml"].status == "fail":
            assert case.stages["libopencor"].status == "skip"
            assert case.stages["cellml2sbml"].status == "skip"
            assert case.stages["roundtrip"].status == "skip"
    path = tmp_path / "results.json"
    result.to_json(path)
    loaded = SuiteResult.from_json(path)
    # to_json rounds max_excess to 3 significant digits (so results.json is
    # stable across machines); everything else roundtrips exactly
    assert set(loaded.cases) == set(result.cases)
    for cid, case in loaded.cases.items():
        original = result.cases[cid]
        assert case.test_tags == original.test_tags
        assert case.component_tags == original.component_tags
        for stage, stage_result in case.stages.items():
            original_stage = original.stages[stage]
            assert stage_result.status == original_stage.status
            assert stage_result.message == original_stage.message
            if original_stage.max_excess is None:
                assert stage_result.max_excess is None
            else:
                assert stage_result.max_excess == pytest.approx(
                    original_stage.max_excess, rel=1e-2
                )


def test_run_suite_skips_unrunnable(tmp_path: Path) -> None:
    root = tmp_path / "semantic"
    shutil.copytree(FIXTURES / "00001", root / "00001")
    (root / "00001" / "00001-sbml-l3v2.xml").unlink()
    result = run_suite(load_cases(root), tmp_path / "work")
    assert result.cases == {}
    assert result.skipped == {"00001": "no L3V2 file"}


def test_run_suite_setup_failure(tmp_path: Path) -> None:
    # a present but unparsable L3V2 file must not abort the whole suite
    root = tmp_path / "semantic"
    shutil.copytree(FIXTURES / "00001", root / "00001")
    (root / "00001" / "00001-sbml-l3v2.xml").write_text("<sbml/>", encoding="utf-8")
    result = run_suite(load_cases(root), tmp_path / "work")
    stages = result.cases["00001"].stages
    assert set(stages) == set(STAGES)
    for stage in stages.values():
        assert stage.status == "fail"
        assert stage.message.startswith("setup:"), stage.message


def test_run_suite_without_expected_uses_the_reference_simulator(
    tmp_path: Path,
) -> None:
    """A case without expected results is compared against sbmlsim-core."""
    import dataclasses

    case = load_cases(FIXTURES, ids=["00001"])[0]
    case = dataclasses.replace(case, expected=None, name="first case")
    result = run_suite([case], tmp_path)
    stages = result.cases["00001"].stages
    assert stages["sbmlsim"].status == "pass" and stages["sbmlsim"].max_excess is None
    for stage in ("sbml2cellml", "libopencor", "cellml2sbml", "roundtrip"):
        assert stages[stage].status == "pass", (stage, stages[stage].message)
    assert result.cases["00001"].name == "first case"


def test_run_suite_reference_failure_skips_simulations(tmp_path: Path) -> None:
    import dataclasses
    import shutil

    root = tmp_path / "semantic"
    shutil.copytree(FIXTURES / "00001", root / "00001")
    sbml = root / "00001" / "00001-sbml-l3v2.xml"
    # a required package sbmlsim-core does not compile, the conversion still runs
    text = sbml.read_text().replace(
        "<sbml ",
        '<sbml xmlns:fbc="http://www.sbml.org/sbml/level3/version1/fbc/version2" '
        'fbc:required="true" ',
        1,
    )
    sbml.write_text(text)
    case = dataclasses.replace(load_cases(root)[0], expected=None)
    result = run_suite([case], tmp_path / "work")
    stages = result.cases["00001"].stages
    assert stages["sbmlsim"].status == "fail"
    assert (
        stages["libopencor"].status == "skip"
        and "sbmlsim failed" in stages["libopencor"].message
    )
    assert stages["roundtrip"].status == "skip"
    assert stages["sbml2cellml"].status in ("pass", "fail")


def test_run_suite_converts_quantities(tmp_path: Path) -> None:
    """A non-unit compartment exercises the amount/concentration conversion."""
    case_dir = tmp_path / "semantic" / "90001"
    case_dir.mkdir(parents=True)
    write_sbml(case_dir / "90001-sbml-l3v2.xml", simple_model("case90001"))
    (case_dir / "90001-settings.txt").write_text(
        "start: 0\n"
        "duration: 4\n"
        "steps: 8\n"
        "variables: S1, S2\n"
        "absolute: 1e-6\n"
        "relative: 1e-4\n"
        "amount: S1, S2\n"
        "concentration:\n",
        encoding="utf-8",
    )
    # cell has size 2; [S1](t) = 10 exp(-0.25 t), S1(t) = 2 [S1](t), and
    # S2(t) = 4 + 20 (1 - exp(-0.25 t)); verified against a simulation of
    # this exact model in a spike, agreeing to better than 1e-7 relative.
    (case_dir / "90001-results.csv").write_text(
        "time,S1,S2\n"
        "0,20,4\n"
        "0.5,17.64993805,6.350061948\n"
        "1,15.57601566,8.423984339\n"
        "1.5,13.74578558,10.25421442\n"
        "2,12.13061319,11.86938681\n"
        "2.5,10.70522857,13.29477143\n"
        "3,9.447331055,14.55266895\n"
        "3.5,8.337240394,15.66275961\n"
        "4,7.357588823,16.64241118\n",
        encoding="utf-8",
    )
    (case_dir / "90001-model.m").write_text(
        "componentTags: Compartment, Species, Reaction, Parameter\n"
        "testTags: Amount, NonUnityCompartment\n"
        "testType: TimeCourse\n",
        encoding="utf-8",
    )
    result = run_suite(load_cases(case_dir.parent), tmp_path / "work")
    stages = result.cases["90001"].stages
    for name in ("sbmlsim", "sbml2cellml", "libopencor", "cellml2sbml", "roundtrip"):
        assert stages[name].status == "pass", f"{name}: {stages[name].message}"


class _Worker:
    """Stand-in for a `SimulatorWorker`: fails the first `failures` calls."""

    def __init__(self, failures: int, message: str) -> None:
        self.failures = failures
        self.message = message
        self.calls: list[dict[str, Any]] = []

    def call(self, function: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if len(self.calls) <= self.failures:
            raise SimulationFailure(f"{self.message} ({len(self.calls)})")
        return {"columns": ["time"], "rows": [[0.0]]}


CVODE_FAILURE = "libopencor: RuntimeError: CVODE Error: CV_TOO_MUCH_WORK"


def test_simulate_uses_the_tight_settings_first() -> None:
    worker = _Worker(failures=0, message=CVODE_FAILURE)
    _simulate(cast(SimulatorWorker, worker), "simulate_sbml", start=0.0)
    assert worker.calls == [{"start": 0.0, **SOLVER_SETTINGS[0]}]


def test_simulate_relaxes_the_tolerances_when_cvode_fails() -> None:
    worker = _Worker(failures=1, message=CVODE_FAILURE)
    result = _simulate(cast(SimulatorWorker, worker), "simulate_sbml", start=0.0)
    assert result["columns"] == ["time"]
    assert worker.calls == [
        {"start": 0.0, **SOLVER_SETTINGS[0]},
        {"start": 0.0, **SOLVER_SETTINGS[1]},
    ]
    tight, relaxed = SOLVER_SETTINGS[0], SOLVER_SETTINGS[1]
    assert relaxed["relative_tolerance"] > tight["relative_tolerance"]
    assert relaxed["absolute_tolerance"] > tight["absolute_tolerance"]


def test_simulate_relaxes_the_tolerances_for_an_integration_error() -> None:
    """sbmlsim-core raises an `IntegrationError` instead of naming CVODE."""
    message = (
        "sbmlsim: IntegrationError: integration failed at t = 7.41e-07 (flag -1): "
        "CVode: mxstep steps taken before reaching tout."
    )
    worker = _Worker(failures=1, message=message)
    _simulate(cast(SimulatorWorker, worker), "simulate_sbml", start=0.0)
    assert len(worker.calls) == 2


def test_simulate_raises_the_first_failure_when_no_settings_integrate() -> None:
    worker = _Worker(failures=len(SOLVER_SETTINGS), message=CVODE_FAILURE)
    with pytest.raises(SimulationFailure, match=r"CV_TOO_MUCH_WORK \(1\)"):
        _simulate(cast(SimulatorWorker, worker), "simulate_sbml", start=0.0)
    assert len(worker.calls) == len(SOLVER_SETTINGS)


def test_simulate_does_not_retry_other_failures() -> None:
    """E.g. a required package: no settings of the solver help."""
    worker = _Worker(
        failures=1, message="sbmlsim: CompileError: required package is not supported"
    )
    with pytest.raises(SimulationFailure, match="required package"):
        _simulate(cast(SimulatorWorker, worker), "simulate_sbml", start=0.0)
    assert len(worker.calls) == 1
