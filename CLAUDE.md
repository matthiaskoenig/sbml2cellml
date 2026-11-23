# CLAUDE.md

This file provides guidance when working with code in this repository.

## Project

`sbml2cellml` converts SBML models to CellML 2.0 and CellML models to SBML
L3V2 with libsbml and libcellml and simulates the result with libopencor.
Python 3.14 (`.python-version`), packaged with
hatchling (version in `src/sbml2cellml/__init__.py`). Runtime dependencies:
`python-libsbml`, `libcellml`, `rich`. The `simulate` extra adds `libopencor`
(CellML), `sbmlsim-core` (SBML), `pandas` and `matplotlib`; the `testsuite`
extra (in `dev`) adds `requests` for the download of the BioModels models,
the cases of the SBML test suite are fetched with `git`.

## Commands

```bash
uv sync --extra dev             # environment, includes libopencor
uv run pre-commit install

pytest                          # all tests (parallel, pytest-xdist)
pytest tests/test_sbml2cellml.py::test_simple_model_initial_values
tox r -e py3.14                 # tests from uv.lock via tox-uv
tox r -e ty                     # type check
tox run-parallel                # py3.14 and ty, run before opening a pull request

ruff check
ruff format
uvx ty check

uv run zensical build --clean --strict   # docs into site/
uv run python scripts/llms_txt.py
uv run zensical serve

sbml2cellml model.xml -o model.cellml
cellml2sbml model.cellml -o model.xml

uv run sbml2cellml-testsuite run        # full SBML test suite, writes testsuite/results.json, docs/testsuite.md and docs/images/testsuite*.svg
tox r -e testsuite                      # gating test against the committed results (SBML2CELLML_TESTSUITE=1), python 3.14 only, as in CI

# local only, not in CI (about 20 minutes, the models are cached in ~/.cache/sbml2cellml/biomodels)
tox r -e biomodels                      # the run below in the locked environment with python 3.14
uv run sbml2cellml-biomodels run        # curated BioModels selection, writes biomodels/results.json, docs/biomodels.md and docs/images/biomodels*.svg
uv run sbml2cellml-biomodels update     # refresh the committed selection biomodels/models.json
uv run sbml2cellml-biomodels report     # rerender docs/biomodels.md and the figures from the results file

# local only, not in CI (the workspaces are cloned into ~/.cache/sbml2cellml/physiome)
tox r -e physiome                       # the run below in the locked environment with python 3.14
uv run sbml2cellml-physiome run         # curated Physiome selection, writes physiome/results.json, docs/physiome.md and docs/images/physiome*.svg
uv run sbml2cellml-physiome update      # refresh the committed selection physiome/models.json
uv run sbml2cellml-physiome report      # rerender docs/physiome.md and the figures from the results file

uv run sbml2cellml-overview             # render docs/models.md, docs/benchmarks.md and docs/images/benchmarks*.svg from the three results files, rerun after any check
```

`develop` is the default branch and takes every change through a pull request; the rulesets in `.github/rulesets/` (applied with `apply.sh`) require the `tests`, `ruff`, `ty` and `docs` checks. Continuous integration is kept minimal: `tests` runs `py3.14` on linux, macos and windows, every workflow cancels a superseded run (`cancel-in-progress: true`), uv caches packages and interpreters, dependabot runs monthly. `main` tracks the latest release and is fast-forwarded by the `sync-main` job of the release workflow. Release steps are in `docs/development.md`: release branch, `uvx bump-my-version bump [major|minor|patch]` (updates `__init__.py` and `CITATION.cff`, no tag), release notes in `docs/release-notes/`, pull request, tag on `develop` after the merge.

## Architecture

