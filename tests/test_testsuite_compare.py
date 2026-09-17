"""Tests of the comparison with the expected results."""

import libsbml
import numpy as np
import pandas as pd
import pytest

from sbml2cellml.testsuite.cases import Settings
from sbml2cellml.testsuite.compare import (
    CompareError,
    compare,
    is_informative,
    requested_frame,
    species_quantities,
    strip_brackets,
)

SETTINGS = Settings(
    start=0.0,
    duration=1.0,
    steps=2,
    variables=("S1", "S2"),
    absolute=1e-3,
    relative=1e-2,
    amount=frozenset({"S1"}),
    concentration=frozenset({"S2"}),
)


def expected() -> pd.DataFrame:
    return pd.DataFrame(
        {"time": [0.0, 0.5, 1.0], "S1": [1.0, 0.5, 0.25], "S2": [0.0, 0.5, 0.75]}
    )


def test_compare_pass() -> None:
    result = expected().copy()
    result["S1"] += (
        0.004  # within 1e-3 + 1e-2 * |e| for e >= 0.3, S1 min is 0.25 -> tol 0.0035
    )
    result.loc[2, "S1"] = 0.25 + 0.003
    comparison = compare(result, expected(), SETTINGS)
    assert comparison.passed, comparison.message
    assert comparison.max_excess <= 0
    assert {v.variable for v in comparison.variables} == {"S1", "S2"}


def test_compare_fail_by_tolerance() -> None:
    result = expected().copy()
    result.loc[2, "S2"] = 0.75 + 0.02
    comparison = compare(result, expected(), SETTINGS)
    assert not comparison.passed
    assert "S2" in comparison.message
    s2 = next(v for v in comparison.variables if v.variable == "S2")
    assert s2.max_error == pytest.approx(0.02)
    assert s2.max_excess > 0


def test_compare_missing_variable_and_rows() -> None:
    result = expected().drop(columns=["S2"])
    comparison = compare(result, expected(), SETTINGS)
    assert (
        not comparison.passed
        and "S2" in comparison.message
        and "missing" in comparison.message
    )
    comparison = compare(expected().iloc[:2], expected(), SETTINGS)
    assert not comparison.passed and "rows" in comparison.message
    shifted = expected()
    shifted["time"] = shifted["time"] + 0.1
    comparison = compare(shifted, expected(), SETTINGS)
    assert not comparison.passed and "time" in comparison.message


def test_compare_nan_fails() -> None:
    result = expected()
    result.loc[1, "S1"] = np.nan
    assert not compare(result, expected(), SETTINGS).passed


def test_compare_duplicate_columns_fails() -> None:
    result = expected().copy()
    result.columns = ["time", "S1", "S1"]
    comparison = compare(result, expected(), SETTINGS)
    assert not comparison.passed
    assert "duplicate column names" in comparison.message

    dup_expected = expected().copy()
    dup_expected.columns = ["time", "time", "S2"]
    comparison = compare(expected(), dup_expected, SETTINGS)
    assert not comparison.passed
    assert "duplicate column names" in comparison.message


def test_compare_zero_rows() -> None:
    empty = pd.DataFrame({"time": [], "S1": [], "S2": []})
    comparison = compare(empty, empty.copy(), SETTINGS)
    assert comparison.passed is False
    assert "no rows" in comparison.message


def test_compare_non_numeric() -> None:
    result = expected()
    result["S1"] = ["a", "b", "c"]
    comparison = compare(result, expected(), SETTINGS)
    assert not comparison.passed
    assert "S1" in comparison.message


