"""Tests of the libopencor simulation.

Skipped when libopencor is not installed, see docs/installation.md.
"""

from pathlib import Path

import libsbml
import matplotlib
import numpy as np
import pytest

from sbml2cellml import convert_sbml2cellml
from sbml2cellml.simulate import SimulationError, plot_timecourse, run_timecourse
from tests.conftest import MODELS_DIR, TEST_MODEL_PATH

pytest.importorskip("libopencor")
matplotlib.use("Agg")


def test_run_timecourse_test_model() -> None:
    df, units = run_timecourse(TEST_MODEL_PATH, start=0.0, end=50.0, steps=10)
    assert list(df.columns) == ["t", "m"]
    assert len(df) == 11
    assert df["t"].iloc[0] == 0.0
    assert df["t"].iloc[-1] == 50.0
    assert df["m"].iloc[0] == 10.0
    assert np.all(np.diff(df["m"].to_numpy()) < 0)
    assert units == {"t": "second", "m": "kilogram"}


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
    assert set(units) == set(df.columns)


def test_run_timecourse_underconstrained_raises(tmp_path: Path) -> None:
    """Known conversion gap, see docs/roadmap.md."""
    cellml_path = tmp_path / "kidney.cellml"
    convert_sbml2cellml(MODELS_DIR / "glimepiride_kidney.xml", cellml_path=cellml_path)
    with pytest.raises(SimulationError, match="underconstrained"):
        run_timecourse(cellml_path)


def test_run_timecourse_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SimulationError):
        run_timecourse(tmp_path / "missing.cellml")


def test_plot_timecourse() -> None:
    df, units = run_timecourse(TEST_MODEL_PATH, end=10.0, steps=5)
    fig = plot_timecourse(df, units, show=False)
    ax = fig.axes[0]
    assert len(ax.lines) == 1
    assert ax.get_xlabel() == "t [second]"