- `sbml2cellml.py`: `convert_sbml2cellml(sbml_path, cellml_path=None, validate=True)`.
  A hierarchical model is flattened first (`sbml.flatten_comp`, with the
  directory of the file as the base path of an external model definition),
  so the submodels become part of the CellML model.
  One CellML component `sbml`, one variable per compartment, parameter and
  species plus `time`. `_variable_units` gives the variables their units when
  the unit annotation of the SBML model is complete (all or nothing: unset
  SBML units are unknown, not dimensionless), else all are `dimensionless`
  with a warning. The calls of function definitions
  are expanded first with libsbml's `expandFunctionDefinitions` conversion and
  the initial assignments evaluated to initial values with
  `expandInitialAssignments` (both skipped with a warning when a function is
  recursive, libsbml crashes on it when read from a file). libsbml leaves an
  initial assignment it evaluates to NaN: `_assign_nan` sets the variable to
  NaN when libsbml knows all of the formula (`_is_known`), so the NaN is its
  value and not the sign of a formula libsbml cannot evaluate; initial
  assignments without math are dropped before. libsbml evaluates
  formulas `_without_rate_rules` in the model (initial assignments, algebraic
  rules at the start): it takes the rate rule of a variable without a value
  yet for its value and crashes when the rate depends on the variable.
  Assignment rules
  become equations
  (their targets get no initial value), rate rules and kinetic laws
  differential equations; a concentration species
  gets its reaction terms divided by the compartment. A concentration
  species in a compartment which changes in time (`_changing`: the target of
  a rate or algebraic rule, or of an assignment rule which uses time or a
  changing variable; not an assignment rule of constants such as a volume
  from a body weight) and which no rule determines gets a second variable
  `<species>_amount` (`_amounts`, `unique_sid`) with the reaction terms and
  the initial amount, and the equation `species = amount / compartment`:
  SBML keeps the amount when the size changes. `rateOf` of such a species is
  `(dA/dt - S * rateOf(C)) / C` (`_Formulas.derivatives`). The initial size
  of a compartment an assignment rule sets is evaluated by libsbml
  (`_value_at_start`). The local parameters of
  a kinetic law become variables `<reaction>_<parameter>` (`unique_sid`).
  Kinetic laws are multiplied with the stoichiometry (no factor for 1) and do
  not change boundary species, the sum is multiplied with the conversion
  factor of the species or model; a
  species reference with an id is a variable of its stoichiometry, every
  reaction with a kinetic law a variable of its rate (`<reaction id> =
  kinetic law`), which the equations of its species use. A model without rate rules,
  reactions and uses of time gets no `time` variable (CellML knows the
  variable of integration only from a differential equation); `simulate`
  runs such an algebraic model as a steady state. A model whose formulas
  use time without a differential equation gets the state `time_state`
  (`_Formulas.time_state`) with `d time_state / d time = 1`, so time is the
  variable of integration. The variable of integration is `time` unless a
  compartment, species, parameter, reaction or species reference has that
  id (`_variable_ids`, `_Formulas.time_id`, the `time_id` of the mathml
  helpers). Events become resets (`_collect_events`, `_Event`,
  `_add_resets`): a variable `<event>_trigger` with the equation
  `piecewise(1, trigger, 0)` and one reset per event assignment, which
  fires when the trigger variable reaches 1 (an event with a delay is
  skipped with a warning; the assignment of a species with an `_amount`
  variable resets the amount). An unset initial value is the value a
  simulator of the SBML model takes (`_initial_value`): 0 for the initial
  amount of a species, 1 for a compartment size, a stoichiometry and a
  parameter. `_collect_formulas` gathers
  all formulas before the initial assignments are evaluated (they do not
  depend on initial values) and replaces `rateOf(x)` by the right-hand side
  of the equation of `x`, also in the initial assignments. An algebraic rule
  becomes `0 = formula`: `_match_algebraic_rules` finds the variable it
  determines, `_solve_algebraic_rules` solves it at the start (libsbml
  evaluates, secant method) for the solver guess and compartment sizes, and
  `_constants_of_algebraic_rules` turns the other initial values of the rule
  into equations, since libcellml takes any variable with an initial value in
  an implicit equation for its unknown. An infinite or NaN value of
  a variable which is not a state becomes an equation. Algebraic
  rules, unevaluated initial assignments and unset initial values are logged
  as warnings. The generated CellML is a fixed contract: tests compare the
  structure and the validity of the example models.
- `cellmlunits.py`: `CellMLUnits` converts every unit definition to CellML
  units (scale to prefix, a power of ten multiplier too, any other multiplier
  `m` to `m^exponent`: CellML applies the exponent to the prefix only; `item`
  as new base units, `avogadro` as dimensionless units) and finds the units of
  compartments, parameters, species (substance per size for a concentration,
  the identical unit definition of the model or new `a_per_b` units) and
  reaction rates (extent per time), with the built-in units of level 1 and 2.
