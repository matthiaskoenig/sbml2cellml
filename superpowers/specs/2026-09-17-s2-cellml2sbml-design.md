# S2: CellML to SBML converter

Date: 2026-09-17
Status: approved design, implementation pending

## Context

S1 (`superpowers/specs/2026-09-16-s1-package-infrastructure-design.md`) made
`sbml2cellml` a package with the SBML to CellML direction. S2 adds the reverse
direction, `cellml2sbml`, which the S3 roundtrip harness needs and which makes
CellML models from the Physiome Model Repository usable with SBML tooling.

## Decisions

| Question | Decision |
|----------|----------|
| Model scope | Any import-free CellML 2.0 model: multiple components, connections, encapsulation. Imports are resolved with `libcellml.Importer` relative to the file and flattened. |
| Units | Converted. Standard CellML units map to SBML unit kinds by name; custom `Units` become `UnitDefinition`s expanded to base kinds. |
| SBML representation | Every variable is a `Parameter`; states get a `RateRule`, algebraic variables an `AssignmentRule`, computed constants an `InitialAssignment`; no compartments, species or reactions. |
| Resets | Converted to SBML `Event`s with an equality trigger, the literal CellML semantics. |
| Converter core | The libcellml `Analyser`: its per-equation AST (`AnalyserEquationAst`) is walked into `libsbml.ASTNode`s, its variable and equation types drive the SBML constructs, and it resolves equivalent variables across components. |
| CLI | Separate `cellml2sbml` entry point mirroring `sbml2cellml`. |
| Tests | libsbml consistency checks plus roadrunner simulations of the produced SBML (`libroadrunner` in the `dev` extra only). |

## Section 1: layout and API

New modules in `src/sbml2cellml/`:

- `cellml2sbml.py`: `convert_cellml2sbml(cellml_path: Path, sbml_path: Path | None = None, validate: bool = True) -> libsbml.SBMLDocument`.
  Reads the model (`cellml.read_model`), resolves and flattens imports when
  `model.hasImports()`, analyses it, builds the SBML L3V2 document from the
  analyser model and the resets, writes it when `sbml_path` is given, and
  validates it with libsbml when `validate` is set. `CellML2SBMLConversionError`
  is raised for a missing file, importer errors, analyser errors, a model type
  other than `ODE` or `ALGEBRAIC`, `NLA` or `EXTERNAL` equations, an
  equation whose left side is neither `ci x` nor `d x / d voi`, and a `ci` in
  a reset which does not resolve. `SBMLValidationError` (from `sbml.py`) is
  raised for consistency errors.
- `variables.py`: `VariableIds`, the SBML id of every CellML variable. Built
  from the analyser model: the variable of integration, the states and the
  other variables; every member of a variable's equivalence set (closure over
  `Variable.equivalentVariable`) maps to the same id. The id is the variable
  name when no other analyser variable has that name, else
  `<component>_<name>`; ids are sanitized to `[A-Za-z_][A-Za-z0-9_]*`.
  `id_for(variable)`, `is_voi(variable)`, `lookup(component_name, variable_name)`.
- `sbmlmath.py`: `ast_to_sbml(node: libcellml.AnalyserEquationAst, ids: VariableIds) -> libsbml.ASTNode`
  (table driven, see section 2), `mathml_to_sbml(mathml: str, component_name: str, ids: VariableIds) -> libsbml.ASTNode`
  for the reset maths (libsbml parses the MathML, `ci` names are remapped).
- `units.py`: `add_units(model_cellml: libcellml.Model, model_sbml: libsbml.Model) -> dict[str, str]`
  adds a `UnitDefinition` per custom `Units` and returns the SBML unit id for
  every CellML units name (standard units map to their own name).
- `sbml.py`: `read_document`, `write_document`, `document_to_string`,
  `validate_document(doc) -> list[str]` (messages of severity `ERROR` or
  `FATAL` after `checkConsistency`), `SBMLValidationError`.
- `cli.py`: `main_cellml2sbml(argv)` behind `[project.scripts] cellml2sbml`;
  `cellml2sbml INPUT.cellml [-o OUTPUT.xml] [--no-validate] [-v]`, default
  output next to the input with the `.xml` suffix, exit 1 with the message on
  stderr for a missing input, a conversion, validation or I/O error.
