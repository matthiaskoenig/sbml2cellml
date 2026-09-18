# Simulation

[`sbml2cellml.simulate`](api/simulate.md) runs a uniform timecourse of a CellML file with [libopencor](https://opencor.ws/libopencor/), which has to be [installed separately](installation.md#simulation-with-libopencor):

```python
from pathlib import Path
from sbml2cellml.simulate import plot_timecourse, run_timecourse

df, units = run_timecourse(Path("model.cellml"), start=0.0, end=100.0, steps=100)
plot_timecourse(df, units)
```

`run_timecourse` returns a pandas data frame with the variable of integration in the first column, followed by the states, the algebraic variables, the constants and the computed constants, and a dictionary with the units of every column. The column names are the variable names of the CellML model, i.e., the SBML ids for a converted model. `steps` is the number of intervals, so the frame has `steps + 1` rows.

A model without differential equations has no variable of integration (the converter leaves `time` out of an SBML model without rate rules and reactions); libopencor computes it as a steady state, and `run_timecourse` returns its values at every requested time point, with the time points in a first column `time`.

libopencor reports a model it cannot simulate, e.g., an invalid or underconstrained model, as issues, which are raised as `SimulationError`, as are two result columns of the same name (the component prefix of the names is dropped). Without libopencor the import of `sbml2cellml.simulate` works, `run_timecourse` raises an `ImportError` with the installation hint.

`examples/cellml_example.py` builds a small model with libcellml directly and simulates it.