- `mathml.py`: libsbml renders formulas as MathML documents; the helpers strip
  the declaration and `math` element, map `sbml:units` to `cellml:units` with
  the CellML name of the units (`units` callable),
  make every number a real with units (`dimensionless` when it has none),
  replace the time symbol by the variable of integration (`time_id`, `time`
  by default) and avogadro by its value (`normalize_math`), replace the
  operators CellML does not have (`simplify_operators`: an n-ary relation by
  the conjunction of its pairs, `quotient` by the floor of the division,
  `implies` by `not a or b`, an n-ary operator with less than two arguments
  by its value) and wrap the equations into the component math. The
  formulas are written as the SBML model has them, negations included:
  libcellml 0.7.2 generates `-(-2.0*a)` for `-((-2) * a)`, which compiles
  (0.7.1 generated `--2.0*a`, a decrement in C).
- `astnodes.py`: construction of formulas as libsbml ASTs (`name`, `number`,
  `apply`, `signed_sum`; `text` for logs only). The converter never turns a
  formula into text and back: the L3 parser reads an id such as `avogadro`,
  `pi`, `NaN` or `true` as the symbol of that name. The formulas of
  `_Formulas` are the ASTs of the model (copies), the mathml helpers take an
  AST (or text, for callers outside the converter).
- `metadata.py`: the names, notes, SBO terms, CV terms and history of the
  SBML elements as RDF/XML next to the CellML file (`<stem>.rdf`, subjects
  `<cellml file>#<id>`), since CellML 2.0 allows no metadata in the model.
  `Record` per element, `collect_metadata`/`write_metadata` for
  `sbml2cellml`, `read_metadata`/`apply_metadata` for `cellml2sbml`. The RDF
  is the dialect of SBML annotations: libsbml writes it from a scratch
  level 3 element (`_terms`, so level 2 models give the same RDF) and parses
  it back through `setAnnotation`; name `dcterms:title`, notes
  `dcterms:description` XML literal, SBO term the first `bq*:is` with a
  single SBO resource. `_set_ids` of `sbml2cellml.py` gives the model, the
  variables (`id` = name) and the units (`units_<name>`) their ids,
  `_metadata_elements` maps them to the SBML elements, `_write_metadata`
  removes the file of an earlier conversion when the model has no metadata.
  `cellml2sbml._add_metadata` applies a record to the parameter of the
  equivalence set of the variable, the unit definition or the model, with
  the CellML id as metaid.
- `cellml.py`: libcellml `Parser`, `Printer`, `Validator` and `Analyser`
  wrappers; issues are returned, `errors()` filters level `ERROR`,
  `CellMLValidationError`. `cellml_version` reads the CellML version from
  the namespace of a document (`None` for 2.0), `read_model(path,
  strict=True)` parses a 1.0 or 1.1 document with `strict=False`, the
  permissive mode which maps it to the CellML 2.0 structures.
- `simulate.py`: libopencor timecourse; the library is imported inside
  `run_timecourse` so the package works without it. The settings are applied
  to `document.simulations[0]`, with `MAXIMUM_NUMBER_OF_STEPS` (100000) internal
  solver steps between two time points instead of the 500 of libopencor.
  The absolute tolerance is scaled with the smallest initial value of a
  state as on the SBML side (`_state_scale`, `scale_tolerance`): libopencor
  fills the arrays of the states only when it runs, so a model whose states
  are small is run once with the given tolerance and again with the scaled
  one, and the first run counts as setup. `timings` takes the wall time of
  `setup` and `simulate`. A result column is the name of the variable
  without the `component/` prefix of libopencor, or the full name when more
  than one variable of the model has that name (`_result_names`), so a model
  of many components keeps its variables apart. Issues raise
  `SimulationError`.
- `sbmlsim.py`: sbmlsim-core timecourse of an SBML model (path or text), the
  library is imported inside `run_timecourse` as well. `compilable_sbml`
  gives the compiler what it reads: level 1 and 2 are converted to L3V2
  (strictly, else without the strict check and with a warning: libsbml
  refuses a strict conversion over issues without mathematics, e.g. the
  `outside` attribute of level 2) and a model which requires `comp` is
  flattened with libsbml. `load_model` converts, compiles (`optimize=True`,
  the results are the same and the module is smaller) and loads a model and
  keeps it by the hash of its text (`MODEL_CACHE_SIZE`), so the same model
  is neither converted nor compiled twice in a process, as libopencor
  caches a CellML file; an instance is per simulation. Every field of a
  request of `simulation/1` is explicit (`solver_settings`), the `Runtime`
  is created once per process (`runtime`; the engine is WebAssembly which
  Wasmtime compiles to native code, cached in `~/.cache/wasmtime`), `[S1]`
  selects a concentration. The states of the solver are amounts, so
  `run_timecourse` multiplies the absolute tolerance with the smallest
  initial value of a state when it is below one (`state_scale` over the
  states of the compiled description and the initial values of the loaded
  model, as roadrunner does): the amounts of a model with a small
  compartment are below the tolerance otherwise and CVODE accepts any
  trajectory (`scale_tolerance=False` switches it off). `timings` takes the
  wall time of the phases, `setup` (conversion, compilation, loading,
  nothing of it for a cached model) and `simulate`.
