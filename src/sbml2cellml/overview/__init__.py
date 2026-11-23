"""The pages which compare the checks of the repository with each other.

`sbml2cellml.testsuite`, `sbml2cellml.biomodels` and `sbml2cellml.physiome`
each write the report of their own run. This package reads their committed
results and renders the two pages across them: `docs/benchmarks.md`, the
wall times of libopencor and sbmlsim-core, and `docs/models.md`, which
models of the three checks work.
"""
