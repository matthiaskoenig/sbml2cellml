"""Compare the rust CellML reader with libcellml over a corpus of models.

The rust reader (`crates/cellml`) is measured against libcellml, the
reader of the python package, on the models of the Physiome check and on
the CellML fixtures of the repository: both read the same document and
their structure is compared, the version, the components with their
variables, the encapsulation and the equivalence sets of the connections.

Of the 101 documents of the corpus, 96 are read identically, 4 are read by
the rust reader alone, since libcellml refuses them (a non whitespace text
in a component, a namespace URI which is not absolute), and 1 differs in
what a variable exposes: the permissive parser of libcellml reads the
interface of a variable of CellML 1.0 from the presence of the attributes
``public_interface`` and ``private_interface`` and not from their values
(cellml/libcellml#1528), the reader takes the value.

The script is run locally, like the checks of BioModels and of the
Physiome repository, and needs the command line of the rust workspace:

```bash
cargo build --release
uv run python scripts/cellml_parity.py
uv run python scripts/cellml_parity.py --count 10 -v
```
"""

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from sbml2cellml.cellml import cellml_version, read_model
from sbml2cellml.physiome.models import model_path, read_selection

REPO = Path(__file__).parent.parent
#: the command line of the rust workspace
BINARY = REPO / "target" / "release" / "cellml-info"
#: the CellML fixtures of the repository
FIXTURES = sorted((REPO / "tests" / "data").glob("*.cellml")) + sorted(
    (REPO / "examples" / "models").glob("*.cellml")
)


