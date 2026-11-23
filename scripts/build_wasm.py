"""Build the WebAssembly module of the online converter.

The online converter of the documentation ([Home](../docs/index.md)) converts
a CellML model to SBML in the browser with the crate `crates/wasm`, which
cargo builds for `wasm32-unknown-unknown`. The module is not committed: this
script builds it and copies it next to the pages, where `zensical build`
picks it up with the other files of `docs/`.

```bash
uv run python scripts/build_wasm.py
uv run zensical serve
```

The `documentation` workflow runs it before the site is built. Without the
module the converter of the page says that it is not built, the rest of the
page works.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
"""The root of the repository."""

CRATE = "sbml2cellml-wasm"
"""The crate of the module."""

TARGET = "wasm32-unknown-unknown"
"""The target of the browser."""

PROFILE = "wasm"
"""The cargo profile of the module, small and without unwinding."""

MODULE = ROOT / "target" / TARGET / PROFILE / "sbml2cellml_wasm.wasm"
"""Where cargo writes the module."""

DESTINATION = ROOT / "docs" / "converter" / "sbml2cellml.wasm"
"""Where the page loads the module from."""


def build() -> None:
    """Build the module with cargo.

    Raises:
        SystemExit: when cargo is missing or the build fails.
    """
    command = [
        "cargo",
        "build",
        "--locked",
        "--profile",
        PROFILE,
        "--target",
        TARGET,
        "-p",
        CRATE,
    ]
    print(" ".join(command))
    try:
        subprocess.run(command, cwd=ROOT, check=True)
    except FileNotFoundError:
        raise SystemExit(
            "cargo is not installed: the online converter needs the rust "
            "toolchain, see https://rustup.rs"
        ) from None
    except subprocess.CalledProcessError as err:
        raise SystemExit(f"the build of {CRATE} failed") from err


def copy() -> Path:
    """Copy the module next to the pages.

    Returns:
        The path of the copy.

    Raises:
        SystemExit: when cargo wrote no module.
    """
    if not MODULE.exists():
        raise SystemExit(f"cargo wrote no module: {MODULE}")
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(MODULE, DESTINATION)
    return DESTINATION


def main() -> None:
    """Build the module and copy it into the documentation."""
    build()
    destination = copy()
    size = destination.stat().st_size / 1024
    print(f"{destination.relative_to(ROOT)}: {size:.0f} KiB")


if __name__ == "__main__":
    sys.exit(main())
