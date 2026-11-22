# Installation

`sbml2cellml` requires python 3.14 and is available from [pypi](https://pypi.org/project/sbml2cellml). The dependencies [python-libsbml](https://pypi.org/project/python-libsbml/) and [libcellml](https://pypi.org/project/libcellml/) ship wheels for Linux, macOS and Windows.

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

The simulators are optional, see [Simulation](simulation.md): [sbmlsim-core](https://matthiaskoenig.github.io/sbmlsim-core/) simulates the SBML models, [libopencor](https://opencor.ws/libopencor/) the CellML models. The `simulate` extra adds both, together with pandas and matplotlib for the timecourse results and plots of [`sbml2cellml.simulate`](api/simulate.md) and [`sbml2cellml.sbmlsim`](api/sbmlsim.md):

```bash
pip install "sbml2cellml[simulate]"
```

### sbmlsim-core { #simulation-with-sbmlsim-core }

sbmlsim-core is available from [pypi](https://pypi.org/project/sbmlsim-core/) and installed with the `simulate` extra. It compiles an SBML model to WebAssembly and simulates it with CVODE of SUNDIALS; wheels exist for python 3.14 on Linux (x86_64, aarch64), macOS (Intel, Apple silicon) and Windows (x86_64). Without sbmlsim-core everything except `sbml2cellml.sbmlsim` works.

### libopencor { #simulation-with-libopencor }

libopencor is available from [pypi](https://pypi.org/project/libopencor/) and installed with the `simulate` extra. Wheels exist for python 3.12 to 3.14 on Linux (x86_64, aarch64), macOS (Intel, Apple silicon) and Windows. Without libopencor everything except `sbml2cellml.simulate` works.

## Running the SBML test suite

The `testsuite` extra adds `requests` for the download of the models of BioModels; the cases of the SBML test suite are fetched with `git`:

```bash
pip install "sbml2cellml[testsuite]"
```

It includes the `simulate` extra and with it both simulators.

## Development version

The current state of the `develop` branch is installed from GitHub:

```bash
pip install git+https://github.com/matthiaskoenig/sbml2cellml.git@develop
```

To work on the repository itself see [Development](development.md).
