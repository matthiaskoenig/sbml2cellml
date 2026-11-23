"""Tests of the sbmlsim-core simulation of SBML models.

Skipped when sbmlsim-core is not installed, see docs/installation.md.
"""

from pathlib import Path

import libsbml
import numpy as np
import pytest

from sbml2cellml.sbmlsim import (
    ABSOLUTE_TOLERANCE,
    MAXIMUM_NUMBER_OF_STEPS,
    RELATIVE_TOLERANCE,
    SimulationError,
    compilable_sbml,
    load_model,
    run_timecourse,
    solver_settings,
    state_scale,
)
from tests.conftest import MODELS_DIR
from tests.sbml_models import simple_model, small_compartment_model, write_sbml

pytest.importorskip("sbmlsim_core")


def test_run_timecourse_of_a_file(tmp_path: Path) -> None:
    """d[S1]/dt = -k1 [S1] / cell with cell = 2, so [S1] = 10 exp(-0.25 t)."""
    sbml_path = write_sbml(tmp_path / "simple.xml", simple_model())
    df = run_timecourse(sbml_path, ["[S1]", "S2", "k1"], start=0.0, end=4.0, steps=8)
    assert list(df.columns) == ["time", "[S1]", "S2", "k1"]
    assert len(df) == 9
    assert df["time"].iloc[-1] == pytest.approx(4.0)
    assert np.allclose(df["[S1]"], 10.0 * np.exp(-0.25 * df["time"]), rtol=1e-6)
    assert (df["k1"] == 0.5).all()


def test_run_timecourse_of_a_document(tmp_path: Path) -> None:
    """The document as a string is simulated as the file is."""
    sbml_path = write_sbml(tmp_path / "simple.xml", simple_model())
    text = sbml_path.read_text(encoding="utf-8")
    assert np.allclose(
        run_timecourse(text, ["[S1]"], end=2.0, steps=4)["[S1]"].to_numpy(),
        run_timecourse(sbml_path, ["[S1]"], end=2.0, steps=4)["[S1]"].to_numpy(),
    )


def test_run_timecourse_of_a_level_2_model() -> None:
    """The repressilator is level 2 version 3, the compiler reads level 3."""
    df = run_timecourse(
        MODELS_DIR / "repressilator.xml", ["PX", "PY", "PZ"], end=10.0, steps=10
    )
    assert list(df.columns) == ["time", "PX", "PY", "PZ"]
    assert (df[["PX", "PY", "PZ"]].iloc[-1] > 0).all()


def test_run_timecourse_of_a_comp_model() -> None:
    """A model which requires the comp package is flattened before it compiles."""
    df = run_timecourse(
        MODELS_DIR / "glimepiride_liver.xml", ["gli_ext"], end=10.0, steps=5
    )
    assert len(df) == 6


def test_compilable_sbml_keeps_a_flat_level_3_model(tmp_path: Path) -> None:
    text = write_sbml(tmp_path / "simple.xml", simple_model()).read_text(
        encoding="utf-8"
    )
    assert compilable_sbml(text) is text


def test_compilable_sbml_converts_a_level_2_model() -> None:
    text = (MODELS_DIR / "repressilator.xml").read_text(encoding="utf-8")
    converted = compilable_sbml(text)
    document = libsbml.readSBMLFromString(converted)
    assert (document.getLevel(), document.getVersion()) == (3, 2)