- `cellml2sbml.py`: `convert_cellml2sbml(cellml_path, sbml_path=None,
  validate=True, metadata=True, hierarchical=False)`,
  analyser driven: parameters by variable type, rules by equation type, initial
  assignments for computed constants and variable-referenced initial values,
  implicit (NLA) equations as algebraic rules,
  resets as events with `eq` trigger and `-order` priority, imports flattened
  with `Importer`. A reset whose test variable is
  `piecewise(1, condition, 0)` and whose test value is 1, as `sbml2cellml`
  writes an event, gives the event the condition as its trigger
  (`_condition_of_a_trigger`): a simulator evaluates it as a boolean
  instead of looking for the root of a step. `read_cellml_model` reads a
  file of any CellML version (1.0 and 1.1 in the permissive mode of
  libcellml, `cellml.cellml_version`) and flattens its imports,
  `analyse_model` analyses it; both are also used by the Physiome check.
  `hierarchical=True` (`--hierarchical`) writes the components as SBML comp
  submodels instead of one flat model (`build_hierarchical_document`): one
  `modelDefinition` per component (id `<component>_component`, the
  parameters named by `variables.ComponentIds`), an encapsulated component
  a submodel of its parent, every equivalence set of more than one variable
  a parameter of the main model with a `ReplacedElement` per member
  (`_replacement_path` nests the `SBaseRef` chain along the encapsulation).
  The flattened hierarchical model is the flat conversion of the same
  model, which `tests/test_hierarchical.py` asserts.
- `variables.py`: `VariableIds` gives one SBML id per equivalence set, a
  component prefix on name clashes; `ComponentIds` one namespace per
  component for the hierarchical conversion, `components(parent)` iterates
  the components of a model recursively; `unique_sid` adds a numeric suffix for
  colliding ids (parameters, unit definitions, the model id and event ids);
  `VariableIds.reserve` reserves an id outside the variables (model, events).
- `sbmlmath.py`: analyser AST to libsbml AST, nested piecewise flattened,
  `mathml_to_sbml` for reset maths. The analyser AST has no units of numbers:
  `NumberUnits` reads them from the MathML of the components and finds the
  equation of an AST by its variables and numbers (in order, else by value).
- `units.py`: CellML to SBML: standard units by name, custom units expanded to
  base kinds (prefix to scale, multiplier `m` to `m^(1/exponent)`), the factor
  of a reference to custom units folded into the first unit, new base units
  `item` as the unit kind.
- `sbml.py`: libsbml helpers, `validate_document` returns error messages, unit
  problems are warnings. `flatten_comp` flattens the submodels of a
  hierarchical model with `CompFlatteningConverter` (`basePath` for an
  external model definition) and returns the document written and read
  again, since an element taken from an external model definition keeps a
  pointer into the document which was freed (libsbml segfaults in
  `setModelHistory` otherwise); `None` when the document does not use
  `comp`.
- `cli.py`: argparse, `[project.scripts]` entry point.
- `console.py`, `log.py`: rich console for scripts and the CLI, opt-in rich
  logging. Library code logs with `logging.getLogger(__name__)` and lazy `%s`
  formatting (ruff `G`), it never prints.