- `__init__.py` re-exports `convert_cellml2sbml`.

## Section 2: mapping

Document: `SBMLDocument(3, 2)`, model id = sanitized CellML model name,
`name` = the original name, `timeUnits` = SBML unit id of the variable of
integration when there is one. No compartment, no species.

Variables (analyser types):

| CellML | SBML |
|--------|------|
| `VARIABLE_OF_INTEGRATION` | no parameter; `ci` references become `csymbol time` |
| `CONSTANT` | `Parameter constant="true" value=<initial value>` |
| `COMPUTED_CONSTANT` (equation `TRUE_CONSTANT` or `VARIABLE_BASED_CONSTANT`) | `Parameter constant="true"` without value plus `InitialAssignment` |
| `ALGEBRAIC` (equation `ALGEBRAIC`) | `Parameter constant="false"` plus `AssignmentRule` |
| `STATE` (equation `ODE`) | `Parameter constant="false" value=<initial value>` plus `RateRule` |
| initial value given as a variable name | `Parameter` without value plus `InitialAssignment` `ci <that variable>` |

Every parameter carries `units` (section 1 mapping) and, when its id was
prefixed with the component, `name` = the CellML variable name.

Equations: the AST root is `EQUALITY`. An `ODE` equation has the left child
`DIFF(BVAR(CI voi), CI x)` and becomes a `RateRule` on `x`; the other
supported types have the left child `CI x` and become the rule or initial
assignment above. `NLA` and `EXTERNAL` equations and any other left side raise.

AST nodes (`AnalyserEquationAst.Type` to `libsbml` type):

- binary: `PLUS`, `MINUS` (unary when there is no right child), `TIMES`,
  `DIVIDE`, `POWER`, `EQ`, `NEQ`, `LT`, `LEQ`, `GT`, `GEQ`, `AND`, `OR`,
  `XOR`, `REM` (`rem`), `MIN` (`min`), `MAX` (`max`).
- `ROOT`: `DEGREE(CN d)` child then x gives `root(d, x)`; without degree
  `root(2, x)`. `LOG`: `LOGBASE(b)` then x gives `log(b, x)`; without logbase
  `log(10, x)`. `LN` unary.
- unary functions: `ABS`, `CEILING`, `FLOOR`, `EXP`, `NOT`, `SIN`, `COS`,
  `TAN`, `SEC`, `CSC`, `COT`, `SINH`, `COSH`, `TANH`, `SECH`, `CSCH`,
  `COTH`, `ASIN`, `ACOS`, `ATAN`, `ASEC`, `ACSC`, `ACOT`, `ASINH`, `ACOSH`,
  `ATANH`, `ASECH`, `ACSCH`, `ACOTH`.
- `PIECEWISE`: the analyser nests `PIECEWISE(PIECE, PIECEWISE(PIECE, OTHERWISE))`;
  flattened into one `piecewise(v1, c1, v2, c2, ..., otherwise)`. `PIECE` is
  `(value, condition)`, `OTHERWISE` is `(value)`.
- leaves: `CI` (variable id or `csymbol time`), `CN` (real value, units on
  numbers are not carried by the analyser AST and are dropped), `PI`, `E`,
  `INF`, `NAN`, `TRUE`, `FALSE`.
- `BVAR`, `DIFF`, `DEGREE`, `LOGBASE` outside the positions above raise.

Resets (`Component.reset(i)` of every component of the flattened model):
`Event id="reset_<n>"`, `useValuesFromTriggerTime="true"`, `Trigger
persistent="true" initialValue="true"` with math `eq(<test variable>, <test
value>)`, `Priority` `-<order>` (lowest CellML order fires first, SBML fires
the highest priority first), one `EventAssignment` on the reset variable with
the reset value. Test and reset maths: the MathML is read with
`libsbml.readMathMLFromString` after replacing `cellml:units` with
`sbml:units`; when the root is `eq` whose left child is the `ci` of the
test (reset) variable, the right child is the expression, else the whole
math is. `ci` names are resolved in the reset's component.

Known limitation, documented: a continuous simulator detects an equality
trigger only when the test variable crosses the test value at an integrator
step; roadrunner did not fire `m == 5` for a decaying `m` in the spike. S3
reports this per model.

