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
            "simulate_sbml",
            sbml=sbml,
            selections=["S1", "S2"],
            start=0.0,
            end=5.0,
            steps=50,
        )
    df = frame(result)
    assert list(df.columns) == ["time", "S1", "S2"]
    assert len(df) == 51
    assert df["time"].iloc[-1] == pytest.approx(5.0)
    assert df["S1"].iloc[0] == pytest.approx(1.5e-4)


def test_simulate_cellml_in_worker() -> None:
    with SimulatorWorker("libopencor") as worker:
        result = worker.call(
            "simulate_cellml",
            cellml_path=str(TEST_MODEL_PATH),
            start=0.0,
            end=10.0,
            steps=5,
        )
    df = frame(result)
    assert list(df.columns) == ["t", "m", "alpha"]
    assert len(df) == 6


def test_worker_error_is_raised() -> None:
    with SimulatorWorker("roadrunner") as worker:
        with pytest.raises(SimulationFailure, match=r"RuntimeError|Exception"):
            worker.call(
                "simulate_sbml",
                sbml="<sbml/>",
                selections=[],
                start=0.0,
                end=1.0,
                steps=1,
            )
        # the worker survives an error
        sbml = (FIXTURES / "00001" / "00001-sbml-l3v2.xml").read_text()
        assert frame(
            worker.call(
                "simulate_sbml",
                sbml=sbml,
                selections=["S1"],
                start=0.0,
                end=1.0,
                steps=1,
            )
        ).shape == (2, 2)


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
            rr.call(
                "simulate_sbml",
                sbml=sbml,
                selections=["S1"],
                start=0.0,
                end=1.0,
                steps=2,
            )
            oc.call(
                "simulate_cellml",
                cellml_path=str(TEST_MODEL_PATH),
                start=0.0,
                end=1.0,
                steps=2,
            )


def test_unknown_function() -> None:
    with SimulatorWorker("x") as worker, pytest.raises(SimulationFailure, match="nope"):
        worker.call("nope")
