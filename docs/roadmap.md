# Roadmap

`sbml2cellml` is developed in steps; this page lists what the current version does not do and what is planned.

## Conversion gaps

- **Units.** Every variable is `dimensionless` and the SBML unit definitions are not converted. Numbers with units in formulas (`cn` elements with `cellml:units`) reference units which do not exist in the CellML model, which libcellml reports as errors. The `time` variable has no unit either.
- **Initial assignments** are skipped with a warning. The initial value would have to be computed from the assignment, e.g., with libroadrunner.
- **Function definitions** are not inlined, so a formula calling a function references an unknown name.
- **Events** are skipped with a warning. CellML 2.0 has no events; a subset could be expressed with resets.
- **Algebraic rules** are skipped with a warning.
- **Stoichiometry** of reactants and products is not applied to the kinetic law.
- **Unset initial values** are set to `1.0` with a warning instead of being computed from the rules.

## Planned

1. **CellML to SBML** converter, so that models can go both ways.
2. **SBML test suite roundtrip.** Every semantic test case is simulated with libroadrunner, converted to CellML, simulated with libopencor, converted back to SBML and simulated again; the results are compared with the expected results of the test suite. The status of every case is published on this site; the check gates on regressions against a committed expected-status list until every case passes.
3. **BioModels check** of the curated models before every release.
4. The conversion gaps above, driven by the failures of the test suite.
