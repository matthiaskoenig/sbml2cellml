"""Build the models of the online simulator of the documentation.

The [online simulator](../docs/index.md) of the landing page simulates a
published model twice in the browser: the CellML side with libopencor and
the SBML side with sbmlsim-core, with one set of sliders for the parameters
of both. A model of [BioModels](https://www.biomodels.org) is an SBML model
which the page converts to CellML, a model of the [Physiome Model
Repository](https://models.physiomeproject.org) a CellML model which it
converts to SBML, both with the WebAssembly module of the rust converters,
so every model of the selection runs in both simulators.

The page needs more than the documents: which parameters its sliders set
(the id of the SBML parameter and the component and the variable of CellML),
which variables its plots show and what the counterpart of a variable is
called on the other side. This script computes all of it from the model, as
the two converters write it, verifies it by simulating both sides of every
model with the python package (the simulators of the browser are the same
WebAssembly modules) and writes the selection next to the page:

```bash
uv run python scripts/build_simulator_models.py
uv run zensical serve
```

`docs/simulator/models.json` and the model files of
`docs/simulator/models/` are committed, since the caches of the BioModels
and the Physiome check are local and the `documentation` workflow cannot
build them. The check of the selection is `tests/test_simulator_models.py`,
which reads the manifest and the models of the documentation.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import libcellml
import libsbml

from sbml2cellml import rust
from sbml2cellml.cellml import cellml_version
from sbml2cellml.cellml2sbml import analyse_model, read_cellml_model
from sbml2cellml.console import console
from sbml2cellml.log import enable_rich_logging
from sbml2cellml.overview.checks import (
    BIOMODELS_MODEL_URL,
    PHYSIOME_MODEL_URL,
    load_runs,
    works,
)
from sbml2cellml.variables import VariableIds, components

logger = logging.getLogger(__name__)

#: where the manifest and the models of the page live, relative to `docs/`
SIMULATOR = Path("simulator")
#: the largest number of sliders of a model, the first parameters of the model
SLIDERS = 6
#: the largest number of series of the two plots, the first states of the model
SERIES = 8
#: the relative difference between the two simulations which is accepted
#: when the selection is verified, the tolerance of the BioModels check
RELATIVE = 1e-3
#: the absolute difference which is accepted, the tolerance of the checks
ABSOLUTE = 1e-6
#: the factor a parameter is changed by when the sliders are verified: both
#: simulations must follow the change and must still agree with each other
PERTURBATION = 1.2
#: the settings of the solver of both simulations, the ones of the page and
#: of the checks of the repository
RELATIVE_TOLERANCE = 1e-9
ABSOLUTE_TOLERANCE = 1e-12
MAXIMUM_STEPS = 100000


@dataclass(frozen=True)
class Choice:
    """A model of the selection of the page."""

    #: id of the model, the case of its check
    id: str
    #: the check the model comes from, `biomodels` or `physiome`
    check: str
    #: end of the timecourse, in the time units of the model
    end: float
    #: number of output steps of the timecourse
    steps: int
    #: title of the model on the page, the title of the check by default
    title: str | None = None
    #: a file of the documentation the page reads the model from, relative
    #: to `docs/`; the model of the check is copied next to the page without
    #: one
    file: str | None = None


#: the models of the page, the first one is the model it opens with
CHOICES: tuple[Choice, ...] = (
    Choice(
        id="BIOMD0000000012",
        check="biomodels",
        end=600,
        steps=600,
        title="Elowitz, Leibler, 2000: repressilator",
        file="roundtrip/repressilator.xml",
    ),
    Choice(
        id="BIOMD0000000156",
        check="biomodels",
        end=100,
        steps=1000,
        title="Geva-Zatorsky, 2006: p53 oscillations",
    ),
    Choice(
        id="BIOMD0000000098",
        check="biomodels",
        end=30,
        steps=600,
        title="Goldbeter, 1990: calcium spikes",
    ),
    Choice(
        id="BIOMD0000000206",
        check="biomodels",
        end=5,
        steps=600,
        title="Wolf, 2000: glycolytic oscillations",
    ),
    Choice(
        id="BIOMD0000000299",
        check="biomodels",
        end=100,
        steps=1000,
        title="Leloup, 1999: circadian rhythms of Neurospora",
    ),
    Choice(
        id="BIOMD0000000521",
        check="biomodels",
        end=100,
        steps=500,
        title="Ribba, 2012: low-grade glioma",
    ),
    Choice(
        id="3c",
        check="physiome",
        end=50,
        steps=1000,
        title="Morris, Lecar, 1981: excitable membrane",
    ),
    Choice(
        id="2a6",
        check="physiome",
        end=10,
        steps=1000,
        title="Noble, 1962: cardiac action potential",
    ),
    Choice(
        id="59",
        check="physiome",
        end=200,
        steps=1000,
        title="Friel, 1995: calcium oscillations",
    ),
    Choice(
        id="3fe",
        check="physiome",
        end=100,
        steps=1000,
        title="Goldbeter, Guilmot, 1995: mitotic oscillator",
    ),
    Choice(
        id="4d",
        check="physiome",
        end=100,
        steps=1000,
        title="Goldbeter, 1995: circadian oscillations of PER",
    ),
    Choice(
        id="48",
        check="physiome",
        end=200,
        steps=1000,
        title="Elowitz, Leibler, 2000: repressilator",
    ),
)


@dataclass
class Parameter:
    """A slider of the page, one parameter of both models."""

    #: id of the SBML parameter, the selection of sbmlsim-core
    sbml: str
    #: component of the CellML variable, for libopencor
    component: str
    #: name of the CellML variable
    variable: str
    #: label of the slider, the id of the parameter of the model
    label: str
    #: name of the parameter, empty when the model gives it none
    name: str
    #: units of the quantity, as the model has them
    unit: str
    #: value of the published model
    value: float
    #: smallest value of the slider
    minimum: float
    #: largest value of the slider
    maximum: float
    #: step of the slider
    step: float


@dataclass
class Series:
    """A series of the two plots, one state of both models."""

    #: label of the series, the name of the CellML variable
    label: str
    #: name of the variable of the CellML result, `component/variable`
    cellml: str
    #: selection of sbmlsim-core which holds the same quantity
    sbml: str


@dataclass
class Model:
    """A model of the page with everything the page needs of it."""

    id: str
    title: str
    check: str
    source: str
    url: str
    direction: str
    file: str
    end: float
    steps: int
    parameters: list[Parameter] = field(default_factory=list)
    series: list[Series] = field(default_factory=list)


def _repository() -> Path:
    """The root of the repository.

    Returns:
        The directory which holds `docs/`.
    """
    return Path(__file__).resolve().parent.parent


def _models_dir() -> Path:
    """Where the model files of the page live.

    Returns:
        The directory of the models, created when it does not exist.
    """
    target = _repository() / "docs" / SIMULATOR / "models"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _slider(value: float) -> tuple[float, float, float]:
    """The range of the slider of a parameter.

    The slider covers the value of the published model up to twice that
    value, so the model it opens with is in the middle of every slider, and
    the lower end is zero for a positive parameter, where a value of zero
    switches a term of the model off.

    Args:
        value: value of the parameter in the published model.

    Returns:
        The smallest value, the largest value and the step of the slider,
        one hundredth of the range.
    """
    if value > 0:
        minimum, maximum = 0.0, 2.0 * value
    elif value < 0:
        minimum, maximum = 2.0 * value, 0.0
    else:
        minimum, maximum = 0.0, 1.0
    return minimum, maximum, (maximum - minimum) / 100.0


def _unit_name(units: str) -> str:
    """The units of a quantity as the model names them.

    The name of the units is what the page shows next to a slider, so it is
    the name of the model (`per_min`, `micromolar_per_minute`) and not the
    base units it stands for, which are a line of text.

    Args:
        units: the units of the quantity, the attribute of SBML or the name
            of the units of CellML.

    Returns:
        The name, empty for a quantity without units and for dimensionless
        ones, which no label of the page shows.
    """
    return "" if units in {"", "dimensionless"} else units


def _name_of(parameter: libsbml.Parameter) -> str:
    """The name of a parameter, next to its id on the slider of the page.

    Args:
        parameter: the SBML parameter.

    Returns:
        The name of the parameter, empty when it has none or when the name
        is the id again.
    """
    name = parameter.getName()
    return "" if name == parameter.getId() else name


def _settable(model: libsbml.Model) -> list[libsbml.Parameter]:
    """The parameters of a model a slider can set, in the order of the model.

    A slider sets the value of a parameter before the initial assignments
    are evaluated, as `preinit` of sbmlsim-core and a change of libopencor
    do, so a parameter which a rule or an initial assignment determines is
    no slider: its value would be overwritten.

    Args:
        model: the SBML model.

    Returns:
        The parameters which are constant, have a finite value which is not
        zero and are determined by nothing else.
    """
    determined = {rule.getVariable() for rule in model.getListOfRules()}
    determined |= {
        assignment.getSymbol() for assignment in model.getListOfInitialAssignments()
    }
    out = []
    for parameter in model.getListOfParameters():
        if not parameter.getConstant() or parameter.getId() in determined:
            continue
        if not parameter.isSetValue():
            continue
        value = parameter.getValue()
        if value == 0.0 or not _finite(value):
            continue
        out.append(parameter)
    return out


def _finite(value: float) -> bool:
    """Whether a value is a finite number.

    Args:
        value: the value.

    Returns:
        Whether the value is neither NaN nor infinite.
    """
    return value == value and abs(value) != float("inf")


def _analyse(text: str) -> Any:
    """Analyse a CellML document as libopencor analyses it.

    Args:
        text: the CellML document.

    Returns:
        The model of the analyser of libcellml.

    Raises:
        SystemExit: if the document cannot be read or analysed.
    """
    parser = libcellml.Parser(True)
    model = parser.parseModel(text)
    if parser.errorCount() > 0:
        raise SystemExit(
            f"the CellML model has errors: {parser.error(0).description()}"
        )
    analyser = libcellml.Analyser()
    analyser.analyseModel(model)
    if analyser.errorCount() > 0:
        raise SystemExit(f"the CellML model: {analyser.error(0).description()}")
    return analyser.analyserModel()


def _states(analysed: Any) -> list[tuple[str, str]]:
    """The states of an analysed CellML model, in the order of the analysis.

    libopencor analyses a model with libcellml and reports the states in
    that order, so the series of the page are the first states of this list.

    Args:
        analysed: the model of the analyser.

    Returns:
        The component and the name of every state.
    """
    states = []
    for index in range(analysed.stateCount()):
        variable = analysed.state(index).variable()
        states.append((variable.parent().name(), variable.name()))
    return states


def _labels(states: list[tuple[str, str]]) -> list[str]:
    """The labels of the states of a model.

    The label of a state is the name of its variable, and the full name when
    another state of the model has that name as well, as the result of the
    python package names its columns.

    Args:
        states: the component and the name of every state.

    Returns:
        One label per state.
    """
    counts: dict[str, int] = {}
    for _, name in states:
        counts[name] = counts.get(name, 0) + 1
    return [
        name if counts[name] == 1 else f"{component}/{name}"
        for component, name in states
    ]


def _selection(name: str, model: libsbml.Model) -> str:
    """The selection of sbmlsim-core which holds a variable of CellML.

    The conversion writes a species as the variable of its concentration, or
    of its amount when the species has only substance units, and gives a
    species in a compartment which changes a second variable
    `<species>_amount`, which is the state of the model. sbmlsim-core selects
    the amount of a species by its id and its concentration as `[id]`.

    Args:
        name: name of the variable of the CellML model.
        model: the SBML model.

    Returns:
        The selection of the same quantity.
    """
    if name.endswith("_amount"):
        base = name[: -len("_amount")]
        if model.getSpecies(base) is not None:
            return base
    species = model.getSpecies(name)
    if species is None:
        return name
    return name if species.getHasOnlySubstanceUnits() else f"[{name}]"


def _title(choice: Choice, titles: dict[str, str]) -> str:
    """The title of a model on the page.

    Args:
        choice: the model of the selection.
        titles: the title of every model of its check.

    Returns:
        The title of the choice, else the title of the check, else the id.
    """
    return choice.title or titles.get(choice.id) or choice.id


def _from_sbml(choice: Choice, text: str, title: str, file: str) -> tuple[Model, str]:
    """What the page needs of a model of BioModels, an SBML model.

    The page converts the SBML document to CellML, so the variables of the
    CellML model are the ids of the SBML model in the one component the
    conversion writes.

    Args:
        choice: the model of the selection.
        text: the SBML document.
        title: the title of the model on the page.
        file: the file of the documentation the page reads the model from.

    Returns:
        The model of the page and the CellML document of the conversion.

    Raises:
        SystemExit: if the conversion refuses the model.
    """
    document = libsbml.readSBMLFromString(text)
    model = document.getModel()
    if model is None:
        raise SystemExit(f"{choice.id}: no model in the SBML document")
    try:
        cellml, warnings, _ = rust.convert_sbml_to_cellml(text, name=choice.id)
    except rust.RustError as error:
        raise SystemExit(
            f"{choice.id}: the conversion refuses the model: {error}"
        ) from error
    for warning in warnings:
        logger.info("%s: %s", choice.id, warning)
    analysed = _analyse(cellml)
    page = Model(
        id=choice.id,
        title=title,
        check=choice.check,
        source="BioModels",
        url=BIOMODELS_MODEL_URL.format(id=choice.id),
        direction="sbml2cellml",
        file=file,
        end=choice.end,
        steps=choice.steps,
    )
    components = _components_of(cellml)
    for parameter in _settable(model):
        if len(page.parameters) == SLIDERS:
            break
        component = components.get(parameter.getId())
        if component is None:
            # a parameter the conversion wrote under another name
            continue
        value = parameter.getValue()
        minimum, maximum, step = _slider(value)
        page.parameters.append(
            Parameter(
                sbml=parameter.getId(),
                component=component,
                variable=parameter.getId(),
                label=parameter.getId(),
                name=_name_of(parameter),
                unit=_unit_name(parameter.getUnits()),
                value=value,
                minimum=minimum,
                maximum=maximum,
                step=step,
            )
        )
    states = _states(analysed)[:SERIES]
    for (component, name), label in zip(states, _labels(states), strict=True):
        page.series.append(
            Series(
                label=label, cellml=f"{component}/{name}", sbml=_selection(name, model)
            )
        )
    return page, cellml


def _components_of(cellml: str) -> dict[str, str]:
    """The component of every variable of a CellML document.

    Args:
        cellml: the CellML document.

    Returns:
        The name of the component of every variable, by the name of the
        variable; a name which more than one component has is left out,
        since a slider must name one variable.
    """
    parser = libcellml.Parser(True)
    model = parser.parseModel(cellml)
    out: dict[str, str] = {}
    duplicates: set[str] = set()
    for index in range(model.componentCount()):
        component = model.component(index)
        for position in range(component.variableCount()):
            name = component.variable(position).name()
            if name in out:
                duplicates.add(name)
            out[name] = component.name()
    for name in duplicates:
        del out[name]
    return out


def _from_cellml(
    choice: Choice, path: Path, text: str, title: str, file: str
) -> tuple[Model, str]:
    """What the page needs of a model of the Physiome Model Repository.

    The page converts the CellML document to SBML, so a slider sets the
    variable of CellML and the parameter of the SBML model which the
    conversion wrote it as (`VariableIds`, the ids of both converters).

    Args:
        choice: the model of the selection.
        path: the file of the CellML model, which libcellml reads.
        text: the CellML document, which the page converts.
        title: the title of the model on the page.
        file: the file of the documentation the page reads the model from.

    Returns:
        The model of the page and the SBML document of the conversion.

    Raises:
        SystemExit: if the conversion refuses the model.
    """
    if rust.has_imports(text):
        raise SystemExit(f"{choice.id}: the model imports, which the page cannot read")
    try:
        sbml, warnings, _ = rust.convert_cellml_to_sbml(text)
    except rust.RustError as error:
        raise SystemExit(
            f"{choice.id}: the conversion refuses the model: {error}"
        ) from error
    for warning in warnings:
        logger.info("%s: %s", choice.id, warning)
    document = libsbml.readSBMLFromString(sbml)
    model = document.getModel()
    if model is None:
        raise SystemExit(f"{choice.id}: no model in the conversion")
    model_cellml = read_cellml_model(path)
    analysed = analyse_model(model_cellml)
    ids = VariableIds(analysed)
    page = Model(
        id=choice.id,
        title=title,
        check=choice.check,
        source="Physiome Model Repository",
        url=PHYSIOME_MODEL_URL.format(id=choice.id),
        direction="cellml2sbml",
        file=file,
        end=choice.end,
        steps=choice.steps,
    )
    settable = {parameter.getId(): parameter for parameter in _settable(model)}
    for variable in _constants(analysed, model_cellml):
        if len(page.parameters) == SLIDERS:
            break
        component = variable.parent().name()
        try:
            sid = ids.lookup(component, variable.name())
        except KeyError:
            continue
        parameter = settable.get(sid)
        if parameter is None:
            continue
        try:
            value = float(variable.initialValue())
        except ValueError:
            # an initial value which is another variable, no slider
            continue
        if value == 0.0 or not _finite(value):
            continue
        minimum, maximum, step = _slider(value)
        page.parameters.append(
            Parameter(
                sbml=sid,
                component=component,
                variable=variable.name(),
                label=variable.name(),
                name="",
                unit=_unit_name(_units_of(variable)),
                value=value,
                minimum=minimum,
                maximum=maximum,
                step=step,
            )
        )
    states = _states(analysed)[:SERIES]
    for (component, name), label in zip(states, _labels(states), strict=True):
        page.series.append(
            Series(
                label=label,
                cellml=f"{component}/{name}",
                sbml=ids.lookup(component, name),
            )
        )
    return page, sbml


def _units_of(variable: Any) -> str:
    """The name of the units of a CellML variable.

    Args:
        variable: the libcellml variable.

    Returns:
        The name of its units, empty when it has none.
    """
    units = variable.units()
    if units is None:
        return ""
    return units if isinstance(units, str) else units.name()


def _constants(analysed: Any, model: Any) -> list[Any]:
    """The constants of an analysed CellML model, in the order of the model.

    A constant of the analyser is a variable with an initial value and no
    equation, which a slider sets; the order is the order of the components
    and their variables in the document, so the sliders of the page are the
    first parameters of the model.

    Args:
        analysed: the model of the analyser.
        model: the CellML model, which gives the order of the variables.

    Returns:
        The variable of every constant of the model.
    """
    constants = {}
    for index in range(analysed.constantCount()):
        variable = analysed.constant(index).variable()
        constants[(variable.parent().name(), variable.name())] = variable
    out = []
    for component in components(model):
        for position in range(component.variableCount()):
            variable = component.variable(position)
            match = constants.get((component.name(), variable.name()))
            if match is not None:
                out.append(match)
    return out


def _changed_cellml(text: str, page: Model) -> str:
    """The CellML document with every slider moved.

    Args:
        text: the CellML document.
        page: the model of the page, whose parameters are the sliders.

    Returns:
        The document with the initial value of every slider multiplied with
        `PERTURBATION`, which is what a change of libopencor does.

    Raises:
        SystemExit: if a slider names a variable the document does not have.
    """
    # a document of CellML 1.0 or 1.1 is read in the permissive mode of
    # libcellml, which maps it to the structures of CellML 2.0, as the
    # package and libopencor read it
    parser = libcellml.Parser(cellml_version(text) is None)
    model = parser.parseModel(text)
    for parameter in page.parameters:
        component = model.component(parameter.component, True)
        variable = None if component is None else component.variable(parameter.variable)
        if variable is None:
            raise SystemExit(
                f"{page.id}: no variable {parameter.component}/{parameter.variable}"
            )
        variable.setInitialValue(repr(parameter.value * PERTURBATION))
    return libcellml.Printer().printModel(model)


def _changed_sbml(text: str, page: Model) -> str:
    """The SBML document with every slider moved.

    Args:
        text: the SBML document.
        page: the model of the page, whose parameters are the sliders.

    Returns:
        The document with the value of every slider multiplied with
        `PERTURBATION`, which is what `preinit` of sbmlsim-core does.

    Raises:
        SystemExit: if a slider names a parameter the document does not have.
    """
    document = libsbml.readSBMLFromString(text)
    model = document.getModel()
    for parameter in page.parameters:
        target = model.getParameter(parameter.sbml)
        if target is None:
            raise SystemExit(f"{page.id}: no parameter {parameter.sbml}")
        target.setValue(parameter.value * PERTURBATION)
    return libsbml.writeSBMLToString(document)


def _run_cellml(text: str, page: Model) -> dict[str, Any]:
    """Simulate the CellML model with libopencor, as the page does.

    Args:
        text: the CellML document.
        page: the model of the page, whose series are read.

    Returns:
        The values of every series by its label.

    Raises:
        SystemExit: if the simulation fails or a series is missing.
    """
    from sbml2cellml.simulate import SimulationError, run_timecourse

    try:
        frame = run_timecourse(
            text,
            start=0.0,
            end=page.end,
            steps=page.steps,
            relative_tolerance=RELATIVE_TOLERANCE,
            absolute_tolerance=ABSOLUTE_TOLERANCE,
            maximum_number_of_steps=MAXIMUM_STEPS,
        )
    except SimulationError as error:
        raise SystemExit(f"{page.id}: libopencor: {error}") from error
    out = {}
    for series in page.series:
        bare = series.cellml.split("/", 1)[1]
        for key in (bare, series.cellml):
            if key in frame.columns:
                out[series.label] = frame[key].to_numpy()
                break
        else:
            raise SystemExit(f"{page.id}: libopencor has no {series.cellml}")
    return out


def _run_sbml(text: str, page: Model) -> dict[str, Any]:
    """Simulate the SBML model with sbmlsim-core, as the page does.

    Args:
        text: the SBML document.
        page: the model of the page, whose selections are read.

    Returns:
        The values of every series by its label.

    Raises:
        SystemExit: if the simulation fails or a selection is missing.
    """
    from sbml2cellml.sbmlsim import run_timecourse
    from sbml2cellml.simulate import SimulationError

    selections = [series.sbml for series in page.series]
    try:
        frame = run_timecourse(
            text,
            selections=selections,
            start=0.0,
            end=page.end,
            steps=page.steps,
            relative_tolerance=RELATIVE_TOLERANCE,
            absolute_tolerance=ABSOLUTE_TOLERANCE,
            maximum_number_of_steps=MAXIMUM_STEPS,
        )
    except SimulationError as error:
        raise SystemExit(f"{page.id}: sbmlsim-core: {error}") from error
    out = {}
    for series in page.series:
        if series.sbml not in frame.columns:
            raise SystemExit(f"{page.id}: sbmlsim-core has no {series.sbml}")
        out[series.label] = frame[series.sbml].to_numpy()
    return out


def _excess(left: dict[str, Any], right: dict[str, Any]) -> float:
    """How far two simulations are apart, relative to the tolerance.

    Args:
        left: the values of the series of one simulation.
        right: the values of the series of the other one.

    Returns:
        The largest difference between the two divided by the tolerance of
        the checks, which is one when the two agree as closely as the
        tolerance allows.
    """
    worst = 0.0
    for label, values in left.items():
        theirs = right[label]
        if len(values) != len(theirs):
            return float("inf")
        for mine, other in zip(values, theirs, strict=True):
            if not _finite(mine) or not _finite(other):
                continue
            tolerance = ABSOLUTE + RELATIVE * abs(other)
            worst = max(worst, abs(mine - other) / tolerance)
    return worst


def _moved(base: dict[str, Any], changed: dict[str, Any]) -> bool:
    """Whether the sliders changed a simulation.

    Args:
        base: the values of the series of the published model.
        changed: the values with every slider moved.

    Returns:
        Whether any series differs, so that the sliders of the page do
        something.
    """
    for label, values in base.items():
        theirs = changed[label]
        if len(values) != len(theirs):
            return True
        for mine, other in zip(values, theirs, strict=True):
            if _finite(mine) and _finite(other) and abs(mine - other) > ABSOLUTE:
                return True
    return False


def _verify(page: Model, cellml: str, sbml: str) -> tuple[float, float, bool]:
    """Simulate both sides of a model as the page simulates them.

    The page shows the two simulations next to each other and the sliders
    drive both, so the two must agree with each other, at the values of the
    published model and with the sliders moved, and the sliders must change
    what the simulations show.

    Args:
        page: the model of the page.
        cellml: the CellML document the page simulates with libopencor.
        sbml: the SBML document it simulates with sbmlsim-core.

    Returns:
        How far the two simulations are apart at the published values and
        with the sliders moved, each relative to the tolerance of the
        checks, and whether the sliders change the simulation.
    """
    base_cellml = _run_cellml(cellml, page)
    base = _excess(base_cellml, _run_sbml(sbml, page))
    moved_cellml = _run_cellml(_changed_cellml(cellml, page), page)
    moved = _excess(moved_cellml, _run_sbml(_changed_sbml(sbml, page), page))
    return base, moved, _moved(base_cellml, moved_cellml)


def _titles() -> dict[str, dict[str, str]]:
    """The title of every model of the BioModels and the Physiome selection.

    Returns:
        The title of every model by its id, per check.
    """
    out: dict[str, dict[str, str]] = {"biomodels": {}, "physiome": {}}
    physiome = _repository() / "physiome" / "models.json"
    if physiome.is_file():
        for entry in json.loads(physiome.read_text(encoding="utf-8"))["models"]:
            if entry.get("title"):
                out["physiome"][entry["id"]] = entry["title"]
    return out


def _source(choice: Choice) -> tuple[Path, str]:
    """Where the document of a model comes from and where the page reads it.

    Args:
        choice: the model of the selection.

    Returns:
        The file of the document and the path the page reads it under,
        relative to `docs/`; the file of the documentation of a choice which
        names one, else the model of the check, which is copied next to the
        page.

    Raises:
        SystemExit: if the model is not in the cache of its check.
    """
    docs = _repository() / "docs"
    if choice.file is not None:
        path = docs / choice.file
        if not path.is_file():
            raise SystemExit(f"{choice.id}: no file {choice.file} of the documentation")
        return path, choice.file
    if choice.check == "biomodels":
        from sbml2cellml.biomodels.models import download_model

        path = download_model(choice.id)
        name = f"{choice.id}.xml"
    else:
        from sbml2cellml.physiome.models import Exposure, model_path

        selection = json.loads(
            (_repository() / "physiome" / "models.json").read_text(encoding="utf-8")
        )
        entry = next(
            (m for m in selection["models"] if m["id"] == choice.id),
            None,
        )
        if entry is None:
            raise SystemExit(f"{choice.id}: not in the Physiome selection")
        path = model_path(
            Exposure(
                id=entry["id"],
                title=entry["title"],
                workspace=entry["workspace"],
                commit=entry["commit"],
                path=entry["path"],
            )
        )
        name = f"{choice.id}.cellml"
    if not path.is_file():
        raise SystemExit(f"{choice.id}: no model in the cache of the check")
    target = _models_dir() / name
    shutil.copyfile(path, target)
    return target, str(SIMULATOR / "models" / name).replace("\\", "/")


def _check(choice: Choice, runs: dict[str, Any]) -> None:
    """Fail when a model of the selection does not pass its check.

    Args:
        choice: the model of the selection.
        runs: the run of every check by its name.

    Raises:
        SystemExit: if the check has no such model or a stage of it fails.
    """
    run = runs.get(choice.check)
    if run is None:
        raise SystemExit(f"{choice.id}: no results of the {choice.check} check")
    if choice.id not in run.result.cases:
        raise SystemExit(f"{choice.id}: not a model of the {choice.check} check")
    if not works(run, choice.id):
        raise SystemExit(
            f"{choice.id}: a stage of the {choice.check} check fails, "
            "the page simulates models which work in both simulators"
        )


def build(ids: list[str] | None = None) -> list[Model]:
    """Build the models of the page and write them next to it.

    Args:
        ids: the models of `CHOICES` to build, all of them by default.

    Returns:
        The models of the page, in the order of `CHOICES`; the manifest and
        the model files are written to `docs/simulator/`.

    Raises:
        SystemExit: if a model does not pass its check, cannot be converted
            or the two simulations do not agree.
    """
    runs = {run.check.name: run for run in load_runs()}
    titles = _titles()
    choices = [c for c in CHOICES if ids is None or c.id in ids]
    pages = []
    for choice in choices:
        _check(choice, runs)
        path, file = _source(choice)
        text = path.read_text(encoding="utf-8")
        title = _title(choice, titles[choice.check])
        if choice.check == "biomodels":
            page, cellml = _from_sbml(choice, text, title, file)
            sbml = text
        else:
            page, sbml = _from_cellml(choice, path, text, title, file)
            cellml = text
        if not page.parameters:
            raise SystemExit(f"{choice.id}: no parameter a slider can set")
        base, moved, changed = _verify(page, cellml, sbml)
        if base > 1.0 or moved > 1.0:
            raise SystemExit(
                f"{choice.id}: the two simulations differ by {max(base, moved):.1f} "
                "times the tolerance of the checks, with the published values "
                f"({base:.1f}) and with the sliders moved ({moved:.1f})"
            )
        if not changed:
            raise SystemExit(
                f"{choice.id}: the sliders do not change the simulation, "
                "the parameters of the model are no sliders"
            )
        console.print(
            f"[green]{choice.id}[/green] {title}: "
            f"{len(page.parameters)} sliders, {len(page.series)} series, "
            f"difference {max(base, moved):.2f} of the tolerance"
        )
        pages.append(page)
    if ids is None:
        _write(pages)
    return pages


def _write(pages: list[Model]) -> None:
    """Write the manifest of the page.

    Args:
        pages: the models of the page, the first one the model it opens
            with.
    """
    manifest = {
        "sliders": SLIDERS,
        "series": SERIES,
        "models": [
            {
                "id": page.id,
                "title": page.title,
                "source": page.source,
                "url": page.url,
                "direction": page.direction,
                "file": page.file,
                "timecourse": {"start": 0, "end": page.end, "steps": page.steps},
                "parameters": [vars(parameter) for parameter in page.parameters],
                "series": [vars(series) for series in page.series],
            }
            for page in pages
        ],
    }
    _models_dir()
    target = _repository() / "docs" / SIMULATOR / "models.json"
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    console.print(f"[bold]{target.relative_to(_repository())}[/bold]")


def main() -> None:
    """Build the models of the online simulator."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--ids",
        nargs="+",
        metavar="ID",
        help="the models of the selection to build, without writing the manifest",
    )
    arguments = parser.parse_args()
    enable_rich_logging()
    build(arguments.ids)


if __name__ == "__main__":
    main()
