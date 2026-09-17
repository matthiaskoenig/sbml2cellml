"""Build a CellML model with libcellml, validate, write and simulate it.

The model is the mass decay `dm/dt = -alpha * m` with `m` in kilogram and
`alpha` in per second; it is the same model as `examples/models/test_model.cellml`.
"""

from pathlib import Path

import libcellml

from sbml2cellml import log
from sbml2cellml.cellml import errors, format_issues, validate_model, write_model
from sbml2cellml.console import console
from sbml2cellml.simulate import plot_timecourse, run_timecourse

RESULTS_DIR: Path = Path(__file__).parent / "results"

MATH_ODE = """
<math xmlns="http://www.w3.org/1998/Math/MathML">
    <apply>
        <eq/>
        <apply>
            <diff/>
            <bvar>
                <ci>t</ci>
            </bvar>
            <ci>m</ci>
        </apply>
        <apply>
            <times/>
            <apply>
              <minus/>
              <ci>alpha</ci>
            </apply>
            <ci>m</ci>
        </apply>
    </apply>
</math>
"""


def example_cellml() -> libcellml.Model:
    """Mass decay model with the variables t, m and alpha."""
    model = libcellml.Model("test_model")

    per_second = libcellml.Units("per_second")
    per_second.addUnit("second", -1)
    model.addUnits(per_second)

    component = libcellml.Component("component")
    component.setMath(MATH_ODE)
    model.addComponent(component)

    variable_time = libcellml.Variable("t")
    variable_time.setUnits("second")

    variable_m = libcellml.Variable("m")
    variable_m.setUnits("kilogram")
    variable_m.setInitialValue(10)

    variable_alpha = libcellml.Variable("alpha")
    variable_alpha.setUnits(per_second)
    variable_alpha.setInitialValue(0.05)

    for variable in [variable_time, variable_m, variable_alpha]:
        component.addVariable(variable)

    return model


if __name__ == "__main__":
    log.enable_rich_logging()
    RESULTS_DIR.mkdir(exist_ok=True)

    model = example_cellml()
    issues = validate_model(model)
    if errors(issues):
        console.print(format_issues(issues), style="error")
    else:
        console.print("CellML model is valid.", style="success")

    cellml_path = RESULTS_DIR / "test_model.cellml"
    write_model(model=model, cellml_path=cellml_path)
    console.print(f"CellML written to '{cellml_path}'")

    df, units = run_timecourse(cellml_path, start=0.0, end=100.0, steps=100)
    console.print(df)
    plot_timecourse(df=df, units=units)