Units: `libsbml.UnitKind_forName` accepts every CellML standard unit name
(`second`, `metre`, `kilogram`, `gram`, `mole`, `litre`, `dimensionless`,
`ampere`, `kelvin`, `candela`, `volt`, ...), so a standard unit is used by
name. A custom `Units` becomes a `UnitDefinition` with the same (sanitized)
id and one `Unit` per base kind: a `unit` referencing a standard unit gives
`Unit(kind, exponent, scale=prefix, multiplier)`; a `unit` referencing a
custom `Units` is expanded recursively, every resulting exponent multiplied
by the outer exponent, and the outer `multiplier * 10^prefix` folded into the
first resulting unit's multiplier as `(multiplier * 10^prefix)^(1/e_first)`
with `e_first` the first unit's exponent before the multiplication. SI prefix
names (`yotta` to `yocto`) and integer prefixes are accepted. A `Units` without
units is dimensionless.

## Section 3: tests

Fixtures: `examples/models/test_model.cellml`; models built with libcellml in
`tests/cellml_models.py` (multi-component with a connection, encapsulation,
an algebraic variable, computed constants, an initial value by reference,
custom units; the reset model of `references/cellml_reset_example.py`; an NLA
model; a model with every AST node type); `tests/data/import_parent.cellml`
and `tests/data/import_child.cellml`.

- `test_variables.py`: unique names keep their name, clashes get the
  component prefix, equivalent variables share one id, the VOI is recognised,
  names are sanitized.
- `test_sbmlmath.py`: every node type round-trips through
  `libsbml.formulaToL3String`; nested piecewise flattens; `root`/`log` with
  and without degree/base; unsupported node raises; `mathml_to_sbml` remaps
  `ci` and the VOI.
- `test_units.py`: standard units by name, prefixed unit, exponent,
  multiplier, custom referencing custom (with the folded factor), `gram`,
  empty units; the definitions validate with libsbml.
- `test_cellml2sbml.py`: test_model gives parameters `alpha` (constant) and
  `m` (state with `RateRule`), `timeUnits="second"`, no consistency errors;
  the multi-component model gives one parameter per equivalence set, the
  rules and initial assignments of section 2, units on every parameter; the
  reset model gives one `Event` with the trigger, priority and assignment;
  the NLA model raises naming the variables; the import fixture resolves and
  converts; a missing file raises; `validate=True` raises
  `SBMLValidationError` for a document made inconsistent on purpose
  (`validate_document` tested directly in `test_sbml.py`).
- `test_roundtrip.py` (skipped without `roadrunner`): `glimepiride_liver.xml`
  to CellML to SBML: the parameter ids equal the ids of the SBML species,
  compartments and parameters, the number of rate rules equals the number of
  species with reactions plus rate rules, and roadrunner simulations of the
  original and the roundtrip SBML agree within `rtol=1e-4` on 11 time points
  over 100 s. `test_model.cellml`: roadrunner on the SBML versus libopencor on
  the CellML agree the same way.
- `test_cli.py`: `cellml2sbml` tests mirroring the S1 ones.

`libroadrunner>=2.10.0` is added to the `dev` extra; the CI `test`, `ty` and
`docs` jobs get back the "Install the python dev files" step of sbmlsim on
linux, since the roadrunner extension links against libpython.

## Section 4: documentation, examples, branch

- `docs/conversion.md`: a "CellML to SBML" section with the API, the CLI,
  the mapping table of section 2 and the limitations; `docs/index.md`: both
  directions in the feature table; `docs/roadmap.md`: item 1 done, new
  limitations (NLA, external variables, units on numbers, equality triggers);
  `docs/api/`: pages for `cellml2sbml`, `variables`, `sbmlmath`, `units`,
  `sbml` and the nav; `CLAUDE.md`, `README.md`, `release-notes/0.1.0.md`
  updated.
- `examples/cellml2sbml_example.py`: converts `test_model.cellml` and the
  reset model into `examples/results/` and prints the SBML.
- Branch `s2-cellml2sbml` from `s1-infrastructure`; pull request into
  `develop` after PR #1 merges (rebased onto `develop` if PR #1 is squashed).

## Out of scope

- Species, compartments or reactions in the SBML output.
- Units on numbers (`cn`) in the SBML math.
- Implicit (`NLA`) equations and external variables.
- CellML 1.x models (the libcellml parser rejects them).
