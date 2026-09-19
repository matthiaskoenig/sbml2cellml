# Conversion

`sbml2cellml` converts in both directions: [SBML to CellML](#sbml-to-cellml) and [CellML to SBML](#cellml-to-sbml). What cannot be converted yet is listed in the [conversion issues](conversion-issues.md).

## SBML to CellML

### Python

[`convert_sbml2cellml`](api/sbml2cellml.md) reads an SBML file, builds the CellML model with libcellml and returns it. With `cellml_path` the CellML is written as well:

```python
from pathlib import Path
from sbml2cellml import convert_sbml2cellml

model = convert_sbml2cellml(Path("model.xml"), cellml_path=Path("model.cellml"))
```

By default the model is validated: the libcellml `Validator` checks it against the CellML specification and the `Analyser` checks that every variable is defined by exactly one equation or initial value. If either reports an error a `CellMLValidationError` with the issues is raised and nothing is written. `validate=False` skips the check, which is useful to inspect a conversion with known gaps; the issues are then available from [`validate_model`](api/cellml.md):

```python
from sbml2cellml.cellml import errors, format_issues, validate_model

model = convert_sbml2cellml(Path("model.xml"), validate=False)
issues = validate_model(model)
print(format_issues(errors(issues)))
```

A file without a model raises `SBML2CellMLConversionError`.

### Logging

The package logs the conversion steps and the constructs it skips (events, algebraic rules which determine no variable, initial assignments libsbml cannot evaluate, unset initial values) and does not print. Scripts enable the rich output of the package with

```python
from sbml2cellml import log

log.enable_rich_logging()
```

An application configures the `sbml2cellml` logger like any other logger.

### Command line

```bash
sbml2cellml model.xml                      # writes model.cellml next to the input
sbml2cellml model.xml -o out/model.cellml  # explicit output
sbml2cellml model.xml --no-validate        # write even if libcellml reports errors
sbml2cellml model.xml -v                   # log the conversion steps
```

The command exits with 1 and the message on stderr when the input does not exist, has no model, or the validation fails.

### Example models

`examples/models/` in the repository holds the glimepiride models of [matthiaskoenig/glconversion-issues.mdmodel](https://github.com/matthiaskoenig/glimepiride-model), which `examples/glimepiride_example.py` converts. The liver and kidney models convert to valid CellML, the intestine and body models hit the [known issues](conversion-issues.md) of the converter.

## CellML to SBML

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

### Mapping

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
| variable written only by a reset | parameter constant="false" (an event assignment needs a non-constant target) |
| reset | event with the trigger `test_variable == test_value`, priority `-order`, one event assignment |
| components and connections | one flat namespace; a variable name used by several unconnected variables is prefixed with its component (`cell_x`), the CellML name is kept as `name`; the model id and event ids also get a numeric suffix when they collide with a variable id |
| imports | resolved and flattened before the conversion |
| implicit equation (`a + s = 5`, a model of type DAE or NLA) | algebraic rule `0 = a + s - 5`, the unknown a `parameter constant="false"` with its initial value (the guess of the solver) |
| model which cannot be analysed (e.g. underconstrained) | CellML2SBMLConversionError |

### Limitations

- A system of coupled implicit equations (`x + y = 4`, `x - y = 2`) cannot be analysed by libcellml, and external variables are not supported; both raise `CellML2SBMLConversionError`.
- Units on numbers in formulas are not carried into the SBML math (the analyser AST has none); libsbml reports them as unit warnings.
- A reset triggers on the equality of the test variable and the test value. A continuous simulator detects the equality only when the test variable crosses the test value at an integrator step, so a reset may not fire in SBML simulators; the roundtrip harness reports this per model.
