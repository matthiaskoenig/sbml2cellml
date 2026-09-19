# Simulation

Both sides of a conversion can be simulated, which is how a conversion is checked: the SBML model with [roadrunner](https://www.libroadrunner.org/), the CellML model with [libopencor](https://opencor.ws/libopencor/). Both simulators are optional, `sbml2cellml` converts without them.

| model | simulator | how |
| --- | --- | --- |
| SBML | roadrunner | the [roadrunner API](#sbml-with-roadrunner) |
| CellML | libopencor | [`sbml2cellml.simulate.run_timecourse`](#cellml-with-libopencor) |

## Setup

The `simulate` extra adds pandas and matplotlib for the timecourse results and plots; roadrunner comes from PyPI, libopencor from its GitHub release, see [Installation](installation.md#simulators):

```bash
pip install "sbml2cellml[simulate]"
pip install libroadrunner
pip install --find-links https://github.com/opencor/libopencor/releases/expanded_assets/v1.20260803.0 libopencor==1.20260803.0
```

!!! warning "One simulator per process"

    roadrunner and libopencor bundle different LLVM versions and crash once both have compiled a model in the same process. Simulate the SBML and the CellML model in separate python processes, e.g., in two scripts which write their results to files. The [SBML test suite](testsuite.md) harness runs every simulator in its own worker process for this reason.

## SBML with roadrunner

roadrunner reads the SBML file and returns the timecourse as a named array, which pandas takes as it is:

```python
import pandas as pd
import roadrunner

rr = roadrunner.RoadRunner("model.xml")
result = rr.simulate(0, 100, steps=100)
df = pd.DataFrame(result, columns=result.colnames)
```

The columns are `time` and the floating species, a species `S1` as concentration `[S1]`. The converted CellML model has one variable per compartment, parameter and species, named by the SBML id, where a species is a concentration unless it has `hasOnlySubstanceUnits`. To get the same columns from roadrunner select them before the simulation:

```python
rr.timeCourseSelections = ["time", "[S1]", "k1", "compartment"]
```

## CellML with libopencor

[`sbml2cellml.simulate`](api/simulate.md) runs a uniform timecourse of a CellML file with libopencor:

```python
from pathlib import Path
from sbml2cellml.simulate import plot_timecourse, run_timecourse

df, units = run_timecourse(Path("model.cellml"), start=0.0, end=100.0, steps=100)
plot_timecourse(df, units)
```

`run_timecourse` returns a pandas data frame with the variable of integration in the first column, followed by the states, the algebraic variables, the constants and the computed constants, and a dictionary with the units of every column. The column names are the variable names of the CellML model, i.e., the SBML ids for a converted model. `steps` is the number of intervals, so the frame has `steps + 1` rows, like the roadrunner result above. `relative_tolerance` and `absolute_tolerance` set the tolerances of the solver.

A model without differential equations has no variable of integration (the converter leaves `time` out of an SBML model without rate rules and reactions); libopencor computes it as a steady state, and `run_timecourse` returns its values at every requested time point, with the time points in a first column `time`.

libopencor reports a model it cannot simulate, e.g., an invalid or underconstrained model, as issues, which are raised as `SimulationError`, as are two result columns of the same name (the component prefix of the names is dropped). Without libopencor the import of `sbml2cellml.simulate` works, `run_timecourse` raises an `ImportError` with the installation hint.

`examples/cellml_example.py` builds a small model with libcellml directly and simulates it.
