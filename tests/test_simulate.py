"""Tests of the libopencor simulation.

Skipped when libopencor is not installed, see docs/installation.md.
"""

from pathlib import Path

import libsbml
import matplotlib
import numpy as np
import pytest

from sbml2cellml import convert_sbml2cellml
from sbml2cellml.cellml import write_model
from sbml2cellml.simulate import SimulationError, plot_timecourse, run_timecourse
from tests.cellml_models import algebraic_model, underconstrained_model
from tests.conftest import MODELS_DIR, TEST_MODEL_PATH
from tests.sbml_models import simple_model, write_sbml

pytest.importorskip("libopencor")
matplotlib.use("Agg")


def test_run_timecourse_test_model() -> None:
    df, units = run_timecourse(TEST_MODEL_PATH, start=0.0, end=50.0, steps=10)
    assert list(df.columns) == ["t", "m", "alpha"]
    assert len(df) == 11
    assert df["t"].iloc[0] == 0.0
    assert df["t"].iloc[-1] == 50.0
    assert df["m"].iloc[0] == 10.0
    assert np.all(np.diff(df["m"].to_numpy()) < 0)
    assert (df["alpha"] == 0.05).all()
    assert units == {"t": "second", "m": "kilogram", "alpha": "per_second"}


def test_run_timecourse_liver(tmp_path: Path) -> None:
    cellml_path = tmp_path / "liver.cellml"
    convert_sbml2cellml(MODELS_DIR / "glimepiride_liver.xml", cellml_path=cellml_path)
    df, units = run_timecourse(cellml_path, end=10.0, steps=10)
    assert df.columns[0] == "time"
    assert len(df) == 11
    # every species is a state or an algebraic variable of the CellML model
    m_sbml = libsbml.readSBMLFromFile(
        str(MODELS_DIR / "glimepiride_liver.xml")
    ).getModel()
    for species in m_sbml.getListOfSpecies():
        assert species.getId() in df.columns
    # compartments are constants of the CellML model
    assert "Vli" in df.columns
    assert set(units) == set(df.columns)


def test_run_timecourse_invalid_model_raises(tmp_path: Path) -> None:
    """The issues of the libopencor analyser become a SimulationError."""
    cellml_path = tmp_path / "underconstrained.cellml"
    write_model(underconstrained_model(), cellml_path)
    with pytest.raises(SimulationError, match="variable 'k' in component 'main'"):
        run_timecourse(cellml_path)


def test_run_timecourse_kidney_assignment_rules(tmp_path: Path) -> None:
    """The targets of the assignment rules follow their rules at every time."""
    cellml_path = tmp_path / "kidney.cellml"
    convert_sbml2cellml(MODELS_DIR / "glimepiride_kidney.xml", cellml_path=cellml_path)
    df, _ = run_timecourse(cellml_path, end=100.0, steps=10)
    assert np.allclose(df["egfr"], df["f_renal_function"] * df["egfr_healthy"])
    assert np.allclose(df["crcl"], df["egfr"] * df["BSA"] / 1.73 * 1.1)


def test_run_timecourse_applies_stoichiometry(tmp_path: Path) -> None:
    """S1 -> S2 with stoichiometry 2 of S1: d[S1]/dt = -2 k1 [S1] / cell."""
    model_sbml = simple_model("stoichiometry")
    model_sbml.getReaction("r1").getReactant(0).setStoichiometry(2.0)
    sbml_path = write_sbml(tmp_path / "stoichiometry.xml", model_sbml)
    cellml_path = tmp_path / "stoichiometry.cellml"
    convert_sbml2cellml(sbml_path, cellml_path=cellml_path)
    df, _ = run_timecourse(
        cellml_path,
        end=4.0,
        steps=8,
        relative_tolerance=1e-10,
        absolute_tolerance=1e-12,
    )
    expected = 10.0 * np.exp(-2 * 0.5 / 2.0 * df["time"])
    assert np.allclose(df["S1"], expected, rtol=1e-6)


