"""SBML to CellML to SBML roundtrips, checked by simulation.

Skipped without roadrunner (and libopencor for the CellML side); both are
part of the dev extra. roadrunner bundles a different LLVM than libopencor
and the two crash once both have JIT-compiled in one interpreter, so
roadrunner is only ever run in a subprocess (see `tests/simulators.py`); the
availability check below uses `importlib.util.find_spec` instead of
`pytest.importorskip` so it does not itself import (and thus load) roadrunner
into this, the libopencor-using, process.
"""

import importlib.util
from pathlib import Path

import libsbml
import numpy as np
import pytest

from sbml2cellml import convert_cellml2sbml, convert_sbml2cellml
from sbml2cellml.sbml import document_to_string
from tests.conftest import MODELS_DIR, TEST_MODEL_PATH
from tests.sbml_models import simple_model, write_sbml
from tests.simulators import simulate_sbml

if importlib.util.find_spec("roadrunner") is None:
    pytest.skip("roadrunner not installed", allow_module_level=True)

END = 100.0
STEPS = 10


def test_roundtrip_glimepiride_liver(tmp_path: Path) -> None:
    sbml_path = MODELS_DIR / "glimepiride_liver.xml"
    cellml_path = tmp_path / "liver.cellml"
    convert_sbml2cellml(sbml_path, cellml_path=cellml_path)
    doc = convert_cellml2sbml(cellml_path)

    original = libsbml.readSBMLFromFile(str(sbml_path)).getModel()
    roundtrip = doc.getModel()
    original_ids = (
        {c.getId() for c in original.getListOfCompartments()}
        | {s.getId() for s in original.getListOfSpecies()}
        | {p.getId() for p in original.getListOfParameters()}
    )
    assert {p.getId() for p in roundtrip.getListOfParameters()} == original_ids

    species_with_reactions = {
        ref.getSpecies()
        for reaction in original.getListOfReactions()
        for ref in list(reaction.getListOfReactants())
        + list(reaction.getListOfProducts())
    }
    rate_rules = {r.getVariable() for r in roundtrip.getListOfRules() if r.isRate()}
    original_rate_rules = {
        r.getVariable() for r in original.getListOfRules() if r.isRate()
    }
    assert rate_rules == species_with_reactions | original_rate_rules

    # the species of the original are concentrations or amounts; the roundtrip
    # parameters carry the same quantity, so the timecourses agree
    selections = sorted(s.getId() for s in original.getListOfSpecies())
    expected = simulate_sbml(
        sbml_path.read_text(),
        [
            f"[{s}]"
            if original.getSpecies(s).getHasOnlySubstanceUnits() is False
            else s
            for s in selections
        ],
        start=0.0,
        end=END,
        steps=STEPS,
    )
    result = simulate_sbml(
        document_to_string(doc), selections, start=0.0, end=END, steps=STEPS
    )
    np.testing.assert_allclose(result, expected, rtol=1e-4, atol=1e-8)


def test_roundtrip_test_model(tmp_path: Path) -> None:
    """The SBML of test_model.cellml simulates like the CellML in libopencor."""
    pytest.importorskip("libopencor")
    from sbml2cellml.simulate import run_timecourse

    doc = convert_cellml2sbml(TEST_MODEL_PATH)
    result = simulate_sbml(
        document_to_string(doc), ["m"], start=0.0, end=END, steps=STEPS
    )
    df, _ = run_timecourse(TEST_MODEL_PATH, start=0.0, end=END, steps=STEPS)
    np.testing.assert_allclose(result[:, 0], df["m"].to_numpy(), rtol=1e-4)


def test_roundtrip_simple_model(tmp_path: Path) -> None:
    """A decaying concentration species in a compartment of size 2 round-trips."""
    sbml_path = write_sbml(tmp_path / "simple.xml", simple_model())
    cellml_path = tmp_path / "simple.cellml"
    convert_sbml2cellml(sbml_path, cellml_path=cellml_path)
    doc = convert_cellml2sbml(cellml_path)
    expected = simulate_sbml(
        sbml_path.read_text(), ["[S1]", "S2"], start=0.0, end=10.0, steps=10
    )
    result = simulate_sbml(
        document_to_string(doc), ["S1", "S2"], start=0.0, end=10.0, steps=10
    )
    assert expected[0, 0] == 10.0 and expected[-1, 0] < 1.0  # S1 really decays
    np.testing.assert_allclose(result, expected, rtol=1e-4, atol=1e-8)
