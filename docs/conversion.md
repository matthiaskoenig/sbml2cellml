# Conversion

## Python

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

## Logging

The package logs the conversion steps and the constructs it skips (events, initial assignments, algebraic rules, unset initial values) and does not print. Scripts enable the rich output of the package with

```python
from sbml2cellml import log

log.enable_rich_logging()
```

An application configures the `sbml2cellml` logger like any other logger.

## Command line

```bash
sbml2cellml model.xml                      # writes model.cellml next to the input
sbml2cellml model.xml -o out/model.cellml  # explicit output
sbml2cellml model.xml --no-validate        # write even if libcellml reports errors
sbml2cellml model.xml -v                   # log the conversion steps
```

The command exits with 1 and the message on stderr when the input does not exist, has no model, or the validation fails.

## Example models

`examples/models/` in the repository holds the glimepiride models of [matthiaskoenig/glimepiride-model](https://github.com/matthiaskoenig/glimepiride-model), which `examples/glimepiride_example.py` converts. The liver and kidney models convert to valid CellML, the intestine and body models hit the [known gaps](roadmap.md) of the converter.
