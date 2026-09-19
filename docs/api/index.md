# API reference

The API reference is generated from the docstrings of the package.

| module | description |
| --- | --- |
| [sbml2cellml](sbml2cellml.md) | Conversion of SBML models to CellML, `convert_sbml2cellml` |
| [cellml2sbml](cellml2sbml.md) | Conversion of CellML models to SBML, `convert_cellml2sbml` |
| [cellml](cellml.md) | Reading, writing and validating CellML models with libcellml |
| [sbml](sbml.md) | Reading, writing and validating SBML documents with libsbml |
| [mathml](mathml.md) | MathML fragments of the equations |
| [sbmlmath](sbmlmath.md) | CellML maths (analyser AST, MathML) to libsbml ASTs |
| [units](units.md) | CellML units to SBML unit definitions |
| [cellmlunits](cellmlunits.md) | SBML units to CellML units, the units of the variables |
| [variables](variables.md) | SBML ids of the CellML variables |
| [simulate](simulate.md) | Timecourse simulation with libopencor (optional dependency) |
| [cli](cli.md) | The `sbml2cellml` and `cellml2sbml` commands |
| [console](console.md) | Shared rich console |
| [log](log.md) | Logging of the package |

## sbml2cellml.testsuite

The `sbml2cellml-testsuite` command runs the [SBML test suite](https://github.com/sbmlteam/sbml-test-suite) through both converters and both simulators, see [SBML test suite](../testsuite.md) and [Development](../development.md#sbml-test-suite).

| module | description |
| --- | --- |
| [testsuite.cases](testsuite.cases.md) | Downloading the suite, reading and filtering the semantic test cases |
| [testsuite.compare](testsuite.compare.md) | Comparison of a simulation with the expected results of a case |
| [testsuite.simulators](testsuite.simulators.md) | The roadrunner and libopencor simulator functions run inside a worker |
| [testsuite.worker](testsuite.worker.md) | Simulators in their own processes |
| [testsuite.runner](testsuite.runner.md) | The pipeline of the harness, five stages per case |
| [testsuite.results](testsuite.results.md) | Results of a suite run: per case and stage, JSON, regressions |
| [testsuite.report](testsuite.report.md) | Markdown report of a suite run, the page `docs/testsuite.md` |
| [testsuite.figure](testsuite.figure.md) | Bar diagram of a suite run, the figures `docs/images/testsuite*.svg` |
| [testsuite.cli](testsuite.cli.md) | The `sbml2cellml-testsuite` command |

## sbml2cellml.biomodels

The `sbml2cellml-biomodels` command runs the manually curated SBML models of [BioModels](https://www.biomodels.org) through the pipeline of the test suite, see [BioModels](../biomodels.md) and [Development](../development.md#biomodels).

| module | description |
| --- | --- |
| [biomodels.models](biomodels.models.md) | Access to the BioModels database: search, model info, download, selection |
| [biomodels.cases](biomodels.cases.md) | Case construction for a BioModels model |
| [biomodels.runner](biomodels.runner.md) | Runner producing the results from a BioModels selection |
| [biomodels.cli](biomodels.cli.md) | The `sbml2cellml-biomodels` command |