def test_run_timecourse_algebraic_model(tmp_path: Path) -> None:
    """Without a variable of integration the values are the same at all times."""
    cellml_path = tmp_path / "algebraic.cellml"
    write_model(algebraic_model(), cellml_path)
    df, units = run_timecourse(cellml_path, start=0.0, end=10.0, steps=5)
    assert df["time"].tolist() == [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
    assert df["a"].tolist() == [2.0] * 6
    assert df["b"].tolist() == [4.0] * 6
    assert set(units) == set(df.columns)


def test_run_timecourse_duplicate_names_raise(tmp_path: Path) -> None:
    """A variable `time` of an algebraic model would replace the time points."""
    model = algebraic_model()
    model.component(0).variable("a").setName("time")
    model.component(0).setMath(
        model.component(0).math().replace("<ci>a</ci>", "<ci>time</ci>")
    )
    cellml_path = tmp_path / "time.cellml"
    write_model(model, cellml_path)
    with pytest.raises(SimulationError, match="'time' occurs twice"):
        run_timecourse(cellml_path)


def test_run_timecourse_boundary_species_is_not_changed_by_reactions(
    tmp_path: Path,
) -> None:
    """S1 (boundary) -> S2: S1 stays 10, S2 = 4 + k1 * S1 * t = 4 + 5 t."""
    model_sbml = simple_model("boundary")
    model_sbml.getSpecies("S1").setBoundaryCondition(True)
    sbml_path = write_sbml(tmp_path / "boundary.xml", model_sbml)
    cellml_path = tmp_path / "boundary.cellml"
    convert_sbml2cellml(sbml_path, cellml_path=cellml_path)
    df, _ = run_timecourse(cellml_path, end=4.0, steps=4)
    assert np.allclose(df["S1"], 10.0)
    assert np.allclose(df["S2"], 4.0 + 5.0 * df["time"])


def test_run_timecourse_applies_conversion_factors(tmp_path: Path) -> None:
    """The species factor (S1: 2) wins over the model factor (S2: 3).

    d[S1]/dt = -2 k1 [S1] / cell, so [S1] = 10 exp(-0.5 t); the amount S2
    grows three times as fast as the reaction runs.
    """
    model_sbml = simple_model("factors")
    for pid, value in (("cf_model", 3.0), ("cf_s1", 2.0)):
        p = model_sbml.createParameter()
        p.setId(pid)
        p.setValue(value)
        p.setConstant(True)
    model_sbml.setConversionFactor("cf_model")
    model_sbml.getSpecies("S1").setConversionFactor("cf_s1")
    sbml_path = write_sbml(tmp_path / "factors.xml", model_sbml)
    cellml_path = tmp_path / "factors.cellml"
    convert_sbml2cellml(sbml_path, cellml_path=cellml_path)
    df, _ = run_timecourse(
        cellml_path,
        end=4.0,
        steps=8,
        relative_tolerance=1e-10,
        absolute_tolerance=1e-12,
    )
    s1 = 10.0 * np.exp(-0.5 * df["time"])
    assert np.allclose(df["S1"], s1, rtol=1e-6)
    # S1 lost (10 - s1) * cell / 2 of reaction extent in amount, S2 gains 3 times that
    assert np.allclose(df["S2"], 4.0 + 3.0 * (10.0 - s1) * 2.0 / 2.0, rtol=1e-6)


def test_run_timecourse_rate_of(tmp_path: Path) -> None:
    """rateOf of a reaction species, a rate rule target and a constant."""
    model_sbml = simple_model("rate_of")
    for pid in ("rate_s1", "rate_x", "rate_k1", "x"):
        p = model_sbml.createParameter()
        p.setId(pid)
        p.setConstant(False)
    model_sbml.getParameter("x").setValue(1.0)
    rule = model_sbml.createRateRule()
    rule.setVariable("x")
    rule.setMath(libsbml.parseL3Formula("rateOf(S1)"))  # nested: dx/dt = d[S1]/dt
    for variable, target in (("rate_s1", "S1"), ("rate_x", "x"), ("rate_k1", "k1")):
        assignment = model_sbml.createAssignmentRule()
        assignment.setVariable(variable)
        assignment.setMath(libsbml.parseL3Formula(f"rateOf({target})"))
    sbml_path = write_sbml(tmp_path / "rate_of.xml", model_sbml)
    cellml_path = tmp_path / "rate_of.cellml"
    convert_sbml2cellml(sbml_path, cellml_path=cellml_path)
    df, _ = run_timecourse(
        cellml_path,
        end=4.0,
        steps=8,
        relative_tolerance=1e-10,
        absolute_tolerance=1e-12,
    )
    # d[S1]/dt = -k1 [S1] / cell = -0.25 [S1]
    assert np.allclose(df["rate_s1"], -0.25 * df["S1"], rtol=1e-6)
    assert np.allclose(df["rate_x"], df["rate_s1"], rtol=1e-6)
    assert np.allclose(df["x"], 1.0 + df["S1"] - 10.0, rtol=1e-6)
    assert np.allclose(df["rate_k1"], 0.0)


def test_run_timecourse_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SimulationError):
        run_timecourse(tmp_path / "missing.cellml")


def test_run_timecourse_tolerances() -> None:
    default_df, _ = run_timecourse(TEST_MODEL_PATH, start=0.0, end=50.0, steps=10)
    tight_df, _ = run_timecourse(
        TEST_MODEL_PATH,
        start=0.0,
        end=50.0,
        steps=10,
        relative_tolerance=1e-9,
        absolute_tolerance=1e-12,
    )
    assert np.allclose(tight_df["m"].to_numpy(), default_df["m"].to_numpy(), rtol=1e-6)


def test_plot_timecourse() -> None:
    df, units = run_timecourse(TEST_MODEL_PATH, end=10.0, steps=5)
    fig = plot_timecourse(df, units, show=False)
    ax = fig.axes[0]
    # one line per column other than the variable of integration: m, alpha
    assert len(ax.lines) == 2
    assert ax.get_xlabel() == "t [second]"
