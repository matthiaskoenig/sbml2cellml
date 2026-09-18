# sbml2cellml: conversion between SBML and CellML
[![GitHub Actions CI/CD Status](https://github.com/matthiaskoenig/sbml2cellml/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/matthiaskoenig/sbml2cellml/actions/workflows/ci-cd.yml) [![Documentation](https://img.shields.io/badge/docs-sbml2cellml-008080.svg)](https://matthiaskoenig.github.io/sbml2cellml) [![Version](https://img.shields.io/pypi/v/sbml2cellml.svg)](https://pypi.org/project/sbml2cellml/) [![Python Versions](https://img.shields.io/pypi/pyversions/sbml2cellml.svg)](https://pypi.org/project/sbml2cellml/) [![MIT License](https://img.shields.io/pypi/l/sbml2cellml.svg)](https://opensource.org/licenses/MIT)

`sbml2cellml` converts between [SBML (Systems Biology Markup Language)](https://sbml.org) and [CellML 2.0](https://cellml.org), so that a model developed with one tooling can be used, simulated and shared in the other ecosystem. The source code is available from [https://github.com/matthiaskoenig/sbml2cellml](https://github.com/matthiaskoenig/sbml2cellml).

## Features

- conversion of compartments, parameters, species, assignment and rate rules and reactions into a single CellML component
- conversion of CellML models to SBML: parameters with rules, unit definitions, resets as events, imports resolved
- validation of the result with [libcellml](https://libcellml.org/)
- timecourse simulation of the CellML with [libopencor](https://opencor.ws/libopencor/), see [Simulation](simulation.md)
- the `sbml2cellml` and `cellml2sbml` command lines
- the SBML test suite harness: every semantic case through both converters and both simulators, results on the [SBML test suite](testsuite.md) page

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
| assignment rule | equation; its target has no initial value, the equation defines it from the start |
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

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22829187.svg)](https://doi.org/10.5281/zenodo.22829187)

If you use `sbml2cellml` please cite the archived software on [Zenodo](https://doi.org/10.5281/zenodo.22829187):

> König, M. (2026). *sbml2cellml: conversion of SBML models to CellML* (Version 0.2.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.22831545

```bibtex
@software{konig_sbml2cellml,
  author    = {König, Matthias},
  title     = {sbml2cellml: conversion of SBML models to CellML},
  year      = {2026},
  month     = sep,
  version   = {0.2.0},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.22831545},
  url       = {https://doi.org/10.5281/zenodo.22831545},
}
```

## License

- Source Code: [MIT](https://opensource.org/license/MIT)
- Documentation: [CC BY-SA 4.0](http://creativecommons.org/licenses/by-sa/4.0/)

## Funding

Matthias König was supported by the Federal Ministry of Education and Research (BMBF, Germany) within the research network Systems Medicine of the Liver (LiSyM, grant number 031L0054) and within ATLAS by grant number 031L0304B, and by the German Research Foundation (DFG) within the Research Unit Program FOR 5151 QuaLiPerF (Quantifying Liver Perfusion-Function Relationship in Complex Resection - A Systems Medicine Approach) by grant number 436883643 and by grant number 465194077 (Priority Programme SPP 2311, Subproject SimLivA).
