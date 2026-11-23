# Physiome check

`sbml2cellml.physiome` runs curated CellML models of the [Physiome Model Repository](https://models.physiomeproject.org) through the pipeline of the SBML test suite, reusing `sbml2cellml.testsuite`, in the order of a CellML model: libopencor simulates the published model, `cellml2sbml` converts it to SBML, sbmlsim-core simulates that, `sbml2cellml` converts it back and libopencor simulates the roundtrip. The results are the [Physiome](https://matthiaskoenig.github.io/sbml2cellml/physiome/) page of the documentation.

The models are real world models of many components, most of them CellML 1.0 and 1.1 documents which libcellml reads in its permissive mode, so the check measures the converters on the models the repository publishes.

| file | content |
| --- | --- |
| `physiome/models.json` | the selection: date, repository and the exposures (id, title, workspace, commit, file), written by `update` |
| `physiome/results.json` | the results of the last run, written by `run` |
| `docs/physiome.md`, `docs/images/physiome*.svg` | the report and its figures, written by `run` and `report` |

The check is run locally and not in continuous integration, it clones the workspace of every model and simulates each of them three times:

```bash
uv run sbml2cellml-physiome run
tox r -e physiome     # the same in the locked environment with python 3.14
```

After a run, `uv run sbml2cellml-overview` rerenders the two pages across the checks (`docs/models.md` and `docs/benchmarks.md`) from the results files; the unit tests fail while they are stale.

How the check works and its options are described in [Development](https://matthiaskoenig.github.io/sbml2cellml/development/#physiome).
