# sbml2cellml: conversion of SBML models to CellML
[![GitHub Actions CI/CD Status](https://github.com/matthiaskoenig/sbml2cellml/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/matthiaskoenig/sbml2cellml/actions/workflows/ci-cd.yml) [![Documentation](https://img.shields.io/badge/docs-sbml2cellml-008080.svg)](https://matthiaskoenig.github.io/sbml2cellml) [![Version](https://img.shields.io/pypi/v/sbml2cellml.svg)](https://pypi.org/project/sbml2cellml/) [![Python Versions](https://img.shields.io/pypi/pyversions/sbml2cellml.svg)](https://pypi.org/project/sbml2cellml/) [![MIT License](https://img.shields.io/pypi/l/sbml2cellml.svg)](https://opensource.org/licenses/MIT)

`sbml2cellml` converts between [SBML (Systems Biology Markup Language)](https://sbml.org) and [CellML 2.0](https://cellml.org), so that a model developed with one tooling can be used, simulated and shared in the other ecosystem. The source code is available from [https://github.com/matthiaskoenig/sbml2cellml](https://github.com/matthiaskoenig/sbml2cellml).

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

The conversion is validated with [libcellml](https://libcellml.org/); the resulting file can be simulated with [libopencor](https://opencor.ws/libopencor/), see [Simulation](simulation.md).

## What is converted

The converter puts every SBML compartment, parameter and species as a variable into a single CellML component, together with the variable of integration `time`.

| SBML | CellML |
| --- | --- |
| compartment | variable with the size as initial value |
| parameter | variable with the value as initial value |
| species | variable in amount (`hasOnlySubstanceUnits`) or concentration |
| assignment rule | equation |
| rate rule | differential equation |
| reaction | kinetic law added to the differential equation of every reactant and product |
| unit definition | not yet, every variable is `dimensionless` |
| units on numbers in formulas | not yet |
| initial assignment | not yet, a warning is logged |
| function definition | not yet |
| event | not yet, a warning is logged |
| algebraic rule | not yet, a warning is logged |

The reverse direction, [CellML to SBML](conversion.md#cellml-to-sbml), maps every variable to a parameter with rules and converts units and resets.

The [Roadmap](roadmap.md) lists what comes next.

## Citation

The citation information is available with the first release.

## License

- Source Code: [MIT](https://opensource.org/license/MIT)
- Documentation: [CC BY-SA 4.0](http://creativecommons.org/licenses/by-sa/4.0/)

## Funding

Matthias König was supported by the Federal Ministry of Education and Research (BMBF, Germany) within the research network Systems Medicine of the Liver (LiSyM, grant number 031L0054) and within ATLAS by grant number 031L0304B, and by the German Research Foundation (DFG) within the Research Unit Program FOR 5151 QuaLiPerF (Quantifying Liver Perfusion-Function Relationship in Complex Resection - A Systems Medicine Approach) by grant number 436883643 and by grant number 465194077 (Priority Programme SPP 2311, Subproject SimLivA).
