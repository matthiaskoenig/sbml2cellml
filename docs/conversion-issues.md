# Conversion issues

The remaining issues of the conversion, i.e., what the current version does not convert or converts with a loss. The failure reasons of the [SBML test suite](testsuite.md#failure-reasons) measure them against the semantic test cases; what is converted is listed in [What is converted](index.md#what-is-converted) and [CellML to SBML](conversion.md#mapping).

## SBML to CellML

- **Units of an incomplete annotation.** The units of the variables are converted when every variable has units in the SBML model, see [Units](conversion.md#units); with a single compartment, species or parameter without units every variable stays `dimensionless`. A number without units in a formula is always `dimensionless`, CellML requires units on every number and SBML has none to give.
- **Unit warnings of libcellml.** The CellML specification applies the exponent of a unit to its prefix but not to its multiplier, which `libcellml.Units.scalingFactor` follows and the converter writes. The unit check of the libcellml 0.7.1 analyser applies the exponent to the multiplier as well, so it warns about equations with units such as `per_min` (`(60 second)^-1` in SBML, `1/60 second^-1` in CellML) which are consistent. The warnings do not make a model invalid.
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
- **New base units** (units without a unit) have no SBML counterpart and are `dimensionless` in SBML, with a warning; only new base units named `item` become the SBML unit kind.
- **Resets** trigger on the equality of the test variable and the test value; a continuous simulator may not fire this trigger, see the [limitations](conversion.md#limitations).
