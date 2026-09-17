# S2: CellML to SBML converter - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `convert_cellml2sbml` and the `cellml2sbml` command, converting any import-free CellML 2.0 model (after import resolution) into SBML L3V2 with parameters, rules, initial assignments, unit definitions and events, verified by libsbml consistency checks and roadrunner simulations.

**Architecture:** The libcellml `Analyser` is the single source of truth: `variables.py` assigns SBML ids to its variables (one per equivalence set), `sbmlmath.py` walks its equation ASTs into `libsbml.ASTNode`s, `units.py` expands CellML units into SBML unit definitions, `cellml2sbml.py` orchestrates (imports, analysis, parameters, rules, resets as events, validation) and `sbml.py` holds the libsbml read/write/validate helpers.

**Tech Stack:** python 3.13, libcellml 0.6 (`Analyser`, `Importer`), python-libsbml 5.21, libroadrunner 2.10 (dev only), pytest, ruff, ty.

**Spec:** `superpowers/specs/2026-09-17-s2-cellml2sbml-design.md`

## Global Constraints

- Runtime dependencies unchanged (`python-libsbml`, `libcellml`, `rich`); `libroadrunner>=2.10.0` is only in the `dev` extra (already added to `pyproject.toml` and `uv.lock` on this branch).
- Library modules log with `logging.getLogger(__name__)` and lazy `%s` formatting, never print; the CLI prints.
- Full type annotations and google-style docstrings on every module, class and function (ruff `D`; `examples/**`, `tests/**` exempt). ty `error-on-warning = true`: rule-specific `# ty: ignore[rule]` only where ty reports a diagnostic; libcellml swig names that ty cannot resolve (seen so far: `libcellml.Logger`, `libcellml.Issue.Level`) get `Any` or a per-line ignore, as in `cellml.py`.
- SBML output: Level 3 Version 2, no compartments, species or reactions; every parameter has `units`.
- No em dash anywhere, use `-`. No co-author trailer in commit messages.
- Branch `s2-cellml2sbml` (checked out, based on `s1-infrastructure`). Use `uv run <command>`. Commit after every task.
- Existing interfaces you build on: `sbml2cellml.cellml.read_model(path)`, `errors(issues)`, `format_issues(issues)`, `CellMLValidationError`; `sbml2cellml.convert_sbml2cellml(sbml_path, cellml_path=None, validate=True)`; `sbml2cellml.simulate.run_timecourse(cellml_path, start, end, steps)`; `sbml2cellml.log.enable_rich_logging(level)`; `tests/conftest.py` `MODELS_DIR`, `TEST_MODEL_PATH`.

---

## File map

| Path | Responsibility | Task |
| --- | --- | --- |
| `src/sbml2cellml/sbml.py`, `tests/test_sbml.py` | libsbml read, write, validate | 1 |
| `src/sbml2cellml/variables.py`, `tests/test_variables.py`, `tests/cellml_models.py` | SBML ids of CellML variables; shared model builders | 1 |
| `src/sbml2cellml/sbmlmath.py`, `tests/test_sbmlmath.py` | analyser AST and MathML to libsbml AST | 2 |
| `src/sbml2cellml/units.py`, `tests/test_units.py` | CellML units to SBML unit definitions | 3 |
| `src/sbml2cellml/cellml2sbml.py`, `tests/test_cellml2sbml.py`, `tests/data/import_*.cellml`, `src/sbml2cellml/__init__.py` | converter, resets as events, imports | 4 |
| `src/sbml2cellml/cli.py`, `tests/test_cli.py`, `pyproject.toml` | `cellml2sbml` command | 5 |
| `tests/test_roundtrip.py`, `examples/cellml2sbml_example.py`, `tests/test_examples.py`, `.github/workflows/*.yml` | roundtrip with roadrunner, example, CI python dev files | 6 |
| `docs/*.md`, `docs/api/*.md`, `zensical.toml`, `CLAUDE.md`, `README.md`, `release-notes/0.1.0.md` | documentation | 7 |
| pull request | 8 (main session) |

---

### Task 1: libsbml helpers, variable ids and the shared test models

**Files:**
- Create: `src/sbml2cellml/sbml.py`, `src/sbml2cellml/variables.py`, `tests/cellml_models.py`
- Test: `tests/test_sbml.py`, `tests/test_variables.py`

**Interfaces:**
- Produces: `sbml.read_document(path) -> libsbml.SBMLDocument`, `sbml.write_document(doc, path) -> None`, `sbml.document_to_string(doc) -> str`, `sbml.validate_document(doc) -> list[str]`, `sbml.SBMLValidationError`; `variables.VariableIds(analyser_model)` with `id_for(variable) -> str`, `lookup(component_name, variable_name) -> str` (raises `KeyError`), `is_voi(variable) -> bool`, `is_voi_key(component_name, variable_name) -> bool`; `variables.sanitize_id(name) -> str`, `variables.variable_key(variable) -> tuple[str, str]`, `variables.equivalence_set(variable) -> list`; `tests.cellml_models.analyse(model) -> libcellml.AnalyserModel`, `multi_component_model()`, `reset_model()`, `nla_model()`, `math_model(rhs_by_variable: dict[str, str]) -> libcellml.Model`.

- [ ] **Step 1: Write the shared model builders**

`tests/cellml_models.py`:

```python
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
        if analyser.issue(k).level() == libcellml.Issue.Level.ERROR
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
            ode("x", "time", "<apply><times/><apply><minus/><ci>rate</ci></apply><ci>x</ci></apply>"),
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
            ode("z", "t_child", "<apply><times/><apply><minus/><ci>kc</ci></apply><ci>z</ci></apply>"),
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
```

- [ ] **Step 2: Write the failing tests**

`tests/test_sbml.py`:

```python
"""Tests of the libsbml helpers."""

from pathlib import Path

import libsbml
import pytest

from sbml2cellml.sbml import (
    SBMLValidationError,
    document_to_string,
    read_document,
    validate_document,
    write_document,
)
from tests.conftest import MODELS_DIR


def parameter_document() -> libsbml.SBMLDocument:
    doc = libsbml.SBMLDocument(3, 2)
    model = doc.createModel()
    model.setId("m")
    p = model.createParameter()
    p.setId("k")
    p.setValue(1.0)
    p.setConstant(True)
    p.setUnits("dimensionless")
    return doc


def test_read_document() -> None:
    doc = read_document(MODELS_DIR / "glimepiride_liver.xml")
    assert doc.getModel() is not None
    assert doc.getModel().getNumSpecies() > 0


def test_read_document_raises_on_broken_xml(tmp_path: Path) -> None:
    path = tmp_path / "broken.xml"
    path.write_text("<sbml this is not xml")
    with pytest.raises(SBMLValidationError):
        read_document(path)


def test_write_and_read_roundtrip(tmp_path: Path) -> None:
    doc = parameter_document()
    path = tmp_path / "m.xml"
    write_document(doc, path)
    assert document_to_string(read_document(path)) == document_to_string(doc)


def test_validate_consistent_document() -> None:
    assert validate_document(parameter_document()) == []


def test_validate_inconsistent_document() -> None:
    doc = parameter_document()
    rule = doc.getModel().createAssignmentRule()
    rule.setVariable("k")  # k is constant, an assignment rule on it is an error
    rule.setMath(libsbml.parseL3Formula("2"))
    errors = validate_document(doc)
    assert errors
    assert errors[0].startswith("[Error]") or errors[0].startswith("[ERROR]")
```

`tests/test_variables.py`:

```python
"""Tests of the SBML ids of CellML variables."""

import libcellml
import pytest

from sbml2cellml.variables import (
    VariableIds,
    equivalence_set,
    sanitize_id,
    variable_key,
)
from tests.cellml_models import analyse, multi_component_model


@pytest.mark.parametrize(
    ("name", "sid"),
    [("x", "x"), ("a-b", "a_b"), ("1x", "_1x"), ("", "_"), ("x.y z", "x_y_z")],
)
def test_sanitize_id(name: str, sid: str) -> None:
    assert sanitize_id(name) == sid


def test_equivalence_set_is_transitive() -> None:
    model = multi_component_model()
    t = model.component("environment").variable("t")
    names = sorted(variable_key(v) for v in equivalence_set(t))
    assert names == [("cell", "time"), ("child", "t_child"), ("environment", "t")]


def test_ids_of_multi_component_model() -> None:
    model = multi_component_model()
    ids = VariableIds(analyse(model))
    # connected variables share one id, unique names keep their name
    assert ids.lookup("environment", "k") == "k"
    assert ids.lookup("cell", "rate") == "k"
    assert ids.lookup("cell", "x0") == "x0"
    assert ids.lookup("cell", "y") == "y"
    assert ids.lookup("child", "z") == "z"
    # the name clash x is resolved with the component prefix
    assert ids.lookup("cell", "x") == "cell_x"
    assert ids.lookup("child", "x") == "child_x"
    # the variable of integration and its equivalents
    for component, name in [("environment", "t"), ("cell", "time"), ("child", "t_child")]:
        assert ids.is_voi_key(component, name)
    assert not ids.is_voi_key("cell", "x")
    assert ids.is_voi(model.component("cell").variable("time"))
    assert ids.id_for(model.component("cell").component("child").variable("x")) == "child_x"


def test_lookup_unknown_raises() -> None:
    ids = VariableIds(analyse(multi_component_model()))
    with pytest.raises(KeyError):
        ids.lookup("cell", "nope")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sbml.py tests/test_variables.py -v`
Expected: FAIL with `ModuleNotFoundError` for `sbml2cellml.sbml` and `sbml2cellml.variables`.

- [ ] **Step 4: Write `sbml.py`**

