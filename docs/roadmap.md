# Roadmap

`sbml2cellml` is developed in steps; this page lists what the current version does not do and what is planned.

## Conversion gaps

### SBML to CellML

- **Units.** Every variable is `dimensionless` and the SBML unit definitions are not converted. Numbers with units in formulas (`cn` elements with `cellml:units`) reference units which do not exist in the CellML model, which libcellml reports as errors. The `time` variable has no unit either.
- **Initial assignments** are skipped with a warning. The initial value would have to be computed from the assignment, e.g., with libroadrunner.
- **Function definitions** are not inlined, so a formula calling a function references an unknown name.
- **Events** are skipped with a warning. CellML 2.0 has no events; a subset could be expressed with resets.
- **Algebraic rules** are skipped with a warning.
- **Stoichiometry** of reactants and products is not applied to the kinetic law.
- **Unset initial values** are set to `1.0` with a warning instead of being computed from the rules.
- **Assignment rule targets** keep an `initial_value`: the value of the SBML element or, when it has none, the `1.0` of the previous item. A variable with an initial value and an equation is not what CellML expects, the libcellml analyser reports the variables of the rule as underconstrained and the validation rejects the model (e.g., the glimepiride kidney model and the `... is underconstrained` failures of the [SBML test suite](testsuite.md#sbml2cellml)).

### CellML to SBML

- **NLA equations and external variables** are not supported and raise `CellML2SBMLConversionError`.
- **Units on numbers** in formulas are not carried into the SBML math.
- **Resets** trigger on the equality of the test variable and the test value; a continuous simulator may not fire this trigger, see the [limitations](conversion.md#limitations).

The failure reasons of the [SBML test suite report](testsuite.md#failure-reasons) are the work list for closing these gaps.

## Planned

1. **CellML to SBML** converter: done, see [Conversion](conversion.md#cellml-to-sbml).
2. **SBML test suite roundtrip**: done, see [SBML test suite](testsuite.md).
3. **BioModels check** of the curated models before every release: done, see [BioModels](biomodels.md).
4. The conversion gaps above, driven by the failures of the test suite.
