# BioModels check

Parked: the check is kept but not run, and it is not part of the documentation
site. The SBML test suite comes first; the check comes back once the
conversion covers more of the suite.

`sbml2cellml.biomodels` runs the manually curated SBML models of [BioModels](https://www.biomodels.org) (about 1075) through the same pipeline as the SBML test suite, reusing `sbml2cellml.testsuite`. These models have no expected results, so the `reference` stage simulates the original SBML with roadrunner over a generic timecourse (0 to 100 time units, 100 steps) and its frame becomes the expected results the `libopencor` and `roundtrip` simulations are compared with, using the same tolerances as the test suite (`1e-3` relative, `1e-6` absolute). A `reference` failure means roadrunner cannot simulate the model, it says nothing about the converters; models with an SBML package or without a variable (no species and no rate-rule or assignment-rule target of its own) are skipped.

```bash
uv run sbml2cellml-biomodels run
```

downloads every model into `~/.cache/sbml2cellml/biomodels` on first use (cached for later runs), runs the pipeline and writes `biomodels/results.json` and `biomodels/report.md`. `--ids BIOMD0000000001,BIOMD0000000012` and `--count N` restrict the run to a subset or the first N ids of the selection, for a quick local check. `uv run sbml2cellml-biomodels report` rerenders the report from a results file.

`uv run sbml2cellml-biomodels update` refreshes the committed selection `biomodels/models.json` (the date, the search query and the sorted ids) from the current BioModels search; it is run occasionally, not on every check.

The `biomodels` workflow (`workflow_dispatch`, Actions tab, "biomodels", "Run workflow") runs the check on GitHub Actions and opens a pull request with the regenerated `biomodels/results.json` and `biomodels/report.md` against `develop`.

The pull request opened with the default token does not trigger the required checks: GitHub does not run workflows for a pull request created by `GITHUB_TOKEN`. Either close and reopen the pull request to start them, or store a fine-grained personal access token with `contents` and `pull-requests` write permission on the repository as the `BIOMODELS_TOKEN` secret, which the workflow prefers over the default token when it is set. Either way, the repository setting "Allow GitHub Actions to create and approve pull requests" (Settings, Actions, General) must be enabled.

The committed `results.json` and `report.md` are from the last run with libcellml 0.6.3 (2026-09-18).
