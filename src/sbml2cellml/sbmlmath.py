"""Conversion of CellML maths to libsbml ASTs.

The libcellml analyser gives every equation as a binary tree of
`AnalyserEquationAst` nodes with the variables resolved. `ast_to_sbml` walks
such a tree into a `libsbml.ASTNode`; the variable of integration becomes the
SBML `time` symbol, variables get their SBML id. `mathml_to_sbml` reads the
MathML of a reset with libsbml and remaps the `ci` names the same way.

The analyser AST has the values of the numbers but not their units.
`NumberUnits` reads them from the MathML of the components and finds the
equation of an analyser AST by its variables and numbers.
"""

import logging
import math
from collections import defaultdict
from collections.abc import Callable, Iterator
from typing import Any
from xml.etree import ElementTree

import libcellml
import libsbml

from sbml2cellml.variables import VariableIds

logger = logging.getLogger(__name__)

AstType = libcellml.AnalyserEquationAst.Type  # ty: ignore[unresolved-attribute]

#: name of the SBML time symbol in formulas
TIME_ID = "time"

#: node types with two children
BINARY: dict[int, int] = {
    AstType.PLUS: libsbml.AST_PLUS,
    AstType.MINUS: libsbml.AST_MINUS,
    AstType.TIMES: libsbml.AST_TIMES,
    AstType.DIVIDE: libsbml.AST_DIVIDE,
    AstType.POWER: libsbml.AST_POWER,
    AstType.EQ: libsbml.AST_RELATIONAL_EQ,
    AstType.NEQ: libsbml.AST_RELATIONAL_NEQ,
    AstType.LT: libsbml.AST_RELATIONAL_LT,
    AstType.LEQ: libsbml.AST_RELATIONAL_LEQ,
    AstType.GT: libsbml.AST_RELATIONAL_GT,
    AstType.GEQ: libsbml.AST_RELATIONAL_GEQ,
    AstType.AND: libsbml.AST_LOGICAL_AND,
    AstType.OR: libsbml.AST_LOGICAL_OR,
    AstType.XOR: libsbml.AST_LOGICAL_XOR,
    AstType.REM: libsbml.AST_FUNCTION_REM,
    AstType.MIN: libsbml.AST_FUNCTION_MIN,
    AstType.MAX: libsbml.AST_FUNCTION_MAX,
}

#: node types with one child
UNARY: dict[int, int] = {
    AstType.ABS: libsbml.AST_FUNCTION_ABS,
    AstType.CEILING: libsbml.AST_FUNCTION_CEILING,
    AstType.FLOOR: libsbml.AST_FUNCTION_FLOOR,
    AstType.EXP: libsbml.AST_FUNCTION_EXP,
    AstType.LN: libsbml.AST_FUNCTION_LN,
    AstType.NOT: libsbml.AST_LOGICAL_NOT,
    AstType.SIN: libsbml.AST_FUNCTION_SIN,
    AstType.COS: libsbml.AST_FUNCTION_COS,
    AstType.TAN: libsbml.AST_FUNCTION_TAN,
    AstType.SEC: libsbml.AST_FUNCTION_SEC,
    AstType.CSC: libsbml.AST_FUNCTION_CSC,
    AstType.COT: libsbml.AST_FUNCTION_COT,
    AstType.SINH: libsbml.AST_FUNCTION_SINH,
    AstType.COSH: libsbml.AST_FUNCTION_COSH,
    AstType.TANH: libsbml.AST_FUNCTION_TANH,
    AstType.SECH: libsbml.AST_FUNCTION_SECH,
    AstType.CSCH: libsbml.AST_FUNCTION_CSCH,
    AstType.COTH: libsbml.AST_FUNCTION_COTH,
    AstType.ASIN: libsbml.AST_FUNCTION_ARCSIN,
    AstType.ACOS: libsbml.AST_FUNCTION_ARCCOS,
    AstType.ATAN: libsbml.AST_FUNCTION_ARCTAN,
    AstType.ASEC: libsbml.AST_FUNCTION_ARCSEC,
    AstType.ACSC: libsbml.AST_FUNCTION_ARCCSC,
    AstType.ACOT: libsbml.AST_FUNCTION_ARCCOT,
    AstType.ASINH: libsbml.AST_FUNCTION_ARCSINH,
    AstType.ACOSH: libsbml.AST_FUNCTION_ARCCOSH,
    AstType.ATANH: libsbml.AST_FUNCTION_ARCTANH,
    AstType.ASECH: libsbml.AST_FUNCTION_ARCSECH,
    AstType.ACSCH: libsbml.AST_FUNCTION_ARCCSCH,
    AstType.ACOTH: libsbml.AST_FUNCTION_ARCCOTH,
}

