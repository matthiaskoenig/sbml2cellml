"""Compare the rust converter of SBML to CellML with the python converter.

The rust converter (`crates/tocellml`, the command `sbml-convert`) writes the
CellML 2.0 of an SBML document without libsbml and without libcellml; the
python converter (`sbml2cellml.sbml2cellml`) writes it with libsbml and
libcellml. Both are run over the SBML models of the repository, the cases of
the SBML test suite and the models of the BioModels check, the CellML of the
rust converter is validated with libcellml, and the two models are compared:
every variable with its units and its initial value, every equation by the
variable it determines, and the names of the unit definitions. The
mathematics is compared as a canonical expression of the MathML of both
sides, so an equation which differs is found whatever the two write it as.

The rust converter refuses what it does not convert yet (an algebraic rule,
an event, an initial assignment, a formula with a delay), which the summary
counts apart from a document which needs a package the reader does not read
(`comp`, whose submodels the python converter flattens with libsbml).

The units of a variable and of a number are compared by what they are and
not by the name they carry: both converters take a unit definition of the
SBML model for the units of a concentration when it means the same units,
and they pick a different one when the model states the same units in two
ways (a scale of `-3` against a multiplier of `0.001`, which libsbml and
with it the python converter do not take for each other). An initial value
is compared to twelve significant digits, since libcellml writes fifteen of
them and the rust writer every digit of the double.

Of the 1692 cases of the SBML test suite, 998 are converted by both
converters and 997 of them give the same CellML model; 569 are refused by
the rust converter and 125 need `comp`. Of the 1075 models of BioModels, 896
are converted by both and 895 of them give the same model.

The two models which differ differ because the rust converter is right and
the python converter follows libsbml:

- case `01282` of the test suite: libsbml evaluates a number as a condition
  of a `piecewise` as true only when it is 1, where every simulator and the
  rust converter take a value which is not zero as true. The expected result
  of the case is the value of the rust converter.
- `BIOMD0000000040` of BioModels: the rust path converts the
  `<stoichiometryMath>` of a species reference, which the reader of SBML
  writes as an assignment rule of the id it gives the reference, where the
  python converter takes the stoichiometry as it stands (issue #86).

The script is run locally, like the checks of BioModels and of the Physiome
repository, and needs the command line of the rust workspace:

```bash
cargo build --release
uv run python scripts/sbml2cellml_parity.py
uv run python scripts/sbml2cellml_parity.py --count 50 -v
uv run python scripts/sbml2cellml_parity.py --corpus suite --count 200
```
"""

import argparse
import math
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
from collections import Counter
from pathlib import Path
from typing import Any

import libcellml

from sbml2cellml import cellml
from sbml2cellml.sbml2cellml import convert_sbml2cellml

REPO = Path(__file__).parent.parent
#: the command line of the rust workspace
BINARY = REPO / "target" / "release" / "sbml-convert"
#: the SBML models of the repository
MODELS = sorted((REPO / "examples" / "models").glob("*.xml"))
#: the namespace of MathML, which every element of a formula is in
MATHML = "{http://www.w3.org/1998/Math/MathML}"
#: the attribute of the units of a number
UNITS = "{http://www.cellml.org/cellml/2.0#}units"
#: significant digits of a number of a formula, so that the notation of a
#: value is no difference: libcellml writes a number with 16 of them and the
#: rust writer every digit of the double
DIGITS = 12

#: the relative tolerance of the comparison of two initial values, which the
#: notation of libcellml rounds
TOLERANCE = 1e-9


def corpus(which: str, count: int | None) -> list[Path]:
    """The SBML files of a corpus.

    Args:
        which: `models` for the models of the repository, `suite` for the
            cases of the SBML test suite, `biomodels` for the models of the
            BioModels check, `all` for all of them.
        count: at most this many files, all of them for `None`.

    Returns:
        The paths of the SBML files.
    """
    paths: list[Path] = []
    if which in ("models", "all"):
        paths.extend(MODELS)
    if which in ("suite", "all"):
        from sbml2cellml.testsuite.cases import ensure_suite, load_cases

        root = ensure_suite()
        paths.extend(
            case.sbml_path for case in load_cases(root) if case.sbml_path is not None
        )
    if which in ("biomodels", "all"):
        from sbml2cellml.biomodels.models import biomodels_cache

        paths.extend(sorted(biomodels_cache().glob("*/*.xml")))
    return paths[:count] if count else paths


