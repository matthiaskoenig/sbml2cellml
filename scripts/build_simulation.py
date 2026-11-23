"""Build the assets of the interactive simulation of the documentation.

The [roundtrip example](../docs/roundtrip.md) simulates the repressilator in
the browser: the CellML model with libopencor and the SBML model with
sbmlsim-core, both as WebAssembly, with one set of sliders for the
parameters of both, and the [online converter](../docs/index.md) simulates
both sides of a conversion the same way. Both pages read the models they
show: libopencor reads a CellML document itself and sbmlsim-core compiles an
SBML document in the browser, so this script writes the modules of
sbmlsim-core which the python package embeds (the compiler, the engine and
the math library) and notes the versions, which the pages load their
JavaScript hosts for.

```bash
uv run python scripts/build_simulation.py
uv run zensical serve
```

The assets are not committed, the `documentation` workflow builds them
before the site is built. Without them the pages say that the simulation is
not available and the rest of them works.
"""

import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import sbmlsim_core

ROOT = Path(__file__).resolve().parent.parent
"""The root of the repository."""

MODEL = ROOT / "docs" / "roundtrip" / "repressilator.xml"
"""The SBML model of the page, which the example writes."""

DESTINATION = ROOT / "docs" / "roundtrip" / "simulation"
"""Where the page loads the assets from."""

RUNTIME_MODULES = ("engine", "mathlib", "compiler")
"""The modules of `sbmlsim_core.runtime_wasm()`, written as `<key>.wasm`.

`engine` and `mathlib` run a compiled model and `compiler` compiles one in
the browser (sbmlsim-core 0.23.0 and newer). A release without the compiler
writes the two it has, and a page then simulates the CellML side of a
conversion alone.
"""


def write_runtime() -> dict[str, int]:
    """Write the modules of sbmlsim-core the pages simulate with.

    The compiler, the engine and the math library are the modules the python
    package embeds, so the browser compiles and runs a model with the
    sbmlsim-core of the checks of the repository.

    Returns:
        The size of every file in bytes, by name.

    Raises:
        SystemExit: when the model of the roundtrip page is missing.
    """
    if not MODEL.is_file():
        raise SystemExit(
            f"the SBML model of the page is missing: {MODEL.relative_to(ROOT)}, "
            "run `uv run python examples/repressilator_example.py --docs`"
        )
    DESTINATION.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in sbmlsim_core.runtime_wasm().items():
        path = DESTINATION / f"{name}.wasm"
        path.write_bytes(content)
        written.append(path)
    return {path.name: path.stat().st_size for path in sorted(written)}


def write_versions() -> dict[str, str]:
    """Write the versions of the simulators the page loads.

    The JavaScript host of sbmlsim-core and the module of libopencor are
    loaded from a CDN, pinned to the versions of the python packages, so the
    browser runs the simulators the checks of the repository run.

    Returns:
        The version by package.

    Raises:
        SystemExit: when a package is not installed.
    """
    versions: dict[str, str] = {}
    for package in ("sbmlsim-core", "libopencor"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError as err:
            raise SystemExit(
                f"{package} is not installed: `uv sync --extra dev`"
            ) from err
    (DESTINATION / "versions.json").write_text(
        json.dumps(versions, indent=2) + "\n", encoding="utf-8"
    )
    return versions


def main() -> None:
    """Write the modules of the simulator and the versions of the pages."""
    sizes = write_runtime()
    versions = write_versions()
    for name, size in sizes.items():
        print(f"{(DESTINATION / name).relative_to(ROOT)}: {size / 1024:.0f} KiB")
    for package, number in versions.items():
        print(f"{package} {number}")


if __name__ == "__main__":
    sys.exit(main())
