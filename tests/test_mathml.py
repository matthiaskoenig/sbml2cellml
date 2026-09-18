"""Tests of the MathML helpers."""

import pytest

from sbml2cellml.mathml import (
    MathMLError,
    cellml_math,
    mathml_for_assignment,
    mathml_for_diff,
    process_mathml_for_cellml,
)


def test_process_strips_header_and_math_element() -> None:
    mathml = process_mathml_for_cellml("k1 * S1")
    assert not mathml.startswith("<?xml")
    assert "<math" not in mathml
    assert "</math>" not in mathml
    assert mathml.startswith("<apply>")
    assert mathml.endswith("</apply>")
    assert "k1" in mathml
    assert "S1" in mathml


def test_process_maps_sbml_units_to_cellml_units() -> None:
    mathml = process_mathml_for_cellml("1.0 dimensionless / V")
    assert 'cellml:units="dimensionless"' in mathml
    assert "sbml:units" not in mathml


@pytest.mark.parametrize("formula", ["2 * k", "2.5 * k", "1e-3 * k", "(3/4) * k"])
def test_process_gives_numbers_without_units_dimensionless(formula: str) -> None:
    """CellML requires units on every number; every variable is dimensionless."""
    mathml = process_mathml_for_cellml(formula)
    assert mathml.count("<cn") == 1
    assert 'cellml:units="dimensionless"' in mathml


def test_process_writes_integers_and_rationals_as_reals() -> None:
    """CellML 2.0 numbers are real or e-notation."""
    integer = process_mathml_for_cellml("2 * k")
    assert 'type="integer"' not in integer
    assert "> 2 </cn>" in integer
    rational = process_mathml_for_cellml("(3/4) * k")
    assert 'type="rational"' not in rational
    assert "> 0.75 </cn>" in rational


def test_process_keeps_e_notation_and_units_of_numbers() -> None:
    assert 'type="e-notation"' in process_mathml_for_cellml("1e-3 * k")
    mathml = process_mathml_for_cellml("2 second * k")
    assert 'cellml:units="second"' in mathml
    assert "dimensionless" not in mathml


def test_process_leaves_infinity_and_nan_without_units() -> None:
    mathml = process_mathml_for_cellml("INF + NaN * k")
    assert "<infinity/>" in mathml
    assert "<notanumber/>" in mathml
    assert "units" not in mathml


def test_process_writes_time_as_the_variable_of_integration() -> None:
    """The SBML time symbol is the variable of integration `time` of CellML."""
    mathml = process_mathml_for_cellml("k * time")
    assert "csymbol" not in mathml
    assert "<ci> time </ci>" in mathml


def test_process_writes_avogadro_as_a_number() -> None:
    mathml = process_mathml_for_cellml("avogadro * k")
    assert "csymbol" not in mathml
    assert 'cellml:units="dimensionless"' in mathml
    assert "6.02214179" in mathml


def test_process_raises_on_invalid_formula() -> None:
    with pytest.raises(MathMLError, match="does not parse"):
        process_mathml_for_cellml("k1 * (")


def test_mathml_for_assignment() -> None:
    mathml = mathml_for_assignment(vid="x", formula="2 * y")
    assert mathml.startswith("<apply>\n  <eq/>\n  <ci>x</ci>")
    assert "y" in mathml
    assert mathml.rstrip().endswith("</apply>")


def test_mathml_for_diff() -> None:
    mathml = mathml_for_diff(vid="S1", formula="- k1 * S1", ivid="time")
    assert "<diff/>" in mathml
    assert "<bvar>\n      <ci>time</ci>\n    </bvar>" in mathml
    assert "<ci>S1</ci>" in mathml


def test_cellml_math_wraps_parts() -> None:
    parts = [mathml_for_assignment("x", "1"), mathml_for_assignment("y", "2")]
    math = cellml_math(parts)
    assert math.startswith(
        '<math xmlns="http://www.w3.org/1998/Math/MathML" '
        'xmlns:cellml="http://www.cellml.org/cellml/2.0#">'
    )
    assert math.endswith("</math>")
    assert math.count("<eq/>") == 2
