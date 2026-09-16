# S1: package and infrastructure baseline - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the migrated `sbml2cellml` scripts into a releasable python package with tests, CI, documentation and the conventions of `pymetadata` and `sbmlsim`, without changing the CellML the converter generates.

**Architecture:** A `src` layout package `sbml2cellml` with one module per concern (`sbml2cellml.py` converter, `cellml.py` libcellml helpers, `mathml.py` MathML helpers, `simulate.py` libopencor timecourse, `cli.py`, `console.py`, `log.py`). Examples and the example models live at the top level outside the package; tests read the models from `examples/models/`. Packaging with hatchling and uv, checks with ruff, ty, pytest and tox, documentation with zensical, GitHub Actions for tests, lint, types, docs and the PyPI release.

**Tech Stack:** python 3.13, hatchling, uv, tox-uv, ruff, ty, pytest, pytest-xdist, python-libsbml, libcellml, libopencor (wheel from GitHub releases), pandas, matplotlib, zensical, mkdocstrings.

**Spec:** `docs/superpowers/specs/2026-09-16-s1-package-infrastructure-design.md`

## Global Constraints

- `requires-python = ">=3.13"`; `.python-version` is `3.13`; ruff `target-version = "py313"`.
- Runtime dependencies are exactly `python-libsbml>=5.21.1`, `libcellml>=0.6.3`, `rich>=15.0.0` (numpy is not needed, `math.isnan` does the NaN check).
- `libopencor==1.20260803.0` comes only from the uv flat index `https://github.com/opencor/libopencor/releases/expanded_assets/v1.20260803.0` (verified to resolve with `uv pip install --find-links`). It is never a runtime or `simulate` dependency.
- Library modules log with `logging.getLogger(__name__)` and lazy `%s` formatting; they never print. `console.py` and the CLI are the only places that print.
- Every module, class and function has full type annotations and a google-style docstring (ruff `D` rules, `examples/**` and `tests/**` exempt from `D`).
- ty runs with `error-on-warning = true`; suppress an unavoidable diagnostic with `# ty: ignore[rule-name]`, never a blanket comment.
- The generated CellML must not change: same component name `sbml`, same variables, same MathML, same `dimensionless` units.
- No em dash anywhere (use `-`). Commit messages carry no co-author line other than the one the session reminder prescribes.
- Run every check with `uv run <command>` (the `.venv` of the repository) unless stated otherwise.
- Work happens on the branch `s1-infrastructure`, which already exists and holds the spec. Commit after every task.

---

## File map

| Path | Responsibility | Task |
| --- | --- | --- |
| `pyproject.toml`, `.ruff.toml`, `tox.ini`, `.pre-commit-config.yaml`, `.bumpversion.toml`, `.gitignore`, `.python-version`, `uv.lock` | packaging, tooling | 1 |
| `src/sbml2cellml/__init__.py` | version, package logger, re-export | 1, 4 |
| `src/sbml2cellml/console.py`, `src/sbml2cellml/log.py` | rich console, opt-in rich logging | 1 |
| `examples/models/*.xml`, `examples/models/test_model.cellml` | example and test models (moved from `models/`) | 1 |
| `references/` | CellML specification pdf, libopencor notebook, reset example (moved from `docs/specifications/`) | 1 |
| `tests/conftest.py` | `MODELS_DIR`, `TEST_MODEL_PATH`, `GLIMEPIRIDE_MODELS` | 1 |
| `src/sbml2cellml/mathml.py`, `tests/test_mathml.py` | MathML helpers | 2 |
| `src/sbml2cellml/cellml.py`, `tests/test_cellml.py` | libcellml read, write, validate | 3 |
| `src/sbml2cellml/sbml2cellml.py`, `tests/test_sbml2cellml.py` | converter | 4 |
| `src/sbml2cellml/simulate.py`, `tests/test_simulate.py` | libopencor timecourse and plot | 5 |
| `src/sbml2cellml/cli.py`, `tests/test_cli.py` | command line | 6 |
| `examples/cellml_example.py`, `examples/glimepiride_example.py`, `tests/test_examples.py` | runnable examples | 7 |
| `.github/workflows/*.yml`, `.github/rulesets/*`, `.github/CODEOWNERS`, `.github/dependabot.yml`, `.github/pull_request_template.md` | CI and repository policy | 8 |
| `zensical.toml`, `docs/*.md`, `docs/api/*.md`, `docs/robots.txt`, `scripts/llms_txt.py` | documentation site | 9 |
| `README.md`, `CITATION.cff`, `.zenodo.json`, `LICENSE`, `release-notes/0.1.0.md`, `CLAUDE.md` | metadata and agent guidance | 10 |
| repository settings (`develop` branch, rulesets, Pages), pull request | one-time setup | 11 |

---

### Task 1: Repository layout, packaging and tooling

**Files:**
- Create: `pyproject.toml` (replace), `.ruff.toml` (replace), `tox.ini`, `.pre-commit-config.yaml`, `.bumpversion.toml`, `.gitignore` (replace), `uv.lock`
- Create: `src/sbml2cellml/__init__.py` (replace), `src/sbml2cellml/console.py` (replace), `src/sbml2cellml/log.py`
- Create: `tests/__init__.py` (empty), `tests/conftest.py`, `tests/test_package.py`
- Move: `models/` to `examples/models/`; `docs/specifications/` to `references/`
- Delete: `src/__init__.py`, `src/sbml2cellml/cellml2sbml.py`, `src/sbml2cellml/examples/`, `src/sbml2cellml/simulator/`

The old modules are deleted here and rewritten in tasks 2 to 5 from the code in this plan; the old code stays in git history (`git show 616665e:src/sbml2cellml/cellml2sbml.py`) for reference.

**Interfaces:**
- Produces: `sbml2cellml.__version__ == "0.1.0"`, `sbml2cellml.log.enable_rich_logging(level, console) -> logging.Logger`, `sbml2cellml.console.console`, `tests.conftest.MODELS_DIR: Path`, `tests.conftest.TEST_MODEL_PATH: Path`, `tests.conftest.GLIMEPIRIDE_MODELS: list[str]`.

- [ ] **Step 1: Move and delete files**

```bash
cd /home/mkoenig/git/sbml2cellml
git mv models examples/models 2>/dev/null || (mkdir -p examples && git mv models examples/models)
mkdir -p references
git mv docs/specifications/cellml_2_0_1_normative_specification.pdf references/
git mv docs/specifications/libopencor.ipynb references/
git mv docs/specifications/cellml_reset_example.py references/
git rm -q src/__init__.py src/sbml2cellml/cellml2sbml.py
git rm -q -r src/sbml2cellml/examples src/sbml2cellml/simulator
ls examples/models references src/sbml2cellml
```

Expected: `examples/models` holds the five `glimepiride_*.xml` files, `glimepiride_*.cellml` files and `test_model.cellml`; `src/sbml2cellml` holds only `__init__.py` and `console.py`. Remove the converted glimepiride files, they are generated:

```bash
git rm -q examples/models/glimepiride_*.cellml
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "sbml2cellml"
dynamic = ["version"]
description = "sbml2cellml converts SBML models to CellML."
readme = "README.md"
requires-python = ">=3.13"
license = "MIT"
license-files = ["LICENSE"]
authors = [
	{name="Matthias König", email="konigmatt@googlemail.com"},
]
maintainers = [
	{name="Matthias König", email="konigmatt@googlemail.com"},
]
classifiers = [
	"Development Status :: 3 - Alpha",
	"Intended Audience :: Science/Research",
	"Operating System :: OS Independent",
	"Programming Language :: Python :: 3.13",
	"Programming Language :: Python :: Implementation :: CPython",
	"Topic :: Scientific/Engineering",
	"Topic :: Scientific/Engineering :: Bio-Informatics",
]
keywords = [
	"modeling",
	"standardization",
	"COMBINE",
	"SBML",
	"CellML",
	"converter",
]
dependencies = [
	# SBML reading and formula parsing
	"python-libsbml>=5.21.1",
	# CellML model building, printing and validation
	"libcellml>=0.6.3",
	# console output of scripts and the CLI
	"rich>=15.0.0",
]

[project.optional-dependencies]
# timecourse results and plots of `sbml2cellml.simulate`; the simulator itself,
# libopencor, is not on PyPI, see docs/installation.md
simulate = [
	"pandas>=3.0.5",
	"matplotlib>=3.11.1",
]
dev = [
	"sbml2cellml[simulate]",
	# wheel from the GitHub release, see [tool.uv.index] below
	"libopencor==1.20260803.0",
	"bump-my-version>=1.5.1",
	"ruff>=0.16.6",
	"pre-commit>=4.6.2",
	"ty>=0.0.79",
	"tox>=4.61.2",
	"tox-uv>=1.20",
	"pytest>=9.1.1",
	"pytest-xdist>=3.8",
	"zensical>=0.0.60",
	"mkdocstrings-python>=2.0.8",
]

[project.scripts]
sbml2cellml = "sbml2cellml.cli:main"

[project.urls]
Homepage = "https://matthiaskoenig.github.io/sbml2cellml"
Documentation = "https://matthiaskoenig.github.io/sbml2cellml"
Repository = "https://github.com/matthiaskoenig/sbml2cellml"
Issues = "https://github.com/matthiaskoenig/sbml2cellml/issues"
Changelog = "https://github.com/matthiaskoenig/sbml2cellml/tree/develop/release-notes"
Download = "https://pypi.org/project/sbml2cellml"

[tool.hatch.version]
path = "./src/sbml2cellml/__init__.py"

[tool.hatch.build.targets.wheel]
packages = ["src/sbml2cellml"]

# libopencor publishes its wheels on GitHub releases instead of PyPI. The
# release page is used as a flat index, which only this package is taken from.
# Bumping libopencor means changing the version here and in the dev extra.
[[tool.uv.index]]
name = "libopencor"
url = "https://github.com/opencor/libopencor/releases/expanded_assets/v1.20260803.0"
format = "flat"
explicit = true

[tool.uv.sources]
libopencor = { index = "libopencor" }

[tool.pytest.ini_options]
testpaths = ["tests"]
# the tests run in parallel (pytest-xdist), `pytest -n 0` runs them in one process
addopts = "-n auto"

[tool.ty.environment]
# the package lives in the src layout, the examples and scripts are modules at
# the root of the repository; the checked python version is inferred from
# `project.requires-python`
root = ["./src", "."]

[tool.ty.src]
include = ["src", "tests", "examples", "scripts"]

[tool.ty.terminal]
# warnings are failures: keep the codebase free of any diagnostic
error-on-warning = true
```

- [ ] **Step 3: Write `.ruff.toml`**

Copy the `sbmlsim` configuration and adjust the per-file ignores (no star imports here):

```bash
cp /home/mkoenig/git/sbmlsim/.ruff.toml .ruff.toml
```

Then replace the `[lint.per-file-ignores]` block with:

```toml
[lint.per-file-ignores]
# the examples and tests are scripts and fixtures, a docstring on every helper
# adds nothing
"examples/**" = ["D"]
"tests/**" = ["D"]
```

- [ ] **Step 4: Write `tox.ini`**

```ini
[tox]
envlist = ty, py3.13

[testenv]
# tox-uv creates the environment from uv.lock with `uv sync`, which honours the
# libopencor index of [tool.uv] in pyproject.toml; the dev extra therefore
# contains libopencor and the simulation tests run instead of being skipped
runner = uv-venv-lock-runner
extras =
    dev
commands =
    pytest {posargs}

[testenv:ty]
runner = uv-venv-lock-runner
extras =
    dev
passenv =
    TY_OUTPUT_FORMAT
commands =
    ty check
```

- [ ] **Step 5: Write `.pre-commit-config.yaml`, `.bumpversion.toml`, `.gitignore`**

```bash
cp /home/mkoenig/git/pymetadata/.pre-commit-config.yaml .pre-commit-config.yaml
```

In the copied file remove the comment about the generated ontology modules and the `--maxkb=1000` args of `check-added-large-files` (the default of 500 kB is enough, the largest model is 292 kB). Keep everything else.

`.bumpversion.toml`:

```toml
[tool.bumpversion]
current_version = "0.1.0"
commit = true
parse = "(?P<major>\\d+)\\.(?P<minor>\\d+)\\.(?P<patch>\\d+)"
serialize = ["{major}.{minor}.{patch}"]
search = "{current_version}"
replace = "{new_version}"
regex = false
ignore_missing_version = false
# no tag: the bump is merged into develop through a pull request, which
# rewrites the commit, so the tag is created on develop afterwards
tag = false
sign_tags = false
tag_name = "{new_version}"
tag_message = "Bump version: {current_version} to {new_version}"
allow_dirty = false
message = "Bump version: {current_version} to {new_version}"
commit_args = ""

[[tool.bumpversion.files]]
filename = "./src/sbml2cellml/__init__.py"

[[tool.bumpversion.files]]
filename = "./CITATION.cff"
```

`.gitignore`:

```gitignore
# python
__pycache__/
*.pyc
*.egg-info/

# packaging artifacts (hatchling builds into dist/)
dist/

# environments, tool caches
.venv/
.tox/
.pytest_cache/
.ruff_cache/
.coverage
coverage.xml
# build cache of zensical
.cache/

# rendered documentation, built by the `documentation` workflow
site/

# generated by the examples
examples/results/

# editors, operating system
.idea/
.vscode/
*~
.DS_Store
```

- [ ] **Step 6: Write the package modules**

`src/sbml2cellml/__init__.py`:

```python
"""sbml2cellml - conversion of SBML models to CellML."""

import logging

# the package does not configure logging, see `sbml2cellml.log`
logging.getLogger(__name__).addHandler(logging.NullHandler())

__author__ = "Matthias Koenig"
__version__ = "0.1.0"

program_name: str = "sbml2cellml"
```