```python
"""Reading, writing and validating SBML documents with libsbml.

The counterpart of `sbml2cellml.cellml` for the SBML side: errors are returned
as messages instead of printed, `SBMLValidationError` is raised by the callers
which want to stop on them.
"""

from pathlib import Path

import libsbml


class SBMLValidationError(ValueError):
    """An SBML document has errors."""


def _errors(doc: libsbml.SBMLDocument) -> list[str]:
    """Messages of severity error or fatal in the error log of a document."""
    log = doc.getErrorLog()
    messages: list[str] = []
    for k in range(log.getNumErrors()):
        error = log.getError(k)
        if error.getSeverity() >= libsbml.LIBSBML_SEV_ERROR:
            messages.append(
                f"[{error.getSeverityAsString()}] {error.getMessage().strip()}"
            )
    return messages


def document_to_string(doc: libsbml.SBMLDocument) -> str:
    """Serialize a document to SBML xml.

    Args:
        doc: SBML document.

    Returns:
        The SBML xml.
    """
    return libsbml.writeSBMLToString(doc)


def write_document(doc: libsbml.SBMLDocument, sbml_path: Path) -> None:
    """Write a document as SBML file.

    Args:
        doc: SBML document.
        sbml_path: path of the file, overwritten if it exists.
    """
    Path(sbml_path).write_text(document_to_string(doc), encoding="utf-8")


def read_document(sbml_path: Path) -> libsbml.SBMLDocument:
    """Read an SBML file.

    Args:
        sbml_path: path of the SBML file.

    Returns:
        The document.

    Raises:
        SBMLValidationError: if the file cannot be read or has no model.
    """
    doc: libsbml.SBMLDocument = libsbml.readSBMLFromFile(str(sbml_path))
    errors = _errors(doc)
    if errors or doc.getModel() is None:
        raise SBMLValidationError(
            f"SBML file '{sbml_path}' could not be read:\n" + "\n".join(errors)
        )
    return doc


def validate_document(doc: libsbml.SBMLDocument) -> list[str]:
    """Check the consistency of a document.

    Runs the libsbml consistency checks (units, identifiers, MathML, SBO,
    modeling practice). Unit problems are reported by libsbml as warnings and
    are not part of the result.

    Args:
        doc: SBML document.

    Returns:
        The messages of severity error or fatal, empty for a consistent document.
    """
    doc.getErrorLog().clearLog()
    doc.checkConsistency()
    return _errors(doc)
```

- [ ] **Step 5: Write `variables.py`**

```python
"""SBML ids of the variables of a CellML model.

libcellml connects variables of different components into equivalence sets,
which the analyser treats as one variable. SBML has one flat id namespace, so
every equivalence set becomes one parameter. The id is the name of the
analyser's representative when no other analyser variable has that name,
otherwise the name is prefixed with the component. Ids are sanitized to SBML
SIds.
"""

import re
from collections import Counter
from typing import Any

import libcellml

#: characters which are not allowed in an SBML SId
SID_INVALID = re.compile(r"[^A-Za-z0-9_]")


def sanitize_id(name: str) -> str:
    """Make a string a valid SBML SId.

    Invalid characters become `_`; a leading digit or an empty string gets a
    `_` prefix.

    Args:
        name: CellML name.

    Returns:
        The SId.
    """
    sid = SID_INVALID.sub("_", name)
    if not sid or not (sid[0].isalpha() or sid[0] == "_"):
        sid = f"_{sid}"
    return sid


def variable_key(variable: Any) -> tuple[str, str]:
    """`(component name, variable name)` of a variable.

    Args:
        variable: libcellml variable with a parent component.

    Returns:
        The key.
    """
    return (variable.parent().name(), variable.name())


def equivalence_set(variable: Any) -> list[Any]:
    """The variable and every variable connected to it, transitively.

    Args:
        variable: libcellml variable.

    Returns:
        The variables of the equivalence set, the given one first.
    """
    seen: dict[tuple[str, str], Any] = {}
    stack = [variable]
    while stack:
        current = stack.pop()
        key = variable_key(current)
        if key in seen:
            continue
        seen[key] = current
        for k in range(current.equivalentVariableCount()):
            stack.append(current.equivalentVariable(k))
    return list(seen.values())


class VariableIds:
    """SBML ids of the variables of an analysed CellML model."""

    def __init__(self, analyser_model: libcellml.AnalyserModel) -> None:
        """Assign the ids.

        Args:
            analyser_model: model of a libcellml analyser without errors.
        """
        self._ids: dict[tuple[str, str], str] = {}
        self._voi: set[tuple[str, str]] = set()

        representatives: list[Any] = []
        voi = analyser_model.voi()
        if voi is not None:
            representatives.append(voi.variable())
        for k in range(analyser_model.stateCount()):
            representatives.append(analyser_model.state(k).variable())
        for k in range(analyser_model.variableCount()):
            representatives.append(analyser_model.variable(k).variable())

        counts = Counter(v.name() for v in representatives)
        for representative in representatives:
            name = representative.name()
            if counts[name] > 1:
                name = f"{representative.parent().name()}_{name}"
            sid = sanitize_id(name)
            for member in equivalence_set(representative):
                self._ids[variable_key(member)] = sid

        if voi is not None:
            for member in equivalence_set(voi.variable()):
                self._voi.add(variable_key(member))

    def lookup(self, component_name: str, variable_name: str) -> str:
        """SBML id of a variable given by component and name.

        Args:
            component_name: name of the component.
            variable_name: name of the variable in that component.

        Returns:
            The SBML id.

        Raises:
            KeyError: if the variable is not part of the analysed model.
        """
        return self._ids[(component_name, variable_name)]

    def id_for(self, variable: Any) -> str:
        """SBML id of a libcellml variable.

        Args:
            variable: libcellml variable with a parent component.

        Returns:
            The SBML id.

        Raises:
            KeyError: if the variable is not part of the analysed model.
        """
        return self._ids[variable_key(variable)]

    def is_voi_key(self, component_name: str, variable_name: str) -> bool:
        """Whether a variable is the variable of integration or equivalent to it."""
        return (component_name, variable_name) in self._voi

    def is_voi(self, variable: Any) -> bool:
        """Whether a libcellml variable is the variable of integration."""
        return variable_key(variable) in self._voi
```

- [ ] **Step 6: Run the tests, lint, type check, commit**

Run: `uv run pytest tests/test_sbml.py tests/test_variables.py -v`
Expected: all pass. If `test_validate_inconsistent_document` finds no error because libsbml reports the rule on a constant parameter differently, print `validate_document(doc)` and adjust the fixture to another certain error (a rate rule on a non-existing variable `rule.setVariable("nope")`), not the assertion.
ty: annotate libcellml objects ty cannot resolve with `Any` (the code above already uses `Any` for variables); `libcellml.AnalyserModel` should resolve.

```bash
uv run ruff check && uv run ruff format && uv run ty check
git add src/sbml2cellml/sbml.py src/sbml2cellml/variables.py tests/cellml_models.py tests/test_sbml.py tests/test_variables.py
git commit -m "Add the libsbml helpers and the SBML ids of CellML variables"
```

---

### Task 2: Analyser AST and MathML to libsbml AST

**Files:**
- Create: `src/sbml2cellml/sbmlmath.py`
- Test: `tests/test_sbmlmath.py`

**Interfaces:**
- Consumes: `variables.VariableIds`, `tests.cellml_models.math_model`, `analyse`, `cn`.
- Produces: `ast_to_sbml(node, ids) -> libsbml.ASTNode`, `variable_node(variable, ids) -> libsbml.ASTNode`, `mathml_to_sbml(mathml, component_name, ids) -> libsbml.ASTNode`, `MathConversionError`, `TIME_ID = "time"`.

- [ ] **Step 1: Write the failing tests**

`tests/test_sbmlmath.py`:

```python
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
    "a_nary": (f"<apply><plus/>{X}{K}{cn('1')}</apply>", "x + k + 1"),
    "a_root": (f"<apply><root/><degree>{cn('3')}</degree>{X}</apply>", "root(3, x)"),
    "a_sqrt": (unary("root"), "sqrt(x)"),
    "a_log": (f"<apply><log/><logbase>{cn('2')}</logbase>{X}</apply>", "log(2, x)"),
    "a_log10": (unary("log"), "log10(x)"),
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
    "a_arcsin": (unary("arcsin"), "arcsin(x)"),
    "a_arccos": (unary("arccos"), "arccos(x)"),
    "a_arctan": (unary("arctan"), "arctan(x)"),
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
    "a_enotation": ('<cn cellml:units="dimensionless" type="e-notation">1<sep/>-2</cn>', "0.01"),
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
        "piecewise(1, (x < 1) && (x > 0 || !(x == 3)) && xor(x != 4, k <= 5) && true, false)",
    ),
}


@pytest.fixture(scope="module")
def converted() -> dict[str, str]:
    """L3 formula of every case, converted through the analyser."""
    model = math_model({name: rhs for name, (rhs, _) in CASES.items()})
    analyser_model = analyse(model)
    ids = VariableIds(analyser_model)
    formulas: dict[str, str] = {}
    for k in range(analyser_model.equationCount()):
        equation = analyser_model.equation(k)
        ast = equation.ast()
        name = ast.leftChild().variable().name() if ast.leftChild().variable() else None
        if name in CASES:
            formulas[name] = libsbml.formulaToL3String(ast_to_sbml(ast.rightChild(), ids))
    return formulas


@pytest.mark.parametrize("name", list(CASES))
def test_ast_to_sbml(name: str, converted: dict[str, str]) -> None:
    assert converted[name] == CASES[name][1]


def test_unsupported_node_raises() -> None:
    model = math_model({"a": "<apply><plus/><ci>x</ci><ci>k</ci></apply>"})
    analyser_model = analyse(model)
    ids = VariableIds(analyser_model)
    ode = next(
        analyser_model.equation(k)
        for k in range(analyser_model.equationCount())
        if analyser_model.equation(k).type() == libcellml.AnalyserEquation.Type.ODE
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sbmlmath.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sbml2cellml.sbmlmath'`.

- [ ] **Step 3: Write the module**

`src/sbml2cellml/sbmlmath.py`:

