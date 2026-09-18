# sbml2cellml: conversion between SBML and CellML
[![GitHub Actions CI/CD Status](https://github.com/matthiaskoenig/sbml2cellml/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/matthiaskoenig/sbml2cellml/actions/workflows/ci-cd.yml) [![Documentation](https://img.shields.io/badge/docs-sbml2cellml-008080.svg)](https://matthiaskoenig.github.io/sbml2cellml) [![Version](https://img.shields.io/pypi/v/sbml2cellml.svg)](https://pypi.org/project/sbml2cellml/) [![Python Versions](https://img.shields.io/pypi/pyversions/sbml2cellml.svg)](https://pypi.org/project/sbml2cellml/) [![MIT License](https://img.shields.io/pypi/l/sbml2cellml.svg)](https://opensource.org/licenses/MIT)

`sbml2cellml` converts between the [Systems Biology Markup Language (SBML)](https://sbml.org) and [CellML 2.0](https://cellml.org), with documentation available from [https://matthiaskoenig.github.io/sbml2cellml](https://matthiaskoenig.github.io/sbml2cellml).

Features include

- conversion of compartments, parameters, species, assignment and rate rules and reactions into a single CellML component
- conversion of CellML models to SBML: parameters with rules, unit definitions, resets as events, imports resolved
- validation of the result with libcellml
- timecourse simulation of the CellML with libopencor
- the `sbml2cellml` and `cellml2sbml` command lines
- the SBML test suite harness: every semantic case through both converters and both simulators, results on the [SBML test suite](https://matthiaskoenig.github.io/sbml2cellml/testsuite/) page

```bash
pip install sbml2cellml
sbml2cellml model.xml -o model.cellml
cellml2sbml model.cellml -o model.xml
```

In the SBML to CellML direction units, events, initial assignments, function definitions and algebraic rules are not converted yet, see the [roadmap](https://matthiaskoenig.github.io/sbml2cellml/roadmap/).

If you have any questions or issues please [open an issue](https://github.com/matthiaskoenig/sbml2cellml/issues).

# How to cite

The Zenodo DOI and the citation are available with the first release.

# License
- Source Code: [MIT](https://opensource.org/license/MIT)
- Documentation: [CC BY-SA 4.0](http://creativecommons.org/licenses/by-sa/4.0/)

# Funding
Matthias König was supported by the Federal Ministry of Education and Research (BMBF, Germany) within the research network Systems Medicine of the Liver (LiSyM, grant number 031L0054) and within ATLAS by grant number 031L0304B, and by the German Research Foundation (DFG) within the Research Unit Program FOR 5151 QuaLiPerF (Quantifying Liver Perfusion-Function Relationship in Complex Resection - A Systems Medicine Approach) by grant number 436883643 and by grant number 465194077 (Priority Programme SPP 2311, Subproject SimLivA).

© 2025-2026 Matthias König