def rust_cellml(path: Path, target: Path) -> str | None:
    """Convert a document with the rust converter.

    Args:
        path: the SBML file.
        target: where the CellML is written.

    Returns:
        `None` when the conversion worked, else the message of its failure.
    """
    result = subprocess.run(
        [str(BINARY), str(path), "-o", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        lines = [line for line in result.stderr.strip().splitlines() if line.strip()]
        return lines[-1].split(": ", 1)[-1] if lines else "failed"
    return None


def python_cellml(path: Path, target: Path) -> str | None:
    """Convert a document with the python converter.

    Args:
        path: the SBML file.
        target: where the CellML is written.

    Returns:
        `None` when the conversion worked, else the message of its failure.
    """
    try:
        convert_sbml2cellml(path, target, validate=False, metadata=False)
    except Exception as err:
        return str(err).splitlines()[0]
    return None


def validation_errors(path: Path) -> list[str]:
    """The errors libcellml reports for a CellML file.

    Only the validator runs: whether the model is complete is not the
    business of the conversion, and the analyser of libcellml refuses a
    model whose unknowns it cannot match.
    """
    model = cellml.read_model(path)
    validator = libcellml.Validator()
    validator.validateModel(model)
    issues = [validator.issue(k) for k in range(validator.issueCount())]
    return [issue.description() for issue in cellml.errors(issues)]


def summary(path: Path) -> dict[str, Any]:
    """What a CellML file holds, for the comparison.

    The units of a variable and of a number are compared by what they are
    and not by their name: the two converters name the units of a
    concentration differently when the SBML model has a definition which
    means the same units and writes them differently, and such a name is no
    difference between the two models. `_classes` gives every name of the
    units of the model the name of the first of the equivalent ones, which
    libcellml compares.

    Args:
        path: the CellML file.

    Returns:
        The variables with their units and their initial value, and the
        equations by the variable they determine.
    """
    model = cellml.read_model(path)
    classes = _classes(model)
    variables: dict[str, tuple[str, str]] = {}
    equations: dict[str, str] = {}
    for index in range(model.componentCount()):
        component = model.component(index)
        for k in range(component.variableCount()):
            variable = component.variable(k)
            name = (
                variable.units().name()
                if variable.units() is not None
                else str(variable.units())
            )
            variables[variable.name()] = (
                classes.get(name) or _content(model, name),
                _number(variable.initialValue()),
            )
        equations.update(_equations(component.math(), classes))
    return {"variables": variables, "equations": equations}


def _classes(model: libcellml.Model) -> dict[str, str]:
    """What the units of every name of the model are, as a canonical text.

    The units are expanded to the base units of CellML with their exponent
    and the factor of the prefixes and the multipliers, so that units of the
    two models are compared by what they are and not by the name a converter
    gives them: `uM` of the SBML model and the `substance_per_litre` the
    python converter adds for the same quotient are the same units.
    """
    return {
        model.units(k).name(): _content(model, model.units(k).name())
        for k in range(model.unitsCount())
    }


def _content(model: libcellml.Model, name: str, depth: int = 0) -> str:
    """The units of a name as the base units they are, with their factor."""
    exponents: dict[str, float] = {}
    factor = 1.0
    for base, exponent, scale in _base_units(model, name, 1.0, 0, depth):
        exponents[base] = exponents.get(base, 0.0) + exponent
        factor *= scale
    # `dimensionless` is no dimension: units of it to any power are the
    # units without it, where its factor stays
    terms = " ".join(
        f"{base}^{exponent:g}"
        for base, exponent in sorted(exponents.items())
        if exponent != 0.0 and base != "dimensionless"
    )
    return f"{terms} * {factor:.9g}"


def _base_units(
    model: libcellml.Model, name: str, exponent: float, prefix: int, depth: int
) -> list[tuple[str, float, float]]:
    """The base units of a name, every one with its exponent and its factor."""
    units = model.units(name) if depth < 20 else None
    if units is None or units.unitCount() == 0:
        # a standard unit of CellML, or new base units of the model
        return [(name, exponent, 10.0 ** (prefix * exponent))]
    found: list[tuple[str, float, float]] = []
    for index in range(units.unitCount()):
        reference, inner_prefix, inner_exponent, multiplier, _ = units.unitAttributes(
            index
        )
        power = exponent * inner_exponent
        factor = multiplier**exponent
        found.extend(
            _base_units(model, reference, power, _prefix(inner_prefix), depth + 1)
        )
        found.append(("", 0.0, factor * 10.0 ** (prefix * power)))
    return found


def _prefix(prefix: str) -> int:
    """The power of ten of a prefix of CellML, by name or as the number."""
    prefixes = {
        "yotta": 24,
        "zetta": 21,
        "exa": 18,
        "peta": 15,
        "tera": 12,
        "giga": 9,
        "mega": 6,
        "kilo": 3,
        "hecto": 2,
        "deca": 1,
        "deci": -1,
        "centi": -2,
        "milli": -3,
        "micro": -6,
        "nano": -9,
        "pico": -12,
        "femto": -15,
        "atto": -18,
        "zepto": -21,
        "yocto": -24,
    }
    if prefix in prefixes:
        return prefixes[prefix]
    try:
        return int(prefix)
    except ValueError:
        return 0


def _number(value: str) -> str:
    """A number as the comparison writes it, the text for a variable."""
    try:
        return f"{float(value):.{DIGITS}g}"
    except ValueError:
        return value


def _equations(math: str, classes: dict[str, str]) -> dict[str, str]:
    """The equations of the mathematics of a component.

    Args:
        math: the `<math>` elements of the component, as libcellml gives
            them (several documents one after the other).
        classes: the name of the units of every equivalent name.

    Returns:
        The right-hand side of every equation as a canonical expression, by
        the variable the equation determines (`d x` for a differential
        equation).
    """
    equations: dict[str, str] = {}
    for part in _documents(math):
        try:
            root = ElementTree.fromstring(part)
        except ElementTree.ParseError as err:
            equations[f"unparsed {len(equations)}"] = str(err)
            continue
        for element in root:
            if _tag(element) != "apply":
                continue
            children = list(element)
            if len(children) != 3 or _tag(children[0]) != "eq":
                equations[_expression(element, classes)] = ""
                continue
            equations[_expression(children[1], classes)] = _expression(
                children[2], classes
            )
    return equations


def _documents(math: str) -> list[str]:
    """The `<math>` documents of a string of them, an empty one included."""
    parts = []
    rest = math
    while "<math" in rest:
        start = rest.index("<math")
        close = rest.find("</math>")
        if close < 0:
            # `<math/>`, a component without an equation
            break
        end = close + len("</math>")
        parts.append(rest[start:end])
        rest = rest[end:]
    return parts


def _tag(element: ElementTree.Element) -> str:
    """The name of an element without the namespace of MathML."""
    return element.tag.removeprefix(MATHML)


def _expression(element: ElementTree.Element, classes: dict[str, str]) -> str:
    """A formula as a canonical expression.

    Every operator is written as a call of the name of its element, so that
    the expression says what the formula computes and nothing of how the two
    converters write it.
    """
    tag = _tag(element)
    text = (element.text or "").strip()
    if tag == "cn":
        value = _cn(element)
        units = element.get(UNITS, "")
        return f"{value}[{classes.get(units, units)}]" if units else value

    if tag == "ci":
        return text
    if tag == "apply":
        children = list(element)
        if not children:
            return "apply()"
        head, arguments = children[0], children[1:]
        if _tag(head) == "diff":
            # `d x / d t`, the bvar is the variable of integration
            variable = [
                _expression(child, classes)
                for child in arguments
                if _tag(child) != "bvar"
            ]
            return f"d {' '.join(variable)}"
        return f"{_tag(head)}({', '.join(_expression(child, classes) for child in arguments)})"
    if tag == "piecewise":
        parts = []
        for child in element:
            values = [_expression(piece, classes) for piece in child]
            parts.append(f"{_tag(child)}({', '.join(values)})")
        return f"piecewise({', '.join(parts)})"
    if tag in ("bvar", "degree", "logbase"):
        return f"{tag}({', '.join(_expression(child, classes) for child in element)})"
    if tag == "math":
        return ", ".join(_expression(child, classes) for child in element)
    return (
        tag
        if not list(element)
        else f"{tag}({', '.join(_expression(child, classes) for child in element)})"
    )


def _cn(element: ElementTree.Element) -> str:
    """The value of a number, the e-notation of MathML included."""
    text = (element.text or "").strip()
    if element.get("type") == "e-notation":
        exponent = "".join((child.tail or "").strip() for child in element)
        text = f"{text}e{exponent}"
    return _number(text)


def differences(rust: dict[str, Any], reference: dict[str, Any]) -> list[str]:
    """What the two models differ in, the first few of every kind."""
    found: list[str] = []
    for key in ("variables", "equations"):
        mine, theirs = rust[key], reference[key]
        missing = sorted(set(theirs) - set(mine))
        extra = sorted(set(mine) - set(theirs))
        if missing:
            found.append(f"{key} only in python: {missing[:3]}")
        if extra:
            found.append(f"{key} only in rust: {extra[:3]}")
        for name in sorted(set(mine) & set(theirs)):
            if not _same(mine[name], theirs[name]):
                found.append(f"{key} of {name}: {mine[name]} != {theirs[name]}")
                break
    return found


def _same(mine: Any, theirs: Any) -> bool:
    """Whether a variable or an equation of the two models is the same.

    A value is compared with a relative tolerance: libcellml writes an
    initial value with 16 digits and the rust writer every digit of the
    double, so the same value is written differently.
    """
    if isinstance(mine, tuple) and isinstance(theirs, tuple):
        units, value = mine
        their_units, their_value = theirs
        return units == their_units and _close(value, their_value)
    return bool(mine == theirs)


def _close(mine: str, theirs: str) -> bool:
    """Whether two values are the same number, or the same text."""
    try:
        return math.isclose(float(mine), float(theirs), rel_tol=TOLERANCE, abs_tol=0.0)
    except ValueError:
        return mine == theirs


def check(path: Path, verbose: bool) -> str:
    """Convert one model with both converters and compare the two.

    Returns:
        `ok` when both convert the model to the same CellML, `refused` when
        the rust converter does not convert the model, `package` when the
        document needs a package the reader does not read, `invalid` when
        libcellml reports an error for what the rust converter writes and
        not for what the python converter writes, `differs` when the two
        models differ, `python` when the python converter alone fails and
        `unreadable` when a written model cannot be read again.
    """
    with tempfile.TemporaryDirectory() as directory:
        mine = Path(directory) / "rust.cellml"
        theirs = Path(directory) / "python.cellml"
        failure = rust_cellml(path, mine)
        if failure is not None:
            # a package the reader does not read, e.g. comp, whose submodels
            # the python converter flattens with libsbml, apart from what
            # the converter itself refuses
            kind = "package" if "is not supported" in failure else "refused"
            if verbose:
                print(f"  {kind}: {path.name}: {failure}")
            return kind
        other = python_cellml(path, theirs)
        if other is not None:
            if verbose:
                print(f"  python: {path.name}: {other}")
            return "python"
        errors = validation_errors(mine)
        # a model which the python converter writes just as invalid is no
        # difference between the two: libcellml has no factorial, for
        # example, and neither converter writes anything else for it
        if errors and not validation_errors(theirs):
            print(f"  invalid: {path.name}: {errors[0]}")
            return "invalid"
        try:
            found = differences(summary(mine), summary(theirs))
        except Exception as err:
            print(f"  unreadable: {path.name}: {err}")
            return "unreadable"
        if found:
            print(f"  differs: {path.name}")
            for difference in found:
                print(f"    {difference}")
            return "differs"
        if verbose:
            print(f"  ok: {path.name}")
        return "ok"


def main() -> int:
    """Run the comparison over a corpus and print the summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        default="all",
        choices=("models", "suite", "biomodels", "all"),
        help="which models to compare",
    )
    parser.add_argument(
        "--count", type=int, default=None, help="at most this many models"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="every model")
    arguments = parser.parse_args()
    if not BINARY.is_file():
        print(f"build the workspace first: {BINARY} is missing")
        return 1
    files = corpus(arguments.corpus, arguments.count)
    print(f"{len(files)} models")
    counts: Counter[str] = Counter()
    for path in files:
        counts[check(path, arguments.verbose)] += 1
    print(
        ", ".join(f"{kind}: {count}" for kind, count in sorted(counts.items()))
        or "nothing to compare"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
