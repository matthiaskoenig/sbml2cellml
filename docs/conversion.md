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
sbml2cellml model.xml --no-metadata        # do not write model.rdf
sbml2cellml model.xml -v                   # log the conversion steps
```

The command exits with 1 and the message on stderr when the input does not exist, has no model, or the validation fails.

### Metadata

CellML 2.0 has no place for metadata: the elements of a model must be in the CellML or MathML namespace, and the only thing a model offers to the outside is the `id` of an element. The names, notes, SBO terms, annotations and the history of the SBML model therefore go into an RDF/XML file next to the CellML file, `model.rdf` for `model.cellml`, in which `model.cellml#<id>` is the subject of an element. The model, every variable and all units have an `id` for this: a variable its name, units `units_<name>`, the model its name. A model without metadata has no file, and `metadata=False` or `--no-metadata` writes none.

The RDF is the one of SBML annotations, written and parsed by libsbml, so an annotation looks as in the SBML file (a level 2 model gives the RDF of level 3):

| SBML | RDF |
| --- | --- |
| `name` | `dcterms:title` (not when the name is the id) |
| `notes` | `dcterms:description` with `rdf:parseType="Literal"`, the XHTML as it is |
| `sboTerm` | the first `bqbiol:is` (`bqmodel:is` for the model) with the single resource `https://identifiers.org/SBO:0000252` |
| CV terms | `bqbiol:*` and `bqmodel:*` with an `rdf:Bag` of resources, nested terms included |
| history | `dcterms:creator` (vCard 4), `dcterms:created`, `dcterms:modified` |

The elements with metadata are the ones with a CellML element: the model, compartments, species, parameters, local parameters, species references with an id, reactions (the variable of the rate) and unit definitions. [`convert_cellml2sbml`](#cellml-to-sbml) reads the file back, so the metadata survives the roundtrip; the [roundtrip example](roundtrip.md) shows the files.

### Units

Every unit definition becomes CellML units of the same name, and every number in a formula keeps its units (`2 mM` is `<cn cellml:units="mM">2</cn>`, a number without units is `dimensionless`). The unit kinds of SBML are the standard units of CellML, except for `item` (new base units) and `avogadro` (dimensionless units with its value as multiplier).

The variables get units when the unit annotation of the SBML model is complete, i.e., when the units of every variable are known:

| variable | units |
| --- | --- |
| `time` | `timeUnits` of the model |
| compartment | its `units`, else the `volumeUnits`, `areaUnits` or `lengthUnits` of the model by its `spatialDimensions` |
| parameter, local parameter | its `units` |
| species with `hasOnlySubstanceUnits` | its `substanceUnits`, else the `substanceUnits` of the model |
| variable `<species>_amount` of a species in concentration whose compartment changes | the units of the substance, as for a species with `hasOnlySubstanceUnits` |
| other species (a concentration) | the units of the substance per the units of the compartment: the unit definition of the model which is identical to it (e.g., `mM`), else new units `mmole_per_litre` |
| stoichiometry of a species reference | `dimensionless` |
| rate of a reaction | `extentUnits` per `timeUnits` of the model |

SBML level 1 and 2 have the units `substance`, `time`, `volume`, `area` and `length` built in, which count as set. Units which are not set are unknown in SBML, not dimensionless: when the units of one variable are missing, all variables stay `dimensionless` and a warning names the variables without units. The values are the same either way, CellML does not convert units within a component.


`examples/models/` in the repository holds the glimepiride models of [matthiaskoenig/glimepiride-model](https://github.com/matthiaskoenig/glimepiride-model), which `examples/glimepiride_example.py` converts. All of them convert to valid CellML; their unit annotation is complete, so the CellML variables have the units of the SBML models.

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
cellml2sbml model.cellml --no-metadata   # do not read model.rdf
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
| custom units | unit definition expanded to base kinds; the prefix becomes the scale, the multiplier `m` of a unit with the exponent `e` the multiplier `m^(1/e)` (SBML applies the exponent to the multiplier as well) |
| units of a number | `sbml:units` of the number, by the id of the unit definition |
| new base units `item` | the unit kind `item` |
| variable written only by a reset | parameter constant="false" (an event assignment needs a non-constant target) |
| reset | event with the trigger `test_variable == test_value`, priority `-order`, one event assignment |
| components and connections | one flat namespace; a variable name used by several unconnected variables is prefixed with its component (`cell_x`), the CellML name is kept as `name`; the model id and event ids also get a numeric suffix when they collide with a variable id |
| imports | resolved and flattened before the conversion |
| metadata in `model.rdf` next to `model.cellml`, see [Metadata](#metadata) | name, notes, SBO term, CV terms and history of the parameter of the variable, the unit definition of the units and the model with that `id`; the `id` is the `metaid` |
| implicit equation (`a + s = 5`, a model of type DAE or NLA) | algebraic rule `0 = a + s - 5`, the unknown a `parameter constant="false"` with its initial value (the guess of the solver) |
| model which cannot be analysed (e.g. underconstrained) | CellML2SBMLConversionError |

### Limitations

- A system of coupled implicit equations (`x + y = 4`, `x - y = 2`) cannot be analysed by libcellml, and external variables are not supported; both raise `CellML2SBMLConversionError`.
- New base units other than `item` have no SBML counterpart and are `dimensionless`, with a warning.
- A reset triggers on the equality of the test variable and the test value. A continuous simulator detects the equality only when the test variable crosses the test value at an integrator step, so a reset may not fire in SBML simulators; the roundtrip harness reports this per model.