```python
"""Conversion of CellML maths to libsbml ASTs.

The libcellml analyser gives every equation as a binary tree of
`AnalyserEquationAst` nodes with the variables resolved. `ast_to_sbml` walks
such a tree into a `libsbml.ASTNode`; the variable of integration becomes the
SBML `time` symbol, variables get their SBML id. `mathml_to_sbml` reads the
MathML of a reset with libsbml and remaps the `ci` names the same way.
"""

import math
from typing import Any

import libcellml
import libsbml

from sbml2cellml.variables import VariableIds

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


def _type_name(node: Any) -> str:
    """Lower case name of the node type, for messages."""
    return libcellml.AnalyserEquationAst.typeAsString(node.type())  # ty: ignore[unresolved-attribute]


def _children(node: Any, ids: VariableIds) -> list[libsbml.ASTNode]:
    """Converted children of a node, one or two."""
    children = [ast_to_sbml(node.leftChild(), ids)]
    if node.rightChild() is not None:
        children.append(ast_to_sbml(node.rightChild(), ids))
    return children


def _apply(node_type: int, children: list[libsbml.ASTNode]) -> libsbml.ASTNode:
    """Node with the given children."""
    node = libsbml.ASTNode(node_type)
    for child in children:
        node.addChild(child)
    return node


def _root(node: Any, ids: VariableIds) -> libsbml.ASTNode:
    """`root(degree, x)`; the square root when no degree is given."""
    left = node.leftChild()
    if left.type() == AstType.DEGREE:
        degree = ast_to_sbml(left.leftChild(), ids)
        radicand = ast_to_sbml(node.rightChild(), ids)
    else:
        degree = _real(2.0)
        radicand = ast_to_sbml(left, ids)
    return _apply(libsbml.AST_FUNCTION_ROOT, [degree, radicand])


def _log(node: Any, ids: VariableIds) -> libsbml.ASTNode:
    """`log(base, x)`; base 10 when no logbase is given."""
    left = node.leftChild()
    if left.type() == AstType.LOGBASE:
        base = ast_to_sbml(left.leftChild(), ids)
        argument = ast_to_sbml(node.rightChild(), ids)
    else:
        base = _real(10.0)
        argument = ast_to_sbml(left, ids)
    return _apply(libsbml.AST_FUNCTION_LOG, [base, argument])


def _piecewise(node: Any, ids: VariableIds) -> libsbml.ASTNode:
    """Flatten the nested piecewise of the analyser into one SBML piecewise.

    The analyser nests `PIECEWISE(PIECE, PIECEWISE(PIECE, OTHERWISE))`; SBML
    takes `piecewise(value, condition, ..., otherwise)`.
    """
    result = libsbml.ASTNode(libsbml.AST_FUNCTION_PIECEWISE)
    current = node
    while current is not None:
        current_type = current.type()
        if current_type == AstType.PIECEWISE:
            _add_piece(result, current.leftChild(), ids)
            current = current.rightChild()
        elif current_type in (AstType.PIECE, AstType.OTHERWISE):
            _add_piece(result, current, ids)
            current = None
        else:
            raise MathConversionError(
                f"Unexpected '{_type_name(current)}' in a piecewise expression."
            )
    return result


def _add_piece(result: libsbml.ASTNode, piece: Any, ids: VariableIds) -> None:
    """Add the value and condition of a piece, or the otherwise value."""
    piece_type = piece.type()
    if piece_type == AstType.PIECE:
        result.addChild(ast_to_sbml(piece.leftChild(), ids))
        result.addChild(ast_to_sbml(piece.rightChild(), ids))
    elif piece_type == AstType.OTHERWISE:
        result.addChild(ast_to_sbml(piece.leftChild(), ids))
    else:
        raise MathConversionError(
            f"Unexpected '{_type_name(piece)}' in a piecewise expression."
        )


def ast_to_sbml(node: Any, ids: VariableIds) -> libsbml.ASTNode:
    """Convert an analyser AST into a libsbml AST.

    Args:
        node: `libcellml.AnalyserEquationAst`, e.g. the right child of the
            `EQUALITY` root of an equation.
        ids: SBML ids of the model.

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
        return _real(float(node.value()))
    if node_type in CONSTANTS:
        return libsbml.ASTNode(CONSTANTS[node_type])
    if node_type in REALS:
        return _real(REALS[node_type])
    if node_type == AstType.MINUS and node.rightChild() is None:
        return _apply(libsbml.AST_MINUS, _children(node, ids))
    if node_type in BINARY:
        return _apply(BINARY[node_type], _children(node, ids))
    if node_type in UNARY:
        return _apply(UNARY[node_type], _children(node, ids))
    if node_type == AstType.ROOT:
        return _root(node, ids)
    if node_type == AstType.LOG:
        return _log(node, ids)
    if node_type == AstType.PIECEWISE:
        return _piecewise(node, ids)
    raise MathConversionError(
        f"MathML element '{_type_name(node)}' cannot be converted to SBML."
    )


def _rename(node: libsbml.ASTNode, component_name: str, ids: VariableIds) -> None:
    """Replace the CellML names of a libsbml AST by the SBML ids, in place."""
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
        _rename(node.getChild(k), component_name, ids)


def mathml_to_sbml(mathml: str, component_name: str, ids: VariableIds) -> libsbml.ASTNode:
    """Read CellML MathML with libsbml and remap the variable names.

    Used for the maths of resets, which the analyser does not cover. Units on
    numbers (`cellml:units`) become `sbml:units`.

    Args:
        mathml: complete `math` element.
        component_name: component the MathML belongs to, resolves the names.
        ids: SBML ids of the model.

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
    _rename(node, component_name, ids)
    return node
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_sbmlmath.py -v`
Expected: all pass. Known uncertainties and how to resolve them, without changing the module's mapping:
- The exact L3 formula strings in `CASES` (spacing, parentheses, `0.01` for the e-notation number, `2 dimensionless`) come from `libsbml.formulaToL3String`; if a case fails only on formatting, print the actual string, confirm it is the same expression, and correct the expected string in the test.
- If the analyser drops an equation from the model (e.g. a variable only defined by a constant), check `analyser_model.equationCount()` and the analyser issues; a CellML validity problem of the fixture (e.g. `arcsec` not allowed on a value less than 1 is fine, validity is structural) must be fixed in `tests/cellml_models.py`.
- `AstType.<NAME>` values: if ty cannot resolve `AnalyserEquationAst.Type`, keep the per-line ignore shown; if it reports an unused ignore, remove it.

- [ ] **Step 5: Lint, type check, commit**

```bash
uv run ruff check && uv run ruff format && uv run ty check
git add src/sbml2cellml/sbmlmath.py tests/test_sbmlmath.py
git commit -m "Add the conversion of CellML maths to libsbml ASTs"
```

---

### Task 3: Units

**Files:**
- Create: `src/sbml2cellml/units.py`
- Test: `tests/test_units.py`

**Interfaces:**
- Consumes: `variables.sanitize_id`.
- Produces: `add_units(model_cellml, model_sbml) -> dict[str, str]`, `unit_id(units_name, unit_ids) -> str`, `expand_units(units, model) -> list[BaseUnit]`, `BaseUnit(kind: int, exponent: float, scale: int, multiplier: float)`, `prefix_scale(prefix) -> int`, `UnitsConversionError`.

- [ ] **Step 1: Write the failing tests**

`tests/test_units.py`:

```python
"""Tests of the conversion of CellML units to SBML unit definitions."""

import libcellml
import libsbml
import pytest

from sbml2cellml.sbml import validate_document
from sbml2cellml.units import (
    BaseUnit,
    UnitsConversionError,
    add_units,
    expand_units,
    prefix_scale,
    unit_id,
)


def model_with_units() -> libcellml.Model:
    model = libcellml.Model("units")
    per_second = libcellml.Units("per_second")
    per_second.addUnit("second", -1.0)
    mM = libcellml.Units("mM")
    mM.addUnit("mole", "milli")
    mM.addUnit("litre", "", -1.0)
    mM_per_min = libcellml.Units("mM_per_min")  # custom referencing custom
    mM_per_min.addUnit("mM")
    mM_per_min.addUnit("second", "", -1.0, 1.0 / 60.0)
    kmM2 = libcellml.Units("kmM2")  # prefix and multiplier on a custom reference
    kmM2.addUnit("mM", "kilo", 2.0, 3.0)
    percent = libcellml.Units("percent")
    percent.addUnit("dimensionless", "", 1.0, 0.01)
    empty = libcellml.Units("nothing")
    for units in [per_second, mM, mM_per_min, kmM2, percent, empty]:
        model.addUnits(units)
    return model


@pytest.mark.parametrize(
    ("prefix", "scale"),
    [("", 0), ("milli", -3), ("kilo", 3), ("micro", -6), ("-5", -5), ("2", 2)],
)
def test_prefix_scale(prefix: str, scale: int) -> None:
    assert prefix_scale(prefix) == scale


def test_prefix_scale_invalid() -> None:
    with pytest.raises(UnitsConversionError):
        prefix_scale("huge")


def test_expand_standard_reference() -> None:
    model = model_with_units()
    assert expand_units(model.units("per_second"), model) == [
        BaseUnit(libsbml.UNIT_KIND_SECOND, -1.0, 0, 1.0)
    ]
    assert expand_units(model.units("mM"), model) == [
        BaseUnit(libsbml.UNIT_KIND_MOLE, 1.0, -3, 1.0),
        BaseUnit(libsbml.UNIT_KIND_LITRE, -1.0, 0, 1.0),
    ]


def test_expand_custom_reference() -> None:
    model = model_with_units()
    assert expand_units(model.units("mM_per_min"), model) == [
        BaseUnit(libsbml.UNIT_KIND_MOLE, 1.0, -3, 1.0),
        BaseUnit(libsbml.UNIT_KIND_LITRE, -1.0, 0, 1.0),
        BaseUnit(libsbml.UNIT_KIND_SECOND, -1.0, 0, pytest.approx(1.0 / 60.0)),
    ]
    # (3 * 10^3 * mM)^2 = (3000^(1/1) * mole 10^-3)^2 * litre^-2
    assert expand_units(model.units("kmM2"), model) == [
        BaseUnit(libsbml.UNIT_KIND_MOLE, 2.0, -3, pytest.approx(3000.0)),
        BaseUnit(libsbml.UNIT_KIND_LITRE, -2.0, 0, 1.0),
    ]


def test_expand_dimensionless_and_empty() -> None:
    model = model_with_units()
    assert expand_units(model.units("percent"), model) == [
        BaseUnit(libsbml.UNIT_KIND_DIMENSIONLESS, 1.0, 0, 0.01)
    ]
    assert expand_units(model.units("nothing"), model) == []


def test_expand_unknown_reference_raises() -> None:
    model = libcellml.Model("bad")
    units = libcellml.Units("bad")
    units.addUnit("furlong")
    model.addUnits(units)
    with pytest.raises(UnitsConversionError, match="furlong"):
        expand_units(units, model)


def test_add_units() -> None:
    model = model_with_units()
    doc = libsbml.SBMLDocument(3, 2)
    model_sbml = doc.createModel()
    model_sbml.setId("units")
    ids = add_units(model, model_sbml)
    assert ids == {
        "per_second": "per_second",
        "mM": "mM",
        "mM_per_min": "mM_per_min",
        "kmM2": "kmM2",
        "percent": "percent",
        "nothing": "nothing",
    }
    assert model_sbml.getNumUnitDefinitions() == 6
    mM = model_sbml.getUnitDefinition("mM")
    assert mM.getNumUnits() == 2
    assert mM.getUnit(0).getKind() == libsbml.UNIT_KIND_MOLE
    assert mM.getUnit(0).getScale() == -3
    nothing = model_sbml.getUnitDefinition("nothing")
    assert nothing.getNumUnits() == 1
    assert nothing.getUnit(0).getKind() == libsbml.UNIT_KIND_DIMENSIONLESS
    assert validate_document(doc) == []
    # standard units are used by name
    assert unit_id("second", ids) == "second"
    assert unit_id("mM", ids) == "mM"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_units.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sbml2cellml.units'`.

