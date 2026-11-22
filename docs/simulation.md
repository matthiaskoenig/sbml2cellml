# Simulation

Both sides of a conversion can be simulated, which is how a conversion is checked: the SBML model with [sbmlsim-core](https://matthiaskoenig.github.io/sbmlsim-core/), the CellML model with [libopencor](https://opencor.ws/libopencor/). Both simulators are optional, `sbml2cellml` converts without them.

| model | simulator | how |
| --- | --- | --- |
| SBML | sbmlsim-core | [`sbml2cellml.sbmlsim.run_timecourse`](#sbml-with-sbmlsim-core) |
| CellML | libopencor | [`sbml2cellml.simulate.run_timecourse`](#cellml-with-libopencor) |

Both simulators integrate with CVODE of SUNDIALS and run in the same python process, so a script can simulate a model and its conversion side by side.

## Setup

The `simulate` extra adds both simulators together with pandas and matplotlib for the timecourse results and plots, see [Installation](installation.md#simulators):

```bash
pip install "sbml2cellml[simulate]"
```

## SBML with sbmlsim-core

[`sbml2cellml.sbmlsim`](api/sbmlsim.md) runs a uniform timecourse of an SBML model. sbmlsim-core compiles the model to WebAssembly and simulates it with its engine, which gives the same results on every host:

```python
from pathlib import Path
from sbml2cellml.sbmlsim import run_timecourse

df = run_timecourse(
    Path("model.xml"), ["[S1]", "k1", "compartment"], start=0.0, end=100.0, steps=100
)
```

The first argument is the path of an SBML file or the document as a string, the second the variables of the result: an id, or `[S1]` for the concentration of a species. The frame has `time` as first column and the selections after it, one row per time point (`steps + 1` rows). `relative_tolerance`, `absolute_tolerance` and `maximum_number_of_steps` set the solver, as for the CellML side below.

The converted CellML model has one variable per compartment, parameter and species, named by the SBML id, where a species is a concentration unless it has `hasOnlySubstanceUnits` (a species in concentration whose compartment changes in time has the additional variable `<species>_amount`), so selecting `[S1]` gives the column which the CellML variable `S1` is compared with.

The compiler of sbmlsim-core reads flat SBML level 3 without a required package: a level 1 or 2 model is converted to level 3 version 2 with libsbml and a model which requires the `comp` package is flattened, both by `run_timecourse` itself (`compilable_sbml`). libsbml refuses the strict conversion of a model over issues which have no mathematics, e.g., the `outside` attribute of a compartment of level 2 or inconsistent units; the conversion is then repeated without the strict check and the issues are logged as a warning. A model it cannot compile or integrate raises an error of sbmlsim-core; without sbmlsim-core the import of `sbml2cellml.sbmlsim` works and `run_timecourse` raises an `ImportError` with the installation hint.

The states of the solver are the amounts of the species, so a model with a small compartment has small states: a species with the concentration 1 in a compartment of 1e-13 litre has the amount 1e-13, far below an absolute tolerance of 1e-12, and CVODE accepts any trajectory of it. `run_timecourse` therefore multiplies the absolute tolerance with the smallest initial value of a state when it is below one (`state_scale`), as roadrunner does; `scale_tolerance=False` switches it off.

## CellML with libopencor

[`sbml2cellml.simulate`](api/simulate.md) runs a uniform timecourse of a CellML file with libopencor:

```python
from pathlib import Path
from sbml2cellml.simulate import plot_timecourse, run_timecourse

df, units = run_timecourse(Path("model.cellml"), start=0.0, end=100.0, steps=100)
plot_timecourse(df, units)
```

`run_timecourse` returns a pandas data frame with the variable of integration in the first column, followed by the states, the algebraic variables, the constants and the computed constants, and a dictionary with the units of every column. The column names are the variable names of the CellML model, i.e., the SBML ids for a converted model. `steps` is the number of intervals, so the frame has `steps + 1` rows, like the SBML result above. `relative_tolerance` and `absolute_tolerance` set the tolerances of the solver (CVODE). `maximum_number_of_steps` is the number of internal steps the solver may take between two time points of the output, 100000 by default: the 500 steps of libopencor end the simulation of many models with `mxstep steps taken before reaching tout`, mostly with tight tolerances or few time points.

A model without differential equations has no variable of integration (the converter leaves `time` out of an SBML model without rate rules and reactions); libopencor computes it as a steady state, and `run_timecourse` returns its values at every requested time point, with the time points in a first column `time`.

libopencor reports a model it cannot simulate, e.g., an invalid or underconstrained model, as issues, which are raised as `SimulationError`, as are two result columns of the same name (the component prefix of the names is dropped). Without libopencor the import of `sbml2cellml.simulate` works, `run_timecourse` raises an `ImportError` with the installation hint.

`examples/cellml_example.py` builds a small model with libcellml directly and simulates it. The [roundtrip example](roundtrip.md) simulates an SBML model, its CellML conversion and the SBML model of the roundtrip and plots the three timecourses side by side.
