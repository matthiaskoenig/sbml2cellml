"""CellML models built with libcellml for the cellml2sbml tests."""

import libcellml

MATHML = '<math xmlns="http://www.w3.org/1998/Math/MathML" xmlns:cellml="http://www.cellml.org/cellml/2.0#">'


def math(*equations: str) -> str:
    """Wrap `apply` elements into the math element of a component."""
    return MATHML + "".join(equations) + "</math>"


def ode(state: str, voi: str, rhs: str) -> str:
    """`d state / d voi = rhs`."""
    return (
        f"<apply><eq/><apply><diff/><bvar><ci>{voi}</ci></bvar><ci>{state}</ci></apply>"
        f"{rhs}</apply>"
    )


def assignment(variable: str, rhs: str) -> str:
    """`variable = rhs`."""
    return f"<apply><eq/><ci>{variable}</ci>{rhs}</apply>"


def cn(value: str, units: str = "dimensionless") -> str:
    """Number with units."""
    return f'<cn cellml:units="{units}">{value}</cn>'


def variable(
    component: libcellml.Component,
    name: str,
    units: str | libcellml.Units,
    initial: float | str | None = None,
    interface: str | None = None,
) -> libcellml.Variable:
    """Add a variable to a component."""
    v = libcellml.Variable(name)
    v.setUnits(units)
    if initial is not None:
        v.setInitialValue(initial)
    if interface is not None:
        v.setInterfaceType(interface)
    component.addVariable(v)
    return v


def analyse(model: libcellml.Model) -> libcellml.AnalyserModel:
    """Analyse a model, failing the test on analyser errors."""
    analyser = libcellml.Analyser()
    analyser.analyseModel(model)
    errors = [
        analyser.issue(k).description()
        for k in range(analyser.issueCount())
        if analyser.issue(k).level() == libcellml.Issue.Level.ERROR  # ty: ignore[unresolved-attribute]
    ]
    assert not errors, errors
    return analyser.model()


def multi_component_model() -> libcellml.Model:
    """Two components with a connection and an encapsulated child.

    environment: t (VOI), k (constant 0.1 per_second)
    cell: time ~ environment.t, rate ~ environment.k, x (state, initial x0),
          x0 (constant 2 mM), y = 2 * x (algebraic), c = 2 * rate (computed constant)
    cell/child: t_child ~ cell.time, kc (constant 0.5), z (state), x = z (algebraic,
          the name clashes with cell.x)
    """
    model = libcellml.Model("multi")
    per_second = libcellml.Units("per_second")
    per_second.addUnit("second", -1.0)
    mM = libcellml.Units("mM")
    mM.addUnit("mole", "milli")
    mM.addUnit("litre", "", -1.0)
    model.addUnits(per_second)
    model.addUnits(mM)

    environment = libcellml.Component("environment")
    cell = libcellml.Component("cell")
    child = libcellml.Component("child")
    model.addComponent(environment)
    model.addComponent(cell)
    cell.addComponent(child)

    t = variable(environment, "t", "second", interface="public")
    k = variable(environment, "k", per_second, 0.1, interface="public")

    time = variable(cell, "time", "second", interface="public_and_private")
    rate = variable(cell, "rate", per_second, interface="public")
    variable(cell, "x", mM, "x0")
    variable(cell, "x0", mM, 2.0)
    variable(cell, "y", mM)
    variable(cell, "c", per_second)
    cell.setMath(
        math(
            ode(
                "x",
                "time",
                "<apply><times/><apply><minus/><ci>rate</ci></apply><ci>x</ci></apply>",
            ),
            assignment("y", f"<apply><times/>{cn('2')}<ci>x</ci></apply>"),
            assignment("c", f"<apply><times/>{cn('2')}<ci>rate</ci></apply>"),
        )
    )

    t_child = variable(child, "t_child", "second", interface="public")
    variable(child, "kc", per_second, 0.5)
    variable(child, "z", mM, 1.0)
    variable(child, "x", mM)
    child.setMath(
        math(
            ode(
                "z",
                "t_child",
                "<apply><times/><apply><minus/><ci>kc</ci></apply><ci>z</ci></apply>",
            ),
            assignment("x", "<ci>z</ci>"),
        )
    )

    libcellml.Variable.addEquivalence(t, time)
    libcellml.Variable.addEquivalence(k, rate)
    libcellml.Variable.addEquivalence(time, t_child)
    return model


def reset_model() -> libcellml.Model:
    """Mass growth with a reset halving m when it reaches m_div."""
    model = libcellml.Model("cell_growth")
    per_second = libcellml.Units("per_second")
    per_second.addUnit("second", -1.0)
    model.addUnits(per_second)

    component = libcellml.Component("environment")
    model.addComponent(component)
    variable(component, "t", "second")
    m = variable(component, "m", "kilogram", 1.0)
    variable(component, "alpha", per_second, 1.2)
    variable(component, "m_div", "kilogram", 7.0)
    component.setMath(
        math(ode("m", "t", "<apply><times/><ci>alpha</ci><ci>m</ci></apply>"))
    )

    reset = libcellml.Reset()
    reset.setOrder(0)
    reset.setVariable(m)
    reset.setTestVariable(m)
    reset.setTestValue(math(assignment("m", "<ci>m_div</ci>")))
    reset.setResetValue(
        math(assignment("m", f"<apply><divide/><ci>m</ci>{cn('2')}</apply>"))
    )
    component.addReset(reset)
    return model


def nla_model() -> libcellml.Model:
    """Two algebraic variables defined by an implicit system."""
    model = libcellml.Model("nla")
    component = libcellml.Component("main")
    model.addComponent(component)
    variable(component, "x", "dimensionless")
    variable(component, "y", "dimensionless")
    component.setMath(
        math(
            f"<apply><eq/><apply><plus/><ci>x</ci><ci>y</ci></apply>{cn('4')}</apply>",
            f"<apply><eq/><apply><minus/><ci>x</ci><ci>y</ci></apply>{cn('2')}</apply>",
        )
    )
    return model


def math_model(rhs_by_variable: dict[str, str]) -> libcellml.Model:
    """Single component with the VOI `t`, the state `x`, the constant `k` and one
    algebraic variable per entry, `name = rhs`."""
    model = libcellml.Model("maths")
    component = libcellml.Component("main")
    model.addComponent(component)
    variable(component, "t", "dimensionless")
    variable(component, "x", "dimensionless", 1.0)
    variable(component, "k", "dimensionless", 0.5)
    for name in rhs_by_variable:
        variable(component, name, "dimensionless")
    equations = [ode("x", "t", "<apply><times/><ci>k</ci><ci>x</ci></apply>")]
    equations.extend(assignment(name, rhs) for name, rhs in rhs_by_variable.items())
    component.setMath(math(*equations))
    return model
