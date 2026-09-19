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
CellML has no symbols either: the SBML time symbol becomes the variable of
integration `TIME_ID`, avogadro its value.
An n-ary operator with less than two arguments is replaced by its value.
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
#: name of the variable of integration, which the SBML time symbol becomes
TIME_ID = "time"

#: opening math element of the CellML component math
CELLML_MATH_OPEN = (
    '<math xmlns="http://www.w3.org/1998/Math/MathML" '
    'xmlns:cellml="http://www.cellml.org/cellml/2.0#">'
)


class MathMLError(ValueError):
    """A formula cannot be rendered as MathML."""


#: value of an operator without arguments (MathML: its identity element)
_EMPTY_OPERATORS = {
    libsbml.AST_PLUS: 0.0,
    libsbml.AST_TIMES: 1.0,
    libsbml.AST_LOGICAL_AND: libsbml.AST_CONSTANT_TRUE,
    libsbml.AST_LOGICAL_OR: libsbml.AST_CONSTANT_FALSE,
    libsbml.AST_LOGICAL_XOR: libsbml.AST_CONSTANT_FALSE,
}


def simplify_operators(node: libsbml.ASTNode) -> libsbml.ASTNode:
    """Replace n-ary operators with less than two arguments.

    MathML allows `plus`, `times`, `and`, `or` and `xor` with one argument
    (the argument) and without any (the identity element), CellML requires
    two.

    Args:
        node: root of the libsbml AST of the formula, changed in place.

    Returns:
        The root, which is another node when the root itself was replaced.
    """
    while node.getType() in _EMPTY_OPERATORS and node.getNumChildren() < 2:
        if node.getNumChildren() == 1:
            node = node.getChild(0).deepCopy()
            continue
        value = _EMPTY_OPERATORS[node.getType()]
        node = libsbml.ASTNode(libsbml.AST_REAL if isinstance(value, float) else value)
        if isinstance(value, float):
            node.setValue(value)
    for k in range(node.getNumChildren()):
        child: libsbml.ASTNode = node.getChild(k)
        simplified = simplify_operators(child)
        if simplified is not child:
            node.replaceChild(k, simplified.deepCopy(), True)
    return node


def normalize_math(node: libsbml.ASTNode) -> None:
    """Make the numbers and symbols of a formula valid CellML, in place.

    The time symbol becomes a reference to the variable of integration
    `TIME_ID`, avogadro a number with libsbml's value. Integers and
    rationals become reals, a finite number without units gets
    `NUMBER_UNITS`. Infinity and NaN stay as they are, they are written as
    the `infinity` and `notanumber` constants, which have no units. The
    delay and rateOf symbols stay, CellML has no counterpart for them.

    Args:
        node: root of the libsbml AST of the formula.
    """
    if node.getType() == libsbml.AST_NAME_TIME:
        node.setType(libsbml.AST_NAME)
        node.setName(TIME_ID)
        # else written as <ci definitionURL=".../symbols/time">
        node.setDefinitionURL("")
    elif node.getType() == libsbml.AST_NAME_AVOGADRO:
        node.setValue(node.getReal())
    if node.isNumber() and math.isfinite(node.getValue()):
        if node.getType() in (libsbml.AST_INTEGER, libsbml.AST_RATIONAL):
            node.setValue(float(node.getValue()))
        if not node.isSetUnits():
            node.setUnits(NUMBER_UNITS)
    for k in range(node.getNumChildren()):
        normalize_math(node.getChild(k))


def process_mathml_for_cellml(formula: str) -> str:
    """Render a formula in SBML L3 syntax as a MathML fragment for CellML.

    Args:
        formula: formula in the SBML level 3 infix syntax, e.g., `k1 * S1`.

    Returns:
        The MathML of the formula without xml declaration and `math` element,
        with `cellml:units` on every finite number and the time and
        avogadro symbols replaced (see `normalize_math`).

    Raises:
        MathMLError: if the formula does not parse.
    """
    ast: libsbml.ASTNode | None = libsbml.parseL3Formula(formula)
    if ast is None:
        raise MathMLError(
            f"Formula does not parse: '{formula}': {libsbml.getLastParseL3Error()}"
        )
    ast = simplify_operators(ast)
    normalize_math(ast)
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


def mathml_for_algebraic(formula: str) -> str:
    """MathML of the implicit equation `0 = formula`.

    Args:
        formula: the expression which is zero, in SBML L3 infix syntax.

    Returns:
        The `apply` element of the equation.
    """
    rhs = process_mathml_for_cellml(formula)
    return f"""<apply>
  <eq/>
  <cn {CELLML_UNITS_ATTRIBUTE}="{NUMBER_UNITS}">0</cn>
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