- `testsuite/`: `sbml2cellml-testsuite run|report` runs the SBML test suite
  through both converters and both simulators. `cases.py` fetches
  `cases/semantic` of the pinned `SUITE_COMMIT` of the suite repository into
  the cache (partial, one commit deep `git` clone, `_git`) and reads
  the cases (`PACKAGE_PREFIXES` skips a case which needs a package the
  converters do not support; `comp` is not among them, its submodels are
  flattened); `compare.py` checks a simulation against the expected results
  (`|value - expected| <= absolute + relative * |expected|` with the
  tolerances of the settings of the case, not the tolerances of the solver);
  `runner.py`'s `SOLVER_SETTINGS` are the solver settings of every
  simulation (tolerances 1e-9/1e-12, 100000 internal steps between two time
  points; relaxed tolerances only when CVODE fails, `_simulate`);
  `simulators.py` has the sbmlsim-core and libopencor functions run
  inside `worker.py`'s `SimulatorWorker` processes (one process per
  simulator for the whole run, for the timeout and the isolation of a
  crash); `runner.py` is the five-stage pipeline
  (`sbmlsim`/`sbml2cellml`/`libopencor`/`cellml2sbml`/`roundtrip`) per
  case, a failed stage keeps the complete text of its exception
  (`error_message`)
  and the wall time of its simulation (`StageResult.seconds`, measured in
  the worker around the call of the simulator, the compilation of the model
  included); `results.py` is `SuiteResult` (JSON) with `regressions`/
  `improvements` and `seconds` per stage (the integration, and the setup of
  the simulator with `setup=True`) and the stages of the run
  (`SuiteResult.stages`, `STAGES` for an SBML first run and `CELLML_STAGES`
  for the Physiome check, `cellml_first`/`comparison_stage`); `report.py` renders
  `docs/testsuite.md` (the solver
  settings of the intro come from `SOLVER_SETTINGS`, `timing_lines` is the
  timing section of the two simulators, the failing cases are
  grouped by `_reason` and listed with their complete errors in fenced
  blocks, nothing is shortened or replaced); `figure.py` its
  bar diagram `docs/images/testsuite.svg` and `testsuite_dark.svg` (also in
  `README.md`) and the timings `testsuite_timings.svg` and
  `testsuite_timings_dark.svg` (libopencor against sbmlsim-core per case on
  logarithmic axes); `cli.py` is the
  `sbml2cellml-testsuite` entry point.
- `biomodels/` (run locally, never in CI; see `biomodels/README.md`):
  `sbml2cellml-biomodels run|update|report` runs the manually
  curated SBML models of BioModels through the same pipeline. `models.py`
  queries and downloads the models through the BioModels REST API, cached on
  disk, and reads/writes the selection `biomodels/models.json`; `cases.py`
  builds a case for a downloaded model with the generic timecourse (0 to 100
  time units, 100 steps; comparison tolerances `RELATIVE` 1e-3 and `ABSOLUTE`
  1e-6); `runner.py` turns a list of ids into cases (skipping
  a failed download or a model without variables) and calls
  `sbml2cellml.testsuite.runner.run_suite`, whose `sbmlsim` stage uses the
  sbmlsim-core simulation of the original model as the expected results since
  BioModels has none; `cli.py` is the `sbml2cellml-biomodels` entry point,
  which renders the report `docs/biomodels.md` with the report and figure
  code of the test suite.
- `physiome/` (run locally, never in CI; see `physiome/README.md`):
  `sbml2cellml-physiome run|update|report` runs curated CellML models of the
  Physiome Model Repository through the same stages in the order of a CellML
  model (`CELLML_STAGES`:
  `libopencor`/`cellml2sbml`/`sbmlsim`/`sbml2cellml`/`roundtrip`), the
  libopencor simulation of the published model as the expected results.
  `models.py` reads the exposures through the webservice of the repository
  (`Accept: application/vnd.physiome.pmr2.json.1`), which gives the title,
  the commit and the CellML file of an exposure, clones the workspace of an
  exposure at that commit into the cache (the repository refuses a shallow
  fetch, so `git init`/`fetch`/`checkout` of the whole workspace, which also
  gives a model the files it imports; `remove_tree` makes a read-only file
  writable before it removes it, since git marks its objects read-only and
  windows refuses to unlink them) and reads/writes the selection
  `physiome/models.json` (one exposure per workspace, the first 100 by id);
  `cases.py` builds the case with the generic timecourse (0 to 100 time
  units, 1000 steps: the models are stiff and switch their right-hand side
  hard, where the two solvers step over the switch differently on a coarse
  output grid; tolerances `RELATIVE` 1e-3 and `ABSOLUTE` 1e-6) and the
  map `PhysiomeCase.columns` from the names of the libopencor result
  (`component/variable` and, for a name no other variable of the model has,
  the name alone, as `simulate._result_names` writes them; the variable of
  integration maps to `time`) to the SBML ids of `VariableIds`, so both
  sides of a comparison hold the same columns; `runner.py` is the pipeline
  (`prepare_cases` skips a model which cannot be cloned, read or analysed
  with the kind of its problem, `skip_reason`/`SKIP_REASONS`, and logs the
  complete error, since the report groups the skipped models by reason;
  `run_case` compares the SBML side against the renamed libopencor result);
  `cli.py` is the `sbml2cellml-physiome` entry point, which renders
  `docs/physiome.md` with the report and figure code of the test suite.