def test_compilable_sbml_converts_a_model_the_strict_check_refuses(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """libsbml refuses a strict conversion over issues without mathematics."""
    strict_conversion = libsbml.SBMLDocument.setLevelAndVersion

    def refuse_strict(
        document: libsbml.SBMLDocument, level: int, version: int, strict: bool
    ) -> bool:
        if strict:
            return False
        return bool(strict_conversion(document, level, version, strict))

    monkeypatch.setattr(libsbml.SBMLDocument, "setLevelAndVersion", refuse_strict)
    text = (MODELS_DIR / "repressilator.xml").read_text(encoding="utf-8")
    with caplog.at_level("WARNING"):
        converted = libsbml.readSBMLFromString(compilable_sbml(text))
    assert (converted.getLevel(), converted.getVersion()) == (3, 2)
    assert "without the strict check" in caplog.text


def test_compilable_sbml_flattens_the_comp_package() -> None:
    text = (MODELS_DIR / "glimepiride_liver.xml").read_text(encoding="utf-8")
    converted = compilable_sbml(text)
    assert not libsbml.readSBMLFromString(converted).getPackageRequired("comp")
    assert "comp:" not in converted


def test_compilable_sbml_without_a_model_raises() -> None:
    with pytest.raises(SimulationError, match="no model"):
        compilable_sbml("<sbml/>")


def test_solver_settings_defaults() -> None:
    settings = solver_settings()
    assert settings["relative_tolerance"] == RELATIVE_TOLERANCE
    assert settings["absolute_tolerance"] == {"scalar": ABSOLUTE_TOLERANCE}
    assert settings["maximum_num_steps"] == MAXIMUM_NUMBER_OF_STEPS
    assert settings["stiff"] is True


def test_solver_settings_are_given_through(tmp_path: Path) -> None:
    settings = solver_settings(1e-9, 1e-12, 100)
    assert settings["relative_tolerance"] == 1e-9
    assert settings["absolute_tolerance"] == {"scalar": 1e-12}
    assert settings["maximum_num_steps"] == 100
    sbml_path = write_sbml(tmp_path / "simple.xml", simple_model())
    # three internal steps are not enough for the integration
    with pytest.raises(Exception, match="mxstep steps taken"):
        run_timecourse(
            sbml_path,
            ["[S1]"],
            end=4.0,
            steps=1,
            relative_tolerance=1e-10,
            absolute_tolerance=1e-14,
            maximum_number_of_steps=3,
        )


def test_state_scale_of_a_concentration_in_a_small_compartment(
    tmp_path: Path,
) -> None:
    """The state is the amount, the concentration times the size."""
    path = write_sbml(tmp_path / "small.xml", small_compartment_model())
    model = load_model(path.read_text(encoding="utf-8"))
    assert state_scale(model) == pytest.approx(1e-13)


def test_state_scale_of_a_model_with_states_of_one(tmp_path: Path) -> None:
    """S1 has the amount 20 and S2 the amount 4, so nothing is scaled."""
    path = write_sbml(tmp_path / "simple.xml", simple_model())
    model = load_model(path.read_text(encoding="utf-8"))
    assert state_scale(model) == pytest.approx(4.0)


def test_load_model_caches_the_compiled_model(tmp_path: Path) -> None:
    """The same text gives the same loaded model, a changed one a new model."""
    path = write_sbml(tmp_path / "simple.xml", simple_model())
    text = path.read_text(encoding="utf-8")
    first = load_model(text)
    assert load_model(text) is first
    assert load_model(text.replace('id="simple"', 'id="other"')) is not first


def test_run_timecourse_scales_the_absolute_tolerance(tmp_path: Path) -> None:
    """[A] = exp(-t) is lost when the tolerance is above the amounts.

    The amount of `A` is 1e-13, the absolute tolerance 1e-12: CVODE accepts
    any trajectory of the amount without the scaling of `state_scale`.
    """
    sbml_path = write_sbml(tmp_path / "small.xml", small_compartment_model())
    scaled = run_timecourse(
        sbml_path,
        ["[A]"],
        start=0.0,
        end=10.0,
        steps=10,
        relative_tolerance=1e-9,
        absolute_tolerance=1e-12,
    )
    assert scaled["[A]"].iloc[-1] == pytest.approx(np.exp(-10.0), rel=1e-6)
    unscaled = run_timecourse(
        sbml_path,
        ["[A]"],
        start=0.0,
        end=10.0,
        steps=10,
        relative_tolerance=1e-9,
        absolute_tolerance=1e-12,
        scale_tolerance=False,
    )
    assert unscaled["[A]"].iloc[-1] != pytest.approx(np.exp(-10.0), rel=1e-3)


def test_run_timecourse_fills_the_timings(tmp_path: Path) -> None:
    path = write_sbml(tmp_path / "simple.xml", simple_model("timed"))
    timings: dict[str, float] = {}
    run_timecourse(path, ["S1"], end=1.0, steps=10, timings=timings)
    assert sorted(timings) == ["setup", "simulate"]
    assert timings["setup"] > 0.0
    assert timings["simulate"] > 0.0
    cached: dict[str, float] = {}
    run_timecourse(path, ["S1"], end=1.0, steps=10, timings=cached)
    assert sorted(cached) == ["setup", "simulate"]
    # the second run takes the model from the cache of `load_model`, which
    # `test_load_model_caches_the_compiled_model` asserts; the wall time of
    # a cache hit is too small to compare with a compilation under load


def test_run_timecourse_warmup_keeps_the_result(tmp_path: Path) -> None:
    """The discarded simulation changes nothing but the timings."""
    path = write_sbml(tmp_path / "simple.xml", simple_model("warm"))
    warm = run_timecourse(path, ["S1"], end=1.0, steps=10, warmup=True)
    cold = run_timecourse(path, ["S1"], end=1.0, steps=10)
    assert np.array_equal(warm.to_numpy(), cold.to_numpy())
