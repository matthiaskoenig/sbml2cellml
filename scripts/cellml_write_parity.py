"""Check the rust CellML writer against libcellml over a corpus of models.

The writer of `crates/cellml` writes a model as a CellML 2.0 document
(`cellml-write`). Every document of the corpus of `cellml_parity.py` (the
models of the Physiome check and the CellML fixtures of the repository) is
written again and the result is measured twice:

- the validator of libcellml validates the written document: it must hold no
  error which the original does not hold as well, since a document of the
  repository is not always a valid document of its own version
- libcellml reads the written document and the original one, and the two
  structures are compared as `cellml_parity.py` compares the two readers: the
  components with their variables, the encapsulation and the equivalence sets
  of the connections. The version is not compared, since the writer writes
  CellML 2.0 for a document of any version.

A document which libcellml refuses to read, or which the rust reader refuses,
is counted and left out: the writer cannot be measured on it.

The script is run locally, like the checks of BioModels and of the Physiome
repository, and needs the command line of the rust workspace:

```bash
cargo build --release
uv run python scripts/cellml_write_parity.py
uv run python scripts/cellml_write_parity.py --count 10 -v
```
"""

import argparse
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import libcellml

from sbml2cellml.cellml import errors, format_issues, read_model
from sbml2cellml.physiome.models import model_path, read_selection

# the script is run as a file, which puts its own directory on the path and not
# the root of the repository, where the package `scripts` lives
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.cellml_parity import (
    FIXTURES,
    REPO,
    _comparable,
    libcellml_summary,
)

#: the command line of the rust workspace
BINARY = REPO / "target" / "release" / "cellml-write"


def written(binary: Path, path: Path, target: Path) -> str | None:
    """Write a document again with the rust writer.

    Args:
        binary: the `cellml-write` command.
        path: the CellML file.
        target: the file to write.

    Returns:
        The message of a document the rust reader or writer refuses, else
        `None`, with the document written to `target`.
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


def validation_errors(path: Path, strict: bool = True) -> list[str]:
    """What the validator of libcellml says against a document.

    The analyser is not asked: whether the equations of a model determine
    every variable is a property of the model, not of the document it is
    written as, and a model of the repository is often a part of a system
    whose other variables another document sets.
    """
    try:
        model = read_model(path, strict=strict)
    except Exception as err:  # the error of the reader is a result here
        return [str(err).splitlines()[0]]
    validator = libcellml.Validator()
    validator.validateModel(model)
    issues = errors([validator.issue(index) for index in range(validator.issueCount())])
    return format_issues(issues).splitlines() if issues else []


def _structure(summary: dict[str, Any]) -> dict[str, Any]:
    """The comparable structure of a summary, without the version."""
    comparable = _comparable(summary)
    del comparable["version"]
    return comparable


def differences(original: Path, result: Path) -> list[str]:
    """The fields libcellml reads differently of the two documents."""
    one = libcellml_summary(original)
    other = libcellml_summary(result)
    if "error" in other:
        return [f"the written document is not read: {other['error']}"]
    return [
        key for key, value in _structure(one).items() if value != _structure(other)[key]
    ]


def check(binary: Path, path: Path, directory: Path) -> tuple[str, list[str]]:
    """Write one document again and measure the result.

    Args:
        binary: the `cellml-write` command.
        path: the CellML file.
        directory: the directory of the written documents.

    Returns:
        The outcome (`ok`, `refused`, `invalid`, `differs` or `unreadable`)
        and the lines which say what is wrong with it.
    """
    # a document libcellml itself does not read cannot measure the writer
    if "error" in libcellml_summary(path):
        return "unreadable", []
    target = directory / f"{path.stem}.written.cellml"
    message = written(binary, path, target)
    if message is not None:
        return "refused", [message]
    # only an error the original does not have is one of the writer: a model of
    # the repository is not always valid or analysable on its own
    before = validation_errors(path, strict=False)
    invalid = [line for line in validation_errors(target) if line not in before]
    if invalid:
        return "invalid", invalid
    found = differences(path, target)
    return ("differs", found) if found else ("ok", [])


def main(argv: list[str] | None = None) -> int:
    """Check the writer over the corpus."""
    parser = argparse.ArgumentParser(
        prog="cellml_write_parity",
        description="Check the rust CellML writer with libcellml.",
    )
    parser.add_argument("files", nargs="*", help="CellML files, the corpus by default")
    parser.add_argument(
        "--binary", default=str(BINARY), help="the cellml-write command"
    )
    parser.add_argument("--count", type=int, help="check only the first N files")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="print every problem"
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
    with tempfile.TemporaryDirectory(prefix="cellml-write-") as name:
        directory = Path(name)
        for path in paths:
            outcome, lines = check(binary, path, directory)
            counts[outcome] += 1
            counts["files"] += 1
            if outcome != "ok" and args.verbose:
                print(f"{path}: {outcome}")
                for line in lines[:5]:
                    print(f"    {line}")
    print(f"{counts['files']} files, {counts['ok']} written identically")
    for key, count in sorted(counts.items()):
        if key not in ("files", "ok"):
            print(f"  {key}: {count}")
    return 1 if counts["invalid"] or counts["differs"] or counts["refused"] else 0


if __name__ == "__main__":
    sys.exit(main())
