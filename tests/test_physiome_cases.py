"""Tests of the case construction of the Physiome check."""

from pathlib import Path

import pytest

from sbml2cellml.cellml import write_model
from sbml2cellml.physiome.cases import (
    ABSOLUTE,
    DURATION,
    RELATIVE,
    STEPS,
    physiome_case,
)
from sbml2cellml.physiome.models import PhysiomeError
from tests.cellml_models import multi_component_model, underconstrained_model
from tests.conftest import DATA_DIR
from tests.physiome_mocks import EXPOSURE_BROKEN, EXPOSURE_MULTI


def test_case_of_a_multi_component_model(tmp_path: Path) -> None:
    path = tmp_path / "multi.cellml"
    write_model(multi_component_model(), path)
    case = physiome_case(EXPOSURE_MULTI, path)

    assert case.cellml_path == path
    assert case.case.id == EXPOSURE_MULTI.id
    assert case.case.name == EXPOSURE_MULTI.title
    assert case.case.expected is None
    assert case.case.settings.start == 0.0
    assert case.case.settings.duration == DURATION
    assert case.case.settings.steps == STEPS
    assert case.case.settings.absolute == ABSOLUTE
    assert case.case.settings.relative == RELATIVE
    # the variable of integration is no comparison variable
    assert "t" not in case.case.settings.variables
    # one id per equivalence set: `environment/k` and `cell/rate` are one
    assert set(case.case.settings.variables) == {
        "k",
        "x0",
        "y",
        "c",
        "kc",
        "z",
        "cell_x",
        "child_x",
    }
    # the child is counted too, it is encapsulated by `cell`
    assert "3 components" in case.case.component_tags
    assert "DifferentialEquations" in case.case.component_tags


def test_columns_keep_the_clashing_names_apart(tmp_path: Path) -> None:
    path = tmp_path / "multi.cellml"
    write_model(multi_component_model(), path)
    columns = physiome_case(EXPOSURE_MULTI, path).columns
    # `cell/x` and `child/x` have the same name, so the component decides
    assert columns["cell/x"] == "cell_x"
    assert columns["child/x"] == "child_x"
    # a name without a clash is mapped as libopencor reports it
    assert columns["z"] == "z"
    assert columns["child/z"] == "z"
    # the equivalence set of `environment/k` and `cell/rate` is one id
    assert columns["environment/k"] == "k"
    assert columns["cell/rate"] == "k"


def test_case_of_a_cellml_1_0_model() -> None:
    case = physiome_case(EXPOSURE_MULTI, DATA_DIR / "decay_cellml_1_0.cellml")
    assert set(case.case.settings.variables) == {"k", "x"}
    assert case.columns["main/x"] == "x"
    assert "DifferentialEquations" in case.case.component_tags
    assert "1 components" in case.case.component_tags


def test_case_of_an_unanalysable_model_raises(tmp_path: Path) -> None:
    path = tmp_path / "broken.cellml"
    write_model(underconstrained_model(), path)
    with pytest.raises(PhysiomeError, match="cannot be analysed"):
        physiome_case(EXPOSURE_BROKEN, path)