`src/sbml2cellml/console.py`:

```python
"""Rich console shared by the scripts, examples and the command line."""

from rich import pretty
from rich.console import Console
from rich.theme import Theme

pretty.install()
custom_theme = Theme(
    {
        "success": "green",
        "info": "blue",
        "warning": "orange3",
        "error": "red",
    }
)

#: the console of the package
console = Console(record=True, theme=custom_theme, log_time=False)
```

`src/sbml2cellml/log.py`: copy `/home/mkoenig/git/pymetadata/src/pymetadata/log.py` and replace every `pymetadata` with `sbml2cellml` (docstring, `PACKAGE_LOGGER`, the import of the console):

```bash
sed 's/pymetadata/sbml2cellml/g' /home/mkoenig/git/pymetadata/src/pymetadata/log.py > src/sbml2cellml/log.py
grep -n "pymetadata" src/sbml2cellml/log.py
```

Expected: no output from `grep`.

- [ ] **Step 7: Write the test scaffolding**

`tests/__init__.py`: empty file.

`tests/conftest.py`:

```python
"""Shared test configuration.

The example models are read from `examples/models/` instead of a second copy
in `tests/data/`; `tests/data/` only holds small fixtures created for a test.
"""

from pathlib import Path

#: models of the examples, also used as test fixtures
MODELS_DIR: Path = Path(__file__).parent.parent / "examples" / "models"
#: simple hand written CellML model (mass decay)
TEST_MODEL_PATH: Path = MODELS_DIR / "test_model.cellml"
#: names of the glimepiride SBML models, `<name>.xml` in `MODELS_DIR`
GLIMEPIRIDE_MODELS: list[str] = [
    "glimepiride_body",
    "glimepiride_body_flat",
    "glimepiride_intestine",
    "glimepiride_kidney",
    "glimepiride_liver",
]
```

`tests/test_package.py`:

```python
"""Tests of the package metadata and the test fixtures."""

import logging

import sbml2cellml
from sbml2cellml import log
from tests.conftest import GLIMEPIRIDE_MODELS, MODELS_DIR, TEST_MODEL_PATH


def test_version() -> None:
    assert sbml2cellml.__version__ == "0.1.0"


def test_models_exist() -> None:
    assert TEST_MODEL_PATH.is_file()
    for name in GLIMEPIRIDE_MODELS:
        assert (MODELS_DIR / f"{name}.xml").is_file(), name


def test_package_logger_has_null_handler() -> None:
    handlers = logging.getLogger("sbml2cellml").handlers
    assert any(isinstance(h, logging.NullHandler) for h in handlers)


def test_enable_rich_logging_is_idempotent() -> None:
    logger = log.enable_rich_logging()
    log.enable_rich_logging()
    rich_handlers = [h for h in logger.handlers if type(h).__name__ == "RichHandler"]
    assert len(rich_handlers) == 1
```

- [ ] **Step 8: Sync the environment and lock**

```bash
uv sync --extra dev
git status --short uv.lock
uv run python -c "import libcellml, libsbml, libopencor, sbml2cellml; print(sbml2cellml.__version__)"
```

Expected: `uv.lock` is created, the import prints `0.1.0`. If `uv sync` cannot find `libopencor`, the flat index is broken: fall back to per-platform `url` sources as described in the spec (section 2) and note it in the task report.

- [ ] **Step 9: Run the checks**

```bash
uv run pytest -v
uv run ruff check
uv run ruff format --check
uv run ty check
```

Expected: 4 tests pass, ruff and ty report nothing. Fix formatting with `uv run ruff format`.

- [ ] **Step 10: Install the git hook and commit**

```bash
uv run pre-commit install
git add -A
git commit -m "Restructure the repository into a src layout package

Move the models to examples/models and the specification material to
references/, remove the modules which are rewritten in the following
commits, and add the packaging with hatchling and uv, the ruff, ty, tox,
pre-commit and bump-my-version configuration, the package logger and the
test scaffolding.

```

If the pre-commit hook rejects the commit, fix what it reports and commit again.

---

### Task 2: MathML helpers

**Files:**
- Create: `src/sbml2cellml/mathml.py`
- Test: `tests/test_mathml.py`

**Interfaces:**
- Produces: `process_mathml_for_cellml(formula: str) -> str`, `mathml_for_assignment(vid: str, formula: str) -> str`, `mathml_for_diff(vid: str, formula: str, ivid: str = "t") -> str`, `cellml_math(parts: list[str]) -> str`, `MathMLError`.

- [ ] **Step 1: Write the failing tests**

`tests/test_mathml.py`:

```python
"""Tests of the MathML helpers."""

import pytest

from sbml2cellml.mathml import (
    MathMLError,
    cellml_math,
    mathml_for_assignment,
    mathml_for_diff,
    process_mathml_for_cellml,
)


def test_process_strips_header_and_math_element() -> None:
    mathml = process_mathml_for_cellml("k1 * S1")
    assert not mathml.startswith("<?xml")
    assert "<math" not in mathml
    assert "</math>" not in mathml
    assert mathml.startswith("<apply>")
    assert mathml.endswith("</apply>")
    assert "k1" in mathml
    assert "S1" in mathml


def test_process_maps_sbml_units_to_cellml_units() -> None:
    mathml = process_mathml_for_cellml("1.0 dimensionless / V")
    assert 'cellml:units="dimensionless"' in mathml
    assert "sbml:units" not in mathml


def test_process_raises_on_invalid_formula() -> None:
    with pytest.raises(MathMLError, match="does not parse"):
        process_mathml_for_cellml("k1 * (")


def test_mathml_for_assignment() -> None:
    mathml = mathml_for_assignment(vid="x", formula="2 * y")
    assert mathml.startswith("<apply>\n  <eq/>\n  <ci>x</ci>")
    assert "y" in mathml
    assert mathml.rstrip().endswith("</apply>")


def test_mathml_for_diff() -> None:
    mathml = mathml_for_diff(vid="S1", formula="- k1 * S1", ivid="time")
    assert "<diff/>" in mathml
    assert "<bvar>\n      <ci>time</ci>\n    </bvar>" in mathml
    assert "<ci>S1</ci>" in mathml


def test_cellml_math_wraps_parts() -> None:
    parts = [mathml_for_assignment("x", "1"), mathml_for_assignment("y", "2")]
    math = cellml_math(parts)
    assert math.startswith(
        '<math xmlns="http://www.w3.org/1998/Math/MathML" '
        'xmlns:cellml="http://www.cellml.org/cellml/2.0#">'
    )
    assert math.endswith("</math>")
    assert math.count("<eq/>") == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_mathml.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sbml2cellml.mathml'`

- [ ] **Step 3: Write the module**

`src/sbml2cellml/mathml.py`:

```python
"""MathML helpers for the math of a CellML component.

libsbml renders a formula as a complete MathML document, i.e., with an xml
declaration and a `math` element. CellML takes the equations of a component as
one `math` element, so the rendered fragments are stripped of the declaration
and the element, combined, and wrapped in a `math` element which declares the
`cellml` namespace for the units of numbers. The `sbml:units` attribute of
libsbml becomes `cellml:units`.
"""

import re

import libsbml

#: xml declaration written by libsbml in front of the math element
XML_DECLARATION = re.compile(r"<\?xml[^>]*\?>")
#: opening math element with its namespace declarations
MATH_OPEN = re.compile(r"<math[^>]*>")
MATH_CLOSE = "</math>"

SBML_UNITS_ATTRIBUTE = "sbml:units"
CELLML_UNITS_ATTRIBUTE = "cellml:units"

#: opening math element of the CellML component math
CELLML_MATH_OPEN = (
    '<math xmlns="http://www.w3.org/1998/Math/MathML" '
    'xmlns:cellml="http://www.cellml.org/cellml/2.0#">'
)


class MathMLError(ValueError):
    """A formula cannot be rendered as MathML."""


def process_mathml_for_cellml(formula: str) -> str:
    """Render a formula in SBML L3 syntax as a MathML fragment for CellML.

    Args:
        formula: formula in the SBML level 3 infix syntax, e.g., `k1 * S1`.

    Returns:
        The MathML of the formula without xml declaration and `math` element,
        with `cellml:units` attributes on numbers with units.

    Raises:
        MathMLError: if the formula does not parse.
    """
    ast: libsbml.ASTNode | None = libsbml.parseL3Formula(formula)
    if ast is None:
        raise MathMLError(
            f"Formula does not parse: '{formula}': {libsbml.getLastParseL3Error()}"
        )
    mathml: str = libsbml.writeMathMLToString(ast)
    mathml = XML_DECLARATION.sub("", mathml)
    mathml = MATH_OPEN.sub("", mathml, count=1)
    mathml = mathml.replace(MATH_CLOSE, "")
    mathml = mathml.replace(SBML_UNITS_ATTRIBUTE, CELLML_UNITS_ATTRIBUTE)
    return mathml.strip()


def mathml_for_assignment(vid: str, formula: str) -> str:
    """MathML of the assignment `vid = formula`.

    Args:
        vid: id of the assigned variable.
        formula: right hand side in SBML L3 infix syntax.

    Returns:
        The `apply` element of the equation.
    """
    rhs = process_mathml_for_cellml(formula)
    return f"""<apply>
  <eq/>
  <ci>{vid}</ci>
  {rhs}
</apply>
"""


def mathml_for_diff(vid: str, formula: str, ivid: str = "t") -> str:
    """MathML of the differential equation `d vid / d ivid = formula`.

    Args:
        vid: id of the state variable.
        formula: right hand side in SBML L3 infix syntax.
        ivid: id of the variable of integration.

    Returns:
        The `apply` element of the equation.
    """
    rhs = process_mathml_for_cellml(formula)
    return f"""<apply>
  <eq/>
  <apply>
    <diff/>
    <bvar>
      <ci>{ivid}</ci>
    </bvar>
    <ci>{vid}</ci>
  </apply>
  {rhs}
</apply>
"""


def cellml_math(parts: list[str]) -> str:
    """Combine equation fragments into the math element of a component.

    Args:
        parts: `apply` elements, e.g., from `mathml_for_assignment`.

    Returns:
        The complete `math` element with the MathML and cellml namespaces.
    """
    return CELLML_MATH_OPEN + "\n" + "\n".join(parts) + "</math>"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_mathml.py -v`
Expected: 6 passed. If `test_process_maps_sbml_units_to_cellml_units` fails because libsbml writes no `sbml:units`, print `process_mathml_for_cellml("1.0 dimensionless / V")` and adjust the assertion to the attribute libsbml writes; the replacement of `sbml:units` itself must stay.

- [ ] **Step 5: Lint, type check, commit**

```bash
uv run ruff check && uv run ruff format && uv run ty check
git add src/sbml2cellml/mathml.py tests/test_mathml.py
git commit -m "Add the MathML helpers

```

---

### Task 3: libcellml helpers

**Files:**
- Create: `src/sbml2cellml/cellml.py`
- Test: `tests/test_cellml.py`

**Interfaces:**
- Consumes: `tests.conftest.TEST_MODEL_PATH`.
- Produces: `read_model(cellml_path: Path) -> libcellml.Model`, `write_model(model: libcellml.Model, cellml_path: Path) -> None`, `model_to_string(model: libcellml.Model) -> str`, `validate_model(model: libcellml.Model) -> list[libcellml.Issue]`, `errors(issues: list[libcellml.Issue]) -> list[libcellml.Issue]`, `format_issue(issue: libcellml.Issue) -> str`, `format_issues(issues: list[libcellml.Issue]) -> str`, `CellMLValidationError`.

- [ ] **Step 1: Write the failing tests**

`tests/test_cellml.py`:

```python
"""Tests of the libcellml helpers."""

from pathlib import Path

import libcellml
import pytest

from sbml2cellml.cellml import (
    CellMLValidationError,
    errors,
    format_issue,
    model_to_string,
    read_model,
    validate_model,
    write_model,
)
from tests.conftest import TEST_MODEL_PATH


def invalid_model() -> libcellml.Model:
    """Model whose math references a variable which does not exist."""
    model = libcellml.Model("invalid")
    component = libcellml.Component("c")
    component.setMath(
        '<math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<apply><eq/><ci>x</ci><ci>y</ci></apply></math>"
    )
    model.addComponent(component)
    return model


def test_read_model() -> None:
    model = read_model(TEST_MODEL_PATH)
    assert model.name() == "test_model"
    assert model.componentCount() == 1
    assert model.component(0).variableCount() == 3


def test_read_model_raises_on_invalid_xml(tmp_path: Path) -> None:
    path = tmp_path / "broken.cellml"
    path.write_text("<model this is not xml")
    with pytest.raises(CellMLValidationError):
        read_model(path)


def test_write_and_read_roundtrip(tmp_path: Path) -> None:
    model = read_model(TEST_MODEL_PATH)
    path = tmp_path / "test_model.cellml"
    write_model(model, path)
    assert path.is_file()
    assert model_to_string(read_model(path)) == model_to_string(model)


def test_validate_valid_model_has_no_issues() -> None:
    model = read_model(TEST_MODEL_PATH)
    assert validate_model(model) == []


def test_validate_invalid_model_has_errors() -> None:
    issues = validate_model(invalid_model())
    assert issues
    assert errors(issues)
    description = format_issue(errors(issues)[0])
    assert description.startswith("[ERROR]")
    assert "'x'" in description or "x" in description
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cellml.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sbml2cellml.cellml'`

- [ ] **Step 3: Write the module**

`src/sbml2cellml/cellml.py`:

