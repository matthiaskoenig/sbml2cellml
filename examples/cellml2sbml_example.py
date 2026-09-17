"""Convert CellML models to SBML.

Converts `examples/models/test_model.cellml` and a model with a reset built
with libcellml, writes the SBML into `examples/results/` and prints it.
"""

from pathlib import Path

import libcellml

from sbml2cellml import convert_cellml2sbml, log
from sbml2cellml.cellml import write_model
from sbml2cellml.console import console
from sbml2cellml.sbml import document_to_string

MODELS_DIR: Path = Path(__file__).parent / "models"
RESULTS_DIR: Path = Path(__file__).parent / "results"


def reset_model() -> libcellml.Model:
    """Mass growth `dm/dt = alpha * m` halved whenever m reaches m_div."""
    model = libcellml.Model("cell_growth")
    per_second = libcellml.Units("per_second")
    per_second.addUnit("second", -1.0)
    model.addUnits(per_second)
    component = libcellml.Component("environment")
    model.addComponent(component)
    for name, units, initial in [
        ("t", "second", None),
        ("m", "kilogram", 1.0),
        ("alpha", per_second, 1.2),
        ("m_div", "kilogram", 7.0),
    ]:
        variable = libcellml.Variable(name)
        variable.setUnits(units)
        if initial is not None:
            variable.setInitialValue(initial)
        component.addVariable(variable)
    component.setMath(
        '<math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<apply><eq/><apply><diff/><bvar><ci>t</ci></bvar><ci>m</ci></apply>"
        "<apply><times/><ci>alpha</ci><ci>m</ci></apply></apply></math>"
    )
    reset = libcellml.Reset()
    reset.setOrder(0)
    reset.setVariable(component.variable("m"))
    reset.setTestVariable(component.variable("m"))
    reset.setTestValue(
        '<math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<apply><eq/><ci>m</ci><ci>m_div</ci></apply></math>"
    )
    reset.setResetValue(
        '<math xmlns="http://www.w3.org/1998/Math/MathML" '
        'xmlns:cellml="http://www.cellml.org/cellml/2.0#">'
        "<apply><eq/><ci>m</ci><apply><divide/><ci>m</ci>"
        '<cn cellml:units="dimensionless">2</cn></apply></apply></math>'
    )
    component.addReset(reset)
    return model


if __name__ == "__main__":
    log.enable_rich_logging()
    RESULTS_DIR.mkdir(exist_ok=True)

    reset_path = RESULTS_DIR / "cell_growth.cellml"
    write_model(reset_model(), reset_path)

    for cellml_path in [MODELS_DIR / "test_model.cellml", reset_path]:
        console.rule(cellml_path.name, style="white")
        sbml_path = RESULTS_DIR / f"{cellml_path.stem}.xml"
        doc = convert_cellml2sbml(cellml_path, sbml_path=sbml_path)
        console.print(document_to_string(doc))
