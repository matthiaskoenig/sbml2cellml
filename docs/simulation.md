# Simulation

Both sides of a conversion can be simulated, which is how a conversion is checked: the SBML model with [sbmlsim-core](https://matthiaskoenig.github.io/sbmlsim-core/), the CellML model with [libopencor](https://opencor.ws/libopencor/). Both simulators are optional, `sbml2cellml` converts without them.

| model | simulator | how |
| --- | --- | --- |
| SBML | sbmlsim-core | [`sbml2cellml.sbmlsim.run_timecourse`](#sbml-with-sbmlsim-core) |
| CellML | libopencor | [`sbml2cellml.simulate.run_timecourse`](#cellml-with-libopencor) |

Both simulators integrate with CVODE of SUNDIALS and run in the same python process, so a script can simulate a model and its conversion side by side.

Both functions take the same call, so the two sides of a conversion are simulated the same way:

```python
run_timecourse(
    model,  # the file, or the document as a string
    selections=None,  # the variables of the result, every one when None
    start=0.0,
    end=1.0,
    steps=100,
    relative_tolerance=None,  # the default of the simulator when None
    absolute_tolerance=None,
    maximum_number_of_steps=None,
    scale_tolerance=True,  # the absolute tolerance follows small states
    warmup=False,  # a discarded run before the timed one
    units=None,  # filled with the unit of every column
    timings=None,  # filled with the wall time of the phases
)
```

The result is a pandas data frame with the time in the first column and the selected variables after it, `steps + 1` rows. The variable of integration is always there, it is never a selection; `units` and `timings` are filled when a dictionary is given, as the solver settings and the two simulators below describe.

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

The first argument is the path of an SBML file or the document as a string, the second the variables of the result: an id, or `[S1]` for the concentration of a species. Without selections the frame holds every variable of the model, as on the CellML side. `relative_tolerance`, `absolute_tolerance` and `maximum_number_of_steps` set the solver, as for the CellML side below, and `units` takes the units the SBML model states for the columns (the `timeUnits` of the model for `time`, the substance units of an amount, substance over size for a concentration and the extent over the time of the model for the rate of a reaction).

The converted CellML model has one variable per compartment, parameter and species, named by the SBML id, where a species is a concentration unless it has `hasOnlySubstanceUnits` (a species in concentration whose compartment changes in time has the additional variable `<species>_amount`), so selecting `[S1]` gives the column which the CellML variable `S1` is compared with.

The compiler of sbmlsim-core reads flat SBML level 3 without a required package: a level 1 or 2 model is converted to level 3 version 2 with libsbml and a model which requires the `comp` package is flattened, both by `run_timecourse` itself (`compilable_sbml`). libsbml refuses the strict conversion of a model over issues which have no mathematics, e.g., the `outside` attribute of a compartment of level 2 or inconsistent units; the conversion is then repeated without the strict check and the issues are logged as a warning. A model it cannot compile or integrate raises an error of sbmlsim-core; without sbmlsim-core the import of `sbml2cellml.sbmlsim` works and `run_timecourse` raises an `ImportError` with the installation hint.

The states of the solver are the amounts of the species, so a model with a small compartment has small states: a species with the concentration 1 in a compartment of 1e-13 litre has the amount 1e-13, far below an absolute tolerance of 1e-12, and CVODE accepts any trajectory of it. `run_timecourse` therefore multiplies the absolute tolerance with the smallest initial value of a state when it is below one (`state_scale` over the states of the compiled model), as roadrunner does; `scale_tolerance=False` switches it off.

`load_model` keeps every model it compiled by the hash of its SBML text (`MODEL_CACHE_SIZE`, 16), so simulating the same model again neither converts it with libsbml nor compiles it a second time; the WebAssembly module of the model is compiled to native code by Wasmtime, which caches the result in `~/.cache/wasmtime` across processes. The simulation itself runs on an instance of its own, so a cached model never carries state from one simulation into the next. `timings` takes the wall time of the two phases when a dictionary is given:

```python
timings: dict[str, float] = {}
df = run_timecourse(Path("model.xml"), ["[S1]"], end=100.0, timings=timings)
print(timings)  # {'setup': 0.0185, 'simulate': 0.0004}
```

`setup` is the conversion, the compilation and the loading of the model, and nothing of it for a model from the cache; `simulate` is the integration.

## CellML with libopencor

[`sbml2cellml.simulate`](api/simulate.md) runs a uniform timecourse of a CellML file with libopencor:

```python
from pathlib import Path
from sbml2cellml.simulate import plot_timecourse, run_timecourse

units: dict[str, str] = {}
df = run_timecourse(Path("model.cellml"), start=0.0, end=100.0, steps=100, units=units)
plot_timecourse(df, units)
```

`run_timecourse` returns a pandas data frame with the variable of integration in the first column, followed by the states, the algebraic variables, the constants and the computed constants of the model, or by the `selections` when they are given. `plot_timecourse` plots every column against the first one and takes the frame of either simulator, with the units of the labels when they were collected. The column names are the variable names of the CellML model, i.e., the SBML ids for a converted model; a name which more than one variable of the model has keeps its component (`membrane/V`), so the variables of a model of many components stay apart. `steps` is the number of intervals, so the frame has `steps + 1` rows, like the SBML result above. `relative_tolerance` and `absolute_tolerance` set the tolerances of the solver (CVODE). `maximum_number_of_steps` is the number of internal steps the solver may take between two time points of the output, 100000 by default: the 500 steps of libopencor end the simulation of many models with `mxstep steps taken before reaching tout`, mostly with tight tolerances or few time points.

The absolute tolerance follows the states of the model as on the SBML side: it is multiplied with the smallest initial value of a state when that value is below one (`scale_tolerance=False` switches it off). libopencor fills the arrays of the states only when it runs, so a model with small states is run once with the given tolerance, which gives the initial values, and again with the scaled one; a model whose states are of the order of one runs once. `timings` takes the wall time of the phases as above, with the first run as part of the `setup`.

A model without differential equations has no variable of integration (the converter leaves `time` out of an SBML model without rate rules and reactions); libopencor computes it as a steady state, and `run_timecourse` returns its values at every requested time point, with the time points in a first column `time`.

The CellML model is read from a file or from a string, as the SBML model is: a document which is given as text is handed to libopencor in memory. libopencor reports a model it cannot simulate, e.g., an invalid or underconstrained model, as issues, which are raised as `SimulationError`, and so is a selection which the model has no variable of. Without libopencor the import of `sbml2cellml.simulate` works, `run_timecourse` raises an `ImportError` with the installation hint.

`examples/cellml_example.py` builds a small model with libcellml directly and simulates it. The [roundtrip example](roundtrip.md) simulates an SBML model, its CellML conversion and the SBML model of the roundtrip and plots the three timecourses side by side.

## In the browser

Both simulators also run in a browser, where they are WebAssembly modules which the pages of this documentation load:

| page | model | simulator |
| --- | --- | --- |
| [Online converter](index.md#online-converter) | the CellML side of any conversion | libopencor |
| [Roundtrip example](roundtrip.md#simulate-in-the-browser) | the repressilator, the CellML model and the SBML model | libopencor and sbmlsim-core |

The online converter converts a model with the WebAssembly module of the rust converters and simulates the CellML side of the conversion with libopencor, which reads the document out of the memory of the page: a model is dropped, converted, integrated and plotted without an installation and without an upload. The settings of the solver are the ones of the python package, the tolerances 1e-9 and 1e-12 and 100000 internal steps between two time points, and the plot shows the first eight states of the model.

The SBML side needs the model compiled: sbmlsim-core compiles an SBML model into a WebAssembly module ahead of time and the compiler is not part of its JavaScript host, so the browser runs the models which are compiled for it, as the roundtrip page does with the repressilator (`scripts/build_simulation.py` compiles it with the python package). The version of a simulator in the browser is the version of the python package of the repository, so both run what the checks run.
