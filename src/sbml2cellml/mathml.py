"""MathML helpers for the math of a CellML component.

libsbml renders a formula as a complete MathML document, i.e., with an xml
declaration and a `math` element. CellML takes the equations of a component as
one `math` element, so the rendered fragments are stripped of the declaration
and the element, combined, and wrapped in a `math` element which declares the
`cellml` namespace for the units of numbers. The `sbml:units` attribute of
libsbml becomes `cellml:units`.

CellML requires units on every number and only knows real and e-notation
numbers: a number without units gets `dimensionless` (the units of every
variable until units are converted), integers and rationals become reals.
"""

import math
import re

import libsbml

#: xml declaration written by libsbml in front of the math element
XML_DECLARATION = re.compile(r"<\?xml[^>]*\?>")
#: opening math element with its namespace declarations
MATH_OPEN = re.compile(r"<math[^>]*>")
MATH_CLOSE = "</math>"

SBML_UNITS_ATTRIBUTE = "sbml:units"
CELLML_UNITS_ATTRIBUTE = "cellml:units"
#: units of a number without units
NUMBER_UNITS = "dimensionless"

#: opening math element of the CellML component math
CELLML_MATH_OPEN = (
    '<math xmlns="http://www.w3.org/1998/Math/MathML" '
    'xmlns:cellml="http://www.cellml.org/cellml/2.0#">'
)


class MathMLError(ValueError):
    """A formula cannot be rendered as MathML."""


def normalize_numbers(node: libsbml.ASTNode) -> None:
    """Make the numbers of a formula valid CellML numbers, in place.

    Integers and rationals become reals, a finite number without units gets
    `NUMBER_UNITS`. Infinity and NaN stay as they are, they are written as
    the `infinity` and `notanumber` constants, which have no units.

    Args:
        node: root of the libsbml AST of the formula.
    """
    if node.isNumber() and math.isfinite(node.getValue()):
        if node.getType() in (libsbml.AST_INTEGER, libsbml.AST_RATIONAL):
            node.setValue(float(node.getValue()))
        if not node.isSetUnits():
            node.setUnits(NUMBER_UNITS)
    for k in range(node.getNumChildren()):
        normalize_numbers(node.getChild(k))


def process_mathml_for_cellml(formula: str) -> str:
    """Render a formula in SBML L3 syntax as a MathML fragment for CellML.

    Args:
        formula: formula in the SBML level 3 infix syntax, e.g., `k1 * S1`.

    Returns:
        The MathML of the formula without xml declaration and `math` element,
        with `cellml:units` on every finite number (see `normalize_numbers`).

    Raises:
        MathMLError: if the formula does not parse.
    """
    ast: libsbml.ASTNode | None = libsbml.parseL3Formula(formula)
    if ast is None:
        raise MathMLError(
            f"Formula does not parse: '{formula}': {libsbml.getLastParseL3Error()}"
        )
    normalize_numbers(ast)
    mathml: str = libsbml.writeMathMLToString(ast)
    mathml = XML_DECLARATION.sub("", mathml)
    mathml = MATH_OPEN.sub("", mathml, count=1)
    mathml = mathml.replace(MATH_CLOSE, "")
    mathml = mathml.replace(SBML_UNITS_ATTRIBUTE, CELLML_UNITS_ATTRIBUTE)
    return mathml.strip()


def mathml_for_assignment(vid: str, formula: str) -> str:
    """MathML of the assignment `vid = formula`.

    Args:
        vid: id of the assigned variable.
        formula: right hand side in SBML L3 infix syntax.

    Returns:
        The `apply` element of the equation.
    """
    rhs = process_mathml_for_cellml(formula)
    return f"""<apply>
  <eq/>
  <ci>{vid}</ci>
  {rhs}
</apply>
"""


def mathml_for_diff(vid: str, formula: str, ivid: str = "t") -> str:
    """MathML of the differential equation `d vid / d ivid = formula`.

    Args:
        vid: id of the state variable.
        formula: right hand side in SBML L3 infix syntax.
        ivid: id of the variable of integration.

    Returns:
        The `apply` element of the equation.
    """
    rhs = process_mathml_for_cellml(formula)
    return f"""<apply>
  <eq/>
  <apply>
    <diff/>
    <bvar>
      <ci>{ivid}</ci>
    </bvar>
    <ci>{vid}</ci>
  </apply>
  {rhs}
</apply>
"""


def cellml_math(parts: list[str]) -> str:
    """Combine equation fragments into the math element of a component.

    Args:
        parts: `apply` elements, e.g., from `mathml_for_assignment`.

    Returns:
        The complete `math` element with the MathML and cellml namespaces.
    """
    return CELLML_MATH_OPEN + "\n" + "\n".join(parts) + "</math>"