#: constants without children
CONSTANTS: dict[int, int] = {
    AstType.PI: libsbml.AST_CONSTANT_PI,
    AstType.E: libsbml.AST_CONSTANT_E,
    AstType.TRUE: libsbml.AST_CONSTANT_TRUE,
    AstType.FALSE: libsbml.AST_CONSTANT_FALSE,
}

#: constants which SBML writes as real numbers
REALS: dict[int, float] = {
    AstType.INF: math.inf,
    AstType.NAN: math.nan,
}


class MathConversionError(ValueError):
    """A CellML expression cannot be converted to SBML."""


def _real(value: float) -> libsbml.ASTNode:
    """Real number node."""
    node = libsbml.ASTNode(libsbml.AST_REAL)
    node.setValue(float(value))
    return node


def _name(node_type: int, name: str) -> libsbml.ASTNode:
    """Name node (variable or time symbol)."""
    node = libsbml.ASTNode(node_type)
    node.setName(name)
    return node


def variable_node(variable: Any, ids: VariableIds) -> libsbml.ASTNode:
    """AST node referencing a CellML variable.

    Args:
        variable: libcellml variable.
        ids: SBML ids of the model.

    Returns:
        The `time` symbol for the variable of integration, else the name node
        with the SBML id.
    """
    if ids.is_voi(variable):
        return _name(libsbml.AST_NAME_TIME, TIME_ID)
    return _name(libsbml.AST_NAME, ids.id_for(variable))


#: units of the numbers of an expression, consumed from the left to the right
type _Units = Iterator[str | None] | None
#: a variable (its SBML id) or a number of an equation
type _Token = tuple[str, str | float]

_MATHML = "{http://www.w3.org/1998/Math/MathML}"
_CELLML_UNITS = "{http://www.cellml.org/cellml/2.0#}units"


def _ast_tokens(node: Any, ids: VariableIds, tokens: list[_Token]) -> None:
    """Variables and numbers of an analyser AST, from the left to the right."""
    if node is None:
        return
    if node.type() == AstType.CI:
        tokens.append(("ci", ids.id_for(node.variable())))
    elif node.type() == AstType.CN:
        tokens.append(("cn", float(node.value())))
    _ast_tokens(node.leftChild(), ids, tokens)
    _ast_tokens(node.rightChild(), ids, tokens)


def count_numbers(node: Any) -> int:
    """Number of `cn` nodes of an analyser AST.

    Args:
        node: `libcellml.AnalyserEquationAst`, may be `None`.

    Returns:
        How many units of `NumberUnits.units_of` belong to `node`.
    """
    if node is None:
        return 0
    return (
        int(node.type() == AstType.CN)
        + count_numbers(node.leftChild())
        + count_numbers(node.rightChild())
    )


def _cn_value(element: ElementTree.Element) -> float:
    """Value of a MathML `cn`, `mantissa<sep/>exponent` for the e-notation."""
    sep = element.find(f"{_MATHML}sep")
    if sep is None:
        return float(element.text or "nan")
    return float(f"{(element.text or '').strip()}e{(sep.tail or '').strip()}")


