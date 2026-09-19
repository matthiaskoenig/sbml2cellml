# BioModels check

`sbml2cellml.biomodels` runs the manually curated SBML models of [BioModels](https://www.biomodels.org) (about 1075) through the same pipeline as the SBML test suite, reusing `sbml2cellml.testsuite`. The results are the [BioModels](https://matthiaskoenig.github.io/sbml2cellml/biomodels/) page of the documentation.

| file | content |
| --- | --- |
| `biomodels/models.json` | the selection: date, search query and sorted ids, written by `update` |
| `biomodels/results.json` | the results of the last run, written by `run` |
| `docs/biomodels.md`, `docs/images/biomodels*.svg` | the report and its bar diagram, written by `run` and `report` |

The check is run locally and not in continuous integration, it downloads and simulates more than a thousand models (about 20 minutes with the models in the cache):

```bash
uv run sbml2cellml-biomodels run
tox r -e biomodels    # the same in the locked environment with python 3.14
```

How the check works and its options are described in [Development](https://matthiaskoenig.github.io/sbml2cellml/development/#biomodels).
