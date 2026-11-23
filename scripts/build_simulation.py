"""Build the assets of the interactive simulation of the roundtrip page.

The [roundtrip example](../docs/roundtrip.md) simulates the repressilator in
the browser: the CellML model with libopencor and the SBML model with
sbmlsim-core, both as WebAssembly, with one set of sliders for the
parameters of both. The CellML model is the file of the page, which
libopencor reads itself; sbmlsim-core takes a model which is compiled ahead
of time, so this script compiles the SBML model of the page with the python
package, writes the engine and the math library it embeds next to it and
notes the versions, which the page loads its JavaScript hosts for.

```bash
uv run python scripts/build_simulation.py
uv run zensical serve
```

The assets are not committed, the `documentation` workflow builds them
before the site is built. Without them the page says that the simulation is
not available and the rest of the page works.
"""

import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import sbmlsim_core

from sbml2cellml.sbmlsim import compilable_sbml

ROOT = Path(__file__).resolve().parent.parent
"""The root of the repository."""

MODEL = ROOT / "docs" / "roundtrip" / "repressilator.xml"
"""The SBML model of the page, which the example writes."""

DESTINATION = ROOT / "docs" / "roundtrip" / "simulation"
"""Where the page loads the assets from."""


def compile_model() -> dict[str, int]:
    """Compile the SBML model and write it with the runtime of its engine.

    Returns:
        The size of every file in bytes, by name.

    Raises:
        SystemExit: when the model is missing or cannot be compiled.
    """
    if not MODEL.is_file():
        raise SystemExit(
            f"the SBML model of the page is missing: {MODEL.relative_to(ROOT)}, "
            "run `uv run python examples/repressilator_example.py --docs`"
        )
    try:
        compiled = sbmlsim_core.compile_sbml(
            compilable_sbml(MODEL.read_text(encoding="utf-8"))
        )
    except sbmlsim_core.CompileError as err:
        raise SystemExit(f"the model cannot be compiled: {err}") from err
    DESTINATION.mkdir(parents=True, exist_ok=True)
    files: dict[str, bytes] = {
        "repressilator.wasm": compiled.wasm,
        "repressilator.json": json.dumps(compiled.description).encode("utf-8"),
        **sbmlsim_core.runtime_wasm(),
    }
    for name, content in files.items():
        path = DESTINATION / (f"{name}.wasm" if name in ("engine", "mathlib") else name)
        path.write_bytes(content)
    return {path.name: path.stat().st_size for path in sorted(DESTINATION.iterdir())}


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
    """Compile the model and write the assets of the page."""
    sizes = compile_model()
    versions = write_versions()
    for name, size in sizes.items():
        print(f"{(DESTINATION / name).relative_to(ROOT)}: {size / 1024:.0f} KiB")
    for package, number in versions.items():
        print(f"{package} {number}")


if __name__ == "__main__":
    sys.exit(main())
