"""Tests of the construction of formulas as libsbml ASTs."""

import math

import libsbml
import pytest

from sbml2cellml import astnodes
from sbml2cellml.mathml import process_mathml_for_cellml


@pytest.mark.parametrize("sid", ["avogadro", "pi", "NaN", "INF", "true", "time"])
def test_name_is_never_a_symbol(sid: str) -> None:
    node = astnodes.name(sid)
    assert node.getType() == libsbml.AST_NAME
    assert process_mathml_for_cellml(node) == f"<ci> {sid} </ci>"


def test_number_with_units() -> None:
    node = astnodes.number(2.5, "litre")
    assert node.getType() == libsbml.AST_REAL
    assert node.getValue() == 2.5
    assert node.getUnits() == "litre"
    assert not astnodes.number(2.5).isSetUnits()


def test_non_finite_numbers() -> None:
    assert "<infinity/>" in process_mathml_for_cellml(astnodes.number(math.inf))
    negative = process_mathml_for_cellml(astnodes.number(-math.inf))
    assert "<minus/>" in negative
    assert "<infinity/>" in negative
    assert "<notanumber/>" in process_mathml_for_cellml(astnodes.number(math.nan))


def test_apply_copies_its_arguments() -> None:
    a = astnodes.name("a")
    quotient = astnodes.apply(libsbml.AST_DIVIDE, a, a)
    a.setName("b")
    assert astnodes.text(quotient) == "a / a"
    assert astnodes.text(astnodes.apply(libsbml.AST_MINUS, quotient)) == "-(a / a)"


def test_signed_sum() -> None:
    a, b, c = (astnodes.name(sid) for sid in "abc")
    minus, plus = libsbml.AST_MINUS, libsbml.AST_PLUS
    assert astnodes.text(astnodes.signed_sum([(plus, a)])) == "a"
    assert astnodes.text(astnodes.signed_sum([(minus, a)])) == "-a"
    total = astnodes.signed_sum([(minus, a), (plus, b), (minus, c)])
    assert astnodes.text(total) == "-a + b - c"
    with pytest.raises(ValueError, match="at least one term"):
        astnodes.signed_sum([])


def test_mathml_of_an_ast_does_not_change_it() -> None:
    node = astnodes.apply(libsbml.AST_TIMES, astnodes.number(2.0), astnodes.name("k"))
    process_mathml_for_cellml(node)
    assert not node.getChild(0).isSetUnits()
