# Roundtrip example

The example converts the repressilator from SBML to CellML and back to SBML and simulates all three models: the SBML model with [sbmlsim-core](https://matthiaskoenig.github.io/sbmlsim-core/), the CellML model with [libopencor](https://opencor.ws/libopencor/) and the SBML model of the roundtrip with sbmlsim-core again.

| | model | simulator |
| --- | --- | --- |
| 1 | SBML `examples/models/repressilator.xml` | sbmlsim-core |
| 2 | CellML, converted from 1 with `sbml2cellml`, with the metadata of 1 as RDF next to it | libopencor |
| 3 | SBML, converted from 2 with `cellml2sbml` | sbmlsim-core |

The repressilator of [Elowitz and Leibler (2000)](https://doi.org/10.1038/35002125) is a ring of three genes whose proteins LacI, TetR and cI each repress the transcription of the next gene, which makes the protein numbers oscillate. The model is [BIOMD0000000012](https://www.ebi.ac.uk/biomodels/BIOMD0000000012) of BioModels (SBML level 2 version 3, CC0) with its names, notes and annotations, which CellML has no place for: they go into an RDF file next to the CellML model and come back in the SBML model of the roundtrip, see [Metadata](conversion.md#metadata).

## Run the example

The example is `examples/repressilator_example.py` of the [repository](https://github.com/matthiaskoenig/sbml2cellml/tree/develop/examples). It needs both simulators, see [Simulation](simulation.md#setup):

```bash
uv sync --extra dev
uv run python examples/repressilator_example.py
```

The models, the metadata, the timecourses and the figure go to `examples/results/`.

## Convert

Two calls convert the model in both directions, each validates its result (libcellml for the CellML model, libsbml for the SBML model). The first one writes `repressilator.rdf` next to `repressilator.cellml`, the second one reads it:

```python
from pathlib import Path

from sbml2cellml import convert_cellml2sbml, convert_sbml2cellml

sbml_path = Path("repressilator.xml")
cellml_path = Path("repressilator.cellml")
roundtrip_path = Path("repressilator_roundtrip.xml")

convert_sbml2cellml(sbml_path, cellml_path=cellml_path)
convert_cellml2sbml(cellml_path, sbml_path=roundtrip_path)
```

The command line does the same:

```bash
sbml2cellml repressilator.xml -o repressilator.cellml
cellml2sbml repressilator.cellml -o repressilator_roundtrip.xml
```

## The models

=== "1 SBML"

    The six species (three mRNAs, three proteins) are amounts in the compartment `cell`, twelve reactions transcribe, translate and degrade them. Assignment rules compute the rate constants from the half lifes and the promoter strengths. The model, the species and the reactions have names, notes, SBO terms and annotations.

    ```{ .xml .listing title="examples/models/repressilator.xml" }
    --8<-- "examples/models/repressilator.xml"
    ```

=== "2 CellML"

    One component `sbml` with a variable for the compartment, every parameter, every species and the rate of every reaction, and the variable of integration `time`. The assignment rules and the kinetic laws are equations, the rates of its reactions the differential equation of a species. Every element has an `id`, which the metadata points at.

    The variables are `dimensionless`: the parameters of the SBML model have no units, and the units are only converted when the annotation is complete, see [Units](conversion.md#units).

    ```{ .xml .listing title="repressilator.cellml" }
    --8<-- "docs/roundtrip/repressilator.cellml"
    ```

=== "2 RDF"

    The names (`dcterms:title`), notes (`dcterms:description`), SBO terms (the first `bqbiol:is`), annotations and the history of the SBML elements, with `repressilator.cellml#<id>` as subject. The RDF is the one of the SBML annotations, in the form of SBML level 3.

    ```{ .xml .listing title="repressilator.rdf" }
    --8<-- "docs/roundtrip/repressilator.rdf"
    ```

=== "3 SBML of the roundtrip"

    CellML has neither compartments nor species: every variable comes back as a parameter, the differential equations as rate rules, the equations as assignment rules, or as initial assignments when they compute a constant, see [CellML to SBML](conversion.md#mapping). The mathematics is the one of the first model, its biological structure is not. The metadata is back: a species is a parameter, but with its name, its notes, its SBO term and its annotations, and the model has its history.

    ```{ .xml .listing title="repressilator_roundtrip.xml" }
    --8<-- "docs/roundtrip/repressilator_roundtrip.xml"
    ```

## Simulate

Both simulators run in the process of the example, see [Simulation](simulation.md). The two SBML models are simulated with sbmlsim-core:

```python
from sbml2cellml.sbmlsim import run_timecourse

df = run_timecourse(sbml_path, ["PX", "PY", "PZ"], start=0.0, end=600.0, steps=600)
```

and the CellML model with libopencor:

```python
from sbml2cellml.simulate import run_timecourse

df, units = run_timecourse(cellml_path, start=0.0, end=600.0, steps=600)
```

The three simulations of the proteins over 600 minutes, side by side:

![Timecourses of the proteins LacI, TetR and cI: SBML with sbmlsim-core, CellML with libopencor, SBML of the roundtrip with sbmlsim-core](images/repressilator.svg#only-light)
![Timecourses of the proteins LacI, TetR and cI: SBML with sbmlsim-core, CellML with libopencor, SBML of the roundtrip with sbmlsim-core](images/repressilator_dark.svg#only-dark)

The simulations agree within the tolerances of the integrators (both CVODE with the default tolerances of the simulator). The largest difference to the first simulation over all time points, with protein numbers of up to 2400 molecules per cell:

--8<-- "docs/roundtrip/repressilator_differences.md"

The [SBML test suite](testsuite.md) and the [BioModels](biomodels.md) check run this pipeline for every model and compare the numbers with tolerances.

## Simulate in the browser

Both simulators also run in the browser, so the two models of the conversion can be compared here: the sliders set the parameters of both, libopencor simulates the CellML model and sbmlsim-core the SBML model it was converted from, both as WebAssembly. The models are the files of this page, nothing is uploaded and the simulations run in this tab.

<div class="simulation" data-simulation
  data-cellml="repressilator.cellml"
  data-model="simulation/repressilator.wasm"
  data-description="simulation/repressilator.json"
  data-engine="simulation/engine.wasm"
  data-mathlib="simulation/mathlib.wasm"
  data-versions="simulation/versions.json">
  <div class="simulation__actions">
    <button class="simulation__button" type="button" data-action="start">Load the simulators and simulate</button>
    <button class="simulation__button" type="button" data-action="reset" disabled>Reset the parameters</button>
  </div>
  <p class="simulation__status" data-role="status" data-kind="info" role="status">The two simulators are about 11 MB, they are loaded when you start the simulation.</p>
  <div class="simulation__plots" data-role="plots" hidden>
    <div class="simulation__sliders" data-role="sliders"></div>
    <div class="simulation__legend">
      <span><span class="simulation__swatch" style="background-color: #4e79a7"></span>LacI (PX)</span>
      <span><span class="simulation__swatch" style="background-color: #f28e2b"></span>TetR (PY)</span>
      <span><span class="simulation__swatch" style="background-color: #59a14f"></span>cI (PZ)</span>
    </div>
    <div class="simulation__charts">
      <figure class="simulation__chart">
        <figcaption>CellML with libopencor, <span data-role="cellml-timing">-</span></figcaption>
        <canvas data-chart="cellml" aria-label="Timecourses of the proteins of the CellML model, simulated with libopencor" role="img"></canvas>
      </figure>
      <figure class="simulation__chart">
        <figcaption>SBML with sbmlsim-core, <span data-role="sbml-timing">-</span></figcaption>
        <canvas data-chart="sbml" aria-label="Timecourses of the proteins of the SBML model, simulated with sbmlsim-core" role="img"></canvas>
      </figure>
    </div>
    <p class="simulation__difference">Proteins per cell over 600 minutes, the same axis for both plots. The largest difference between the two simulations over all time points and all three proteins: <strong data-role="difference">-</strong>.</p>
  </div>
</div>

## The complete example

??? example "examples/repressilator_example.py"

    ```{ .python .listing }
    --8<-- "examples/repressilator_example.py"
    ```