- `overview/` (no simulation, rendered from the committed results of the
  three checks): `sbml2cellml-overview` writes the two pages across them.
  `checks.py` holds the `Check` of every check (its title, its page, its
  results file, what a case of it is and the url of a model), `load_runs`
  reads the results files (a missing one is logged and left out) and
  `works` whether every stage of a case passes; `ROLES` names what the
  stages do, which is the same for a check whose source is the SBML model
  and one whose source is the CellML model. `figure.py` renders the
  integration time of libopencor against the one of sbmlsim-core over every
  check (one color and one marker per check) and the median setup and
  integration time per check; `report.py` renders `docs/benchmarks.md` (the
  wall times, from `timing_pairs` and `setup_pairs` of the test suite
  figures) and `docs/models.md` (every model of BioModels and of the
  Physiome Model Repository with the status of its stages and whether it
  works, and the models which do not run with their reason); `cli.py` is
  the `sbml2cellml-overview` entry point. `tests/test_overview.py` renders
  both pages from the committed results files and fails when they differ
  from the committed pages, so a check which ran without the overview being
  rerun is caught by the unit tests.

## Conventions

- ty with `error-on-warning = true`: zero diagnostics, rule specific
  `# ty: ignore[rule-name]` only.
- Full type annotations and google-style docstrings on every module, class and
  function (ruff `D`; `examples/` and `tests/` exempt).
- `examples/` at the top level holds the runnable examples and
  `examples/models/` the glimepiride SBML models, `repressilator.xml`
  (BIOMD0000000012) and `test_model.cellml`; the
  tests read the models via `MODELS_DIR` in `tests/conftest.py`.
  `examples/repressilator_example.py --docs` writes the models, the table and
  the figures of the documentation page `docs/roundtrip.md`
  (`docs/roundtrip/`, `docs/images/repressilator*.svg`, included with
  `pymdownx.snippets`); `tests/test_examples.py` fails when
  the documented models differ from the ones the example writes. Generated
  CellML goes to the gitignored `examples/results/`. Small fixtures created
  for a test go to `tests/data/`.
- Known conversion issues are documented in `docs/conversion-issues.md` and encoded in the
  tests (`delay_model` in `tests/test_sbml2cellml.py`, the kidney model in
  `tests/test_simulate.py`); fixing a gap means removing its test, not
  weakening the assertion.
- No em dash in any text, use `-`.
- Release notes go in `docs/release-notes/x.y.z.md` as part of a release
  commit, the logo below the heading, with an entry in the nav of
  `zensical.toml` and in the overview `docs/release-notes/index.md`
  (`tests/test_package.py` checks all three); the release workflow uses the
  file as body of the GitHub release.
- The logo is `docs/images/sbml2cellml-logo.png`, referenced by its absolute
  URL on `develop` in the README and the release notes; the favicon set
  (`favicon.svg`, also the header logo, `favicon.ico`, `apple-touch-icon.png`)
  is in `docs/images/favicon/`, linked in `overrides/main.html`.
- `references/` holds the CellML specification and libopencor notes, it is not
  part of the documentation site.
- Test models built with libcellml live in `tests/cellml_models.py`;
  `tests/data/` holds the import fixtures.
- the roundtrip tests simulate the SBML side with sbmlsim-core
  (`tests/simulators.py`) and the CellML side with libopencor, both in the
  process of the test.
- `testsuite/results.json`, `docs/testsuite.md` and `docs/images/testsuite*.svg`
  (the bar diagram and the timings) are generated by `sbml2cellml-testsuite
  run` (or `report`) and committed;
  the full-suite test (`tests/test_testsuite_full.py`) fails on regressions
  against them; accept improvements by regenerating them.
- `biomodels/models.json`, `biomodels/results.json`, `docs/biomodels.md` and
  `docs/images/biomodels*.svg` are generated (`update` and `run`) and
  committed. The check runs locally only, there is no workflow and no gating
  test for it: rerun it after converter changes, review the regressions it
  prints and commit the regenerated files. The same holds for
  `physiome/models.json`, `physiome/results.json`, `docs/physiome.md` and
  `docs/images/physiome*.svg`.
- `docs/models.md`, `docs/benchmarks.md` and `docs/images/benchmarks*.svg`
  are rendered from the three results files by `sbml2cellml-overview` and
  committed; rerun the command whenever a check wrote new results, the unit
  tests fail while they are stale.
