"""Tests of the BioModels runner: prepare_cases and run_biomodels."""

from pathlib import Path

import libsbml
import pytest

from sbml2cellml.biomodels import runner
from sbml2cellml.testsuite.results import STAGES
from tests.biomodels_mocks import INFO_A, INFO_B, mock_downloads, write_comp_model


@pytest.fixture
def comp_path(tmp_path: Path) -> Path:
    return write_comp_model(tmp_path / "comp_model.xml")


@pytest.fixture(autouse=True)
def _mocks(monkeypatch: pytest.MonkeyPatch, comp_path: Path) -> None:
    mock_downloads(monkeypatch, runner, comp_path)


def _no_species_model(path: Path) -> Path:
    """Write an SBML file with a compartment but no species."""
    doc = libsbml.SBMLDocument(3, 2)
    model: libsbml.Model = doc.createModel()
    model.setId("no_species")
    compartment: libsbml.Compartment = model.createCompartment()
    compartment.setId("cell")
    compartment.setSize(1.0)
    compartment.setConstant(True)
    libsbml.writeSBMLToFile(doc, str(path))
    return path


def test_prepare_cases() -> None:
    cases, skipped = runner.prepare_cases(["BIOMD_A", "BIOMD_B", "BIOMD_C"])
    assert [case.id for case in cases] == ["BIOMD_A", "BIOMD_B"]
    assert "comp:package" in cases[1].component_tags
    assert skipped == {"BIOMD_C": "download failed: BioModelsError"}


def test_prepare_cases_skips_model_without_species(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_species_path = _no_species_model(tmp_path / "no_species.xml")
    monkeypatch.setattr(runner, "model_info", lambda model_id, cache=None: INFO_A)
    monkeypatch.setattr(
        runner, "download_model", lambda model_id, cache=None: no_species_path
    )
    cases, skipped = runner.prepare_cases(["BIOMD_A"])
    assert cases == []
    assert skipped == {"BIOMD_A": "no species"}


def test_run_biomodels(tmp_path: Path) -> None:
    result = runner.run_biomodels(["BIOMD_A", "BIOMD_B", "BIOMD_C"], work_dir=tmp_path)
    assert result.suite == "biomodels"
    assert result.skipped == {
        "BIOMD_B": "package comp",
        "BIOMD_C": "download failed: BioModelsError",
    }
    case_a = result.cases["BIOMD_A"]
    assert case_a.name == INFO_A.name
    assert set(case_a.stages) == set(STAGES)
    assert case_a.stages["reference"].status == "pass"
    assert case_a.stages["sbml2cellml"].status == "pass"
    # the liver model has no dose, so the reference, libopencor and roundtrip
    # trajectories are all constant zero and the tolerance comparison passes
    # trivially; still asserted explicitly, not merely "not fail"
    assert case_a.stages["libopencor"].status == "pass"
    assert case_a.stages["roundtrip"].status == "pass"
    assert INFO_B.id not in result.cases
