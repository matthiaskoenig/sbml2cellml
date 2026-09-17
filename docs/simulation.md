# Simulation

[`sbml2cellml.simulate`](api/simulate.md) runs a uniform timecourse of a CellML file with [libopencor](https://opencor.ws/libopencor/), which has to be [installed separately](installation.md#simulation-with-libopencor):

```python
from pathlib import Path
from sbml2cellml.simulate import plot_timecourse, run_timecourse

df, units = run_timecourse(Path("model.cellml"), start=0.0, end=100.0, steps=100)
plot_timecourse(df, units)
```

`run_timecourse` returns a pandas data frame with the variable of integration in the first column, followed by the states and the algebraic variables, and a dictionary with the units of every column. The column names are the variable names of the CellML model, i.e., the SBML ids for a converted model. `steps` is the number of intervals, so the frame has `steps + 1` rows.

libopencor reports a model it cannot simulate, e.g., an invalid or underconstrained model, as issues, which are raised as `SimulationError`. Without libopencor the import of `sbml2cellml.simulate` works, `run_timecourse` raises an `ImportError` with the installation hint.

`examples/cellml_example.py` builds a small model with libcellml directly and simulates it.
