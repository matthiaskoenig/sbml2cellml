"""Construction of formulas as libsbml ASTs.

The converter keeps every formula as the AST libsbml reads from the model and
builds the new ones (reaction terms, amounts, rates) from nodes. A formula as
text in the syntax of libsbml cannot tell an id from a symbol of the syntax:
a parameter `avogadro`, `pi` or `NaN` would be read back as the constant.
"""

import libsbml


def name(sid: str) -> libsbml.ASTNode:
    """The reference to the element of an id, never a symbol of that name."""
    node = libsbml.ASTNode(libsbml.AST_NAME)
    node.setName(sid)
    return node


def number(value: float, units: str | None = None) -> libsbml.ASTNode:
    """A real number, infinity and NaN included.

    Args:
        value: the value.
        units: id of the SBML units of the number, none when `None`.
    """
    node = libsbml.ASTNode(libsbml.AST_REAL)
    node.setValue(value)
    if units is not None:
        node.setUnits(units)
    return node


def apply(operator: int, *arguments: libsbml.ASTNode) -> libsbml.ASTNode:
    """An operator or function applied to copies of its arguments.

    Args:
        operator: type of the node, e.g. `libsbml.AST_TIMES`.
        arguments: the arguments in their order, they are not changed.
    """
    node = libsbml.ASTNode(operator)
    for argument in arguments:
        node.addChild(argument.deepCopy())
    return node


def signed_sum(terms: list[tuple[int, libsbml.ASTNode]]) -> libsbml.ASTNode:
    """The sum of terms which are added (`AST_PLUS`) or subtracted (`AST_MINUS`).

    Args:
        terms: sign and term, at least one; the terms are not changed and
            every term is copied once, whatever the number of terms.

    Returns:
        `((-a + b) - c) ...`, the terms in their order.
    """
    result: libsbml.ASTNode | None = None
    for sign, term in terms:
        if result is None:
            result = term.deepCopy() if sign == libsbml.AST_PLUS else apply(sign, term)
            continue
        parent = libsbml.ASTNode(sign)
        parent.addChild(result)
        parent.addChild(term.deepCopy())
        result = parent
    if result is None:
        raise ValueError("A sum needs at least one term.")
    return result


def text(node: libsbml.ASTNode) -> str:
    """The formula in the syntax of libsbml, for logs and messages only."""
    formula: str = libsbml.formulaToL3String(node)
    return formula