```python
"""Reading, writing and validating CellML models with libcellml.

The functions wrap the libcellml `Parser`, `Printer`, `Validator` and
`Analyser`. Issues are returned instead of printed, so a caller decides what
to do with them; `errors` filters the issues of level `ERROR`.
"""

from pathlib import Path

import libcellml

#: name of every issue level of libcellml
LEVEL_NAMES: dict[int, str] = {
    libcellml.Issue.Level.ERROR: "ERROR",
    libcellml.Issue.Level.WARNING: "WARNING",
    libcellml.Issue.Level.MESSAGE: "MESSAGE",
}


class CellMLValidationError(ValueError):
    """A CellML model has issues of level ERROR."""


def _issues(logger: libcellml.Logger) -> list[libcellml.Issue]:
    """Issues collected by a libcellml logger (parser, validator, analyser)."""
    return [logger.issue(k) for k in range(logger.issueCount())]


def format_issue(issue: libcellml.Issue) -> str:
    """Format an issue as `[LEVEL] description`.

    Args:
        issue: issue of a libcellml logger.

    Returns:
        The one line description of the issue.
    """
    level = LEVEL_NAMES.get(issue.level(), str(issue.level()))
    return f"[{level}] {issue.description()}"


def format_issues(issues: list[libcellml.Issue]) -> str:
    """Format issues as one line per issue.

    Args:
        issues: issues of a libcellml logger.

    Returns:
        The formatted issues joined by newlines.
    """
    return "\n".join(format_issue(issue) for issue in issues)


def errors(issues: list[libcellml.Issue]) -> list[libcellml.Issue]:
    """The issues of level ERROR.

    Args:
        issues: issues of a libcellml logger.

    Returns:
        The subset of issues with level `ERROR`.
    """
    return [issue for issue in issues if issue.level() == libcellml.Issue.Level.ERROR]


def model_to_string(model: libcellml.Model) -> str:
    """Serialize a model to CellML 2.0.

    Args:
        model: CellML model.

    Returns:
        The CellML xml.
    """
    printer = libcellml.Printer()
    return printer.printModel(model)


def write_model(model: libcellml.Model, cellml_path: Path) -> None:
    """Write a model as CellML file.

    Args:
        model: CellML model.
        cellml_path: path of the file, overwritten if it exists.
    """
    Path(cellml_path).write_text(model_to_string(model), encoding="utf-8")


def read_model(cellml_path: Path) -> libcellml.Model:
    """Read a CellML file.

    Args:
        cellml_path: path of the CellML file.

    Returns:
        The parsed model.

    Raises:
        CellMLValidationError: if the parser reports errors.
    """
    parser = libcellml.Parser()
    model = parser.parseModel(Path(cellml_path).read_text(encoding="utf-8"))
    parser_errors = errors(_issues(parser))
    if parser_errors:
        raise CellMLValidationError(
            f"CellML file '{cellml_path}' could not be parsed:\n"
            f"{format_issues(parser_errors)}"
        )
    return model


def validate_model(model: libcellml.Model) -> list[libcellml.Issue]:
    """Validate and analyse a model.

    The validator checks the model against the CellML specification, the
    analyser checks that the equations define every variable exactly once.

    Args:
        model: CellML model.

    Returns:
        The issues of the validator followed by the issues of the analyser,
        empty for a valid model.
    """
    validator = libcellml.Validator()
    validator.validateModel(model)
    issues = _issues(validator)

    analyser = libcellml.Analyser()
    analyser.analyseModel(model)
    issues.extend(_issues(analyser))
    return issues
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cellml.py -v`
Expected: 5 passed.

- [ ] **Step 5: Lint, type check, commit**

```bash
uv run ruff check && uv run ruff format && uv run ty check
git add src/sbml2cellml/cellml.py tests/test_cellml.py
git commit -m "Add the libcellml helpers

```

If ty reports `libcellml.Logger`, `libcellml.Issue` or `libcellml.Issue.Level` as unresolved attributes (the swig wrapper is plain python, so it should resolve), replace the annotation with `Any` from `typing` for that name only and keep the rest typed.

---

### Task 4: The SBML to CellML converter

**Files:**
- Create: `src/sbml2cellml/sbml2cellml.py`
- Modify: `src/sbml2cellml/__init__.py` (re-export)
- Test: `tests/test_sbml2cellml.py`

**Interfaces:**
- Consumes: `sbml2cellml.mathml` (`mathml_for_assignment`, `mathml_for_diff`, `cellml_math`), `sbml2cellml.cellml` (`validate_model`, `errors`, `format_issues`, `write_model`, `CellMLValidationError`), `tests.conftest.MODELS_DIR`, `GLIMEPIRIDE_MODELS`.
- Produces: `convert_sbml2cellml(sbml_path: Path, cellml_path: Path | None = None, validate: bool = True) -> libcellml.Model`, `SBML2CellMLConversionError`, constants `COMPONENT_ID = "sbml"`, `TIME_ID = "time"`; `sbml2cellml.convert_sbml2cellml` re-export.

- [ ] **Step 1: Write the failing tests**

`tests/test_sbml2cellml.py`:

```python
"""Tests of the SBML to CellML conversion."""

import logging
from pathlib import Path

import libcellml
import libsbml
import pytest

from sbml2cellml import convert_sbml2cellml
from sbml2cellml.cellml import CellMLValidationError, errors, read_model, validate_model
from sbml2cellml.sbml2cellml import COMPONENT_ID, TIME_ID, SBML2CellMLConversionError
from tests.conftest import GLIMEPIRIDE_MODELS, MODELS_DIR

#: models the current converter renders as valid CellML
VALID_MODELS = ["glimepiride_kidney", "glimepiride_liver"]
#: models with known conversion gaps, see docs/roadmap.md
INVALID_MODELS = {
    "glimepiride_intestine": "function definition and units on numbers",
    "glimepiride_body": "units on numbers in formulas",
    "glimepiride_body_flat": "units on numbers in formulas",
}


def write_sbml(path: Path, model: libsbml.Model) -> Path:
    """Write the document of a model."""
    doc = model.getSBMLDocument()
    libsbml.writeSBMLToFile(doc, str(path))
    return path


def simple_model(mid: str = "simple") -> libsbml.Model:
    """SBML L3V2 model with one compartment, one parameter and two species.

    S1 is in concentration, S2 in amount, one reaction S1 -> S2 with `k1 * S1`.
    """
    doc = libsbml.SBMLDocument(3, 2)
    model: libsbml.Model = doc.createModel()
    model.setId(mid)
    c: libsbml.Compartment = model.createCompartment()
    c.setId("cell")
    c.setSize(2.0)
    c.setConstant(True)
    p: libsbml.Parameter = model.createParameter()
    p.setId("k1")
    p.setValue(0.5)
    p.setConstant(True)
    s1: libsbml.Species = model.createSpecies()
    s1.setId("S1")
    s1.setCompartment("cell")
    s1.setInitialConcentration(10.0)
    s1.setHasOnlySubstanceUnits(False)
    s1.setBoundaryCondition(False)
    s1.setConstant(False)
    s2: libsbml.Species = model.createSpecies()
    s2.setId("S2")
    s2.setCompartment("cell")
    s2.setInitialAmount(4.0)
    s2.setHasOnlySubstanceUnits(True)
    s2.setBoundaryCondition(False)
    s2.setConstant(False)
    r: libsbml.Reaction = model.createReaction()
    r.setId("r1")
    r.setReversible(False)
    reactant: libsbml.SpeciesReference = r.createReactant()
    reactant.setSpecies("S1")
    reactant.setConstant(True)
    reactant.setStoichiometry(1.0)
    product: libsbml.SpeciesReference = r.createProduct()
    product.setSpecies("S2")
    product.setConstant(True)
    product.setStoichiometry(1.0)
    klaw: libsbml.KineticLaw = r.createKineticLaw()
    klaw.setMath(libsbml.parseL3Formula("k1 * S1"))
    return model


def variables(model: libcellml.Model) -> dict[str, libcellml.Variable]:
    component = model.component(0)
    return {
        component.variable(k).name(): component.variable(k)
        for k in range(component.variableCount())
    }


@pytest.mark.parametrize("name", GLIMEPIRIDE_MODELS)
def test_convert_glimepiride_structure(name: str, tmp_path: Path) -> None:
    sbml_path = MODELS_DIR / f"{name}.xml"
    cellml_path = tmp_path / f"{name}.cellml"
    model = convert_sbml2cellml(sbml_path, cellml_path=cellml_path, validate=False)

    assert model.componentCount() == 1
    assert model.component(0).name() == COMPONENT_ID

    doc = libsbml.readSBMLFromFile(str(sbml_path))
    m_sbml = doc.getModel()
    n_expected = (
        m_sbml.getNumCompartments()
        + m_sbml.getNumParameters()
        + m_sbml.getNumSpecies()
        + 1
    )
    assert model.component(0).variableCount() == n_expected
    assert TIME_ID in variables(model)

    # the written file parses back without issues
    assert cellml_path.is_file()
    read_model(cellml_path)


@pytest.mark.parametrize("name", VALID_MODELS)
def test_convert_glimepiride_valid(name: str) -> None:
    model = convert_sbml2cellml(MODELS_DIR / f"{name}.xml", validate=False)
    assert errors(validate_model(model)) == []


@pytest.mark.parametrize("name", list(INVALID_MODELS))
def test_convert_glimepiride_invalid(name: str) -> None:
    """Known conversion gaps, remove the model from INVALID_MODELS once fixed."""
    model = convert_sbml2cellml(MODELS_DIR / f"{name}.xml", validate=False)
    assert errors(validate_model(model)), INVALID_MODELS[name]


def test_validate_raises_for_invalid_model() -> None:
    with pytest.raises(CellMLValidationError):
        convert_sbml2cellml(MODELS_DIR / "glimepiride_body.xml", validate=True)


def test_validate_passes_for_valid_model(tmp_path: Path) -> None:
    cellml_path = tmp_path / "liver.cellml"
    convert_sbml2cellml(
        MODELS_DIR / "glimepiride_liver.xml", cellml_path=cellml_path, validate=True
    )
    assert cellml_path.is_file()


def test_missing_model_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.xml"
    path.write_text('<?xml version="1.0"?><sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2"/>')
    with pytest.raises(SBML2CellMLConversionError, match="No model"):
        convert_sbml2cellml(path)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(SBML2CellMLConversionError):
        convert_sbml2cellml(tmp_path / "does_not_exist.xml")


def test_simple_model_initial_values(tmp_path: Path) -> None:
    sbml_path = write_sbml(tmp_path / "simple.xml", simple_model())
    model = convert_sbml2cellml(sbml_path)
    v = variables(model)
    assert model.name() == "simple"
    assert set(v) == {TIME_ID, "cell", "k1", "S1", "S2"}
    assert float(v["cell"].initialValue()) == 2.0
    assert float(v["k1"].initialValue()) == 0.5
    # concentration stays concentration, amount stays amount
    assert float(v["S1"].initialValue()) == 10.0
    assert float(v["S2"].initialValue()) == 4.0
    # the reaction term of a concentration species is scaled by the compartment
    math = model.component(0).math()
    assert "<diff/>" in math
    assert 'cellml:units="dimensionless"' in math


def test_amount_given_for_concentration_species(tmp_path: Path) -> None:
    model_sbml = simple_model("amounts")
    s1: libsbml.Species = model_sbml.getSpecies("S1")
    s1.unsetInitialConcentration()
    s1.setInitialAmount(6.0)  # concentration species, amount given: 6 / 2
    sbml_path = write_sbml(tmp_path / "amounts.xml", model_sbml)
    v = variables(convert_sbml2cellml(sbml_path))
    assert float(v["S1"].initialValue()) == 3.0


def test_nan_initial_value_logs_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    model_sbml = simple_model("nan")
    p: libsbml.Parameter = model_sbml.createParameter()
    p.setId("k_undefined")
    p.setConstant(True)
    sbml_path = write_sbml(tmp_path / "nan.xml", model_sbml)
    with caplog.at_level(logging.WARNING, logger="sbml2cellml"):
        v = variables(convert_sbml2cellml(sbml_path))
    assert float(v["k_undefined"].initialValue()) == 1.0
    assert "k_undefined" in caplog.text


def test_event_and_initial_assignment_log_warnings(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    model_sbml = simple_model("events")
    ia: libsbml.InitialAssignment = model_sbml.createInitialAssignment()
    ia.setSymbol("k1")
    ia.setMath(libsbml.parseL3Formula("2 * 0.5"))
    event: libsbml.Event = model_sbml.createEvent()
    event.setId("e1")
    event.setUseValuesFromTriggerTime(True)
    trigger: libsbml.Trigger = event.createTrigger()
    trigger.setMath(libsbml.parseL3Formula("time > 10"))
    trigger.setPersistent(True)
    trigger.setInitialValue(True)
    ea: libsbml.EventAssignment = event.createEventAssignment()
    ea.setVariable("k1")
    ea.setMath(libsbml.parseL3Formula("1.0"))
    sbml_path = write_sbml(tmp_path / "events.xml", model_sbml)
    with caplog.at_level(logging.WARNING, logger="sbml2cellml"):
        convert_sbml2cellml(sbml_path, validate=False)
    assert "Event 'e1'" in caplog.text
    assert "InitialAssignment for 'k1'" in caplog.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sbml2cellml.py -v`
Expected: FAIL with `ImportError: cannot import name 'convert_sbml2cellml' from 'sbml2cellml'`

- [ ] **Step 3: Write the converter**

`src/sbml2cellml/sbml2cellml.py`:

```python
"""Conversion of SBML models to CellML 2.0.

The conversion puts every SBML compartment, parameter and species as a variable
into a single CellML component `sbml`, together with the variable of
integration `time`. Assignment rules become equations, rate rules and the
kinetic laws of the reactions become differential equations. All variables are
`dimensionless`, the units of the SBML model are not converted yet.

Not supported yet (logged as warning, see docs/roadmap.md): unit definitions,
initial assignments, function definitions, events and algebraic rules. The
stoichiometry of a reaction is not applied to its kinetic law either.
"""

import logging
import math
from pathlib import Path

import libcellml
import libsbml

from sbml2cellml import cellml, mathml
from sbml2cellml.cellml import CellMLValidationError

logger = logging.getLogger(__name__)

#: name of the single component which holds the model
COMPONENT_ID = "sbml"
#: name of the variable of integration
TIME_ID = "time"
#: units of every variable until units are converted
UNITS_ID = "dimensionless"


class SBML2CellMLConversionError(ValueError):
    """The SBML document cannot be converted."""


def convert_sbml2cellml(
    sbml_path: Path, cellml_path: Path | None = None, validate: bool = True
) -> libcellml.Model:
    """Convert an SBML file to a CellML model.

    Args:
        sbml_path: path of the SBML file.
        cellml_path: path the CellML is written to, not written if `None`.
        validate: validate and analyse the CellML model with libcellml and
            raise if it has errors.

    Returns:
        The CellML model.

    Raises:
        SBML2CellMLConversionError: if the file has no model.
        CellMLValidationError: if `validate` is set and the model has errors.
    """
    doc: libsbml.SBMLDocument = libsbml.readSBMLFromFile(str(sbml_path))
    model_sbml: libsbml.Model | None = doc.getModel()
    if model_sbml is None:
        raise SBML2CellMLConversionError(f"No model in SBML file '{sbml_path}'.")
    mid: str = model_sbml.getId() if model_sbml.isSetId() else Path(sbml_path).stem
    logger.info("Converting SBML model '%s' from '%s'", mid, sbml_path)

    model = libcellml.Model(mid)
    component = libcellml.Component(COMPONENT_ID)
    model.addComponent(component)

    per_second = libcellml.Units("per_second")
    per_second.addUnit("second", -1)
    model.addUnits(per_second)

    time = libcellml.Variable(TIME_ID)
    time.setUnits(UNITS_ID)
    component.addVariable(time)

    compartment_sizes = _add_compartments(component, model_sbml)
    _add_parameters(component, model_sbml)
    in_amount = _add_species(component, model_sbml, compartment_sizes)

    assignment_rules, rate_rules = _collect_rules(model_sbml)
    reaction_terms = _collect_reaction_terms(model_sbml, in_amount)

    parts: list[str] = []
    for vid, formula in assignment_rules.items():
        logger.info("%s = %s", vid, formula)
        parts.append(mathml.mathml_for_assignment(vid=vid, formula=formula))
    for vid, formula in rate_rules.items():
        logger.info("d%s/dt = %s", vid, formula)
        parts.append(mathml.mathml_for_diff(vid=vid, formula=formula, ivid=TIME_ID))
    for vid, formula in reaction_terms.items():
        logger.info("d%s/dt = %s", vid, formula)
        parts.append(mathml.mathml_for_diff(vid=vid, formula=formula, ivid=TIME_ID))
    component.setMath(mathml.cellml_math(parts))

    event: libsbml.Event
    for event in model_sbml.getListOfEvents():
        logger.warning(
            "Event '%s' not converted, events are not supported yet.", event.getId()
        )
    assignment: libsbml.InitialAssignment
    for assignment in model_sbml.getListOfInitialAssignments():
        logger.warning(
            "InitialAssignment for '%s' not converted, initial assignments are "
            "not supported yet.",
            assignment.getSymbol(),
        )

    if validate:
        issues = cellml.errors(cellml.validate_model(model))
        if issues:
            raise CellMLValidationError(
                f"CellML model '{mid}' converted from '{sbml_path}' has "
                f"{len(issues)} errors:\n{cellml.format_issues(issues)}"
            )

    if cellml_path is not None:
        cellml.write_model(model, cellml_path)
        logger.info("CellML written to '%s'", cellml_path)

    return model


def _initial_value(sid: str, value: float) -> float:
    """Replace a NaN initial value by 1.0 with a warning.

    A NaN is what libsbml returns for an unset value; the value would have to
    be calculated from the rules and initial assignments, which is not
    supported yet.
    """
    if math.isnan(value):
        logger.warning("Initial value of '%s' is not set, using 1.0.", sid)
        return 1.0
    return value


def _add_variable(component: libcellml.Component, sid: str, value: float) -> None:
    """Add a dimensionless variable with an initial value to the component."""
    variable = libcellml.Variable(sid)
    variable.setUnits(UNITS_ID)
    variable.setInitialValue(value)
    component.addVariable(variable)


def _add_compartments(
    component: libcellml.Component, model_sbml: libsbml.Model
) -> dict[str, float]:
    """Add the compartments as variables.

    Returns:
        The initial size of every compartment by id.
    """
    sizes: dict[str, float] = {}
    compartment: libsbml.Compartment
    for compartment in model_sbml.getListOfCompartments():
        cid: str = compartment.getId()
        sizes[cid] = _initial_value(cid, compartment.getSize())
        _add_variable(component, cid, sizes[cid])
        logger.info("'%s' variable for compartment", cid)
    return sizes


def _add_parameters(component: libcellml.Component, model_sbml: libsbml.Model) -> None:
    """Add the parameters as variables."""
    parameter: libsbml.Parameter
    for parameter in model_sbml.getListOfParameters():
        pid: str = parameter.getId()
        _add_variable(component, pid, _initial_value(pid, parameter.getValue()))
        logger.info("'%s' variable for parameter", pid)


def _add_species(
    component: libcellml.Component,
    model_sbml: libsbml.Model,
    compartment_sizes: dict[str, float],
) -> dict[str, bool]:
    """Add the species as variables.

    A species with `hasOnlySubstanceUnits` is a variable in amount, every other
    species a variable in concentration; the initial value is converted with
    the size of the compartment when it is given in the other quantity.

    Returns:
        Whether the variable of a species is in amount, by species id.
    """
    in_amount: dict[str, bool] = {}
    species: libsbml.Species
    for species in model_sbml.getListOfSpecies():
        sid: str = species.getId()
        size = compartment_sizes[species.getCompartment()]
        amount = species.getHasOnlySubstanceUnits()
        in_amount[sid] = amount

        if species.isSetInitialAmount():
            value = _initial_value(sid, species.getInitialAmount())
            initial = value if amount else value / size
        elif species.isSetInitialConcentration():
            value = _initial_value(sid, species.getInitialConcentration())
            initial = value * size if amount else value
        else:
            initial = _initial_value(sid, math.nan)
        _add_variable(component, sid, initial)
        logger.info("'%s' variable for species", sid)
    return in_amount


def _collect_rules(
    model_sbml: libsbml.Model,
) -> tuple[dict[str, str], dict[str, str]]:
    """Collect the assignment and rate rules as formulas.

    Returns:
        The assignment rules and the rate rules, formula by variable id.
    """
    assignment_rules: dict[str, str] = {}
    rate_rules: dict[str, str] = {}
    rule: libsbml.Rule
    for rule in model_sbml.getListOfRules():
        formula: str = libsbml.formulaToL3String(rule.getMath())
        if rule.getTypeCode() == libsbml.SBML_ASSIGNMENT_RULE:
            assignment_rules[rule.getVariable()] = formula
        elif rule.getTypeCode() == libsbml.SBML_RATE_RULE:
            rate_rules[rule.getVariable()] = formula
        else:
            logger.warning(
                "AlgebraicRule '%s' not converted, algebraic rules are not "
                "supported yet.",
                formula,
            )
    return assignment_rules, rate_rules


def _collect_reaction_terms(
    model_sbml: libsbml.Model, in_amount: dict[str, bool]
) -> dict[str, str]:
    """Collect the rate of change of every species from the kinetic laws.

    The kinetic law of a reaction is in amount per time. It is subtracted for
    every reactant and added for every product; for a species in concentration
    the sum is divided by the size of its compartment.

    Returns:
        The right hand side of `d species / d time`, by species id.
    """
    terms: dict[str, str] = {}
    reaction: libsbml.Reaction
    for reaction in model_sbml.getListOfReactions():
        klaw: libsbml.KineticLaw | None = reaction.getKineticLaw()
        if klaw is None:
            logger.warning(
                "Reaction '%s' has no kinetic law and is not converted.",
                reaction.getId(),
            )
            continue
        formula: str = libsbml.formulaToL3String(klaw.getMath())
        reference: libsbml.SpeciesReference
        for reference in reaction.getListOfReactants():
            _append_term(terms, reference.getSpecies(), f"- ({formula})")
        for reference in reaction.getListOfProducts():
            _append_term(terms, reference.getSpecies(), f"+ ({formula})")

    for sid, formula in terms.items():
        if not in_amount[sid]:
            cid: str = model_sbml.getSpecies(sid).getCompartment()
            terms[sid] = f"1.0 dimensionless/{cid} * ({formula})"
    return terms


def _append_term(terms: dict[str, str], sid: str, term: str) -> None:
    """Append a term to the rate of change of a species."""
    terms[sid] = f"{terms[sid]} {term}" if sid in terms else term
```

Then add the re-export to `src/sbml2cellml/__init__.py` so the file reads:

```python
"""sbml2cellml - conversion of SBML models to CellML."""

import logging

from sbml2cellml.sbml2cellml import convert_sbml2cellml

# the package does not configure logging, see `sbml2cellml.log`
logging.getLogger(__name__).addHandler(logging.NullHandler())

__author__ = "Matthias Koenig"
__version__ = "0.1.0"

program_name: str = "sbml2cellml"

__all__ = ["convert_sbml2cellml"]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_sbml2cellml.py -v`
Expected: all pass. Possible deviations and what to do:
- `test_convert_glimepiride_valid[glimepiride_kidney]` fails: the spike of 2026-09-16 showed 0 validator and 0 analyser issues in process for the kidney model; if libcellml now reports errors, print them, and move the model to `INVALID_MODELS` with the reported reason only if the errors are conversion gaps (units, functions, unconstrained variables), not a bug in this rewrite.
- `test_missing_file_raises` fails with a different exception: `libsbml.readSBMLFromFile` on a missing path returns a document without model, so `SBML2CellMLConversionError` is expected; if libsbml raises itself, catch nothing and change the test to that exception type.

- [ ] **Step 5: Verify the generated CellML is unchanged**

The rewrite must produce the same CellML as the migrated script, up to two
documented differences: whitespace between MathML elements (the old
`mathml_for_diff` left four trailing spaces after every equation), and the
initial value of a species in concentration whose SBML gives an initial amount
(the old code multiplied by the compartment size instead of dividing, see the
spec, "Behaviour changes in S1"). The check compares the whitespace-normalized
math and the variables. Write the script below to `check_unchanged.py` in the
scratchpad directory and run it:

```bash
SCRATCH=/tmp/claude-1000/-home-mkoenig-git-sbml2cellml/cd30810e-7682-427b-aa26-9798000051f0/scratchpad/old
mkdir -p $SCRATCH
git show 616665e:src/sbml2cellml/cellml2sbml.py > $SCRATCH/old_converter.py
cd $SCRATCH && uv run --project /home/mkoenig/git/sbml2cellml python check_unchanged.py; cd /home/mkoenig/git/sbml2cellml
```

`check_unchanged.py`:

```python
import re
import sys
import types
from pathlib import Path

import libsbml

from sbml2cellml.console import console

# the old script imports the console of sbmlutils
m = types.ModuleType("sbmlutils")
mc = types.ModuleType("sbmlutils.console")
mc.console = console
sys.modules["sbmlutils"] = m
sys.modules["sbmlutils.console"] = mc

import old_converter  # noqa: E402

from sbml2cellml import convert_sbml2cellml  # noqa: E402


def normalize(math: str) -> str:
    return re.sub(r">\s+<", "><", math).strip()


def variables(model):
    c = model.component(0)
    return {
        c.variable(k).name(): (c.variable(k).units().name(), c.variable(k).initialValue())
        for k in range(c.variableCount())
    }


models = Path("/home/mkoenig/git/sbml2cellml/examples/models")
ok = True
for name in [
    "glimepiride_liver",
    "glimepiride_kidney",
    "glimepiride_intestine",
    "glimepiride_body",
    "glimepiride_body_flat",
]:
    old = old_converter.convert_sbml2cellml(models / f"{name}.xml", verbose=False)
    new = convert_sbml2cellml(models / f"{name}.xml", validate=False)
    same_math = normalize(old.component(0).math()) == normalize(new.component(0).math())
    v_old, v_new = variables(old), variables(new)
    same_names = list(v_old) == list(v_new)
    # species in concentration with an initial amount are the documented difference
    m_sbml = libsbml.readSBMLFromFile(str(models / f"{name}.xml")).getModel()
    allowed = {
        s.getId()
        for s in m_sbml.getListOfSpecies()
        if s.isSetInitialAmount() and not s.getHasOnlySubstanceUnits()
    }
    differing = [k for k in v_old if v_old[k] != v_new.get(k)]
    unexpected = [k for k in differing if k not in allowed]
    status = "identical" if same_math and same_names and not unexpected else "DIFFERENT"
    ok = ok and status == "identical"
    print(
        f"{name}: {status} (math {same_math}, names {same_names}, "
        f"expected differences {differing}, unexpected {unexpected})"
    )
sys.exit(0 if ok else 1)
```

Expected: `identical` for all five models and exit code 0. A `DIFFERENT` is a
bug in the rewrite: diff the two math strings or the variables and fix the
converter, not the check.

- [ ] **Step 6: Lint, type check, commit**

```bash
uv run ruff check && uv run ruff format && uv run ty check
git add src/sbml2cellml/sbml2cellml.py src/sbml2cellml/__init__.py tests/test_sbml2cellml.py
git commit -m "Add the SBML to CellML converter as a library module

The converter logs instead of printing, validates the model on request and
writes the file itself. The generated CellML is identical to the one of the
migrated script.

```

---

### Task 5: Simulation with libopencor

**Files:**
- Create: `src/sbml2cellml/simulate.py`
- Test: `tests/test_simulate.py`

