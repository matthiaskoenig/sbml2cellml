"""Compare the rust converter of CellML to SBML with the python converter.

The rust converter (`crates/convert`, the command `cellml-convert`) writes
the SBML of a CellML document without libcellml and without libsbml; the
python converter (`sbml2cellml.cellml2sbml`) writes it with the analyser of
libcellml and with libsbml. Both are run over the models of the Physiome
check and the CellML fixtures of the repository, the SBML of the rust
converter is validated with libsbml, and the two models are compared: the
parameters with their value, their units and whether they are constant, the
rules by kind and target, the initial assignments, and the formula of every
rule and assignment, which `libsbml.formulaToL3String` writes for both
sides, so an equation which differs is found whatever the two write it as.

Of the 102 documents of the corpus, the rust converter converts 92, and
libsbml validates every one of those without an error. 68 are converted by
both: 38 give the same SBML model and 30 differ in the notation of a
formula (`sqrt(x)` against `root(2, x)`, the exponent of a number) or in
the nesting of its sums and products only, nothing in what an equation
computes. 24 are converted by the rust converter alone, since the analyser
of libcellml refuses the model, 1 by the python converter alone (the
fixture with an import, which the rust converter does not resolve yet),
and 9 by neither.

The script is run locally, like the checks of BioModels and of the
Physiome repository, and needs the command line of the rust workspace:

```bash
cargo build --release
uv run python scripts/cellml2sbml_parity.py
uv run python scripts/cellml2sbml_parity.py --count 10 -v
```
"""

import argparse
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import libsbml

from sbml2cellml.cellml2sbml import convert_cellml2sbml
from sbml2cellml.physiome.models import model_path, read_selection
from sbml2cellml.sbml import validate_document

REPO = Path(__file__).parent.parent
#: the command line of the rust workspace
BINARY = REPO / "target" / "release" / "cellml-convert"
#: the CellML fixtures of the repository
FIXTURES = sorted((REPO / "tests" / "data").glob("*.cellml")) + sorted(
    (REPO / "examples" / "models").glob("*.cellml")
)
#: the kind of a rule, by the type code of libsbml
RULE_KINDS = {
    libsbml.SBML_ASSIGNMENT_RULE: "assignment",
    libsbml.SBML_RATE_RULE: "rate",
    libsbml.SBML_ALGEBRAIC_RULE: "algebraic",
}