- [ ] **Step 3: Write the module**

`src/sbml2cellml/units.py`:

```python
"""Conversion of CellML units to SBML unit definitions.

The standard units of CellML (`second`, `metre`, `kilogram`, `gram`, `mole`,
`litre`, `dimensionless`, `ampere`, `kelvin`, ...) are all unit kinds of SBML
level 3 and are used by name. A custom `Units` becomes a `UnitDefinition`
whose units reference base kinds only: a reference to another custom `Units`
is expanded recursively.
"""

from dataclasses import dataclass
from typing import Any

import libcellml
import libsbml

from sbml2cellml.variables import sanitize_id

#: SI prefixes of CellML, by name
PREFIXES: dict[str, int] = {
    "yotta": 24,
    "zetta": 21,
    "exa": 18,
    "peta": 15,
    "tera": 12,
    "giga": 9,
    "mega": 6,
    "kilo": 3,
    "hecto": 2,
    "deca": 1,
    "deci": -1,
    "centi": -2,
    "milli": -3,
    "micro": -6,
    "nano": -9,
    "pico": -12,
    "femto": -15,
    "atto": -18,
    "zepto": -21,
    "yocto": -24,
}


class UnitsConversionError(ValueError):
    """CellML units cannot be converted to SBML."""


@dataclass
class BaseUnit:
    """One unit of an SBML unit definition: `(multiplier * 10^scale * kind)^exponent`."""

    kind: int
    exponent: float
    scale: int
    multiplier: float


def prefix_scale(prefix: str) -> int:
    """Scale of a CellML unit prefix.

    Args:
        prefix: SI prefix name (`milli`), an integer string (`-3`) or empty.

    Returns:
        The power of ten.

    Raises:
        UnitsConversionError: if the prefix is unknown.
    """
    if not prefix:
        return 0
    if prefix in PREFIXES:
        return PREFIXES[prefix]
    try:
        return int(prefix)
    except ValueError as err:
        raise UnitsConversionError(f"Unknown unit prefix '{prefix}'.") from err


def expand_units(units: Any, model: libcellml.Model) -> list[BaseUnit]:
    """Expand CellML units into SBML base units.

    A `unit` referencing a standard unit gives one base unit. A `unit`
    referencing a custom `Units` is expanded recursively, every resulting
    exponent multiplied by the outer exponent and the outer factor
    `multiplier * 10^prefix` folded into the multiplier of the first resulting
    unit (as `factor^(1/e)` with `e` the exponent of that unit before the
    multiplication, so that the product stays the same).

    Args:
        units: libcellml units.
        model: model the units belong to, resolves references to custom units.

    Returns:
        The base units, empty for units without any `unit` (dimensionless).

    Raises:
        UnitsConversionError: for an unknown reference or prefix.
    """
    result: list[BaseUnit] = []
    for k in range(units.unitCount()):
        reference, prefix, exponent, multiplier, _ = units.unitAttributes(k)
        kind = libsbml.UnitKind_forName(reference)
        if kind != libsbml.UNIT_KIND_INVALID:
            result.append(BaseUnit(kind, exponent, prefix_scale(prefix), multiplier))
            continue
        child = model.units(reference)
        if child is None:
            raise UnitsConversionError(
                f"Units '{reference}' referenced by '{units.name()}' are not defined."
            )
        expanded = expand_units(child, model)
        if not expanded:
            continue
        factor = multiplier * 10.0 ** prefix_scale(prefix)
        first_exponent = expanded[0].exponent
        for index, base in enumerate(expanded):
            base_multiplier = base.multiplier
            if index == 0:
                base_multiplier *= factor ** (1.0 / first_exponent)
            result.append(
                BaseUnit(base.kind, base.exponent * exponent, base.scale, base_multiplier)
            )
    return result


def add_units(model_cellml: libcellml.Model, model_sbml: libsbml.Model) -> dict[str, str]:
    """Add a unit definition for every custom units of a CellML model.

    Args:
        model_cellml: CellML model.
        model_sbml: SBML model the definitions are added to.

    Returns:
        The SBML unit id by CellML units name, for `unit_id`.
    """
    ids: dict[str, str] = {}
    for k in range(model_cellml.unitsCount()):
        units = model_cellml.units(k)
        uid = sanitize_id(units.name())
        definition = model_sbml.createUnitDefinition()
        definition.setId(uid)
        if uid != units.name():
            definition.setName(units.name())
        expanded = expand_units(units, model_cellml)
        if not expanded:
            expanded = [BaseUnit(libsbml.UNIT_KIND_DIMENSIONLESS, 1.0, 0, 1.0)]
        for base in expanded:
            unit = definition.createUnit()
            unit.setKind(base.kind)
            unit.setExponent(base.exponent)
            unit.setScale(base.scale)
            unit.setMultiplier(base.multiplier)
        ids[units.name()] = uid
    return ids


def unit_id(units_name: str, unit_ids: dict[str, str]) -> str:
    """SBML unit id of a CellML units name.

    Args:
        units_name: name of the units of a variable.
        unit_ids: result of `add_units`.

    Returns:
        The unit definition id for custom units, the name itself for standard units.
    """
    return unit_ids.get(units_name, units_name)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_units.py -v`
Expected: all pass. `Units.addUnit` overloads: `addUnit(reference, exponent)`, `addUnit(reference, prefix)`, `addUnit(reference, prefix, exponent, multiplier)`; if a fixture line fails on the overload, use the four-argument form with `""` as prefix. `unitAttributes(k)` returns `[reference, prefix, exponent, multiplier, id]` (verified in a spike).

- [ ] **Step 5: Lint, type check, commit**

```bash
uv run ruff check && uv run ruff format && uv run ty check
git add src/sbml2cellml/units.py tests/test_units.py
git commit -m "Add the conversion of CellML units to SBML unit definitions"
```

---

### Task 4: The converter

**Files:**
- Create: `src/sbml2cellml/cellml2sbml.py`, `tests/data/import_parent.cellml`, `tests/data/import_child.cellml`
- Modify: `src/sbml2cellml/__init__.py`
- Test: `tests/test_cellml2sbml.py`

**Interfaces:**
- Consumes: everything from tasks 1 to 3; `sbml2cellml.cellml.read_model`, `errors`, `format_issues`.
- Produces: `convert_cellml2sbml(cellml_path: Path, sbml_path: Path | None = None, validate: bool = True) -> libsbml.SBMLDocument`, `build_document(model, analyser_model) -> libsbml.SBMLDocument`, `CellML2SBMLConversionError`; `sbml2cellml.convert_cellml2sbml` re-export.

- [ ] **Step 1: Write the import fixtures**

`tests/data/import_child.cellml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<model xmlns="http://www.cellml.org/cellml/2.0#" name="child">
  <units name="per_second">
    <unit units="second" exponent="-1"/>
  </units>
  <component name="decay">
    <variable name="t" units="second" interface="public"/>
    <variable name="m" units="dimensionless" initial_value="10" interface="public"/>
    <variable name="k" units="per_second" initial_value="0.1"/>
    <math xmlns="http://www.w3.org/1998/Math/MathML">
      <apply><eq/>
        <apply><diff/><bvar><ci>t</ci></bvar><ci>m</ci></apply>
        <apply><times/><apply><minus/><ci>k</ci></apply><ci>m</ci></apply>
      </apply>
    </math>
  </component>
</model>
```

`tests/data/import_parent.cellml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<model xmlns="http://www.cellml.org/cellml/2.0#" name="parent">
  <import xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="import_child.cellml">
    <component name="decay_import" component_ref="decay"/>
  </import>
</model>
```

- [ ] **Step 2: Write the failing tests**

`tests/test_cellml2sbml.py`:

