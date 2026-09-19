# S6: names, notes and annotations (issue #44)

Date: 2026-09-19
Status: decisions by the user (storage, reaction rate variables), remaining design approved for implementation without further feedback

## Context

The names, notes, annotations (CV terms), SBO terms and the model history of an SBML model are lost in the conversion. CellML 2.0 allows no element outside the CellML and MathML namespaces (specification 1.2.4; libcellml drops an embedded `rdf:RDF` with parser issues). Its elements only have an `id` attribute for external metadata to point at. The metadata therefore goes into a second file, and `cellml2sbml` reads it back, so a roundtrip keeps it.

## Decisions

| Question | Decision |
|----------|----------|
| Storage | RDF/XML sidecar `<stem>.rdf` next to `<stem>.cellml`, subject `<cellml file name>#<id>` (relative URI, valid when both files move together or go into a COMBINE archive). |
| Reactions | Every reaction with a kinetic law gets its rate variable `<reaction id> = kinetic law` (before: only reactions whose id a formula uses). The species equations are sums of the rate variables. The variable carries the metadata of the reaction. |
| RDF dialect | The one of SBML annotations, written and parsed by libsbml: `bqbiol:*`/`bqmodel:*` with `rdf:Bag` (nested terms included), history as `dcterms:creator` (vCard4), `dcterms:created`, `dcterms:modified`. No RDF library. The terms go through a scratch L3V2 object, so level 2 models give the same dialect. |
| Name | `dcterms:title`, literal. |
| Notes | `dcterms:description` with `rdf:parseType="Literal"`, the XHTML children of `notes` as they are. |
| SBO term | The first child after title and description: `bqbiol:is` (`bqmodel:is` for the model) with one resource `https://identifiers.org/SBO:0000252`. Reading: the first `is` element with exactly one SBO resource is the SBO term, everything else are CV terms. |
| Not converted | Annotations which are not RDF (COPASI, layout), and the metadata of rules, function definitions, events, initial assignments, constraints and unit kinds, which have no CellML element. Documented as conversion issue. |

## Section 1: ids and the rate variables (`sbml2cellml.py`)

- Every variable gets `id` = its name (unique in the single component). The model gets `id` = its name, every units element `id` = `units_<name>`; both made unique against the variable ids with `unique_sid`.
- `_Formulas.rates` of every reaction becomes a variable: `reaction_ids` is every reaction with a kinetic law, `_collect_reaction_terms` uses `astnodes.name(rid)` instead of the kinetic law. The units of the variables stay all or nothing: a model whose extent or time units are unset has no units of the rates and converts without units, as before for a referenced reaction.
- `convert_sbml2cellml(sbml_path, cellml_path=None, validate=True, metadata=True)`: with a `cellml_path` and `metadata`, `metadata.write_metadata` writes the sidecar; nothing is written when no element has metadata, and a stale sidecar of an earlier conversion is removed then.

## Section 2: `metadata.py`

- `Record(name: str, notes: str, sbo: str, annotation: str)`: notes as the XHTML children, annotation as the remaining children of the `rdf:Description` (CV terms, history), both serialized XML.
- `collect_metadata(model_sbml, element_ids) -> dict[str, Record]`: `element_ids` maps the CellML id to the SBML element (model, compartments, species, parameters, local parameters, species references with an id, reactions, unit definitions).
- `write_metadata(records, cellml_name, path)`, `read_metadata(path, cellml_name) -> dict[str, Record]` (subjects of another file are ignored), `apply_metadata(element, record, metaid)`: name (only when the element has none from the conversion), notes, SBO term, annotation through `setAnnotation` with `rdf:about="#<metaid>"`.
- The file is written with `xml.etree` (fixed prefixes, indented, deterministic), a name which equals the id is not written.

## Section 3: `cellml2sbml.py`

- `convert_cellml2sbml(cellml_path, sbml_path=None, validate=True, metadata=True)` reads `<stem>.rdf` next to the CellML file when it exists. A record is applied to the parameter of the equivalence set of the variable with that `id`, to the unit definition of the units with that `id` and to the model; the metaid is the CellML id. Records without a counterpart are logged at info level.
- CLI: `--no-metadata` for both commands.

## Section 4: tests, example, docs

- unit tests per property and direction, a model without metadata writes no file, stale sidecar removed, roundtrip of the annotated BIOMD0000000012 (name, notes, SBO term, CV terms of a species and a reaction, model history), validity of the CellML with ids.
- `examples/models/repressilator.xml` becomes the complete BioModels file, the documentation page shows the RDF as a tab and the restored annotations in the SBML of the roundtrip; `docs/roundtrip/repressilator.rdf` is kept current by the example test.
- `docs/index.md` mapping, `docs/conversion.md` (metadata section, CellML to SBML mapping), `docs/conversion-issues.md`, `CLAUDE.md`, API page `metadata`.
- SBML test suite and BioModels rerun: the generated CellML of every model with reactions changes, no regressions accepted.