def rust_summary(binary: Path, path: Path) -> dict[str, Any]:
    """What the rust reader reads of a document.

    Args:
        binary: the `cellml-info` command.
        path: the CellML file.

    Returns:
        The summary, or a dict with the key `error`.
    """
    result = subprocess.run(
        [str(binary), str(path)], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return {
            "error": result.stderr.strip().splitlines()[-1]
            if result.stderr
            else "failed"
        }
    return json.loads(result.stdout)[0]


def _components(parent: Any) -> list[Any]:
    """The components of a model or component, the children after it."""
    found = []
    for index in range(parent.componentCount()):
        component = parent.component(index)
        found.append(component)
        found += _components(component)
    return found


def _interfaces(variable: Any) -> tuple[bool, bool]:
    """Whether a variable is exposed to the siblings and to the children.

    `interfaceType` of the python binding gives the text of the attribute,
    `public_and_private` for a variable which is exposed to both.
    """
    interface = variable.interfaceType()
    return (
        interface in ("public", "public_and_private"),
        interface in ("private", "public_and_private"),
    )


def _equivalence_sets(components: list[Any]) -> list[list[str]]:
    """The equivalence sets of libcellml, as `component/variable` names.

    A variable is named by its component and its name, not by the identity
    of its object: the python binding gives a new wrapper on every access,
    so two accesses of the same variable are two objects.
    """
    index: dict[tuple[str, str], int] = {}
    names: list[str] = []
    variables: list[Any] = []
    for component in components:
        for position in range(component.variableCount()):
            variable = component.variable(position)
            index[(component.name(), variable.name())] = len(names)
            names.append(f"{component.name()}/{variable.name()}")
            variables.append(variable)
    parent = list(range(len(names)))

    def find(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for position, variable in enumerate(variables):
        for other in range(variable.equivalentVariableCount()):
            equivalent = variable.equivalentVariable(other)
            owner = equivalent.parent()
            if owner is None:
                continue
            found = index.get((owner.name(), equivalent.name()))
            if found is None:
                continue
            first, second = sorted((find(position), find(found)))
            parent[second] = first

    sets: dict[int, list[str]] = {}
    for position, name in enumerate(names):
        sets.setdefault(find(position), []).append(name)
    return sorted(sorted(members) for members in sets.values())


def libcellml_summary(path: Path) -> dict[str, Any]:
    """What libcellml reads of a document, in the shape of `rust_summary`."""
    try:
        model = read_model(path, strict=False)
    except Exception as err:  # the error of a reader is a result here
        return {"error": str(err).splitlines()[0]}
    components = _components(model)
    return {
        "version": cellml_version(path.read_text(encoding="utf-8")) or "2.0",
        "name": model.name(),
        "components": [
            {
                "name": component.name(),
                "variables": [
                    {
                        "name": component.variable(position).name(),
                        "units": (
                            component.variable(position).units().name()
                            if component.variable(position).units() is not None
                            else ""
                        ),
                        "initial_value": component.variable(position).initialValue()
                        or None,
                        "public": _interfaces(component.variable(position))[0],
                        "private": _interfaces(component.variable(position))[1],
                    }
                    for position in range(component.variableCount())
                ],
            }
            for component in components
        ],
        "encapsulation": sorted(
            [component.name(), component.parent().name()]
            for component in components
            if component.parent() is not None
            and component.parent().name() != model.name()
        ),
        "equivalence_sets": _equivalence_sets(components),
    }


def _comparable(summary: dict[str, Any]) -> dict[str, Any]:
    """The fields of a summary both readers have, in a comparable order."""
    return {
        "version": summary["version"],
        "name": summary["name"],
        "components": sorted(
            (
                component["name"],
                sorted(
                    (
                        variable["name"],
                        variable["units"],
                        variable["initial_value"],
                        variable["public"],
                        variable["private"],
                    )
                    for variable in component["variables"]
                ),
            )
            for component in summary["components"]
        ),
        "encapsulation": sorted(list(pair) for pair in summary["encapsulation"]),
        "equivalence_sets": sorted(
            sorted(members) for members in summary["equivalence_sets"]
        ),
    }


def differences(rust: dict[str, Any], reference: dict[str, Any]) -> list[str]:
    """The fields the two readers disagree on."""
    if "error" in rust or "error" in reference:
        if "error" in rust and "error" in reference:
            return []
        reader = "rust" if "error" in rust else "libcellml"
        message = (rust if "error" in rust else reference)["error"]
        return [f"only {reader} fails: {message}"]
    one, other = _comparable(rust), _comparable(reference)
    return [key for key in one if one[key] != other[key]]


def main(argv: list[str] | None = None) -> int:
    """Compare the two readers over the corpus."""
    parser = argparse.ArgumentParser(
        prog="cellml_parity",
        description="Compare the rust CellML reader with libcellml.",
    )
    parser.add_argument("files", nargs="*", help="CellML files, the corpus by default")
    parser.add_argument("--binary", default=str(BINARY), help="the cellml-info command")
    parser.add_argument("--count", type=int, help="compare only the first N files")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="print every difference"
    )
    args = parser.parse_args(argv)

    binary = Path(args.binary)
    if not binary.is_file():
        print(f"{binary} does not exist, run `cargo build --release`", file=sys.stderr)
        return 1

    if args.files:
        paths = [Path(name) for name in args.files]
    else:
        paths = list(FIXTURES)
        for exposure in read_selection(REPO / "physiome" / "models.json").models:
            try:
                paths.append(model_path(exposure))
            except Exception as err:  # a model which is not in the cache
                print(f"{exposure.id}: {err}", file=sys.stderr)
    if args.count is not None:
        paths = paths[: args.count]

    counts: Counter[str] = Counter()
    for path in paths:
        found = differences(rust_summary(binary, path), libcellml_summary(path))
        counts["files"] += 1
        if found:
            counts["differ"] += 1
            for key in found:
                counts[key] += 1
            if args.verbose:
                print(f"{path}: {', '.join(found)}")
    print(f"{counts['files']} files, {counts['differ']} differ")
    for key, count in sorted(counts.items()):
        if key not in ("files", "differ"):
            print(f"  {key}: {count}")
    return 1 if counts["differ"] else 0


if __name__ == "__main__":
    sys.exit(main())
