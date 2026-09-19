# Roundtrip example

The example converts the repressilator from SBML to CellML and back to SBML and simulates all three models: the SBML model with [roadrunner](https://www.libroadrunner.org/), the CellML model with [libopencor](https://opencor.ws/libopencor/) and the SBML model of the roundtrip with roadrunner again.

| | model | simulator |
| --- | --- | --- |
| 1 | SBML `examples/models/repressilator.xml` | roadrunner |
| 2 | CellML, converted from 1 with `sbml2cellml`, with the metadata of 1 as RDF next to it | libopencor |
| 3 | SBML, converted from 2 with `cellml2sbml` | roadrunner |

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

roadrunner and libopencor cannot run in one python process, see [Simulation](simulation.md#setup). The example therefore simulates the SBML models with a script of its own, which writes the timecourse to a CSV file:

```{ .python .listing title="examples/roadrunner_timecourse.py" }
--8<-- "examples/roadrunner_timecourse.py"
```

The CellML model is simulated in the process of the example:

```python
from sbml2cellml.simulate import run_timecourse

df, units = run_timecourse(cellml_path, start=0.0, end=600.0, steps=600)
```

The three simulations of the proteins over 600 minutes, side by side:

![Timecourses of the proteins LacI, TetR and cI: SBML with roadrunner, CellML with libopencor, SBML of the roundtrip with roadrunner](images/repressilator.svg#only-light)
![Timecourses of the proteins LacI, TetR and cI: SBML with roadrunner, CellML with libopencor, SBML of the roundtrip with roadrunner](images/repressilator_dark.svg#only-dark)

The simulations agree within the tolerances of the integrators (both CVODE with the default tolerances of the simulator). The largest difference to the first simulation over all time points, with protein numbers of up to 2400 molecules per cell:

--8<-- "docs/roundtrip/repressilator_differences.md"

The [SBML test suite](testsuite.md) and the [BioModels](biomodels.md) check run this pipeline for every model and compare the numbers with tolerances.

## The complete example

??? example "examples/repressilator_example.py"

    ```{ .python .listing }
    --8<-- "examples/repressilator_example.py"
    ```