class NumberUnits:
    """Units of the numbers of the equations of a CellML model.

    The equations are read from the MathML of the components. An analyser
    AST is matched with the equation which has the same variables and
    numbers in the same order; the analyser may have rearranged an equation,
    which is then found by its variables and numbers in any order and gives
    the units by the value of the numbers. An equation is handed out once,
    so equations which only differ in their units stay apart.
    """

    def __init__(
        self, model: libcellml.Model, ids: VariableIds, unit_id: Callable[[str], str]
    ) -> None:
        """Read the numbers of all equations.

        Args:
            model: the (flattened) CellML model.
            ids: SBML ids of the model.
            unit_id: SBML unit id of a CellML units name.
        """
        self._ids = ids
        #: tokens and number units of the equations not handed out yet
        self._equations: dict[tuple[_Token, ...], list[list[str | None]]]
        self._equations = defaultdict(list)
        stack = [model.component(k) for k in range(model.componentCount())]
        while stack:
            component = stack.pop(0)
            stack[0:0] = [
                component.component(k) for k in range(component.componentCount())
            ]
            self._read(component, unit_id)

    def _read(self, component: Any, unit_id: Callable[[str], str]) -> None:
        """Read the equations of a component."""
        if not component.math().strip():
            return
        try:
            # a component may have several math elements
            root = ElementTree.fromstring(f"<root>{component.math()}</root>")
        except ElementTree.ParseError:
            logger.warning(
                "Math of component '%s' does not parse, its numbers have no units.",
                component.name(),
            )
            return
        for equation in root.iterfind(f"{_MATHML}math/{_MATHML}apply"):
            tokens: list[_Token] = []
            units: list[str | None] = []
            for element in equation.iter():
                if element.tag == f"{_MATHML}ci":
                    name = (element.text or "").strip()
                    try:
                        tokens.append(("ci", self._ids.lookup(component.name(), name)))
                    except KeyError:
                        tokens.append(("ci", name))
                elif element.tag == f"{_MATHML}cn":
                    tokens.append(("cn", _cn_value(element)))
                    name = element.get(_CELLML_UNITS)
                    units.append(unit_id(name) if name else None)
            self._equations[tuple(tokens)].append(units)

    def units_of(self, ast: Any) -> _Units:
        """Units of the numbers of an equation.

        Args:
            ast: root of the analyser AST of the equation.

        Returns:
            The units of its numbers from the left to the right, for
            `ast_to_sbml`; `None` when the AST has no numbers or the
            equation is not found (logged).
        """
        tokens: list[_Token] = []
        _ast_tokens(ast, self._ids, tokens)
        values = [value for kind, value in tokens if kind == "cn"]
        if not values:
            return None
        candidates = self._equations.get(tuple(tokens))
        if candidates:
            return iter(candidates.pop(0))
        # a rearranged equation: the same variables and numbers in any order
        key = sorted(tokens, key=repr)
        for equation, remaining in self._equations.items():
            if remaining and sorted(equation, key=repr) == key:
                by_value: dict[str | float, set[str | None]] = defaultdict(set)
                numbers = [value for kind, value in equation if kind == "cn"]
                for value, units in zip(numbers, remaining[0], strict=True):
                    by_value[value].add(units)
                if all(len(by_value[value]) == 1 for value in values):
                    remaining.pop(0)
                    return iter([next(iter(by_value[value])) for value in values])
        logger.warning(
            "Units of the numbers %s of an equation not found, they have no units.",
            values,
        )
        return None


def _type_name(node: Any) -> str:
    """Lower case name of the node type, for messages."""
    return libcellml.AnalyserEquationAst.typeAsString(node.type())


def _children(node: Any, ids: VariableIds, units: _Units) -> list[libsbml.ASTNode]:
    """Converted children of a node, one or two."""
    children = [ast_to_sbml(node.leftChild(), ids, units)]
    if node.rightChild() is not None:
        children.append(ast_to_sbml(node.rightChild(), ids, units))
    return children


def _apply(node_type: int, children: list[libsbml.ASTNode]) -> libsbml.ASTNode:
    """Node with the given children."""
    node = libsbml.ASTNode(node_type)
    for child in children:
        node.addChild(child)
    return node


def _root(node: Any, ids: VariableIds, units: _Units) -> libsbml.ASTNode:
    """`root(degree, x)`; the square root when no degree is given."""
    left = node.leftChild()
    if left.type() == AstType.DEGREE:
        degree = ast_to_sbml(left.leftChild(), ids, units)
        radicand = ast_to_sbml(node.rightChild(), ids, units)
    else:
        degree = _real(2.0)
        radicand = ast_to_sbml(left, ids, units)
    return _apply(libsbml.AST_FUNCTION_ROOT, [degree, radicand])


def _log(node: Any, ids: VariableIds, units: _Units) -> libsbml.ASTNode:
    """`log(base, x)`; base 10 when no logbase is given."""
    left = node.leftChild()
    if left.type() == AstType.LOGBASE:
        base = ast_to_sbml(left.leftChild(), ids, units)
        argument = ast_to_sbml(node.rightChild(), ids, units)
    else:
        base = _real(10.0)
        argument = ast_to_sbml(left, ids, units)
    return _apply(libsbml.AST_FUNCTION_LOG, [base, argument])


def _piecewise(node: Any, ids: VariableIds, units: _Units) -> libsbml.ASTNode:
    """Flatten the nested piecewise of the analyser into one SBML piecewise.

    The analyser nests `PIECEWISE(PIECE, PIECEWISE(PIECE, OTHERWISE))`; SBML
    takes `piecewise(value, condition, ..., otherwise)`.
    """
    result = libsbml.ASTNode(libsbml.AST_FUNCTION_PIECEWISE)
    current = node
    while current is not None:
        current_type = current.type()
        if current_type == AstType.PIECEWISE:
            _add_piece(result, current.leftChild(), ids, units)
            current = current.rightChild()
        elif current_type in (AstType.PIECE, AstType.OTHERWISE):
            _add_piece(result, current, ids, units)
            current = None
        else:
            raise MathConversionError(
                f"Unexpected '{_type_name(current)}' in a piecewise expression."
            )
    return result


