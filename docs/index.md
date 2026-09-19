# sbml2cellml: conversion between SBML and CellML
[![GitHub Actions CI/CD Status](https://github.com/matthiaskoenig/sbml2cellml/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/matthiaskoenig/sbml2cellml/actions/workflows/ci-cd.yml) [![Documentation](https://img.shields.io/badge/docs-sbml2cellml-008080.svg)](https://matthiaskoenig.github.io/sbml2cellml) [![Version](https://img.shields.io/pypi/v/sbml2cellml)](https://pypi.org/project/sbml2cellml/) [![Python Versions](https://img.shields.io/pypi/pyversions/sbml2cellml)](https://pypi.org/project/sbml2cellml/) [![MIT License](https://img.shields.io/pypi/l/sbml2cellml)](https://opensource.org/licenses/MIT)

`sbml2cellml` converts between [SBML (Systems Biology Markup Language)](https://sbml.org) and [CellML 2.0](https://cellml.org), so that a model developed with one tooling can be used, simulated and shared in the other ecosystem. The source code is available from [https://github.com/matthiaskoenig/sbml2cellml](https://github.com/matthiaskoenig/sbml2cellml).

## Features

- conversion of compartments, parameters, species, assignment and rate rules and reactions into a single CellML component
- conversion of the units: unit definitions, the units of numbers and, for a model with a complete unit annotation, the units of every variable
- conversion of CellML models to SBML: parameters with rules, unit definitions and units of numbers, resets as events, imports resolved
- validation of the result with [libcellml](https://libcellml.org/)
- timecourse simulation of the SBML with [roadrunner](https://www.libroadrunner.org/) and of the CellML with [libopencor](https://opencor.ws/libopencor/), both optional, see [Simulation](simulation.md)
- the `sbml2cellml` and `cellml2sbml` command lines
- the SBML test suite harness: every semantic case through both converters and both simulators, results on the [SBML test suite](testsuite.md) page
- the same check for the manually curated models of [BioModels](https://www.biomodels.org), results on the [BioModels](biomodels.md) page

## Quickstart

```python
from pathlib import Path
from sbml2cellml import convert_sbml2cellml

model = convert_sbml2cellml(Path("model.xml"), cellml_path=Path("model.cellml"))
```

or on the command line:

```bash
sbml2cellml model.xml -o model.cellml
cellml2sbml model.cellml -o model.xml
```

The conversion is validated with [libcellml](https://libcellml.org/); the resulting file can be simulated with [libopencor](https://opencor.ws/libopencor/) and compared with the roadrunner simulation of the SBML model, see [Simulation](simulation.md).

## What is converted

The converter puts every SBML compartment, parameter and species as a variable into a single CellML component, together with the variable of integration `time` when the model has differential equations (rate rules or reactions).

| SBML | CellML |
| --- | --- |
| compartment | variable with the size as initial value |
| parameter | variable with the value as initial value |
| species | variable in amount (`hasOnlySubstanceUnits`) or concentration |
| species in concentration whose compartment changes in time | a second variable `<species>_amount` which the reactions change, and the equation `species = amount / compartment`: the amount is kept when the size changes, not the concentration |
| assignment rule | equation; its target has no initial value, the equation defines it from the start |
| rate rule | differential equation |
| reaction | kinetic law times the stoichiometry added to the differential equation of every reactant and product which is not a boundary species, divided by the size of the compartment for a species in concentration |
| conversion factor of a species or the model | factor of the reaction terms of the species |
| species reference with an id | variable of its stoichiometry, which rules may set |
| reaction id in a formula | variable of the rate of the reaction |
| unit definition | units of the same name; the scale becomes the prefix, the multiplier `m` of a unit with the exponent `e` becomes `m^e` (CellML applies the exponent to the prefix only) |
| unit kinds `item` and `avogadro` | new base units `item`, dimensionless units `avogadro` with the multiplier 6.02214179e23; every other unit kind is a standard unit of CellML |
| units of a compartment, parameter or species | units of the variable when the unit annotation of the model is complete, else every variable is `dimensionless`, see [Units](conversion.md#units) |
| numbers in formulas | real numbers with their units, `dimensionless` when they have none |
| time and avogadro symbols | the variable of integration `time`, the number 6.02214179e23 |
| rateOf symbol | the right-hand side of the differential equation of its variable, 0 without one |
| delay symbol | not yet |
| rule or kinetic law without math | ignored, it has no effect |
| initial assignment | evaluated to the initial value (not to NaN, a warning is logged) |
| infinite or NaN value | the equation `x = INF` (or `-INF`, `NaN`), not for a state |
| function definition | calls replaced by the body of the function |
| local parameter of a kinetic law | variable `<reaction>_<parameter>` (numeric suffix when taken) |
| event | not yet, a warning is logged |
| algebraic rule | implicit equation `0 = formula` for the variable the rule determines, which starts from the solution at the start time; the constants of the rule become equations `y = value` |
| `plus`, `times`, `and`, `or`, `xor` with less than two arguments | their value (the argument or the identity element) |

The reverse direction, [CellML to SBML](conversion.md#cellml-to-sbml), maps every variable to a parameter with rules and converts units and resets.

The [conversion issues](conversion-issues.md) list what is not converted yet, the [SBML test suite](testsuite.md) and [BioModels](biomodels.md) pages how many of the semantic test cases and of the curated models pass.

The [release notes](release-notes/index.md) list the changes of every version.

## Citation

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22829187.svg)](https://doi.org/10.5281/zenodo.22829187)

If you use `sbml2cellml` please cite the archived software on [Zenodo](https://doi.org/10.5281/zenodo.22829187):

> König, M. (2026). *sbml2cellml: conversion of SBML models to CellML* (Version 0.3.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.22838601

```bibtex
@software{konig_sbml2cellml,
  author    = {König, Matthias},
  title     = {sbml2cellml: conversion of SBML models to CellML},
  year      = {2026},
  month     = sep,
  version   = {0.3.0},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.22838601},
  url       = {https://doi.org/10.5281/zenodo.22838601},
}
```

## License

- Source Code: [MIT](https://opensource.org/license/MIT)
- Documentation: [CC BY-SA 4.0](http://creativecommons.org/licenses/by-sa/4.0/)

## Funding

Matthias König was supported by the Federal Ministry of Education and Research (BMBF, Germany) within the research network Systems Medicine of the Liver (LiSyM, grant number 031L0054) and within ATLAS by grant number 031L0304B, and by the German Research Foundation (DFG) within the Research Unit Program FOR 5151 QuaLiPerF (Quantifying Liver Perfusion-Function Relationship in Complex Resection - A Systems Medicine Approach) by grant number 436883643 and by grant number 465194077 (Priority Programme SPP 2311, Subproject SimLivA).