```python
"""Tests of the CellML to SBML conversion."""

from pathlib import Path

import libsbml
import pytest

from sbml2cellml import convert_cellml2sbml
from sbml2cellml.cellml import write_model
from sbml2cellml.cellml2sbml import CellML2SBMLConversionError, build_document
from sbml2cellml.sbml import validate_document
from tests.cellml_models import analyse, multi_component_model, nla_model, reset_model
from tests.conftest import TEST_MODEL_PATH

DATA_DIR = Path(__file__).parent / "data"


def parameters(model: libsbml.Model) -> dict[str, libsbml.Parameter]:
    return {p.getId(): p for p in model.getListOfParameters()}


def rules(model: libsbml.Model) -> dict[str, libsbml.Rule]:
    return {r.getVariable(): r for r in model.getListOfRules()}


def initial_assignments(model: libsbml.Model) -> dict[str, str]:
    return {
        ia.getSymbol(): libsbml.formulaToL3String(ia.getMath())
        for ia in model.getListOfInitialAssignments()
    }


def test_convert_test_model(tmp_path: Path) -> None:
    sbml_path = tmp_path / "test_model.xml"
    doc = convert_cellml2sbml(TEST_MODEL_PATH, sbml_path=sbml_path)
    model = doc.getModel()
    assert doc.getLevel() == 3
    assert doc.getVersion() == 2
    assert model.getId() == "test_model"
    assert model.getTimeUnits() == "second"
    assert model.getNumCompartments() == 0
    assert model.getNumSpecies() == 0
    p = parameters(model)
    assert set(p) == {"m", "alpha"}
    assert p["alpha"].getConstant() and p["alpha"].getValue() == 0.05
    assert p["alpha"].getUnits() == "per_second"
    assert not p["m"].getConstant() and p["m"].getValue() == 10.0
    assert p["m"].getUnits() == "kilogram"
    r = rules(model)
    assert set(r) == {"m"}
    assert r["m"].isRate()
    assert libsbml.formulaToL3String(r["m"].getMath()) == "-alpha * m"
    assert model.getUnitDefinition("per_second") is not None
    assert validate_document(doc) == []
    assert sbml_path.is_file()
    assert libsbml.readSBMLFromFile(str(sbml_path)).getModel().getId() == "test_model"


def test_convert_multi_component_model(tmp_path: Path) -> None:
    cellml_path = tmp_path / "multi.cellml"
    write_model(multi_component_model(), cellml_path)
    doc = convert_cellml2sbml(cellml_path)
    model = doc.getModel()
    assert model.getTimeUnits() == "second"
    p = parameters(model)
    assert set(p) == {"k", "cell_x", "x0", "y", "c", "kc", "z", "child_x"}
    # constants
    assert p["k"].getConstant() and p["k"].getValue() == 0.1 and p["k"].getUnits() == "per_second"
    assert p["x0"].getConstant() and p["x0"].getValue() == 2.0 and p["x0"].getUnits() == "mM"
    assert p["kc"].getConstant() and p["kc"].getValue() == 0.5
    # computed constant: constant parameter with an initial assignment
    assert p["c"].getConstant() and not p["c"].isSetValue()
    # states
    assert not p["cell_x"].getConstant() and not p["cell_x"].isSetValue()
    assert p["cell_x"].getName() == "x"
    assert not p["z"].getConstant() and p["z"].getValue() == 1.0
    # algebraic
    assert not p["y"].getConstant() and not p["y"].isSetValue()
    assert not p["child_x"].getConstant()
    ia = initial_assignments(model)
    assert ia == {"cell_x": "x0", "c": "2 * k"}
    r = rules(model)
    assert set(r) == {"cell_x", "z", "y", "child_x"}
    assert r["cell_x"].isRate()
    assert libsbml.formulaToL3String(r["cell_x"].getMath()) == "-k * cell_x"
    assert r["z"].isRate()
    assert r["y"].isAssignment()
    assert libsbml.formulaToL3String(r["y"].getMath()) == "2 * cell_x"
    assert libsbml.formulaToL3String(r["child_x"].getMath()) == "z"
    assert validate_document(doc) == []


def test_convert_reset_model(tmp_path: Path) -> None:
    cellml_path = tmp_path / "reset.cellml"
    write_model(reset_model(), cellml_path)
    doc = convert_cellml2sbml(cellml_path)
    model = doc.getModel()
    assert model.getNumEvents() == 1
    event = model.getEvent(0)
    assert event.getId() == "reset_1"
    assert event.getUseValuesFromTriggerTime()
    trigger = event.getTrigger()
    assert trigger.getPersistent() and trigger.getInitialValue()
    assert libsbml.formulaToL3String(trigger.getMath()) == "m == m_div"
    assert libsbml.formulaToL3String(event.getPriority().getMath()) == "-0"
    assert event.getNumEventAssignments() == 1
    assignment = event.getEventAssignment(0)
    assert assignment.getVariable() == "m"
    assert libsbml.formulaToL3String(assignment.getMath()) == "m / 2 dimensionless"
    assert validate_document(doc) == []


def test_convert_nla_model_raises(tmp_path: Path) -> None:
    cellml_path = tmp_path / "nla.cellml"
    write_model(nla_model(), cellml_path)
    with pytest.raises(CellML2SBMLConversionError, match="nla"):
        convert_cellml2sbml(cellml_path)


def test_convert_with_imports() -> None:
    doc = convert_cellml2sbml(DATA_DIR / "import_parent.cellml")
    model = doc.getModel()
    p = parameters(model)
    assert set(p) == {"m", "k"}
    assert rules(model)["m"].isRate()
    assert model.getUnitDefinition("per_second") is not None
    assert validate_document(doc) == []


def test_convert_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CellML2SBMLConversionError, match="does not exist"):
        convert_cellml2sbml(tmp_path / "missing.cellml")


def test_convert_invalid_cellml_raises(tmp_path: Path) -> None:
    path = tmp_path / "invalid.cellml"
    path.write_text(
        '<?xml version="1.0"?><model xmlns="http://www.cellml.org/cellml/2.0#" name="bad">'
        '<component name="c"><variable name="x" units="second"/>'
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><apply><eq/><ci>x</ci><ci>y</ci></apply></math>'
        "</component></model>"
    )
    with pytest.raises(CellML2SBMLConversionError, match="analysed"):
        convert_cellml2sbml(path)


def test_build_document_is_consistent_and_detects_injected_error() -> None:
    model = reset_model()
    doc = build_document(model, analyse(model))
    assert validate_document(doc) == []
    # an assignment rule on the constant alpha makes the document inconsistent
    rule = doc.getModel().createAssignmentRule()
    rule.setVariable("alpha")
    rule.setMath(libsbml.parseL3Formula("1"))
    assert validate_document(doc)


def test_validate_flag(tmp_path: Path) -> None:
    """A model the analyser accepts but libsbml rejects does not exist by
    construction; the flag is exercised through the CLI tests. Here only the
    unchanged behaviour: validate=False still writes the file."""
    sbml_path = tmp_path / "out.xml"
    convert_cellml2sbml(TEST_MODEL_PATH, sbml_path=sbml_path, validate=False)
    assert sbml_path.is_file()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cellml2sbml.py -v`
Expected: FAIL with `ImportError: cannot import name 'convert_cellml2sbml' from 'sbml2cellml'`.

- [ ] **Step 4: Write the converter**

`src/sbml2cellml/cellml2sbml.py`:

```python
"""Conversion of CellML 2.0 models to SBML level 3 version 2.

The libcellml analyser classifies the variables and equations of the model
and resolves the connections between components; the converter renders its
model as SBML: every variable is a parameter, states get rate rules,
algebraic variables assignment rules, computed constants initial assignments,
and the resets of the components become events. CellML units become unit
definitions. There are no compartments, species or reactions.
"""

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import libcellml
import libsbml

from sbml2cellml import cellml, sbml
from sbml2cellml.sbml import SBMLValidationError
from sbml2cellml.sbmlmath import (
    MathConversionError,
    ast_to_sbml,
    mathml_to_sbml,
    variable_node,
)
from sbml2cellml.units import UnitsConversionError, add_units, unit_id
from sbml2cellml.variables import VariableIds, sanitize_id

logger = logging.getLogger(__name__)

AstType = libcellml.AnalyserEquationAst.Type  # ty: ignore[unresolved-attribute]
EquationType = libcellml.AnalyserEquation.Type  # ty: ignore[unresolved-attribute]
VariableType = libcellml.AnalyserVariable.Type  # ty: ignore[unresolved-attribute]
ModelType = libcellml.AnalyserModel.Type  # ty: ignore[unresolved-attribute]


class CellML2SBMLConversionError(ValueError):
    """The CellML model cannot be converted."""


def convert_cellml2sbml(
    cellml_path: Path, sbml_path: Path | None = None, validate: bool = True
) -> libsbml.SBMLDocument:
    """Convert a CellML file to an SBML document.

    Args:
        cellml_path: path of the CellML file; imports are resolved relative to it.
        sbml_path: path the SBML is written to, not written if `None`.
        validate: check the consistency of the document with libsbml and raise
            if it has errors.

    Returns:
        The SBML document.

    Raises:
        CellML2SBMLConversionError: if the file does not exist, the imports
            cannot be resolved, the analyser reports errors, the model is not
            an ODE or algebraic model, or a construct is not supported.
        CellMLValidationError: if the file cannot be parsed.
        SBMLValidationError: if `validate` is set and the document has errors.
    """
    cellml_path = Path(cellml_path)
    if not cellml_path.is_file():
        raise CellML2SBMLConversionError(f"CellML file does not exist: '{cellml_path}'.")
    model = cellml.read_model(cellml_path)
    logger.info("Converting CellML model '%s' from '%s'", model.name(), cellml_path)
    model = _flatten(model, cellml_path.parent)
    analyser_model = _analyse(model)
    try:
        doc = build_document(model, analyser_model)
    except (MathConversionError, UnitsConversionError, KeyError) as err:
        raise CellML2SBMLConversionError(
            f"CellML model '{model.name()}' cannot be converted: {err}"
        ) from err

    if validate:
        errors = sbml.validate_document(doc)
        if errors:
            raise SBMLValidationError(
                f"SBML document converted from '{cellml_path}' has "
                f"{len(errors)} errors:\n" + "\n".join(errors)
            )
    if sbml_path is not None:
        sbml.write_document(doc, sbml_path)
        logger.info("SBML written to '%s'", sbml_path)
    return doc


def _flatten(model: libcellml.Model, base_path: Path) -> libcellml.Model:
    """Resolve the imports of a model and flatten it, if it has any."""
    if not model.hasImports():
        return model
    importer = libcellml.Importer()
    importer.resolveImports(model, str(base_path))
    issues = [importer.issue(k) for k in range(importer.issueCount())]
    errors = cellml.errors(issues)
    if errors or model.hasUnresolvedImports():
        raise CellML2SBMLConversionError(
            f"Imports of CellML model '{model.name()}' cannot be resolved from "
            f"'{base_path}':\n{cellml.format_issues(errors)}"
        )
    flat = importer.flattenModel(model)
    logger.info("Resolved and flattened the imports of '%s'", model.name())
    return flat


def _analyse(model: libcellml.Model) -> Any:
    """Analyse a model, raising on errors and unsupported model types."""
    analyser = libcellml.Analyser()
    analyser.analyseModel(model)
    issues = [analyser.issue(k) for k in range(analyser.issueCount())]
    errors = cellml.errors(issues)
    if errors:
        raise CellML2SBMLConversionError(
            f"CellML model '{model.name()}' cannot be analysed:\n"
            f"{cellml.format_issues(errors)}"
        )
    analyser_model = analyser.model()
    model_type = analyser_model.type()
    if model_type not in (ModelType.ODE, ModelType.ALGEBRAIC):
        type_name = libcellml.AnalyserModel.typeAsString(model_type)  # ty: ignore[unresolved-attribute]
        raise CellML2SBMLConversionError(
            f"CellML model '{model.name()}' is of type '{type_name}', only ODE "
            f"and algebraic models are supported."
        )
    return analyser_model


def build_document(model: libcellml.Model, analyser_model: Any) -> libsbml.SBMLDocument:
    """Build the SBML document of an analysed CellML model.

    Args:
        model: the (flattened) CellML model.
        analyser_model: its analyser model without errors.

    Returns:
        The SBML document, not validated.

    Raises:
        MathConversionError, UnitsConversionError, KeyError: for constructs
            which cannot be converted; `convert_cellml2sbml` wraps them.
    """
    doc = libsbml.SBMLDocument(3, 2)
    model_sbml: libsbml.Model = doc.createModel()
    name = model.name() or "model"
    model_sbml.setId(sanitize_id(name))
    model_sbml.setName(name)

    unit_ids = add_units(model, model_sbml)
    ids = VariableIds(analyser_model)

    voi = analyser_model.voi()
    if voi is not None:
        model_sbml.setTimeUnits(unit_id(voi.variable().units().name(), unit_ids))

    for k in range(analyser_model.stateCount()):
        _add_parameter(model_sbml, analyser_model.state(k), ids, unit_ids, constant=False)
    for k in range(analyser_model.variableCount()):
        variable = analyser_model.variable(k)
        variable_type = variable.type()
        if variable_type == VariableType.EXTERNAL:
            raise MathConversionError(
                f"External variable '{variable.variable().name()}' is not supported."
            )
        constant = variable_type in (VariableType.CONSTANT, VariableType.COMPUTED_CONSTANT)
        _add_parameter(model_sbml, variable, ids, unit_ids, constant=constant)

    for k in range(analyser_model.equationCount()):
        _add_equation(model_sbml, analyser_model.equation(k), ids)

    _add_events(model_sbml, model, ids)
    return doc


def _add_parameter(
    model_sbml: libsbml.Model,
    analyser_variable: Any,
    ids: VariableIds,
    unit_ids: dict[str, str],
    constant: bool,
) -> None:
    """Add the parameter of a variable, with its value or initial assignment."""
    variable = analyser_variable.variable()
    sid = ids.id_for(variable)
    parameter: libsbml.Parameter = model_sbml.createParameter()
    parameter.setId(sid)
    parameter.setConstant(constant)
    parameter.setUnits(unit_id(variable.units().name(), unit_ids))
    if sid != variable.name():
        parameter.setName(variable.name())
    logger.info("'%s' parameter for variable '%s'", sid, variable.name())

    initialising = analyser_variable.initialisingVariable()
    if initialising is None or not initialising.initialValue():
        return
    initial = initialising.initialValue()
    try:
        parameter.setValue(float(initial))
    except ValueError:
        # the initial value is the name of another variable of the same component
        reference = ids.lookup(initialising.parent().name(), initial)
        assignment: libsbml.InitialAssignment = model_sbml.createInitialAssignment()
        assignment.setSymbol(sid)
        node = libsbml.ASTNode(libsbml.AST_NAME)
        node.setName(reference)
        assignment.setMath(node)
        logger.info("%s initialised from '%s'", sid, reference)


def _add_equation(model_sbml: libsbml.Model, equation: Any, ids: VariableIds) -> None:
    """Add the rule or initial assignment of an equation."""
    equation_type = equation.type()
    type_name = libcellml.AnalyserEquation.typeAsString(equation_type)  # ty: ignore[unresolved-attribute]
    names = [equation.variable(k).variable().name() for k in range(equation.variableCount())]
    if equation_type in (EquationType.NLA, EquationType.EXTERNAL):
        raise MathConversionError(
            f"Equation of type '{type_name}' for {names} is not supported."
        )
    ast = equation.ast()
    if ast.type() != AstType.EQUALITY:
        raise MathConversionError(f"Equation for {names} is not an equality.")
    left, right = ast.leftChild(), ast.rightChild()
    rhs = ast_to_sbml(right, ids)

    if equation_type == EquationType.ODE:
        state = left.rightChild() if left.type() == AstType.DIFF else None
        if state is None or state.type() != AstType.CI:
            raise MathConversionError(f"ODE for {names} does not start with a derivative.")
        sid = ids.id_for(state.variable())
        rule: libsbml.Rule = model_sbml.createRateRule()
        rule.setVariable(sid)
        rule.setMath(rhs)
        logger.info("d%s/dt = %s", sid, libsbml.formulaToL3String(rhs))
        return

    if left.type() != AstType.CI:
        raise MathConversionError(
            f"Equation of type '{type_name}' for {names} is implicit, only "
            f"'variable = expression' is supported."
        )
    sid = ids.id_for(left.variable())
    if equation_type in (EquationType.TRUE_CONSTANT, EquationType.VARIABLE_BASED_CONSTANT):
        assignment: libsbml.InitialAssignment = model_sbml.createInitialAssignment()
        assignment.setSymbol(sid)
        assignment.setMath(rhs)
        logger.info("%s = %s (initial assignment)", sid, libsbml.formulaToL3String(rhs))
    elif equation_type == EquationType.ALGEBRAIC:
        rule = model_sbml.createAssignmentRule()
        rule.setVariable(sid)
        rule.setMath(rhs)
        logger.info("%s = %s", sid, libsbml.formulaToL3String(rhs))
    else:
        raise MathConversionError(
            f"Equation of type '{type_name}' for {names} is not supported."
        )


def _components(parent: Any) -> Iterator[Any]:
    """The components of a model or component, recursively (encapsulation)."""
    for k in range(parent.componentCount()):
        component = parent.component(k)
        yield component
        yield from _components(component)


def _add_events(model_sbml: libsbml.Model, model: libcellml.Model, ids: VariableIds) -> None:
    """Add an event per reset of every component."""
    index = 0
    for component in _components(model):
        for k in range(component.resetCount()):
            index += 1
            _add_reset(model_sbml, component, component.reset(k), index, ids)


def _add_reset(
    model_sbml: libsbml.Model, component: Any, reset: Any, index: int, ids: VariableIds
) -> None:
    """Add the event of a reset.

    The trigger is the equality of the test variable and the test value, the
    priority the negated order (CellML applies the lowest order first, SBML
    the highest priority), the assignment sets the reset variable.
    """
    test_variable = reset.testVariable()
    variable = reset.variable()
    event: libsbml.Event = model_sbml.createEvent()
    event.setId(f"reset_{index}")
    event.setUseValuesFromTriggerTime(True)

    trigger: libsbml.Trigger = event.createTrigger()
    trigger.setPersistent(True)
    trigger.setInitialValue(True)
    condition = libsbml.ASTNode(libsbml.AST_RELATIONAL_EQ)
    condition.addChild(variable_node(test_variable, ids))
    condition.addChild(_reset_expression(reset.testValue(), test_variable, component, ids))
    trigger.setMath(condition)

    priority: libsbml.Priority = event.createPriority()
    order = libsbml.ASTNode(libsbml.AST_REAL)
    order.setValue(-float(reset.order()))
    priority.setMath(order)

    assignment: libsbml.EventAssignment = event.createEventAssignment()
    assignment.setVariable(ids.id_for(variable))
    assignment.setMath(_reset_expression(reset.resetValue(), variable, component, ids))
    logger.info(
        "reset_%d: %s == %s -> %s",
        index,
        ids.id_for(test_variable),
        libsbml.formulaToL3String(condition.getChild(1)),
        ids.id_for(variable),
    )


def _reset_expression(
    mathml: str, variable: Any, component: Any, ids: VariableIds
) -> libsbml.ASTNode:
    """Expression of a test or reset value.

    The MathML is either the expression itself or the equation
    `variable = expression`, in which case the right side is used.
    """
    node = mathml_to_sbml(mathml, component.name(), ids)
    if (
        node.getType() == libsbml.AST_RELATIONAL_EQ
        and node.getNumChildren() == 2
        and node.getChild(0).getType() == libsbml.AST_NAME
        and node.getChild(0).getName() == ids.id_for(variable)
    ):
        return node.getChild(1).deepCopy()
    return node
```

`src/sbml2cellml/__init__.py`: add the import and the export:

```python
from sbml2cellml.cellml2sbml import convert_cellml2sbml
from sbml2cellml.sbml2cellml import convert_sbml2cellml
...
__all__ = ["convert_cellml2sbml", "convert_sbml2cellml"]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cellml2sbml.py -v`
Expected: all pass. Points to check if not:
- `test_convert_multi_component_model`: the expected formulas assume the analyser keeps `-rate * x` as `MINUS(CI rate)` times `CI x`; print the actual formula and, if it is the same expression with different formatting, fix the expected string. The set of parameter ids and the rule kinds must hold as written.
- The priority prints as `-0`; if libsbml prints `0` or `-0.0`, adjust the expected string only.
- `test_convert_nla_model_raises`: the analyser reports the model type `nla`; if it instead reports errors at analysis (`match="analysed"`), keep the `match="nla"` and include the type name in that message too.
- `test_convert_invalid_cellml_raises`: the analyser rejects the model because `y` is undefined; if the parser already rejects it, the raised exception is `CellMLValidationError`: change the fixture so it parses (it should) rather than the assertion.
- ty: the `# ty: ignore[unresolved-attribute]` comments on the four `Type` aliases and the two `typeAsString` calls are there because ty cannot see the swig nested enums (as in `cellml.py`); remove any ty reports as unused.

- [ ] **Step 6: Full suite, lint, type check, commit**

```bash
uv run pytest
uv run ruff check && uv run ruff format && uv run ty check
git add src/sbml2cellml/cellml2sbml.py src/sbml2cellml/__init__.py tests/test_cellml2sbml.py tests/data
git commit -m "Add the CellML to SBML converter

Parameters, rate and assignment rules and initial assignments from the
libcellml analyser model, unit definitions from the CellML units, events
from the resets, imports resolved and flattened."
```

---

### Task 5: The `cellml2sbml` command

