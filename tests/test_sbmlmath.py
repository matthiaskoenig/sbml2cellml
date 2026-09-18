"""Tests of the conversion of CellML maths to libsbml ASTs."""

import libcellml
import libsbml
import pytest

from sbml2cellml.sbmlmath import (
    MathConversionError,
    ast_to_sbml,
    mathml_to_sbml,
    variable_node,
)
from sbml2cellml.variables import VariableIds
from tests.cellml_models import analyse, cn, math_model

X = "<ci>x</ci>"
K = "<ci>k</ci>"


def unary(op: str, arg: str = X) -> str:
    return f"<apply><{op}/>{arg}</apply>"


def binary(op: str, a: str, b: str) -> str:
    return f"<apply><{op}/>{a}{b}</apply>"


CASES: dict[str, tuple[str, str]] = {
    # name: (CellML MathML right hand side, libsbml L3 formula)
    "a_plus": (binary("plus", X, K), "x + k"),
    "a_minus": (binary("minus", X, K), "x - k"),
    "a_neg": (unary("minus"), "-x"),
    "a_times": (binary("times", X, K), "x * k"),
    "a_divide": (binary("divide", X, K), "x / k"),
    "a_power": (binary("power", X, cn("2")), "x^2"),
    "a_nary": (f"<apply><plus/>{X}{K}{cn('1')}</apply>", "x + (k + 1)"),
    "a_root": (f"<apply><root/><degree>{cn('3')}</degree>{X}</apply>", "root(3, x)"),
    "a_sqrt": (unary("root"), "root(2, x)"),
    "a_log": (f"<apply><log/><logbase>{cn('2')}</logbase>{X}</apply>", "log(2, x)"),
    "a_log10": (unary("log"), "log(10, x)"),
    "a_ln": (unary("ln"), "ln(x)"),
    "a_exp": (unary("exp"), "exp(x)"),
    "a_abs": (unary("abs"), "abs(x)"),
    "a_ceiling": (unary("ceiling"), "ceil(x)"),
    "a_floor": (unary("floor"), "floor(x)"),
    "a_rem": (binary("rem", X, cn("3")), "rem(x, 3)"),
    "a_min": (binary("min", X, K), "min(x, k)"),
    "a_max": (binary("max", X, K), "max(x, k)"),
    "a_sin": (unary("sin"), "sin(x)"),
    "a_cos": (unary("cos"), "cos(x)"),
    "a_tan": (unary("tan"), "tan(x)"),
    "a_sec": (unary("sec"), "sec(x)"),
    "a_csc": (unary("csc"), "csc(x)"),
    "a_cot": (unary("cot"), "cot(x)"),
    "a_sinh": (unary("sinh"), "sinh(x)"),
    "a_cosh": (unary("cosh"), "cosh(x)"),
    "a_tanh": (unary("tanh"), "tanh(x)"),
    "a_sech": (unary("sech"), "sech(x)"),
    "a_csch": (unary("csch"), "csch(x)"),
    "a_coth": (unary("coth"), "coth(x)"),
    "a_arcsin": (unary("arcsin"), "asin(x)"),
    "a_arccos": (unary("arccos"), "acos(x)"),
    "a_arctan": (unary("arctan"), "atan(x)"),
    "a_arcsec": (unary("arcsec"), "arcsec(x)"),
    "a_arccsc": (unary("arccsc"), "arccsc(x)"),
    "a_arccot": (unary("arccot"), "arccot(x)"),
    "a_arcsinh": (unary("arcsinh"), "arcsinh(x)"),
    "a_arccosh": (unary("arccosh"), "arccosh(x)"),
    "a_arctanh": (unary("arctanh"), "arctanh(x)"),
    "a_arcsech": (unary("arcsech"), "arcsech(x)"),
    "a_arccsch": (unary("arccsch"), "arccsch(x)"),
    "a_arccoth": (unary("arccoth"), "arccoth(x)"),
    "a_pi": ("<pi/>", "pi"),
    "a_e": ("<exponentiale/>", "exponentiale"),
    "a_inf": ("<infinity/>", "INF"),
    "a_nan": ("<notanumber/>", "NaN"),
    "a_enotation": (
        '<cn cellml:units="dimensionless" type="e-notation">1<sep/>-2</cn>',
        "0.01",
    ),
    "a_time": ("<ci>t</ci>", "time"),
    "a_piecewise": (
        f"<piecewise><piece>{K}{binary('lt', X, cn('1'))}</piece>"
        f"<piece>{cn('0')}{binary('geq', X, cn('2'))}</piece>"
        f"<otherwise>{X}</otherwise></piecewise>",
        "piecewise(k, x < 1, 0, x >= 2, x)",
    ),
    "a_logic": (
        f"<piecewise><piece>{cn('1')}<apply><and/>{binary('lt', X, cn('1'))}"
        f"<apply><or/>{binary('gt', X, cn('0'))}<apply><not/>{binary('eq', X, cn('3'))}</apply></apply>"
        f"<apply><xor/>{binary('neq', X, cn('4'))}{binary('leq', K, cn('5'))}</apply>"
        f"<true/></apply></piece><otherwise><false/></otherwise></piecewise>",
        "piecewise(1, (x < 1) && (((x > 0) || !(x == 3)) && (xor((x != 4), (k <= 5)) && true)), false)",
    ),
    "a_piecewise_no_otherwise": (
        f"<piecewise><piece>{K}{binary('lt', X, cn('1'))}</piece></piecewise>",
        "piecewise(k, x < 1)",
    ),
    "a_piecewise_single": (
        f"<piecewise><piece>{K}{binary('lt', X, cn('1'))}</piece>"
        f"<piece>{X}{binary('gt', X, cn('2'))}</piece></piecewise>",
        "piecewise(k, x < 1, x, x > 2)",
    ),
}


