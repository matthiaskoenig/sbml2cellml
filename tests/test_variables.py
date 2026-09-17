"""Tests of the SBML ids of CellML variables."""

import libcellml
import pytest

from sbml2cellml.variables import (
    VariableIds,
    equivalence_set,
    sanitize_id,
    variable_key,
)
from tests.cellml_models import analyse, multi_component_model
from tests.cellml_models import variable as add_variable


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


def test_ids_deduplicate_sanitized_collisions() -> None:
    # "x" clashes between "cell" and "child", so both get a component prefix;
    # "other.cell_x" is a unique name that happens to equal the resulting
    # prefixed id "cell_x" of "cell.x". The second one processed must not
    # silently overwrite the first.
    model = libcellml.Model("collide")
    cell = libcellml.Component("cell")
    child = libcellml.Component("child")
    other = libcellml.Component("other")
    model.addComponent(cell)
    model.addComponent(child)
    model.addComponent(other)
    add_variable(cell, "x", "dimensionless", 1.0)
    add_variable(child, "x", "dimensionless", 2.0)
    add_variable(other, "cell_x", "dimensionless", 3.0)

    ids = VariableIds(analyse(model))
    cell_x = ids.lookup("cell", "x")
    child_x = ids.lookup("child", "x")
    other_cell_x = ids.lookup("other", "cell_x")

    assert cell_x != other_cell_x
    assert len({cell_x, child_x, other_cell_x}) == 3
    assert any(sid.endswith("_2") for sid in (cell_x, child_x, other_cell_x))


def test_lookup_unknown_raises() -> None:
    ids = VariableIds(analyse(multi_component_model()))
    with pytest.raises(KeyError):
        ids.lookup("cell", "nope")