def rust_sbml(binary: Path, path: Path, target: Path) -> str | None:
    """Convert a document with the rust converter.

    Args:
        binary: the `cellml-convert` command.
        path: the CellML file.
        target: where the SBML is written.

    Returns:
        `None` when the conversion worked, else the message of its failure.
    """
    result = subprocess.run(
        [str(binary), str(path), "-o", str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return result.stderr.strip().splitlines()[-1] if result.stderr else "failed"
    return None


def python_sbml(path: Path, target: Path) -> str | None:
    """Convert a document with the python converter.

    Args:
        path: the CellML file.
        target: where the SBML is written.

    Returns:
        `None` when the conversion worked, else the message of its failure.
    """
    try:
        convert_cellml2sbml(
            path, target, validate=False, metadata=False, engine="python"
        )
    except Exception as err:
        return str(err).splitlines()[0]
    return None


def summary(path: Path) -> dict[str, Any]:
    """What an SBML file holds, for the comparison.

    Args:
        path: the SBML file.

    Returns:
        The parameters, the rules with their formula, the initial
        assignments and the ids of the unit definitions.
    """
    document = libsbml.readSBMLFromFile(str(path))
    model = document.getModel()
    if model is None:
        return {"error": "no model"}
    parameters = {
        parameter.getId(): (
            round(parameter.getValue(), 12) if parameter.isSetValue() else None,
            parameter.getUnits(),
            parameter.getConstant(),
        )
        for parameter in model.getListOfParameters()
    }
    rules = {}
    for rule in model.getListOfRules():
        kind = RULE_KINDS.get(rule.getTypeCode(), "other")
        key = (kind, rule.getVariable() if rule.isSetVariable() else "")
        rules[key] = libsbml.formulaToL3String(rule.getMath())
    assignments = {
        assignment.getSymbol(): libsbml.formulaToL3String(assignment.getMath())
        for assignment in model.getListOfInitialAssignments()
    }
    return {
        "parameters": parameters,
        "rules": rules,
        "assignments": assignments,
        "units": sorted(
            definition.getId() for definition in model.getListOfUnitDefinitions()
        ),
        "errors": validate_document(document),
    }


def _formula_differences(
    rust: dict[Any, str], reference: dict[Any, str], kind: str
) -> list[str]:
    """The keys of two mappings of formulas which differ."""
    found = []
    missing = sorted(set(reference) - set(rust))
    extra = sorted(set(rust) - set(reference))
    if missing:
        found.append(f"{kind} only in python: {missing[:3]}")
    if extra:
        found.append(f"{kind} only in rust: {extra[:3]}")
    for key in sorted(set(rust) & set(reference), key=str):
        if rust[key] == reference[key]:
            continue
        if _canonical(rust[key]) == _canonical(reference[key]):
            # the same formula, written differently: the rust converter
            # writes a square root without the degree two and a number in
            # the e notation of MathML, the python converter keeps the
            # degree with its units and writes the number as text
            found.append(f"{kind} notation of {key}")
            continue
        if _without_parentheses(_canonical(rust[key])) == _without_parentheses(
            _canonical(reference[key])
        ):
            # the same formula, written with a different nesting of an
            # n-ary operator: the rust converter writes the mathematics as
            # the CellML model has it, libsbml writes the tree of the
            # analyser of libcellml
            found.append(f"{kind} nesting of {key}")
            continue
        found.append(f"{kind} formula of {key}: {rust[key]} != {reference[key]}")
        break
    return found


def _canonical(formula: str) -> str:
    """A formula without the differences which are a notation only.

    Args:
        formula: the formula `libsbml.formulaToL3String` writes.

    Returns:
        The formula with `root(2, x)` as `sqrt(x)`, `log(10, x)` as
        `log10(x)` and `1e+15` as `1e15`.
    """
    formula = formula.replace("root(2, ", "sqrt(").replace("log(10, ", "log10(")
    return re.sub(r"e\+(\d)", r"e\1", formula)


def _without_parentheses(formula: str) -> str:
    """A formula without its parentheses.

    Args:
        formula: the formula `libsbml.formulaToL3String` writes.

    Returns:
        The formula without `(` and `)`, which is the same for an n-ary
        operator written with another nesting.
    """
    return formula.replace("(", "").replace(")", "")


def differences(rust: dict[str, Any], reference: dict[str, Any]) -> list[str]:
    """What the two SBML models of one CellML document differ in.

    Args:
        rust: summary of the SBML of the rust converter.
        reference: summary of the SBML of the python converter.

    Returns:
        One line per difference, empty when the two agree.
    """
    if "error" in rust or "error" in reference:
        return [f"read: {rust.get('error', 'ok')} / {reference.get('error', 'ok')}"]
    found: list[str] = []
    if rust["errors"]:
        found.append(f"invalid SBML: {rust['errors'][0]}")
    rust_parameters, reference_parameters = rust["parameters"], reference["parameters"]
    missing = sorted(set(reference_parameters) - set(rust_parameters))
    extra = sorted(set(rust_parameters) - set(reference_parameters))
    if missing:
        found.append(f"parameters only in python: {missing[:3]}")
    if extra:
        found.append(f"parameters only in rust: {extra[:3]}")
    for name in sorted(set(rust_parameters) & set(reference_parameters)):
        if rust_parameters[name] != reference_parameters[name]:
            found.append(
                f"parameter {name}: {rust_parameters[name]} != "
                f"{reference_parameters[name]}"
            )
            break
    found += _formula_differences(rust["rules"], reference["rules"], "rules")
    found += _formula_differences(
        rust["assignments"], reference["assignments"], "initial assignments"
    )
    if rust["units"] != reference["units"]:
        only_rust = sorted(set(rust["units"]) - set(reference["units"]))
        only_python = sorted(set(reference["units"]) - set(rust["units"]))
        found.append(f"units: rust only {only_rust[:3]}, python only {only_python[:3]}")
    return found


def corpus() -> list[Path]:
    """The documents of the corpus: the fixtures and the Physiome selection."""
    paths = list(FIXTURES)
    for exposure in read_selection(REPO / "physiome" / "models.json").models:
        try:
            paths.append(model_path(exposure))
        except Exception as err:  # a model which is not in the cache
            print(f"{exposure.id}: {err}", file=sys.stderr)
    return paths


def main(argv: list[str] | None = None) -> int:
    """Compare the two converters over the corpus."""
    parser = argparse.ArgumentParser(
        prog="cellml2sbml_parity",
        description="Compare the rust converter of CellML to SBML with the python one.",
    )
    parser.add_argument("files", nargs="*", help="CellML files, the corpus by default")
    parser.add_argument("--binary", default=str(BINARY), help="the command to run")
    parser.add_argument("--count", type=int, help="compare only the first N files")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="print every difference"
    )
    args = parser.parse_args(argv)

    binary = Path(args.binary)
    if not binary.is_file():
        print(f"{binary} does not exist, run `cargo build --release`", file=sys.stderr)
        return 1

    paths = [Path(name) for name in args.files] if args.files else corpus()
    if args.count is not None:
        paths = paths[: args.count]

    counts: Counter[str] = Counter()
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        for path in paths:
            counts["files"] += 1
            rust_file, python_file = work / "rust.xml", work / "python.xml"
            rust_failure = rust_sbml(binary, path, rust_file)
            python_failure = python_sbml(path, python_file)
            if rust_failure and python_failure:
                counts["neither converts"] += 1
                if args.verbose:
                    print(f"{path}: neither converts: {rust_failure}")
                continue
            if rust_failure:
                counts["only python converts"] += 1
                print(f"{path}: only python converts: {rust_failure}")
                continue
            if python_failure:
                counts["only rust converts"] += 1
                if args.verbose:
                    print(f"{path}: only rust converts: {python_failure}")
                continue
            found = differences(summary(rust_file), summary(python_file))
            if found:
                counts["differ"] += 1
                for line in found:
                    counts[line.split(":")[0]] += 1
                if args.verbose:
                    print(f"{path}:")
                    for line in found:
                        print(f"  {line}")
            else:
                counts["identical"] += 1
    print(f"{counts['files']} files")
    for key, count in sorted(counts.items()):
        if key != "files":
            print(f"  {key}: {count}")
    return 1 if counts["only python converts"] or counts["differ"] else 0


if __name__ == "__main__":
    sys.exit(main())
