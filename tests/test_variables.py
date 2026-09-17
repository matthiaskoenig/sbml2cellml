"""Tests of the SBML ids of CellML variables."""

import pytest

from sbml2cellml.variables import (
    VariableIds,
    equivalence_set,
    sanitize_id,
    variable_key,
)
from tests.cellml_models import analyse, multi_component_model


@pytest.mark.parametrize(
    ("name", "sid"),
    [("x", "x"), ("a-b", "a_b"), ("1x", "_1x"), ("", "_"), ("x.y z", "x_y_z")],
)
def test_sanitize_id(name: str, sid: str) -> None:
    assert sanitize_id(name) == sid


def test_equivalence_set_is_transitive() -> None:
    model = multi_component_model()
    t = model.component("environment").variable("t")
    names = sorted(variable_key(v) for v in equivalence_set(t))
    assert names == [("cell", "time"), ("child", "t_child"), ("environment", "t")]


def test_ids_of_multi_component_model() -> None:
    model = multi_component_model()
    ids = VariableIds(analyse(model))
    # connected variables share one id, unique names keep their name
    assert ids.lookup("environment", "k") == "k"
    assert ids.lookup("cell", "rate") == "k"
    assert ids.lookup("cell", "x0") == "x0"
    assert ids.lookup("cell", "y") == "y"
    assert ids.lookup("child", "z") == "z"
    # the name clash x is resolved with the component prefix
    assert ids.lookup("cell", "x") == "cell_x"
    assert ids.lookup("child", "x") == "child_x"
    # the variable of integration and its equivalents
    for component, name in [
        ("environment", "t"),
        ("cell", "time"),
        ("child", "t_child"),
    ]:
        assert ids.is_voi_key(component, name)
    assert not ids.is_voi_key("cell", "x")
    assert ids.is_voi(model.component("cell").variable("time"))
    assert (
        ids.id_for(model.component("cell").component("child").variable("x"))
        == "child_x"
    )


def test_lookup_unknown_raises() -> None:
    ids = VariableIds(analyse(multi_component_model()))
    with pytest.raises(KeyError):
        ids.lookup("cell", "nope")