def test_species_quantities_and_requested_frame() -> None:
    doc = libsbml.SBMLDocument(3, 2)
    model = doc.createModel()
    c = model.createCompartment()
    c.setId("cell")
    c.setSize(2.0)
    c.setConstant(True)
    for sid, amount in [("S1", True), ("S2", False)]:
        s = model.createSpecies()
        s.setId(sid)
        s.setCompartment("cell")
        s.setHasOnlySubstanceUnits(amount)
        s.setConstant(False)
        s.setBoundaryCondition(False)
    quantities = species_quantities(model)
    assert quantities == {"S1": (True, "cell"), "S2": (False, "cell")}

    df = pd.DataFrame(
        {"time": [0.0, 1.0], "S1": [4.0, 2.0], "S2": [1.0, 3.0], "cell": [2.0, 2.0]}
    )
    # S1 is an amount variable requested as amount, S2 a concentration variable requested as concentration
    same = requested_frame(df, quantities, SETTINGS)
    assert list(same.columns) == ["time", "S1", "S2"]
    assert same["S1"].tolist() == [4.0, 2.0] and same["S2"].tolist() == [1.0, 3.0]
    # swapped requests convert with the compartment
    swapped = Settings(
        0.0, 1.0, 1, ("S1", "S2"), 0, 0, frozenset({"S2"}), frozenset({"S1"})
    )
    converted = requested_frame(df, quantities, swapped)
    assert converted["S1"].tolist() == [2.0, 1.0]
    assert converted["S2"].tolist() == [2.0, 6.0]


def test_requested_frame_missing_compartment_raises() -> None:
    doc = libsbml.SBMLDocument(3, 2)
    model = doc.createModel()
    c = model.createCompartment()
    c.setId("cell")
    c.setSize(2.0)
    c.setConstant(True)
    for sid, amount in [("S1", True), ("S2", False)]:
        s = model.createSpecies()
        s.setId(sid)
        s.setCompartment("cell")
        s.setHasOnlySubstanceUnits(amount)
        s.setConstant(False)
        s.setBoundaryCondition(False)
    quantities = species_quantities(model)
    df = pd.DataFrame({"time": [0.0, 1.0], "S1": [4.0, 2.0], "S2": [1.0, 3.0]})
    # no conversion needed: the missing compartment column is irrelevant
    same = requested_frame(df, quantities, SETTINGS)
    assert same["S1"].tolist() == [4.0, 2.0] and same["S2"].tolist() == [1.0, 3.0]
    # swapped requests need a conversion, and the compartment is missing
    swapped = Settings(
        0.0, 1.0, 1, ("S1", "S2"), 0, 0, frozenset({"S2"}), frozenset({"S1"})
    )
    with pytest.raises(CompareError, match="cell"):
        requested_frame(df, quantities, swapped)


def test_requested_frame_no_time_column_raises() -> None:
    doc = libsbml.SBMLDocument(3, 2)
    model = doc.createModel()
    c = model.createCompartment()
    c.setId("cell")
    c.setSize(2.0)
    c.setConstant(True)
    s = model.createSpecies()
    s.setId("S1")
    s.setCompartment("cell")
    s.setHasOnlySubstanceUnits(True)
    s.setConstant(False)
    s.setBoundaryCondition(False)
    quantities = species_quantities(model)
    # an algebraic-only model: libopencor result without a variable of
    # integration
    df = pd.DataFrame({"S1": [4.0, 2.0]})
    with pytest.raises(CompareError, match="no time column"):
        requested_frame(df, quantities, SETTINGS)


def test_is_informative_constant_frame_is_not_informative() -> None:
    constant = pd.DataFrame(
        {"time": [0.0, 0.5, 1.0], "S1": [1.0, 1.0, 1.0], "S2": [0.0, 0.0, 0.0]}
    )
    assert is_informative(constant, SETTINGS) is False


def test_is_informative_decaying_frame_is_informative() -> None:
    assert is_informative(expected(), SETTINGS) is True


def test_strip_brackets() -> None:
    df = pd.DataFrame({"time": [0.0], "[S1]": [1.0], "k": [2.0]})
    assert list(strip_brackets(df).columns) == ["time", "S1", "k"]