@pytest.fixture(scope="module")
def converted() -> dict[str, str]:
    """L3 formula of every case, converted through the analyser."""
    model = math_model({name: rhs for name, (rhs, _) in CASES.items()})
    analyser_model = analyse(model)
    ids = VariableIds(analyser_model)
    formulas: dict[str, str] = {}
    for k in range(analyser_model.analyserEquationCount()):
        equation = analyser_model.analyserEquation(k)
        ast = equation.ast()
        name = ast.leftChild().variable().name() if ast.leftChild().variable() else None
        if name in CASES:
            formulas[name] = libsbml.formulaToL3String(
                ast_to_sbml(ast.rightChild(), ids)
            )
    return formulas


@pytest.mark.parametrize("name", list(CASES))
def test_ast_to_sbml(name: str, converted: dict[str, str]) -> None:
    assert converted[name] == CASES[name][1]


def test_unsupported_node_raises() -> None:
    model = math_model({"a": "<apply><plus/><ci>x</ci><ci>k</ci></apply>"})
    analyser_model = analyse(model)
    ids = VariableIds(analyser_model)
    ode = next(
        analyser_model.analyserEquation(k)
        for k in range(analyser_model.analyserEquationCount())
        if analyser_model.analyserEquation(k).type()
        == libcellml.AnalyserEquation.Type.ODE  # ty: ignore[unresolved-attribute]
    )
    # the left side of an ODE holds a DIFF node, which has no place in an expression
    with pytest.raises(MathConversionError, match="diff"):
        ast_to_sbml(ode.ast().leftChild(), ids)


def test_variable_node() -> None:
    model = math_model({})
    ids = VariableIds(analyse(model))
    component = model.component("main")
    assert libsbml.formulaToL3String(variable_node(component.variable("k"), ids)) == "k"
    time = variable_node(component.variable("t"), ids)
    assert time.getType() == libsbml.AST_NAME_TIME
    assert libsbml.formulaToL3String(time) == "time"


def test_mathml_to_sbml_remaps_names() -> None:
    model = math_model({})
    ids = VariableIds(analyse(model))
    mathml = (
        '<math xmlns="http://www.w3.org/1998/Math/MathML" '
        'xmlns:cellml="http://www.cellml.org/cellml/2.0#">'
        f"<apply><times/><ci>k</ci><ci>t</ci>{cn('2')}</apply></math>"
    )
    node = mathml_to_sbml(mathml, "main", ids)
    assert libsbml.formulaToL3String(node) == "k * time * 2 dimensionless"
    with pytest.raises(MathConversionError, match="unknown"):
        mathml_to_sbml(mathml.replace("<ci>k</ci>", "<ci>nope</ci>"), "main", ids)
    with pytest.raises(MathConversionError, match="parsed"):
        mathml_to_sbml("<math>not closed", "main", ids)