**Interfaces:**
- Consumes: `tests.conftest.TEST_MODEL_PATH`, `MODELS_DIR`, `sbml2cellml.convert_sbml2cellml`.
- Produces: `run_timecourse(cellml_path: Path, start: float = 0.0, end: float = 100.0, steps: int = 100) -> tuple[pd.DataFrame, dict[str, str]]`, `plot_timecourse(df: pd.DataFrame, units: dict[str, str], show: bool = True) -> Figure`, `SimulationError`, `LIBOPENCOR_INSTALL: str`.

- [ ] **Step 1: Write the failing tests**

`tests/test_simulate.py`:

```python
"""Tests of the libopencor simulation.

Skipped when libopencor is not installed, see docs/installation.md.
"""

from pathlib import Path

import libsbml
import matplotlib
import numpy as np
import pytest

from sbml2cellml import convert_sbml2cellml
from sbml2cellml.simulate import SimulationError, plot_timecourse, run_timecourse
from tests.conftest import MODELS_DIR, TEST_MODEL_PATH

pytest.importorskip("libopencor")
matplotlib.use("Agg")


def test_run_timecourse_test_model() -> None:
    df, units = run_timecourse(TEST_MODEL_PATH, start=0.0, end=50.0, steps=10)
    assert list(df.columns) == ["t", "m"]
    assert len(df) == 11
    assert df["t"].iloc[0] == 0.0
    assert df["t"].iloc[-1] == 50.0
    assert df["m"].iloc[0] == 10.0
    assert np.all(np.diff(df["m"].to_numpy()) < 0)
    assert units == {"t": "second", "m": "kilogram"}


def test_run_timecourse_liver(tmp_path: Path) -> None:
    cellml_path = tmp_path / "liver.cellml"
    convert_sbml2cellml(MODELS_DIR / "glimepiride_liver.xml", cellml_path=cellml_path)
    df, units = run_timecourse(cellml_path, end=10.0, steps=10)
    assert df.columns[0] == "time"
    assert len(df) == 11
    # every species is a state or an algebraic variable of the CellML model
    m_sbml = libsbml.readSBMLFromFile(str(MODELS_DIR / "glimepiride_liver.xml")).getModel()
    for species in m_sbml.getListOfSpecies():
        assert species.getId() in df.columns
    assert set(units) == set(df.columns)


def test_run_timecourse_underconstrained_raises(tmp_path: Path) -> None:
    """Known conversion gap, see docs/roadmap.md."""
    cellml_path = tmp_path / "kidney.cellml"
    convert_sbml2cellml(MODELS_DIR / "glimepiride_kidney.xml", cellml_path=cellml_path)
    with pytest.raises(SimulationError, match="underconstrained"):
        run_timecourse(cellml_path)


def test_run_timecourse_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SimulationError):
        run_timecourse(tmp_path / "missing.cellml")


def test_plot_timecourse() -> None:
    df, units = run_timecourse(TEST_MODEL_PATH, end=10.0, steps=5)
    fig = plot_timecourse(df, units, show=False)
    ax = fig.axes[0]
    assert len(ax.lines) == 1
    assert ax.get_xlabel() == "t [second]"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_simulate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sbml2cellml.simulate'`

- [ ] **Step 3: Write the module**

`src/sbml2cellml/simulate.py`:

```python
"""Simulation of CellML models with libopencor.

libopencor is not on PyPI; it is imported when a simulation runs, so the rest
of the package works without it. See `LIBOPENCOR_INSTALL`.
"""

import logging
from pathlib import Path
from typing import Any

import pandas as pd
from matplotlib import pyplot as plt
from matplotlib.figure import Figure

logger = logging.getLogger(__name__)

#: how to install libopencor, the message of the ImportError
LIBOPENCOR_INSTALL = (
    "libopencor is not installed. It is not on PyPI; install the wheel for "
    "your platform and python version from "
    "https://github.com/opencor/libopencor/releases, see "
    "https://matthiaskoenig.github.io/sbml2cellml/installation/"
)


class SimulationError(RuntimeError):
    """libopencor reported issues for the file, the document or the run."""


def _libopencor() -> Any:
    """Import libopencor with an installation hint on failure."""
    try:
        import libopencor
    except ImportError as err:
        raise ImportError(LIBOPENCOR_INSTALL) from err
    return libopencor


def _raise_on_issues(what: str, issues: Any) -> None:
    """Raise a SimulationError with the descriptions of the issues, if any."""
    descriptions = [issue.description for issue in issues]
    if descriptions:
        raise SimulationError(f"{what}: " + "; ".join(descriptions))


def _variable_name(name: str) -> str:
    """Variable name without the `component/` prefix of libopencor."""
    return name.rsplit("/", 1)[-1]


def run_timecourse(
    cellml_path: Path, start: float = 0.0, end: float = 100.0, steps: int = 100
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Run a uniform timecourse of a CellML model.

    Args:
        cellml_path: path of the CellML file.
        start: start time of the output.
        end: end time of the output.
        steps: number of steps, the output has `steps + 1` rows.

    Returns:
        The timecourse with the variable of integration in the first column
        followed by the states and the algebraic variables, and the units of
        every column.

    Raises:
        ImportError: if libopencor is not installed.
        SimulationError: if libopencor reports issues, e.g., for a model which
            is not valid or not fully constrained.
    """
    libopencor = _libopencor()
    path = Path(cellml_path).resolve()
    if not path.is_file():
        raise SimulationError(f"file: '{path}' does not exist")

    file = libopencor.File(str(path))
    _raise_on_issues("file", file.issues)
    document = libopencor.SedDocument(file)
    _raise_on_issues("document", document.issues)

    # the timecourse settings of the simulation libopencor created for the file
    simulation = document.simulations[0]
    simulation.initial_time = start
    simulation.output_start_time = start
    simulation.output_end_time = end
    simulation.number_of_steps = steps

    instance = document.instantiate()
    _raise_on_issues("instance", instance.issues)
    instance.run()
    _raise_on_issues("run", instance.issues)

    task = instance.tasks[0]
    voi = _variable_name(task.voi_name)
    data: dict[str, Any] = {voi: task.voi}
    units: dict[str, str] = {voi: task.voi_unit}
    for k in range(task.state_count):
        name = _variable_name(task.state_name(k))
        data[name] = task.state(k)
        units[name] = task.state_unit(k)
    for k in range(task.algebraic_variable_count):
        name = _variable_name(task.algebraic_variable_name(k))
        data[name] = task.algebraic_variable(k)
        units[name] = task.algebraic_variable_unit(k)

    logger.info("Simulated '%s': %d rows, %d columns", path, steps + 1, len(data))
    return pd.DataFrame(data), units


def plot_timecourse(
    df: pd.DataFrame, units: dict[str, str], show: bool = True
) -> Figure:
    """Plot every column of a timecourse against the first column.

    Args:
        df: timecourse from `run_timecourse`.
        units: units of the columns from `run_timecourse`.
        show: call `matplotlib.pyplot.show`.

    Returns:
        The figure.
    """
    fig, ax = plt.subplots(nrows=1, ncols=1)
    voi = df.columns[0]
    for name in df.columns[1:]:
        ax.plot(df[voi], df[name], label=f"{name} [{units[name]}]")
    ax.set_xlabel(f"{voi} [{units[voi]}]")
    ax.set_ylabel("value")
    ax.legend()
    if show:
        plt.show()
    return fig
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_simulate.py -v`
Expected: 5 passed. The spike of 2026-09-16 showed for `test_model.cellml`: voi `component/t` in `second`, state `component/m` in `kilogram`, `m` from 10.0 down to 0.82 at t=50, and for the kidney model file issues starting with "Analyser: variable 'egfr_healthy' in component 'sbml' is underconstrained". If the liver model has no algebraic variables in the results, `set(units) == set(df.columns)` still holds. If `task.algebraic_variable_count` does not exist, use `dir(task)` to find the accessor of the algebraic variables (the spike listed `algebraic_variable`, `algebraic_variable_count`, `algebraic_variable_name`, `algebraic_variable_unit`).

- [ ] **Step 5: Lint, type check, commit**

```bash
uv run ruff check && uv run ruff format && uv run ty check
```

ty: if `import libopencor` is reported as `unresolved-import` (a compiled extension without stubs), append `  # ty: ignore[unresolved-import]` to that import line. If ty then reports `unused-ignore-comment`, remove it again; do not leave either diagnostic.

```bash
git add src/sbml2cellml/simulate.py tests/test_simulate.py
git commit -m "Add the libopencor timecourse simulation

The timecourse settings are applied to the simulation of the SED-ML
document, which the migrated script did not do, and the results include
the algebraic variables.

```

---

### Task 6: Command line interface

**Files:**
- Create: `src/sbml2cellml/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `sbml2cellml.convert_sbml2cellml`, `SBML2CellMLConversionError`, `CellMLValidationError`, `sbml2cellml.log.enable_rich_logging`, `sbml2cellml.__version__`.
- Produces: `main(argv: list[str] | None = None) -> int`, `build_parser() -> argparse.ArgumentParser`.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
"""Tests of the command line interface."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sbml2cellml.cli import main
from tests.conftest import MODELS_DIR


def test_convert_with_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "liver.cellml"
    code = main([str(MODELS_DIR / "glimepiride_liver.xml"), "-o", str(out)])
    assert code == 0
    assert out.is_file()
    assert str(out) in capsys.readouterr().out


def test_default_output_next_to_input(tmp_path: Path) -> None:
    sbml_path = tmp_path / "liver.xml"
    shutil.copy(MODELS_DIR / "glimepiride_liver.xml", sbml_path)
    assert main([str(sbml_path)]) == 0
    assert (tmp_path / "liver.cellml").is_file()


def test_missing_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main([str(tmp_path / "missing.xml")])
    assert code == 1
    assert "missing.xml" in capsys.readouterr().err


def test_invalid_model_fails_with_validation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "body.cellml"
    code = main([str(MODELS_DIR / "glimepiride_body.xml"), "-o", str(out)])
    assert code == 1
    assert "errors" in capsys.readouterr().err
    assert not out.exists()


def test_invalid_model_written_without_validation(tmp_path: Path) -> None:
    out = tmp_path / "body.cellml"
    code = main([str(MODELS_DIR / "glimepiride_body.xml"), "-o", str(out), "--no-validate"])
    assert code == 0
    assert out.is_file()


def test_verbose_logs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "liver.cellml"
    assert main([str(MODELS_DIR / "glimepiride_liver.xml"), "-o", str(out), "-v"]) == 0
    captured = capsys.readouterr()
    assert "variable for species" in captured.out + captured.err


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0
    assert "0.1.0" in capsys.readouterr().out


def test_entry_point_installed(tmp_path: Path) -> None:
    """The console script of the package works."""
    out = tmp_path / "liver.cellml"
    result = subprocess.run(
        [sys.executable, "-m", "sbml2cellml.cli", str(MODELS_DIR / "glimepiride_liver.xml"), "-o", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert out.is_file()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sbml2cellml.cli'`

- [ ] **Step 3: Write the module**

`src/sbml2cellml/cli.py`:

```python
"""Command line interface of sbml2cellml.

    sbml2cellml INPUT.xml [-o OUTPUT.cellml] [--no-validate] [-v]

converts an SBML file to CellML. Without `-o` the CellML is written next to
the input with the `.cellml` suffix.
"""

import argparse
import logging
import sys
from pathlib import Path

from sbml2cellml import __version__, log
from sbml2cellml.cellml import CellMLValidationError
from sbml2cellml.sbml2cellml import SBML2CellMLConversionError, convert_sbml2cellml


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser of the command.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="sbml2cellml", description="Convert an SBML model to CellML."
    )
    parser.add_argument("input", help="SBML file")
    parser.add_argument(
        "-o",
        "--output",
        help="CellML file, by default the input with the suffix .cellml",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="write the CellML even if libcellml reports errors",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="log the conversion steps"
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command.

    Args:
        argv: arguments without the program name, `sys.argv[1:]` by default.

    Returns:
        0 on success, 1 on a missing input, a conversion or a validation error.
    """
    args = build_parser().parse_args(argv)
    if args.verbose:
        log.enable_rich_logging(logging.INFO)

    sbml_path = Path(args.input)
    if not sbml_path.is_file():
        print(f"Input file does not exist: '{sbml_path}'", file=sys.stderr)
        return 1
    cellml_path = (
        Path(args.output) if args.output else sbml_path.with_suffix(".cellml")
    )

    try:
        convert_sbml2cellml(
            sbml_path, cellml_path=cellml_path, validate=not args.no_validate
        )
    except (SBML2CellMLConversionError, CellMLValidationError) as err:
        print(str(err), file=sys.stderr)
        return 1

    print(cellml_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 8 passed. `test_verbose_logs`: the rich handler writes to the package console, which is `sys.stdout` at import time; if `capsys` does not capture it, change the assertion to use `caplog` with `caplog.at_level(logging.INFO, logger="sbml2cellml")` and check `"variable for species" in caplog.text` instead.

Also check the installed script:

```bash
uv run sbml2cellml --version
```

Expected: `0.1.0`.

- [ ] **Step 5: Lint, type check, commit**

```bash
uv run ruff check && uv run ruff format && uv run ty check
git add src/sbml2cellml/cli.py tests/test_cli.py
git commit -m "Add the sbml2cellml command line