**Files:**
- Modify: `src/sbml2cellml/cli.py`, `pyproject.toml` (`[project.scripts]`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `convert_cellml2sbml`, `CellML2SBMLConversionError`, `SBMLValidationError`, `CellMLValidationError`.
- Produces: `cli.main_cellml2sbml(argv: list[str] | None = None) -> int`, `cli.build_parser_cellml2sbml() -> argparse.ArgumentParser`, script `cellml2sbml`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
from sbml2cellml.cli import main_cellml2sbml
from tests.conftest import TEST_MODEL_PATH


def test_cellml2sbml_convert_with_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "test_model.xml"
    code = main_cellml2sbml([str(TEST_MODEL_PATH), "-o", str(out)])
    assert code == 0
    assert out.is_file()
    assert str(out) in capsys.readouterr().out


def test_cellml2sbml_default_output_next_to_input(tmp_path: Path) -> None:
    cellml_path = tmp_path / "test_model.cellml"
    shutil.copy(TEST_MODEL_PATH, cellml_path)
    assert main_cellml2sbml([str(cellml_path)]) == 0
    assert (tmp_path / "test_model.xml").is_file()


def test_cellml2sbml_missing_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main_cellml2sbml([str(tmp_path / "missing.cellml")])
    assert code == 1
    assert "missing.cellml" in capsys.readouterr().err


def test_cellml2sbml_invalid_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "invalid.cellml"
    path.write_text(
        '<?xml version="1.0"?><model xmlns="http://www.cellml.org/cellml/2.0#" name="bad">'
        '<component name="c"><variable name="x" units="second"/>'
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><apply><eq/><ci>x</ci><ci>y</ci></apply></math>'
        "</component></model>"
    )
    code = main_cellml2sbml([str(path)])
    assert code == 1
    assert "analysed" in capsys.readouterr().err


def test_cellml2sbml_verbose_logs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "test_model.xml"
    assert main_cellml2sbml([str(TEST_MODEL_PATH), "-o", str(out), "-v"]) == 0
    captured = capsys.readouterr()
    assert "parameter for variable" in captured.out + captured.err


def test_cellml2sbml_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main_cellml2sbml(["--version"])
    assert info.value.code == 0
    assert "0.1.0" in capsys.readouterr().out


def test_cellml2sbml_entry_point_installed(tmp_path: Path) -> None:
    out = tmp_path / "test_model.xml"
    script = shutil.which("cellml2sbml")
    assert script is not None, "cellml2sbml console script not installed, run uv sync"
    result = subprocess.run(
        [script, str(TEST_MODEL_PATH), "-o", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert out.is_file()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ImportError: cannot import name 'main_cellml2sbml'`.

- [ ] **Step 3: Rewrite `cli.py` with both commands**

Replace `src/sbml2cellml/cli.py` by:

```python
"""Command line interfaces of sbml2cellml.

    sbml2cellml INPUT.xml [-o OUTPUT.cellml] [--no-validate] [-v]
    cellml2sbml INPUT.cellml [-o OUTPUT.xml] [--no-validate] [-v]

convert between SBML and CellML. Without `-o` the output is written next to
the input with the suffix of the other format.
"""

import argparse
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sbml2cellml import __version__, log
from sbml2cellml.cellml import CellMLValidationError
from sbml2cellml.cellml2sbml import CellML2SBMLConversionError, convert_cellml2sbml
from sbml2cellml.sbml import SBMLValidationError
from sbml2cellml.sbml2cellml import SBML2CellMLConversionError, convert_sbml2cellml

#: errors reported with exit code 1 instead of a traceback
CONVERSION_ERRORS = (
    SBML2CellMLConversionError,
    CellML2SBMLConversionError,
    CellMLValidationError,
    SBMLValidationError,
    OSError,
)


def _build_parser(prog: str, description: str, input_help: str, output_help: str) -> argparse.ArgumentParser:
    """Parser shared by both commands."""
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument("input", help=input_help)
    parser.add_argument("-o", "--output", help=output_help)
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="write the output even if the validation reports errors",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="log the conversion steps"
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser of the `sbml2cellml` command.

    Returns:
        The parser.
    """
    return _build_parser(
        prog="sbml2cellml",
        description="Convert an SBML model to CellML.",
        input_help="SBML file",
        output_help="CellML file, by default the input with the suffix .cellml",
    )


def build_parser_cellml2sbml() -> argparse.ArgumentParser:
    """Build the argument parser of the `cellml2sbml` command.

    Returns:
        The parser.
    """
    return _build_parser(
        prog="cellml2sbml",
        description="Convert a CellML model to SBML.",
        input_help="CellML file",
        output_help="SBML file, by default the input with the suffix .xml",
    )


def _run(
    parser: argparse.ArgumentParser,
    convert: Callable[..., Any],
    suffix: str,
    argv: list[str] | None,
) -> int:
    """Run a conversion command.

    Args:
        parser: parser of the command.
        convert: converter taking the input path, the output path and `validate`.
        suffix: suffix of the default output file.
        argv: arguments without the program name, `sys.argv[1:]` by default.

    Returns:
        0 on success, 1 on a missing input, a conversion, a validation or an
        I/O error.
    """
    args = parser.parse_args(argv)
    if args.verbose:
        log.enable_rich_logging(logging.INFO)

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"Input file does not exist: '{input_path}'", file=sys.stderr)
        return 1
    output_path = Path(args.output) if args.output else input_path.with_suffix(suffix)

    try:
        convert(input_path, output_path, not args.no_validate)
    except CONVERSION_ERRORS as err:
        print(str(err), file=sys.stderr)
        return 1

    print(output_path)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the `sbml2cellml` command.

    Args:
        argv: arguments without the program name, `sys.argv[1:]` by default.

    Returns:
        0 on success, 1 on a missing input, a conversion, a validation or an
        I/O error.
    """
    return _run(
        build_parser(),
        lambda sbml_path, cellml_path, validate: convert_sbml2cellml(
            sbml_path, cellml_path=cellml_path, validate=validate
        ),
        ".cellml",
        argv,
    )


def main_cellml2sbml(argv: list[str] | None = None) -> int:
    """Run the `cellml2sbml` command.

    Args:
        argv: arguments without the program name, `sys.argv[1:]` by default.

    Returns:
        0 on success, 1 on a missing input, a conversion, a validation or an
        I/O error.
    """
    return _run(
        build_parser_cellml2sbml(),
        lambda cellml_path, sbml_path, validate: convert_cellml2sbml(
            cellml_path, sbml_path=sbml_path, validate=validate
        ),
        ".xml",
        argv,
    )


if __name__ == "__main__":
    sys.exit(main())
```

In `pyproject.toml` `[project.scripts]` add `cellml2sbml = "sbml2cellml.cli:main_cellml2sbml"`. Then `uv sync --extra dev` so the console script is installed (`uv run cellml2sbml --version` prints `0.1.0`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: all pass (the S1 tests of `main` unchanged).

- [ ] **Step 5: Lint, type check, commit**

```bash
uv run ruff check && uv run ruff format && uv run ty check
git add src/sbml2cellml/cli.py tests/test_cli.py pyproject.toml uv.lock
git commit -m "Add the cellml2sbml command"
```

---

### Task 6: Roundtrip tests, example, CI

**Files:**
- Create: `tests/test_roundtrip.py`, `examples/cellml2sbml_example.py`
- Modify: `tests/test_examples.py`, `.github/workflows/ci-cd.yml`, `.github/workflows/ty.yml`, `.github/workflows/docs.yml`

**Interfaces:**
- Consumes: `convert_sbml2cellml`, `convert_cellml2sbml`, `simulate.run_timecourse`, `roadrunner.RoadRunner`.

- [ ] **Step 1: Write the roundtrip tests**

`tests/test_roundtrip.py`:

```python
"""SBML to CellML to SBML roundtrips, checked by simulation.

Skipped without roadrunner (and libopencor for the CellML side); both are
part of the dev extra.
"""

from pathlib import Path

import libsbml
import numpy as np
import pytest

from sbml2cellml import convert_cellml2sbml, convert_sbml2cellml
from sbml2cellml.sbml import document_to_string
from tests.conftest import MODELS_DIR, TEST_MODEL_PATH

roadrunner = pytest.importorskip("roadrunner")

END = 100.0
STEPS = 10


def simulate_sbml(sbml: str, selections: list[str]) -> np.ndarray:
    """Roadrunner timecourse of the selections (without time), rows are time points."""
    rr = roadrunner.RoadRunner(sbml)
    rr.timeCourseSelections = ["time", *selections]
    result = rr.simulate(0.0, END, STEPS + 1)
    return np.asarray(result)[:, 1:]


def test_roundtrip_glimepiride_liver(tmp_path: Path) -> None:
    sbml_path = MODELS_DIR / "glimepiride_liver.xml"
    cellml_path = tmp_path / "liver.cellml"
    convert_sbml2cellml(sbml_path, cellml_path=cellml_path)
    doc = convert_cellml2sbml(cellml_path)

    original = libsbml.readSBMLFromFile(str(sbml_path)).getModel()
    roundtrip = doc.getModel()
    original_ids = (
        {c.getId() for c in original.getListOfCompartments()}
        | {s.getId() for s in original.getListOfSpecies()}
        | {p.getId() for p in original.getListOfParameters()}
    )
    assert {p.getId() for p in roundtrip.getListOfParameters()} == original_ids

    species_with_reactions = {
        ref.getSpecies()
        for reaction in original.getListOfReactions()
        for ref in list(reaction.getListOfReactants()) + list(reaction.getListOfProducts())
    }
    rate_rules = {r.getVariable() for r in roundtrip.getListOfRules() if r.isRate()}
    original_rate_rules = {r.getVariable() for r in original.getListOfRules() if r.isRate()}
    assert rate_rules == species_with_reactions | original_rate_rules

    # the species of the original are concentrations or amounts; the roundtrip
    # parameters carry the same quantity, so the timecourses agree
    selections = sorted(s.getId() for s in original.getListOfSpecies())
    expected = simulate_sbml(sbml_path.read_text(), [f"[{s}]" if original.getSpecies(s).getHasOnlySubstanceUnits() is False else s for s in selections])
    result = simulate_sbml(document_to_string(doc), selections)
    np.testing.assert_allclose(result, expected, rtol=1e-4, atol=1e-8)


def test_roundtrip_test_model(tmp_path: Path) -> None:
    """The SBML of test_model.cellml simulates like the CellML in libopencor."""
    pytest.importorskip("libopencor")
    from sbml2cellml.simulate import run_timecourse

    doc = convert_cellml2sbml(TEST_MODEL_PATH)
    result = simulate_sbml(document_to_string(doc), ["m"])
    df, _ = run_timecourse(TEST_MODEL_PATH, start=0.0, end=END, steps=STEPS)
    np.testing.assert_allclose(result[:, 0], df["m"].to_numpy(), rtol=1e-4)
```

Run: `uv run pytest tests/test_roundtrip.py -v`
Expected: both pass. If `test_roundtrip_glimepiride_liver` fails on the values:
- print the first rows of `expected` and `result`; a species in concentration must be selected as `[id]` in roadrunner (concentration) and its roundtrip parameter holds the concentration; an amount species (`hasOnlySubstanceUnits`) is selected as `id`. The selection expression above does that; fix the expression, not the tolerance, if a species is selected wrongly.
- a mismatch limited to variables whose SBML initial value is NaN (`egfr`-like assignment-rule targets) means the roundtrip lost an assignment rule; that is a converter bug to fix in `cellml2sbml.py`.
- a systematic difference from a compartment size other than 1 means the concentration scaling `1.0 dimensionless/{cid}` of the S1 converter (kept as is in S1) does not round-trip; report it as DONE_WITH_CONCERNS with the numbers instead of loosening the tolerance.

- [ ] **Step 2: Write the example and extend the example test**

`examples/cellml2sbml_example.py`:

```python
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
```

In `tests/test_examples.py` add the case `("cellml2sbml_example.py", "cell_growth.xml")` to the parametrize list.

Run: `uv run pytest tests/test_examples.py -v`
Expected: 3 passed.

- [ ] **Step 3: CI python dev files**

roadrunner's extension links against libpython, which the standalone interpreters of `setup-uv` do not expose on linux. Copy the step from `/home/mkoenig/git/sbmlsim/.github/workflows/ci-cd.yml` ("Install the python dev files (linux only)", the `if [ "$RUNNER_OS" == "Linux" ]` block with deadsnakes and `python${{ matrix.python-version }}-dev`) into the `test` job of `.github/workflows/ci-cd.yml` before the `setup-uv` step. Copy the unconditional variant from `/home/mkoenig/git/sbmlsim/.github/workflows/ty.yml` and `docs.yml` ("Install the python dev files", `python3.14-dev` changed to `python3.13-dev`) into the `ty` job of `ty.yml` and the `docs` job of `docs.yml` before their `setup-uv` steps. Keep the comments. Validate the yaml (`uv run --with pyyaml python -c "import yaml,glob;[yaml.safe_load(open(p)) for p in glob.glob('.github/workflows/*.yml')];print('ok')"`).

- [ ] **Step 4: Full suite, lint, type check, commit**

```bash
uv run pytest
uv run ruff check && uv run ruff format && uv run ty check
git add tests/test_roundtrip.py examples/cellml2sbml_example.py tests/test_examples.py .github/workflows
git commit -m "Add the roundtrip tests, the cellml2sbml example and the python dev files in CI"
```

---

### Task 7: Documentation

**Files:**
- Modify: `docs/index.md`, `docs/conversion.md`, `docs/roadmap.md`, `docs/api/index.md`, `zensical.toml`, `CLAUDE.md`, `README.md`, `release-notes/0.1.0.md`, `docs/development.md`
- Create: `docs/api/cellml2sbml.md`, `docs/api/variables.md`, `docs/api/sbmlmath.md`, `docs/api/units.md`, `docs/api/sbml.md`

- [ ] **Step 1: API pages and nav**

Five pages of the form (`docs/api/cellml2sbml.md`):

```markdown
# cellml2sbml

::: sbml2cellml.cellml2sbml
```

for `cellml2sbml`, `variables`, `sbmlmath`, `units`, `sbml`. In `zensical.toml` add them to the "API reference" nav after `sbml2cellml`: `cellml2sbml`, `cellml`, `sbml`, `mathml`, `sbmlmath`, `units`, `variables`, `simulate`, `cli`, `console`, `log` (alphabetical apart from the two converters first). In `docs/api/index.md` add the rows:

| module | description |
| --- | --- |
| [cellml2sbml](cellml2sbml.md) | Conversion of CellML models to SBML, `convert_cellml2sbml` |
| [sbml](sbml.md) | Reading, writing and validating SBML documents with libsbml |
| [sbmlmath](sbmlmath.md) | CellML maths (analyser AST, MathML) to libsbml ASTs |
| [units](units.md) | CellML units to SBML unit definitions |
| [variables](variables.md) | SBML ids of the CellML variables |

- [ ] **Step 2: Narrative pages**

`docs/conversion.md`: rename the top heading to "SBML to CellML" for the existing content (keep it), and append:

````markdown
# CellML to SBML

[`convert_cellml2sbml`](api/cellml2sbml.md) reads a CellML 2.0 file, resolves its imports relative to the file, analyses it with libcellml and builds an SBML level 3 version 2 document:

```python
from pathlib import Path
from sbml2cellml import convert_cellml2sbml

doc = convert_cellml2sbml(Path("model.cellml"), sbml_path=Path("model.xml"))
```

or on the command line:

```bash
cellml2sbml model.cellml                 # writes model.xml next to the input
cellml2sbml model.cellml -o out/model.xml
cellml2sbml model.cellml --no-validate   # write even if libsbml reports errors
cellml2sbml model.cellml -v
```

By default the document is checked with the libsbml consistency checks and a `SBMLValidationError` with the messages is raised on errors (unit problems are warnings and do not stop the conversion).

## Mapping

CellML has no species, compartments or reactions: every variable becomes a parameter, the equations become rules. The libcellml analyser decides the kind of every variable and equation and merges the variables which are connected across components.

| CellML | SBML |
| --- | --- |
| variable of integration | the `time` symbol, `timeUnits` of the model |
| constant | `parameter constant="true"` with the initial value |
| computed constant (`c = 2 * k`) | `parameter constant="true"` with an initial assignment |
| algebraic variable | `parameter constant="false"` with an assignment rule |
| state (`dx/dt = ...`) | `parameter constant="false"` with a rate rule |
| initial value given as a variable name | initial assignment |
| standard units | the SBML unit kind of the same name |
| custom units | unit definition expanded to base kinds |
| reset | event with the trigger `test_variable == test_value`, priority `-order`, one event assignment |
| components and connections | one flat namespace; a variable name used by several unconnected variables is prefixed with its component (`cell_x`), the CellML name is kept as `name` |
| imports | resolved and flattened before the conversion |

## Limitations

- Implicit equations (`x + y = 4`, a system the analyser classifies as NLA) and external variables are not supported and raise `CellML2SBMLConversionError`.
- Units on numbers in formulas are not carried into the SBML math (the analyser AST has none); libsbml reports them as unit warnings.
- A reset triggers on the equality of the test variable and the test value. A continuous simulator detects the equality only when the test variable crosses the test value at an integrator step, so a reset may not fire in SBML simulators; the roundtrip harness reports this per model.
````

`docs/index.md`: in the intro sentence say "converts between SBML and CellML 2.0" and in the quickstart add the `cellml2sbml` line after the `sbml2cellml` command; add below the "What is converted" table one sentence: "The reverse direction, [CellML to SBML](conversion.md#cellml-to-sbml), maps every variable to a parameter with rules and converts units and resets."

`docs/roadmap.md`: under "Planned", replace item 1 by "1. **CellML to SBML** converter: done, see [Conversion](conversion.md#cellml-to-sbml)." and add to "Conversion gaps" a subsection "CellML to SBML" listing: NLA equations and external variables; units on numbers; equality triggers of resets (see the limitations).

`docs/development.md`: in the "Setup development environment" sentence on the `dev` extra add "and libroadrunner for the roundtrip tests"; in "Testing" add "The roundtrip tests (`tests/test_roundtrip.py`) need roadrunner and are skipped without it."; note the python dev files step of the CI (one sentence in the checks table description or after it: "On linux the CI installs the python dev files before uv, because the roadrunner extension links against libpython.").

- [ ] **Step 3: README, CLAUDE.md, release notes**

`README.md`: intro "converts between SBML and CellML 2.0"; features add "- conversion of CellML models to SBML: parameters with rules, unit definitions, resets as events, imports resolved" and "- the `sbml2cellml` and `cellml2sbml` command lines" (replace the existing CLI bullet); the code block gains `cellml2sbml model.cellml -o model.xml`.

`CLAUDE.md`: Project paragraph: "converts SBML models to CellML 2.0 and CellML models to SBML L3V2"; dev extra also has `libroadrunner`. Commands: add `cellml2sbml model.cellml -o model.xml`. Architecture: add entries for `cellml2sbml.py` (analyser driven: parameters by variable type, rules by equation type, initial assignments for computed constants and variable-referenced initial values, resets as events with `eq` trigger and `-order` priority, imports flattened with `Importer`), `variables.py` (one SBML id per equivalence set, component prefix on clashes), `sbmlmath.py` (analyser AST to libsbml AST, nested piecewise flattened, `mathml_to_sbml` for reset maths), `units.py` (standard units by name, custom units expanded to base kinds, factor folded into the first unit), `sbml.py` (libsbml helpers, `validate_document` returns error messages, unit problems are warnings). Conventions: add "Test models built with libcellml live in `tests/cellml_models.py`; `tests/data/` holds the import fixtures."

`release-notes/0.1.0.md`: features add "- `convert_cellml2sbml` converts CellML 2.0 models (imports resolved, multiple components) to SBML L3V2 with parameters, rules, initial assignments, unit definitions and events for resets" and "- the `cellml2sbml` command line"; limitations add "- CellML to SBML: implicit (NLA) equations and external variables are not supported, units on numbers are dropped".

- [ ] **Step 4: Build and commit**

```bash
uv run zensical build --clean --strict
uv run python scripts/llms_txt.py
grep -rn "—" docs/*.md CLAUDE.md README.md release-notes/0.1.0.md || echo "no em dash"
uv run ruff check && uv run ruff format --check && uv run ty check
git add docs zensical.toml CLAUDE.md README.md release-notes/0.1.0.md
git commit -m "Document the CellML to SBML conversion"
```

Expected: strict build passes with zero warnings, `no em dash`.

---

### Task 8: Pull request

Run by the main session.

- [ ] **Step 1: Full verification**

```bash
uv run pre-commit run --all-files
uv run tox run-parallel
uv run zensical build --clean --strict
uvx hatch build && uvx twine check dist/* && unzip -l dist/*.whl | grep -c "sbml2cellml/" && rm -rf dist
```

Expected: all green; the wheel lists 13 package files (8 of S1 plus `cellml2sbml.py`, `sbml.py`, `sbmlmath.py`, `units.py`, `variables.py`).

- [ ] **Step 2: Push and open the pull request**

If PR #1 has been merged into `develop` meanwhile: `git fetch origin && git rebase --onto origin/develop s1-infrastructure s2-cellml2sbml` (the S1 commits are replaced by the squash commit). Then:

```bash
git push -u origin s2-cellml2sbml
gh pr create --base develop --head s2-cellml2sbml --title "CellML to SBML converter (S2)" --body "..."
gh pr checks --watch
```

The body follows the pull request template: summary of the mapping, the spec and plan paths, the checklist. If PR #1 is still open, the PR lists "Stacked on #1" in the summary. Expected: `tests`, `ruff`, `ty`, `docs` pass.
