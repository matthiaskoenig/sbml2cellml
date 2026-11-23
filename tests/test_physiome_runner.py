"""Tests of the Physiome runner: prepare_cases and run_physiome."""

from pathlib import Path

import pytest

from sbml2cellml.physiome import runner
from sbml2cellml.testsuite.results import CELLML_STAGES
from tests.physiome_mocks import (
    EXPOSURE_BROKEN,
    EXPOSURE_MISSING,
    EXPOSURE_MULTI,
    mock_workspaces,
)


@pytest.fixture(autouse=True)
def _mocks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mock_workspaces(monkeypatch, tmp_path / "workspaces")


def test_prepare_cases() -> None:
    cases, skipped = runner.prepare_cases([EXPOSURE_MULTI])
    assert [case.case.id for case in cases] == ["multi"]
    assert skipped == {}


def test_prepare_cases_skips_a_workspace_which_cannot_be_cloned() -> None:
    cases, skipped = runner.prepare_cases([EXPOSURE_MISSING])
    assert cases == []
    assert skipped == {"missing": "PhysiomeError: Exposure missing cannot be cloned"}


def test_prepare_cases_skips_an_unanalysable_model() -> None:
    cases, skipped = runner.prepare_cases([EXPOSURE_BROKEN])
    assert cases == []
    assert skipped == {"broken": "model cannot be analysed"}


def test_run_physiome(tmp_path: Path) -> None:
    result = runner.run_physiome(
        [EXPOSURE_MULTI, EXPOSURE_MISSING], work_dir=tmp_path / "work"
    )
    assert result.suite == "physiome"
    assert result.stages == CELLML_STAGES
    assert result.skipped == {
        "missing": "PhysiomeError: Exposure missing cannot be cloned"
    }
    case = result.cases["multi"]
    assert case.name == EXPOSURE_MULTI.title
    assert set(case.stages) == set(CELLML_STAGES)
    # the whole pipeline of a model of two connected components with an
    # encapsulated child, from the CellML side
    assert case.stages["libopencor"].status == "pass"
    assert case.stages["cellml2sbml"].status == "pass"
    assert case.stages["sbmlsim"].status == "pass"
    assert case.stages["sbml2cellml"].status == "pass"
    assert case.stages["roundtrip"].status == "pass"
    # the states decay, so the expected results move more than the tolerance
    assert case.informative is True
    assert (tmp_path / "work" / "multi.xml").is_file()
    assert (tmp_path / "work" / "multi-roundtrip.cellml").is_file()


def test_run_physiome_without_cases(tmp_path: Path) -> None:
    result = runner.run_physiome([EXPOSURE_MISSING], work_dir=tmp_path / "work")
    assert result.cases == {}
    assert set(result.skipped) == {"missing"}
