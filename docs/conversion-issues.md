# Conversion issues

The remaining issues of the conversion, i.e., what the current version does not convert or converts with a loss. The failure reasons of the [SBML test suite](testsuite.md#failure-reasons) measure them against the semantic test cases; what is converted is listed in [What is converted](index.md#what-is-converted) and [CellML to SBML](conversion.md#mapping).

## SBML to CellML

- **Units.** Every variable is `dimensionless` and the SBML unit definitions are not converted. A number without units in a formula is `dimensionless` too, but a number with the units of an SBML unit definition (e.g., `2 mM`) references units which do not exist in the CellML model, which libcellml reports as an error. The `time` variable has no unit either.
- **Initial assignments** are evaluated to initial values (libsbml's `expandInitialAssignments`), so the CellML model has the value but not the formula; libsbml does not evaluate an assignment to NaN, which stays unconverted with a warning.
- **An infinite or NaN initial value of a state** cannot be expressed: CellML initial values are real numbers (a constant gets the equation `x = INF` instead).
- **Events** are skipped with a warning. CellML 2.0 has no events; a subset could be expressed with resets.
- **Coupled algebraic rules**, which determine their variables only together (`x + y = 4`, `x - y = 2`), cannot be analysed by libcellml; an algebraic rule which determines no variable is skipped with a warning.
- **stoichiometryMath** of level 2 species references is not converted, the stoichiometry attribute is used.
- **N-ary relations** such as `a > b > c` are not split into binary ones; CellML only has binary relations.
- **Time without differential equations.** CellML knows the variable of integration only from a differential equation: a model without one has no `time` variable, and a formula using time in such a model cannot be converted.
- **An SBML id `time`** collides with the variable of integration `time` of the CellML model and with the time column of the simulation results.
- **The delay symbol** is not converted, CellML has no delays.
- **rateOf** of a variable whose rate depends on itself, or which an assignment rule sets, is not converted; in an initial assignment neither when the rate has a local parameter.
- **Unset initial values** of variables which no assignment rule or initial assignment sets are `1.0`, with a warning.

## CellML to SBML

- **External variables** are not supported and raise `CellML2SBMLConversionError`; a system of coupled implicit equations cannot be analysed by libcellml.
- **Units on numbers** in formulas are not carried into the SBML math.
- **Resets** trigger on the equality of the test variable and the test value; a continuous simulator may not fire this trigger, see the [limitations](conversion.md#limitations).
