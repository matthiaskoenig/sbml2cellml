# sbml2cellml: conversion between SBML and CellML
[![GitHub Actions CI/CD Status](https://github.com/matthiaskoenig/sbml2cellml/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/matthiaskoenig/sbml2cellml/actions/workflows/ci-cd.yml) [![Documentation](https://img.shields.io/badge/docs-sbml2cellml-008080.svg)](https://matthiaskoenig.github.io/sbml2cellml) [![Version](https://img.shields.io/pypi/v/sbml2cellml)](https://pypi.org/project/sbml2cellml/) [![Python Versions](https://img.shields.io/pypi/pyversions/sbml2cellml)](https://pypi.org/project/sbml2cellml/) [![MIT License](https://img.shields.io/pypi/l/sbml2cellml)](https://opensource.org/licenses/MIT)

`sbml2cellml` converts between the [Systems Biology Markup Language (SBML)](https://sbml.org) and [CellML 2.0](https://cellml.org), with documentation available from [https://matthiaskoenig.github.io/sbml2cellml](https://matthiaskoenig.github.io/sbml2cellml).

Features include

- conversion of compartments, parameters, species, assignment and rate rules and reactions into a single CellML component
- conversion of the units: unit definitions, the units of numbers and, for a model with a complete unit annotation, the units of every variable
- names, notes, SBO terms, annotations and the model history as RDF next to the CellML model, restored in the conversion back to SBML
- conversion of CellML models to SBML: parameters with rules, unit definitions and units of numbers, resets as events, imports resolved
- validation of the result with libcellml
- timecourse simulation of the SBML with roadrunner and of the CellML with libopencor, both optional
- the `sbml2cellml` and `cellml2sbml` command lines
- the SBML test suite harness: every semantic case through both converters and both simulators, results on the [SBML test suite](https://matthiaskoenig.github.io/sbml2cellml/testsuite/) page
- the same check for the manually curated models of [BioModels](https://www.biomodels.org), results on the [BioModels](https://matthiaskoenig.github.io/sbml2cellml/biomodels/) page

```bash
pip install sbml2cellml
sbml2cellml model.xml -o model.cellml
cellml2sbml model.cellml -o model.xml
```

In the SBML to CellML direction events and delays are not converted yet, see the [conversion issues](https://matthiaskoenig.github.io/sbml2cellml/conversion-issues/).

# SBML test suite
Every semantic case of the [SBML test suite](https://github.com/sbmlteam/sbml-test-suite) is simulated with roadrunner (`roadrunner`), converted to CellML (`sbml2cellml`), simulated with libopencor (`libopencor`), converted back to SBML (`cellml2sbml`) and simulated with roadrunner again (`roundtrip`). The details are on the [SBML test suite](https://matthiaskoenig.github.io/sbml2cellml/testsuite/) page.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/matthiaskoenig/sbml2cellml/develop/docs/images/testsuite_dark.svg">
  <img alt="Cases of the SBML test suite which pass, fail and skip the stages of the roundtrip" src="https://raw.githubusercontent.com/matthiaskoenig/sbml2cellml/develop/docs/images/testsuite.svg">
</picture>

# BioModels
The manually curated SBML models of [BioModels](https://www.biomodels.org) go through the same roundtrip. They have no expected results, so the roadrunner simulation of the original model over 100 time units (`roadrunner`) is what the libopencor simulation of the CellML (`libopencor`) and the roadrunner simulation of the SBML converted back (`roundtrip`) are compared with. The details are on the [BioModels](https://matthiaskoenig.github.io/sbml2cellml/biomodels/) page.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/matthiaskoenig/sbml2cellml/develop/docs/images/biomodels_dark.svg">
  <img alt="Curated models of BioModels which pass, fail and skip the stages of the roundtrip" src="https://raw.githubusercontent.com/matthiaskoenig/sbml2cellml/develop/docs/images/biomodels.svg">
</picture>

If you have any questions or issues please [open an issue](https://github.com/matthiaskoenig/sbml2cellml/issues).

# How to cite
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

# License
- Source Code: [MIT](https://opensource.org/license/MIT)
- Documentation: [CC BY-SA 4.0](http://creativecommons.org/licenses/by-sa/4.0/)

# Funding
Matthias König was supported by the Federal Ministry of Education and Research (BMBF, Germany) within the research network Systems Medicine of the Liver (LiSyM, grant number 031L0054) and within ATLAS by grant number 031L0304B, and by the German Research Foundation (DFG) within the Research Unit Program FOR 5151 QuaLiPerF (Quantifying Liver Perfusion-Function Relationship in Complex Resection - A Systems Medicine Approach) by grant number 436883643 and by grant number 465194077 (Priority Programme SPP 2311, Subproject SimLivA).

© 2025-2026 Matthias König
