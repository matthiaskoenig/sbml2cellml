"""MathML helpers for the math of a CellML component.

libsbml renders a formula as a complete MathML document, i.e., with an xml
declaration and a `math` element. CellML takes the equations of a component as
one `math` element, so the rendered fragments are stripped of the declaration
and the element, combined, and wrapped in a `math` element which declares the
`cellml` namespace for the units of numbers. The `sbml:units` attribute of
libsbml becomes `cellml:units`.
"""

import re

import libsbml

#: xml declaration written by libsbml in front of the math element
XML_DECLARATION = re.compile(r"<\?xml[^>]*\?>")
#: opening math element with its namespace declarations
MATH_OPEN = re.compile(r"<math[^>]*>")
MATH_CLOSE = "</math>"

SBML_UNITS_ATTRIBUTE = "sbml:units"
CELLML_UNITS_ATTRIBUTE = "cellml:units"

#: opening math element of the CellML component math
CELLML_MATH_OPEN = (
    '<math xmlns="http://www.w3.org/1998/Math/MathML" '
    'xmlns:cellml="http://www.cellml.org/cellml/2.0#">'
)


class MathMLError(ValueError):
    """A formula cannot be rendered as MathML."""


def process_mathml_for_cellml(formula: str) -> str:
    """Render a formula in SBML L3 syntax as a MathML fragment for CellML.

    Args:
        formula: formula in the SBML level 3 infix syntax, e.g., `k1 * S1`.

    Returns:
        The MathML of the formula without xml declaration and `math` element,
        with `cellml:units` attributes on numbers with units.

    Raises:
        MathMLError: if the formula does not parse.
    """
    ast: libsbml.ASTNode | None = libsbml.parseL3Formula(formula)
    if ast is None:
        raise MathMLError(
            f"Formula does not parse: '{formula}': {libsbml.getLastParseL3Error()}"
        )
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