```

---

### Task 7: Examples

**Files:**
- Create: `examples/__init__.py` (empty), `examples/cellml_example.py`, `examples/glimepiride_example.py`
- Test: `tests/test_examples.py`

**Interfaces:**
- Consumes: `sbml2cellml.convert_sbml2cellml`, `sbml2cellml.cellml` (`validate_model`, `errors`, `format_issues`, `write_model`), `sbml2cellml.simulate` (`run_timecourse`, `plot_timecourse`), `sbml2cellml.log.enable_rich_logging`, `sbml2cellml.console.console`.
- Produces: `examples.cellml_example.example_cellml() -> libcellml.Model`, `examples.glimepiride_example.convert_glimepiride_models(results_dir: Path) -> dict[str, Path]`.

- [ ] **Step 1: Write the failing test**

`tests/test_examples.py`:

```python
"""The examples run without error.

They write into `examples/results/` (gitignored) and simulate with libopencor,
so they are skipped without it.
"""

import runpy
from pathlib import Path

import matplotlib
import pytest

pytest.importorskip("libopencor")
matplotlib.use("Agg")

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


@pytest.mark.parametrize(
    ("script", "result"),
    [
        ("cellml_example.py", "test_model.cellml"),
        ("glimepiride_example.py", "glimepiride_body.cellml"),
    ],
)
def test_example_runs(
    script: str, result: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MPLBACKEND", "Agg")
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(EXAMPLES_DIR / script), run_name="__main__")
    assert (EXAMPLES_DIR / "results" / result).is_file()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_examples.py -v`
Expected: FAIL with `FileNotFoundError` for `examples/cellml_example.py`.

- [ ] **Step 3: Write the examples**

`examples/__init__.py`: empty file.

`examples/cellml_example.py`:

```python
"""Build a CellML model with libcellml, validate, write and simulate it.

The model is the mass decay `dm/dt = -alpha * m` with `m` in kilogram and
`alpha` in per second; it is the same model as `examples/models/test_model.cellml`.
"""

from pathlib import Path

import libcellml

from sbml2cellml import log
from sbml2cellml.cellml import errors, format_issues, validate_model, write_model
from sbml2cellml.console import console
from sbml2cellml.simulate import plot_timecourse, run_timecourse

RESULTS_DIR: Path = Path(__file__).parent / "results"

MATH_ODE = """
<math xmlns="http://www.w3.org/1998/Math/MathML">
    <apply>
        <eq/>
        <apply>
            <diff/>
            <bvar>
                <ci>t</ci>
            </bvar>
            <ci>m</ci>
        </apply>
        <apply>
            <times/>
            <apply>
              <minus/>
              <ci>alpha</ci>
            </apply>
            <ci>m</ci>
        </apply>
    </apply>
</math>
"""


def example_cellml() -> libcellml.Model:
    """Mass decay model with the variables t, m and alpha."""
    model = libcellml.Model("test_model")

    per_second = libcellml.Units("per_second")
    per_second.addUnit("second", -1)
    model.addUnits(per_second)

    component = libcellml.Component("component")
    component.setMath(MATH_ODE)
    model.addComponent(component)

    variable_time = libcellml.Variable("t")
    variable_time.setUnits("second")

    variable_m = libcellml.Variable("m")
    variable_m.setUnits("kilogram")
    variable_m.setInitialValue(10)

    variable_alpha = libcellml.Variable("alpha")
    variable_alpha.setUnits(per_second)
    variable_alpha.setInitialValue(0.05)

    for variable in [variable_time, variable_m, variable_alpha]:
        component.addVariable(variable)

    return model


if __name__ == "__main__":
    log.enable_rich_logging()
    RESULTS_DIR.mkdir(exist_ok=True)

    model = example_cellml()
    issues = validate_model(model)
    if errors(issues):
        console.print(format_issues(issues), style="error")
    else:
        console.print("CellML model is valid.", style="success")

    cellml_path = RESULTS_DIR / "test_model.cellml"
    write_model(model=model, cellml_path=cellml_path)
    console.print(f"CellML written to '{cellml_path}'")

    df, units = run_timecourse(cellml_path, start=0.0, end=100.0, steps=100)
    console.print(df)
    plot_timecourse(df=df, units=units)
```

`examples/glimepiride_example.py`:

```python
"""Convert the glimepiride models to CellML and simulate the liver model.

The models are the physiologically based pharmacokinetic models of
https://github.com/matthiaskoenig/glimepiride-model. The current converter
renders the liver and kidney models as valid CellML; the intestine and body
models hit known conversion gaps (units on numbers, function definitions), see
https://matthiaskoenig.github.io/sbml2cellml/roadmap/. Only the liver model
is fully constrained for libopencor.
"""

from pathlib import Path

from sbml2cellml import convert_sbml2cellml, log
from sbml2cellml.cellml import errors, format_issues, validate_model
from sbml2cellml.console import console
from sbml2cellml.simulate import plot_timecourse, run_timecourse

MODELS_DIR: Path = Path(__file__).parent / "models"
RESULTS_DIR: Path = Path(__file__).parent / "results"

MODEL_NAMES: list[str] = [
    "glimepiride_kidney",
    "glimepiride_liver",
    "glimepiride_intestine",
    "glimepiride_body",
    "glimepiride_body_flat",
]
#: models which libopencor can simulate
SIMULATED_MODELS: list[str] = ["glimepiride_liver"]


def convert_glimepiride_models(results_dir: Path) -> dict[str, Path]:
    """Convert every model into `results_dir` and report the validation.

    Returns:
        The CellML path of every model by name.
    """
    results_dir.mkdir(exist_ok=True)
    cellml_paths: dict[str, Path] = {}
    for name in MODEL_NAMES:
        console.rule(name, style="white")
        cellml_path = results_dir / f"{name}.cellml"
        model = convert_sbml2cellml(
            MODELS_DIR / f"{name}.xml", cellml_path=cellml_path, validate=False
        )
        issues = errors(validate_model(model))
        if issues:
            console.print(f"{len(issues)} errors:", style="error")
            console.print(format_issues(issues[:5]))
        else:
            console.print("valid CellML", style="success")
        cellml_paths[name] = cellml_path
    return cellml_paths


if __name__ == "__main__":
    log.enable_rich_logging()
    paths = convert_glimepiride_models(RESULTS_DIR)
    for name in SIMULATED_MODELS:
        console.rule(f"simulate {name}", style="white")
        df, units = run_timecourse(paths[name], start=0.0, end=100.0, steps=100)
        console.print(df)
        plot_timecourse(df=df, units=units)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_examples.py -v`
Expected: 2 passed and `examples/results/` exists with the CellML files; `git status` must not list it (gitignored).

- [ ] **Step 5: Full suite, lint, type check, commit**

```bash
uv run pytest
uv run ruff check && uv run ruff format && uv run ty check
git add examples/__init__.py examples/cellml_example.py examples/glimepiride_example.py tests/test_examples.py
git commit -m "Move the examples to the top level and run them in the tests

```

---

### Task 8: GitHub workflows, rulesets and repository files

**Files:**
- Create: `.github/workflows/ci-cd.yml`, `.github/workflows/ruff.yml`, `.github/workflows/ty.yml`, `.github/workflows/docs.yml`, `.github/rulesets/develop.json`, `.github/rulesets/main.json`, `.github/rulesets/tags.json`, `.github/rulesets/apply.sh`, `.github/CODEOWNERS`, `.github/dependabot.yml`, `.github/pull_request_template.md`

**Interfaces:**
- Produces: the check names `tests`, `ruff`, `ty`, `docs` which the rulesets require; the `pypi` environment and `release-notes/<tag>.md` which the release job reads (task 10 writes `release-notes/0.1.0.md`).

- [ ] **Step 1: Copy the files which are identical to sbmlsim and pymetadata**

```bash
mkdir -p .github/workflows .github/rulesets
cp /home/mkoenig/git/sbmlsim/.github/workflows/ruff.yml .github/workflows/ruff.yml
cp /home/mkoenig/git/sbmlsim/.github/rulesets/develop.json .github/rulesets/develop.json
cp /home/mkoenig/git/sbmlsim/.github/rulesets/main.json .github/rulesets/main.json
cp /home/mkoenig/git/sbmlsim/.github/rulesets/tags.json .github/rulesets/tags.json
cp /home/mkoenig/git/sbmlsim/.github/rulesets/apply.sh .github/rulesets/apply.sh
cp /home/mkoenig/git/pymetadata/.github/CODEOWNERS .github/CODEOWNERS
cp /home/mkoenig/git/pymetadata/.github/dependabot.yml .github/dependabot.yml
cp /home/mkoenig/git/pymetadata/.github/pull_request_template.md .github/pull_request_template.md
sed -i 's/sbmlsim/sbml2cellml/g' .github/rulesets/apply.sh
grep -rn "sbmlsim\|pymetadata" .github/
```

Expected: `grep` prints nothing. `apply.sh` must stay executable (`ls -l .github/rulesets/apply.sh` shows `x`).

- [ ] **Step 2: Write `ci-cd.yml`**

Start from `/home/mkoenig/git/sbmlsim/.github/workflows/ci-cd.yml` and apply these changes, nothing else:

1. matrix: `python-version: ["3.13"]`, remove the `exclude` block (all three operating systems run 3.13).
2. remove the step "Install the python dev files (linux only)" (no libroadrunner in S1).
3. in every `setup-uv` step of the `release` job use `python-version: "3.13"`.
4. `environment.url` of the release job: `https://pypi.org/p/sbml2cellml`.
5. the "Test with tox" step becomes:

```yaml
    - name: Test with tox
      run:
        uvx --with tox-uv tox -e py${{ matrix.python-version }}
```

(identical to sbmlsim, listed to be explicit that tox-uv is required for the lock runner of `tox.ini`).

Read the result top to bottom: the `test`, `tests`, `release` and `sync-main` jobs are present with `timeout-minutes`, `permissions`, `concurrency` and the trusted publishing step `pypa/gh-action-pypi-publish@release/v1`.

- [ ] **Step 3: Write `ty.yml`**

Copy `/home/mkoenig/git/sbmlsim/.github/workflows/ty.yml`, remove the "Install the python dev files" step, and set `python-version: "3.13"`.

- [ ] **Step 4: Write `docs.yml`**

Copy `/home/mkoenig/git/sbmlsim/.github/workflows/docs.yml`, remove the "Install the python dev files" step, set `python-version: "3.13"`, and replace `sbmlsim` in the comment of the `deploy` job by `sbml2cellml`.

- [ ] **Step 5: Validate the yaml and commit**

```bash
uv run python -c "import yaml, glob; [yaml.safe_load(open(p)) for p in glob.glob('.github/workflows/*.yml')]; print('ok')" 2>/dev/null || uv run --with pyyaml python -c "import yaml, glob; [yaml.safe_load(open(p)) for p in glob.glob('.github/workflows/*.yml')]; print('ok')"
uv run python -c "import json, glob; [json.load(open(p)) for p in glob.glob('.github/rulesets/*.json')]; print('ok')"
grep -rn "sbmlsim\|pymetadata\|libroadrunner\|deadsnakes\|3.14" .github/
git add .github
git commit -m "Add the GitHub workflows, rulesets and repository files

Tests on linux, windows and macOS with python 3.13, ruff, ty and the
documentation build as required checks, the PyPI release on a tag through
trusted publishing, and the rulesets of develop, main and the tags.

```

Expected: both validations print `ok`, `grep` prints nothing.

---

### Task 9: Documentation site

**Files:**
- Create: `zensical.toml`, `docs/README.md`, `docs/index.md`, `docs/installation.md`, `docs/conversion.md`, `docs/simulation.md`, `docs/roadmap.md`, `docs/development.md`, `docs/api/index.md`, `docs/api/sbml2cellml.md`, `docs/api/cellml.md`, `docs/api/mathml.md`, `docs/api/simulate.md`, `docs/api/cli.md`, `docs/api/console.md`, `docs/api/log.md`, `docs/robots.txt`, `scripts/__init__.py` (empty), `scripts/llms_txt.py`

**Interfaces:**
- Consumes: the docstrings of every module (the API pages render them).
- Produces: the site built by `docs.yml`; `docs/roadmap.md` referenced by the docstrings and the README.

- [ ] **Step 1: Configuration and script**

```bash
cp /home/mkoenig/git/pymetadata/zensical.toml zensical.toml
mkdir -p docs/api scripts
cp /home/mkoenig/git/pymetadata/scripts/llms_txt.py scripts/llms_txt.py
sed -i 's/pymetadata\.omex/sbml2cellml.sbml2cellml/g' scripts/llms_txt.py
sed 's/pymetadata/sbml2cellml/g' /home/mkoenig/git/pymetadata/docs/robots.txt > docs/robots.txt
sed 's/pymetadata/sbml2cellml/g' /home/mkoenig/git/pymetadata/docs/README.md > docs/README.md
touch scripts/__init__.py
grep -n "pymetadata" scripts/llms_txt.py docs/robots.txt docs/README.md
```

Expected: `grep` prints nothing.

Edit `zensical.toml`:
- `site_name = "sbml2cellml"`, `site_url = "https://matthiaskoenig.github.io/sbml2cellml/"`, `site_description = "Conversion of SBML models to CellML"`, `copyright = 'Copyright &copy; 2025-2026 <a href="https://livermetabolism.com">Matthias König</a>'`, `repo_url = "https://github.com/matthiaskoenig/sbml2cellml"`, `repo_name = "matthiaskoenig/sbml2cellml"`.
- remove the `favicon` and `logo` lines of `[project.theme]` (no logo yet).
- `nav`:

```toml
nav = [
  { "Home" = "index.md" },
  { "Installation" = "installation.md" },
  { "User guide" = [
    { "Conversion" = "conversion.md" },
    { "Simulation" = "simulation.md" },
  ] },
  { "Roadmap" = "roadmap.md" },
  { "API reference" = [
    { "Overview" = "api/index.md" },
    { "sbml2cellml" = "api/sbml2cellml.md" },
    { "cellml" = "api/cellml.md" },
    { "mathml" = "api/mathml.md" },
    { "simulate" = "api/simulate.md" },
    { "cli" = "api/cli.md" },
    { "console" = "api/console.md" },
    { "log" = "api/log.md" },
  ] },
  { "Contributing" = "development.md" },
]
```

