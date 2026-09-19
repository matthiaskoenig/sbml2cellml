# Installation

`sbml2cellml` requires python 3.13 or 3.14 and is available from [pypi](https://pypi.org/project/sbml2cellml). The dependencies [python-libsbml](https://pypi.org/project/python-libsbml/) and [libcellml](https://pypi.org/project/libcellml/) ship wheels for Linux, macOS and Windows.

!!! warning "Windows"

    Windows is currently not supported: the Windows wheels of libcellml 0.7.1 contain ARM64 binaries, which do not load on x64 Windows ([cellml/libcellml#1460](https://github.com/cellml/libcellml/issues/1460)). Linux and macOS are tested.

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

## Simulators { #simulators }

The simulators are optional, see [Simulation](simulation.md): [roadrunner](https://www.libroadrunner.org/) simulates the SBML models, [libopencor](https://opencor.ws/libopencor/) the CellML models. The `simulate` extra adds pandas and matplotlib for the timecourse results and plots of [`sbml2cellml.simulate`](api/simulate.md):

```bash
pip install "sbml2cellml[simulate]"
```

### roadrunner

roadrunner is available from [pypi](https://pypi.org/project/libroadrunner/):

```bash
pip install libroadrunner
```

### libopencor { #simulation-with-libopencor }

libopencor is not on PyPI. Its wheels are published with the [GitHub releases of libopencor](https://github.com/opencor/libopencor/releases); the release page can be used as a package index, e.g. for the release `v1.20260803.0`:

```bash
pip install --find-links https://github.com/opencor/libopencor/releases/expanded_assets/v1.20260803.0 libopencor==1.20260803.0
```

or, with uv,

```bash
uv pip install --find-links https://github.com/opencor/libopencor/releases/expanded_assets/v1.20260803.0 libopencor==1.20260803.0
```

Wheels exist for python 3.12 to 3.14 on Linux (x86_64, aarch64), macOS (Intel, Apple silicon) and Windows. Without libopencor everything except `sbml2cellml.simulate` works.

## Running the SBML test suite

The `testsuite` extra adds `libroadrunner` and `requests` for the `sbml2cellml-testsuite` command:

```bash
pip install "sbml2cellml[testsuite]"
```

Like `simulate`, it needs the libopencor wheel installed separately, see above.

## Development version

The current state of the `develop` branch is installed from GitHub:

```bash
pip install git+https://github.com/matthiaskoenig/sbml2cellml.git@develop
```

To work on the repository itself see [Development](development.md).