def _add_piece(
    result: libsbml.ASTNode, piece: Any, ids: VariableIds, units: _Units
) -> None:
    """Add the value and condition of a piece, or the otherwise value."""
    piece_type = piece.type()
    if piece_type == AstType.PIECE:
        result.addChild(ast_to_sbml(piece.leftChild(), ids, units))
        result.addChild(ast_to_sbml(piece.rightChild(), ids, units))
    elif piece_type == AstType.OTHERWISE:
        result.addChild(ast_to_sbml(piece.leftChild(), ids, units))
    else:
        raise MathConversionError(
            f"Unexpected '{_type_name(piece)}' in a piecewise expression."
        )


def ast_to_sbml(node: Any, ids: VariableIds, units: _Units = None) -> libsbml.ASTNode:
    """Convert an analyser AST into a libsbml AST.

    Args:
        node: `libcellml.AnalyserEquationAst`, e.g. the right child of the
            `EQUALITY` root of an equation.
        ids: SBML ids of the model.
        units: SBML units of the numbers below `node`, from the left to the
            right (`NumberUnits.units_of`); a number takes the next one, no
            units when it is `None`.

    Returns:
        The libsbml AST.

    Raises:
        MathConversionError: for a node type without SBML counterpart, e.g.
            `DIFF` or `BVAR` outside the left side of an ODE.
    """
    node_type = node.type()
    if node_type == AstType.CI:
        return variable_node(node.variable(), ids)
    if node_type == AstType.CN:
        number = _real(float(node.value()))
        number_units = next(units, None) if units is not None else None
        if number_units is not None:
            number.setUnits(number_units)
        return number
    if node_type in CONSTANTS:
        return libsbml.ASTNode(CONSTANTS[node_type])
    if node_type in REALS:
        return _real(REALS[node_type])
    if node_type == AstType.MINUS and node.rightChild() is None:
        return _apply(libsbml.AST_MINUS, _children(node, ids, units))
    if node_type in BINARY:
        return _apply(BINARY[node_type], _children(node, ids, units))
    if node_type in UNARY:
        return _apply(UNARY[node_type], _children(node, ids, units))
    if node_type == AstType.ROOT:
        return _root(node, ids, units)
    if node_type == AstType.LOG:
        return _log(node, ids, units)
    if node_type == AstType.PIECEWISE:
        return _piecewise(node, ids, units)
    raise MathConversionError(
        f"MathML element '{_type_name(node)}' cannot be converted to SBML."
    )


def _rename(
    node: libsbml.ASTNode,
    component_name: str,
    ids: VariableIds,
    unit_id: Callable[[str], str] | None,
) -> None:
    """Replace the CellML names of a libsbml AST by the SBML ids, in place.

    With `unit_id` the units of the numbers as well.
    """
    if unit_id is not None and node.isNumber() and node.isSetUnits():
        node.setUnits(unit_id(node.getUnits()))
    if node.getType() == libsbml.AST_NAME:
        name = node.getName()
        try:
            sid = ids.lookup(component_name, name)
        except KeyError as err:
            raise MathConversionError(
                f"Variable '{name}' of component '{component_name}' is unknown."
            ) from err
        if ids.is_voi_key(component_name, name):
            node.setType(libsbml.AST_NAME_TIME)
            node.setName(TIME_ID)
        else:
            node.setName(sid)
    for k in range(node.getNumChildren()):
        _rename(node.getChild(k), component_name, ids, unit_id)


def mathml_to_sbml(
    mathml: str,
    component_name: str,
    ids: VariableIds,
    unit_id: Callable[[str], str] | None = None,
) -> libsbml.ASTNode:
    """Read CellML MathML with libsbml and remap the variable names.

    Used for the maths of resets, which the analyser does not cover. Units on
    numbers (`cellml:units`) become `sbml:units`.

    Args:
        mathml: complete `math` element.
        component_name: component the MathML belongs to, resolves the names.
        ids: SBML ids of the model.
        unit_id: SBML unit id of a CellML units name, the name itself when
            `None`.

    Returns:
        The libsbml AST.

    Raises:
        MathConversionError: if the MathML does not parse or a name is unknown.
    """
    sbml_mathml = mathml.replace(
        'xmlns:cellml="http://www.cellml.org/cellml/2.0#"',
        'xmlns:sbml="http://www.sbml.org/sbml/level3/version2/core"',
    ).replace("cellml:units", "sbml:units")
    node = libsbml.readMathMLFromString(sbml_mathml)
    if node is None:
        raise MathConversionError("MathML could not be parsed by libsbml.")
    _rename(node, component_name, ids, unit_id)
    return node