Keep the theme features, palettes, plugins and markdown extensions unchanged.

- [ ] **Step 2: API pages**

Each `docs/api/<module>.md` contains a heading and the directive, e.g. `docs/api/cellml.md`:

```markdown
# cellml

::: sbml2cellml.cellml
```

Write the seven pages for `sbml2cellml`, `cellml`, `mathml`, `simulate`, `cli`, `console`, `log` (directive `::: sbml2cellml.<module>`). `docs/api/index.md`:

```markdown
# API reference

The API reference is generated from the docstrings of the package.

| module | description |
| --- | --- |
| [sbml2cellml](sbml2cellml.md) | Conversion of SBML models to CellML, `convert_sbml2cellml` |
| [cellml](cellml.md) | Reading, writing and validating CellML models with libcellml |
| [mathml](mathml.md) | MathML fragments of the equations |
| [simulate](simulate.md) | Timecourse simulation with libopencor (optional dependency) |
| [cli](cli.md) | The `sbml2cellml` command |
| [console](console.md) | Shared rich console |
| [log](log.md) | Logging of the package |
```

- [ ] **Step 3: Narrative pages**

`docs/index.md`:

````markdown
# sbml2cellml: conversion of SBML models to CellML
[![GitHub Actions CI/CD Status](https://github.com/matthiaskoenig/sbml2cellml/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/matthiaskoenig/sbml2cellml/actions/workflows/ci-cd.yml) [![Documentation](https://img.shields.io/badge/docs-sbml2cellml-008080.svg)](https://matthiaskoenig.github.io/sbml2cellml) [![Version](https://img.shields.io/pypi/v/sbml2cellml.svg)](https://pypi.org/project/sbml2cellml/) [![Python Versions](https://img.shields.io/pypi/pyversions/sbml2cellml.svg)](https://pypi.org/project/sbml2cellml/) [![MIT License](https://img.shields.io/pypi/l/sbml2cellml.svg)](https://opensource.org/licenses/MIT)

`sbml2cellml` converts models in the [Systems Biology Markup Language (SBML)](https://sbml.org) to [CellML 2.0](https://cellml.org), so that a model developed with SBML tooling can be used, simulated and shared in the CellML ecosystem. The source code is available from [https://github.com/matthiaskoenig/sbml2cellml](https://github.com/matthiaskoenig/sbml2cellml).

## Quickstart

```python
from pathlib import Path
from sbml2cellml import convert_sbml2cellml

model = convert_sbml2cellml(Path("model.xml"), cellml_path=Path("model.cellml"))
```

or on the command line:

```bash
sbml2cellml model.xml -o model.cellml
```

The conversion is validated with [libcellml](https://libcellml.org/); the resulting file can be simulated with [libopencor](https://opencor.ws/libopencor/), see [Simulation](simulation.md).

## What is converted

The converter puts every SBML compartment, parameter and species as a variable into a single CellML component, together with the variable of integration `time`.

| SBML | CellML |
| --- | --- |
| compartment | variable with the size as initial value |
| parameter | variable with the value as initial value |
| species | variable in amount (`hasOnlySubstanceUnits`) or concentration |
| assignment rule | equation |
| rate rule | differential equation |
| reaction | kinetic law added to the differential equation of every reactant and product |
| unit definition | not yet, every variable is `dimensionless` |
| units on numbers in formulas | not yet |
| initial assignment | not yet, a warning is logged |
| function definition | not yet |
| event | not yet, a warning is logged |
| algebraic rule | not yet, a warning is logged |

The [Roadmap](roadmap.md) lists what comes next.

## Citation

The citation information is available with the first release.

## License

- Source Code: [MIT](https://opensource.org/license/MIT)
- Documentation: [CC BY-SA 4.0](http://creativecommons.org/licenses/by-sa/4.0/)

## Funding

Matthias König was supported by the Federal Ministry of Education and Research (BMBF, Germany) within the research network Systems Medicine of the Liver (LiSyM, grant number 031L0054) and within ATLAS by grant number 031L0304B, and by the German Research Foundation (DFG) within the Research Unit Program FOR 5151 QuaLiPerF (Quantifying Liver Perfusion-Function Relationship in Complex Resection - A Systems Medicine Approach) by grant number 436883643 and by grant number 465194077 (Priority Programme SPP 2311, Subproject SimLivA).
````

`docs/installation.md`:

````markdown
# Installation

`sbml2cellml` requires python 3.13 and is available from [pypi](https://pypi.org/project/sbml2cellml). The dependencies [python-libsbml](https://pypi.org/project/python-libsbml/) and [libcellml](https://pypi.org/project/libcellml/) ship wheels for Linux, macOS and Windows; libcellml has no wheel for python 3.14 yet, which is why 3.14 is not supported.

## With uv

```bash
uv add sbml2cellml
```

or into an existing virtual environment

```bash
uv pip install sbml2cellml
```

## With pip

```bash
pip install sbml2cellml
```

## Simulation with libopencor

The `simulate` extra adds pandas and matplotlib for the timecourse results and plots of [`sbml2cellml.simulate`](simulation.md):

```bash
pip install "sbml2cellml[simulate]"
```

The simulator itself, [libopencor](https://opencor.ws/libopencor/), is not on PyPI. Its wheels are published with the [GitHub releases of libopencor](https://github.com/opencor/libopencor/releases); the release page can be used as a package index, e.g. for the release `v1.20260803.0`:

```bash
pip install --find-links https://github.com/opencor/libopencor/releases/expanded_assets/v1.20260803.0 libopencor==1.20260803.0
```

or, with uv,

```bash
uv pip install --find-links https://github.com/opencor/libopencor/releases/expanded_assets/v1.20260803.0 libopencor==1.20260803.0
```

Wheels exist for python 3.12 to 3.14 on Linux (x86_64, aarch64), macOS (Intel, Apple silicon) and Windows. Without libopencor everything except `sbml2cellml.simulate` works.

## Development version

The current state of the `develop` branch is installed from GitHub:

```bash
pip install git+https://github.com/matthiaskoenig/sbml2cellml.git@develop
```

To work on the repository itself see [Development](development.md).
````

`docs/conversion.md`:

````markdown
# Conversion

## Python

[`convert_sbml2cellml`](api/sbml2cellml.md) reads an SBML file, builds the CellML model with libcellml and returns it. With `cellml_path` the CellML is written as well:

```python
from pathlib import Path
from sbml2cellml import convert_sbml2cellml

model = convert_sbml2cellml(Path("model.xml"), cellml_path=Path("model.cellml"))
```

By default the model is validated: the libcellml `Validator` checks it against the CellML specification and the `Analyser` checks that every variable is defined by exactly one equation or initial value. If either reports an error a `CellMLValidationError` with the issues is raised and nothing is written. `validate=False` skips the check, which is useful to inspect a conversion with known gaps; the issues are then available from [`validate_model`](api/cellml.md):

```python
from sbml2cellml.cellml import errors, format_issues, validate_model

model = convert_sbml2cellml(Path("model.xml"), validate=False)
issues = validate_model(model)
print(format_issues(errors(issues)))
```

A file without a model raises `SBML2CellMLConversionError`.

## Logging

The package logs the conversion steps and the constructs it skips (events, initial assignments, algebraic rules, unset initial values) and does not print. Scripts enable the rich output of the package with

```python
from sbml2cellml import log

log.enable_rich_logging()
```

An application configures the `sbml2cellml` logger like any other logger.

## Command line

```bash
sbml2cellml model.xml                      # writes model.cellml next to the input
sbml2cellml model.xml -o out/model.cellml  # explicit output
sbml2cellml model.xml --no-validate        # write even if libcellml reports errors
sbml2cellml model.xml -v                   # log the conversion steps
```

The command exits with 1 and the message on stderr when the input does not exist, has no model, or the validation fails.

## Example models

`examples/models/` in the repository holds the glimepiride models of [matthiaskoenig/glimepiride-model](https://github.com/matthiaskoenig/glimepiride-model), which `examples/glimepiride_example.py` converts. The liver and kidney models convert to valid CellML, the intestine and body models hit the [known gaps](roadmap.md) of the converter.
````

`docs/simulation.md`:

````markdown
# Simulation

[`sbml2cellml.simulate`](api/simulate.md) runs a uniform timecourse of a CellML file with [libopencor](https://opencor.ws/libopencor/), which has to be [installed separately](installation.md#simulation-with-libopencor):

```python
from pathlib import Path
from sbml2cellml.simulate import plot_timecourse, run_timecourse

df, units = run_timecourse(Path("model.cellml"), start=0.0, end=100.0, steps=100)
plot_timecourse(df, units)
```

`run_timecourse` returns a pandas data frame with the variable of integration in the first column, followed by the states and the algebraic variables, and a dictionary with the units of every column. The column names are the variable names of the CellML model, i.e., the SBML ids for a converted model. `steps` is the number of intervals, so the frame has `steps + 1` rows.

libopencor reports a model it cannot simulate, e.g., an invalid or underconstrained model, as issues, which are raised as `SimulationError`. Without libopencor the import of `sbml2cellml.simulate` works, `run_timecourse` raises an `ImportError` with the installation hint.

`examples/cellml_example.py` builds a small model with libcellml directly and simulates it.
````

`docs/roadmap.md`:

```markdown
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
```

`docs/development.md`: copy `/home/mkoenig/git/pymetadata/docs/development.md` and adapt:

```bash
sed 's/pymetadata/sbml2cellml/g' /home/mkoenig/git/pymetadata/docs/development.md > docs/development.md
```

Then edit `docs/development.md`:
- the table of the checks: `tests` row content is "the test matrix, linux, macos and windows with python 3.13".
- "Setup development environment": the sentence on the `dev` extra becomes "The `dev` extra contains everything used below, i.e., pytest, ruff, ty, tox, pre-commit, zensical and bump-my-version, together with the `simulate` extra and libopencor. libopencor is not on PyPI; `[tool.uv.index]` in `pyproject.toml` points uv at the wheels of its GitHub release, so `uv sync` installs it like any other dependency (pip users see [Installation](installation.md#simulation-with-libopencor))."; the python version sentence becomes "The python version is taken from `.python-version` (3.13, the only supported version until libcellml ships a wheel for 3.14)."
- "Testing": tox environments are `py3.13` and `ty`, replace `py3.11` to `py3.14` mentions accordingly; `uv python install 3.13`; replace the sentence on web services by "The simulation tests and the examples need libopencor and are skipped without it; with `uv sync --extra dev` it is installed."; add after the tox paragraph: "The tox environments are created from `uv.lock` by tox-uv (`runner = uv-venv-lock-runner` in `tox.ini`), which is what makes the libopencor index available to them."
- remove the section "Regenerating the ontologies" and the step 2 of "Release" which refers to it (renumber the steps).
- add a section before "Release":

```markdown
## Repository setup { #repository-setup }

The one-time setup of the GitHub repository, for the record:

1. `develop` is created from `main` and made the default branch: `gh repo edit matthiaskoenig/sbml2cellml --default-branch develop`
2. the merge settings and rulesets are applied: `.github/rulesets/apply.sh`
3. the GitHub Pages source is set to GitHub Actions: `gh api -X POST repos/matthiaskoenig/sbml2cellml/pages -f build_type=workflow`
4. the PyPI trusted publisher is registered on [pypi.org](https://pypi.org/manage/account/publishing/) for the project `sbml2cellml`, owner `matthiaskoenig`, repository `sbml2cellml`, workflow `ci-cd.yml`, environment `pypi` (as a pending publisher before the first release)
5. the repository is enabled in the [Zenodo GitHub integration](https://zenodo.org/account/settings/github/), so that a GitHub release is archived with a DOI
```

- "Release" step 9: `uv venv --python 3.13`.
- read the whole file once and remove anything which only applies to pymetadata (ontologies, `pronto`, web services, `CODEOWNERS` stays).

- [ ] **Step 4: Build the site**

```bash
uv run zensical build --clean
uv run python scripts/llms_txt.py
ls site/llms.txt site/llms-full.txt site/api/cellml/index.html
grep -c "convert_sbml2cellml" site/api/sbml2cellml/index.html
```

Expected: the build has no warnings about missing pages or unresolved `:::` directives, the files exist and the grep count is at least 1. A warning of mkdocstrings about a docstring is a docstring bug: fix the docstring.

- [ ] **Step 5: Lint, type check, commit**

```bash
uv run ruff check && uv run ruff format && uv run ty check
git add zensical.toml docs scripts
git commit -m "Add the zensical documentation

```

`docs/superpowers/` is already committed and is not in the nav, so zensical ignores it for navigation but still renders it; that is acceptable.

---

### Task 10: README, citation, Zenodo, license, release notes, CLAUDE.md

**Files:**
- Create: `README.md` (replace), `CITATION.cff`, `.zenodo.json` (replace), `LICENSE` (replace), `release-notes/0.1.0.md`, `CLAUDE.md`

- [ ] **Step 1: `README.md`**

````markdown
# sbml2cellml: conversion of SBML models to CellML
[![GitHub Actions CI/CD Status](https://github.com/matthiaskoenig/sbml2cellml/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/matthiaskoenig/sbml2cellml/actions/workflows/ci-cd.yml) [![Documentation](https://img.shields.io/badge/docs-sbml2cellml-008080.svg)](https://matthiaskoenig.github.io/sbml2cellml) [![Version](https://img.shields.io/pypi/v/sbml2cellml.svg)](https://pypi.org/project/sbml2cellml/) [![Python Versions](https://img.shields.io/pypi/pyversions/sbml2cellml.svg)](https://pypi.org/project/sbml2cellml/) [![MIT License](https://img.shields.io/pypi/l/sbml2cellml.svg)](https://opensource.org/licenses/MIT)

`sbml2cellml` converts models in the [Systems Biology Markup Language (SBML)](https://sbml.org) to [CellML 2.0](https://cellml.org), with documentation available from [https://matthiaskoenig.github.io/sbml2cellml](https://matthiaskoenig.github.io/sbml2cellml).

Features include

- conversion of compartments, parameters, species, assignment and rate rules and reactions into a single CellML component
- validation of the result with libcellml
- timecourse simulation of the CellML with libopencor
- the `sbml2cellml` command line

```bash
pip install sbml2cellml
sbml2cellml model.xml -o model.cellml
```

Units, events, initial assignments, function definitions and algebraic rules are not converted yet, see the [roadmap](https://matthiaskoenig.github.io/sbml2cellml/roadmap/).

If you have any questions or issues please [open an issue](https://github.com/matthiaskoenig/sbml2cellml/issues).

# How to cite

The Zenodo DOI and the citation are available with the first release.

# License
- Source Code: [MIT](https://opensource.org/license/MIT)
- Documentation: [CC BY-SA 4.0](http://creativecommons.org/licenses/by-sa/4.0/)

# Funding
Matthias König was supported by the Federal Ministry of Education and Research (BMBF, Germany) within the research network Systems Medicine of the Liver (LiSyM, grant number 031L0054) and within ATLAS by grant number 031L0304B, and by the German Research Foundation (DFG) within the Research Unit Program FOR 5151 QuaLiPerF (Quantifying Liver Perfusion-Function Relationship in Complex Resection - A Systems Medicine Approach) by grant number 436883643 and by grant number 465194077 (Priority Programme SPP 2311, Subproject SimLivA).

© 2025-2026 Matthias König
````

- [ ] **Step 2: `CITATION.cff`**

```yaml
cff-version: 1.2.0
message: "If you use sbml2cellml, please cite it as below."
title: "sbml2cellml: conversion of SBML models to CellML"
abstract: "sbml2cellml converts models in the Systems Biology Markup Language (SBML) to CellML 2.0."
type: software
authors:
  - family-names: "König"
    given-names: "Matthias"
    orcid: "https://orcid.org/0000-0003-1725-179X"
    affiliation: "Humboldt-University Berlin, Faculty of Life Science, Institute for Biology, Biology, Berlin; University Lübeck; University Hospital Schleswig-Holstein, Campus Lübeck, First Department of Medicine, Germany"
version: "0.1.0"
license: MIT
repository-code: "https://github.com/matthiaskoenig/sbml2cellml"
url: "https://matthiaskoenig.github.io/sbml2cellml"
keywords:
  - modeling
  - standardization
  - COMBINE
  - SBML
  - CellML
  - converter
```

`date-released` and `doi` are added with the first release (see the release steps in `docs/development.md`).

- [ ] **Step 3: `.zenodo.json`**

```json
{
  "upload_type": "software",
  "title": "sbml2cellml: conversion of SBML models to CellML",
  "creators": [
    {
      "orcid": "0000-0003-1725-179X",
      "affiliation": "Humboldt-University Berlin, Faculty of Life Science, Institute for Biology, Biology, Berlin; University Lübeck; University Hospital Schleswig-Holstein, Campus Lübeck, First Department of Medicine, Germany",
      "name": "König, Matthias"
    }
  ],
  "description": "<p><code>sbml2cellml</code> converts models in the Systems Biology Markup Language (SBML) to CellML 2.0, with source code available from <a href=\"https://github.com/matthiaskoenig/sbml2cellml\">https://github.com/matthiaskoenig/sbml2cellml</a> and documentation from <a href=\"https://matthiaskoenig.github.io/sbml2cellml\">https://matthiaskoenig.github.io/sbml2cellml</a>.</p><p>If you have any questions or issues please <a href=\"https://github.com/matthiaskoenig/sbml2cellml/issues\">open an issue</a>.</p><h2>Funding</h2><p>Matthias König (MK) was supported by the Federal Ministry of Education and Research (BMBF, Germany) within the research network Systems Medicine of the Liver (LiSyM, grant number 031L0054). MK is supported by the Federal Ministry of Education and Research (BMBF, Germany) within ATLAS by grant number 031L0304B and by the German Research Foundation (DFG) within the Research Unit Program FOR 5151 QuaLiPerF (Quantifying Liver Perfusion-Function Relationship in Complex Resection - A Systems Medicine Approach) by grant number 436883643 and by grant number 465194077 (Priority Programme SPP 2311, Subproject SimLivA).</p>",
  "access_right": "open",
  "license": "MIT",
  "keywords": [
    "modeling",
    "standardization",
    "COMBINE",
    "SBML",
    "CellML",
    "converter"
  ]
}
```

- [ ] **Step 4: `LICENSE` and `release-notes/0.1.0.md`**

In `LICENSE` change the first line to `Copyright (c) 2025-2026 Matthias König`, nothing else.

`release-notes/0.1.0.md`:

```markdown
# Release notes for sbml2cellml 0.1.0

First release of sbml2cellml, the conversion of SBML models to CellML 2.0.

## Features
- `convert_sbml2cellml` converts compartments, parameters, species, assignment and rate rules and reactions into a single CellML component and validates the result with libcellml
- `sbml2cellml.simulate` runs a timecourse of a CellML file with libopencor and returns a pandas data frame
- the `sbml2cellml` command line

## Limitations
- units are not converted, every variable is dimensionless
- events, initial assignments, function definitions and algebraic rules are not converted
- see the roadmap in the documentation

Your sbml2cellml team
```

- [ ] **Step 5: `CLAUDE.md`**

````markdown
# CLAUDE.md

This file provides guidance when working with code in this repository.

## Project

`sbml2cellml` converts SBML models to CellML 2.0 with libsbml and libcellml and
simulates the result with libopencor. Python 3.13 only (libcellml has no wheel
for 3.14 yet), packaged with hatchling (version in `src/sbml2cellml/__init__.py`).
Runtime dependencies: `python-libsbml`, `libcellml`, `rich`. The
`simulate` extra adds `pandas` and `matplotlib`; libopencor itself is not on
PyPI and comes from a uv flat index on its GitHub release (`[tool.uv.index]`
in `pyproject.toml`), it is part of the `dev` extra.

## Commands

```bash
uv sync --extra dev             # environment, includes libopencor
uv run pre-commit install

pytest                          # all tests (parallel, pytest-xdist)
pytest tests/test_sbml2cellml.py::test_simple_model_initial_values
tox r -e py3.13                 # tests from uv.lock via tox-uv
tox r -e ty                     # type check
tox run-parallel

ruff check
ruff format
uvx ty check

uv run zensical build --clean   # docs into site/
uv run python scripts/llms_txt.py
uv run zensical serve

sbml2cellml model.xml -o model.cellml
```

`develop` is the default branch and takes every change through a pull request;
the rulesets in `.github/rulesets/` (applied with `apply.sh`) require the
`tests`, `ruff`, `ty` and `docs` checks. `main` tracks the latest release and
is fast-forwarded by the `sync-main` job of the release workflow. Release
steps are in `docs/development.md`: release branch,
`uvx bump-my-version bump [major|minor|patch]` (updates `__init__.py` and
`CITATION.cff`, no tag), release notes in `release-notes/`, pull request, tag
on `develop` after the merge.

## Architecture

- `sbml2cellml.py`: `convert_sbml2cellml(sbml_path, cellml_path=None, validate=True)`.
  One CellML component `sbml`, one variable per compartment, parameter and
  species plus `time`, all `dimensionless`. Assignment rules become equations,
  rate rules and kinetic laws differential equations; a concentration species
  gets its reaction terms divided by the compartment. Events, initial
  assignments, algebraic rules and unset initial values (set to 1.0) are logged
  as warnings. The generated CellML is a fixed contract: tests compare the
  structure and the validity of the example models.
- `mathml.py`: libsbml renders formulas as MathML documents; the helpers strip
  the declaration and `math` element, map `sbml:units` to `cellml:units` and
  wrap the equations into the component math.
- `cellml.py`: libcellml `Parser`, `Printer`, `Validator` and `Analyser`
  wrappers; issues are returned, `errors()` filters level `ERROR`,
  `CellMLValidationError`.
- `simulate.py`: libopencor timecourse; the library is imported inside
  `run_timecourse` so the package works without it. The settings are applied
  to `document.simulations[0]`. Results drop the `component/` prefix of the
  variable names. Issues raise `SimulationError`.
- `cli.py`: argparse, `[project.scripts]` entry point.
- `console.py`, `log.py`: rich console for scripts and the CLI, opt-in rich
  logging. Library code logs with `logging.getLogger(__name__)` and lazy `%s`
  formatting (ruff `G`), it never prints.

## Conventions

- ty with `error-on-warning = true`: zero diagnostics, rule specific
  `# ty: ignore[rule-name]` only.
- Full type annotations and google-style docstrings on every module, class and
  function (ruff `D`; `examples/` and `tests/` exempt).
- `examples/` at the top level holds the runnable examples and
  `examples/models/` the glimepiride SBML models and `test_model.cellml`; the
  tests read the models via `MODELS_DIR` in `tests/conftest.py`. Generated
  CellML goes to the gitignored `examples/results/`. Small fixtures created
  for a test go to `tests/data/`.
- Known conversion gaps are documented in `docs/roadmap.md` and encoded in the
  tests (`INVALID_MODELS` in `tests/test_sbml2cellml.py`, the kidney model in
  `tests/test_simulate.py`); fixing a gap means removing the model from the
  list, not weakening the assertion.
- No em dash in any text, use `-`.
- Release notes go in `release-notes/` as part of a release commit.
- `references/` holds the CellML specification and libopencor notes, it is not
  part of the documentation site.
````

- [ ] **Step 6: Check and commit**

```bash
uv run python -c "import json; json.load(open('.zenodo.json')); print('ok')"
uv run --with cffconvert cffconvert --validate 2>/dev/null || echo "cffconvert not available, skip"
grep -rn "—" README.md CITATION.cff CLAUDE.md docs/*.md release-notes/0.1.0.md || echo "no em dash"
uv run zensical build --clean
git add README.md CITATION.cff .zenodo.json LICENSE release-notes CLAUDE.md
git commit -m "Add the README, citation, Zenodo metadata, release notes and CLAUDE.md

```

Expected: `ok`, `no em dash`, the site builds.

---

### Task 11: Repository setup and pull request

Run by the main session, not a subagent: it changes GitHub settings.

- [ ] **Step 1: Full verification on the branch**

```bash
uv run pre-commit run --all-files
uv run tox run-parallel
uv run zensical build --clean && uv run python scripts/llms_txt.py
uvx hatch build && uvx twine check dist/*
rm -rf dist
```

Expected: all green. The wheel contains `sbml2cellml/*.py` only (no `examples`, no `tests`): `unzip -l dist/*.whl` before removing `dist`.

- [ ] **Step 2: Create `develop` and make it the default branch**

```bash
git push -u origin s1-infrastructure
git branch develop main
git push -u origin develop
gh repo edit matthiaskoenig/sbml2cellml --default-branch develop
gh repo view matthiaskoenig/sbml2cellml --json defaultBranchRef -q .defaultBranchRef.name
```

Expected: `develop`.

- [ ] **Step 3: Apply the rulesets and the merge settings**

```bash
.github/rulesets/apply.sh
gh api repos/matthiaskoenig/sbml2cellml/rulesets --jq '.[].name'
```

Expected: `develop`, `main`, `tags`.

- [ ] **Step 4: GitHub Pages from Actions**

```bash
gh api -X POST repos/matthiaskoenig/sbml2cellml/pages -f build_type=workflow
```

Expected: HTTP 201, or 409 if Pages exists already; then `gh api -X PUT repos/matthiaskoenig/sbml2cellml/pages -f build_type=workflow`.

- [ ] **Step 5: Open the pull request**

```bash
gh pr create --base develop --head s1-infrastructure --title "Package and infrastructure baseline (S1)" --body "$(cat <<'EOF'
## Summary

Turns the migrated scripts into a releasable package following the conventions of pymetadata and sbmlsim:

- src layout with one module per concern: converter, libcellml helpers, MathML helpers, libopencor simulation, CLI, console and logging
- packaging with hatchling and uv, libopencor from a flat index on its GitHub release
- tests with pytest (parallel) and tox-uv; the generated CellML is unchanged
- GitHub Actions for tests, ruff, ty, docs and the PyPI release, rulesets for develop, main and tags
- zensical documentation with API reference and roadmap
- README, CITATION.cff, .zenodo.json, release notes, CLAUDE.md

Spec: `docs/superpowers/specs/2026-09-16-s1-package-infrastructure-design.md`, plan: `docs/superpowers/plans/2026-09-16-s1-package-infrastructure.md`.

## Checklist

- [x] the pull request targets `develop`
- [x] tests were added or updated for the change
- [x] `tox run-parallel` passes locally (tests and `ty`)
- [x] `ruff check` and `ruff format` are clean, e.g., via `pre-commit run --all-files`
- [x] public functions and classes have type annotations and a docstring
- [x] user visible changes are in `release-notes/` and, if needed, in `docs/`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
gh pr checks --watch
```

Expected: the four checks `tests`, `ruff`, `ty`, `docs` pass. A failing check is fixed on the branch and pushed; the pull request is not merged by the plan, the maintainer merges it.

- [ ] **Step 6: Manual steps for the maintainer**

Report these to the maintainer, they cannot be scripted:

1. PyPI trusted publisher (pending) for `sbml2cellml`: owner `matthiaskoenig`, repository `sbml2cellml`, workflow `ci-cd.yml`, environment `pypi`, at https://pypi.org/manage/account/publishing/
2. Zenodo GitHub integration for `matthiaskoenig/sbml2cellml` at https://zenodo.org/account/settings/github/
3. Merge the pull request, then release `0.1.0` following `docs/development.md`.
