"""Tests of the rust reader and converter in the process (`sbml2cellml.rust`)."""

from pathlib import Path

import libsbml
import pytest

from sbml2cellml import cellml, rust
from sbml2cellml.cellml import write_model
from sbml2cellml.cellml2sbml import CellML2SBMLConversionError, convert_cellml2sbml
from sbml2cellml.sbml import validate_document
from sbml2cellml.sbml2cellml import SBML2CellMLConversionError, convert_sbml2cellml
from tests.cellml_models import multi_component_model, reset_model
from tests.conftest import DATA_DIR, MODELS_DIR
from tests.sbml_models import (
    annotated_species,
    event_model,
    simple_model,
    write_sbml,
)

TEST_MODEL_PATH = MODELS_DIR / "test_model.cellml"


def test_convert_cellml_to_sbml_writes_a_document() -> None:
    sbml_text, warnings = rust.convert_cellml_to_sbml(
        TEST_MODEL_PATH.read_text(encoding="utf-8")
    )
    doc = libsbml.readSBMLFromString(sbml_text)
    assert doc.getLevel() == 3 and doc.getVersion() == 2
    assert doc.getModel().getId() == "test_model"
    assert validate_document(doc) == []
    assert warnings == []


def test_a_document_which_is_no_model_raises() -> None:
    with pytest.raises(rust.RustError):
        rust.convert_cellml_to_sbml("<not-a-model/>")


def test_cellml_version_of_every_version() -> None:
    assert rust.cellml_version(TEST_MODEL_PATH.read_text(encoding="utf-8")) == "2.0"
    text = (DATA_DIR / "decay_cellml_1_0.cellml").read_text(encoding="utf-8")
    assert rust.cellml_version(text) == "1.0"


def test_has_imports() -> None:
    parent = (DATA_DIR / "import_parent.cellml").read_text(encoding="utf-8")
    assert rust.has_imports(parent)
    assert not rust.has_imports(TEST_MODEL_PATH.read_text(encoding="utf-8"))


def test_the_engines_agree_on_the_example_model() -> None:
    """Both engines write the same parameters and rules for the example."""
    documents = {
        engine: convert_cellml2sbml(TEST_MODEL_PATH, engine=engine).getModel()
        for engine in ("rust", "python")
    }
    values = {
        engine: {
            p.getId(): (p.getConstant(), p.getValue() if p.isSetValue() else None)
            for p in model.getListOfParameters()
        }
        for engine, model in documents.items()
    }
    assert values["rust"] == values["python"]
    rules = {
        engine: {
            rule.getVariable(): (
                rule.getTypeCode(),
                libsbml.formulaToL3String(rule.getMath()),
            )
            for rule in model.getListOfRules()
        }
        for engine, model in documents.items()
    }
    assert rules["rust"] == rules["python"]


def test_resets_become_events_with_the_rust_engine(tmp_path: Path) -> None:
    """The events of the rust engine are the events of the python engine."""
    cellml_path = tmp_path / "reset.cellml"
    write_model(reset_model(), cellml_path)
    events = {}
    for engine in ("rust", "python"):
        model = convert_cellml2sbml(cellml_path, engine=engine).getModel()
        events[engine] = [
            (
                event.getId(),
                libsbml.formulaToL3String(event.getTrigger().getMath()),
                libsbml.formulaToL3String(event.getPriority().getMath()),
                [
                    (a.getVariable(), libsbml.formulaToL3String(a.getMath()))
                    for a in event.getListOfEventAssignments()
                ],
            )
            for event in model.getListOfEvents()
        ]
        # `count` is only ever written by a reset, so it is no constant
        assert not model.getParameter("count").getConstant()
    assert events["rust"] == events["python"]
    assert events["rust"][0][0] == "reset_1"


def test_the_rust_engine_flattens_imports_with_libcellml() -> None:
    """A document with imports is flattened before the rust converter reads it."""
    model = convert_cellml2sbml(DATA_DIR / "import_parent.cellml", engine="rust")
    ids = {p.getId() for p in model.getModel().getListOfParameters()}
    assert "k" in ids
    assert validate_document(model) == []


def test_the_rust_engine_refuses_the_hierarchical_conversion() -> None:
    with pytest.raises(CellML2SBMLConversionError, match="hierarchical"):
        convert_cellml2sbml(TEST_MODEL_PATH, engine="rust", hierarchical=True)


def test_an_operator_which_sbml_does_not_have_is_refused(tmp_path: Path) -> None:
    cellml_path = tmp_path / "partial.cellml"
    cellml_path.write_text(
        TEST_MODEL_PATH.read_text(encoding="utf-8").replace(
            "<minus/>", "<partialdiff/>", 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(rust.RustError, match="partialdiff"):
        rust.convert_cellml_to_sbml(cellml_path.read_text(encoding="utf-8"))
    with pytest.raises(CellML2SBMLConversionError, match="rust engine"):
        convert_cellml2sbml(cellml_path, engine="rust", validate=False)


def test_auto_converts_with_python_what_rust_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model the rust converter refuses is converted with python."""

    def refuse(text: str) -> tuple[str, list[str]]:
        raise rust.RustError("refused for the test")

    monkeypatch.setattr(rust, "convert_cellml_to_sbml", refuse)
    model = convert_cellml2sbml(TEST_MODEL_PATH).getModel()
    assert model.getId() == "test_model"


def test_the_engines_give_a_quantity_the_same_id(tmp_path: Path) -> None:
    """Both engines name a parameter after the same variable of its set.

    The Physiome check maps the names of the libopencor result, which are
    the variables the analyser of libcellml picks, to the SBML ids, so the
    rust converter has to pick the same variable of an equivalence set.
    """
    cellml_path = tmp_path / "multi.cellml"
    write_model(multi_component_model(), cellml_path)
    ids = {}
    for engine in ("rust", "python"):
        model = convert_cellml2sbml(cellml_path, engine=engine).getModel()
        ids[engine] = {
            parameter.getId(): parameter.getName()
            for parameter in model.getListOfParameters()
        }
    assert ids["rust"] == ids["python"]
    # `rate` of the component which uses it is `k` of the one which has its
    # value, as the analyser of libcellml names the set
    assert "k" in ids["rust"] and "rate" not in ids["rust"]


def test_convert_sbml_to_cellml_writes_a_model() -> None:
    sbml_path = MODELS_DIR / "repressilator.xml"
    cellml_text, warnings = rust.convert_sbml_to_cellml(
        sbml_path.read_text(encoding="utf-8"), "repressilator"
    )
    model = cellml.parse_model(cellml_text)
    assert model.name() == "BIOMD0000000012"
    assert cellml.errors(cellml.validate_model(model)) == []
    assert any("unit annotation is incomplete" in warning for warning in warnings)


def test_a_document_which_is_no_sbml_model_raises() -> None:
    with pytest.raises(rust.RustError):
        rust.convert_sbml_to_cellml("<not-a-model/>", "none")


def test_the_engines_write_the_same_model(tmp_path: Path) -> None:
    """Both engines give the variables of a model the same initial values."""
    sbml_path = write_sbml(tmp_path / "simple.xml", simple_model())
    values = {}
    for engine in ("rust", "python"):
        model = convert_sbml2cellml(sbml_path, engine=engine)
        component = model.component(0)
        values[engine] = {
            component.variable(k).name(): (
                component.variable(k).initialValue(),
                component.variable(k).units().name(),
            )
            for k in range(component.variableCount())
        }
    assert values["rust"] == values["python"]


def test_the_rust_engine_converts_the_events_of_a_model(tmp_path: Path) -> None:
    sbml_path = write_sbml(tmp_path / "events.xml", event_model())
    model = convert_sbml2cellml(sbml_path, engine="rust")
    component = model.component(0)
    assert component.resetCount() == 1
    assert component.reset(0).testVariable().name() == "e1_trigger"


def test_the_python_engine_writes_the_metadata_of_a_model(tmp_path: Path) -> None:
    """A model with metadata is converted by python, which writes the RDF."""
    model_sbml = simple_model("annotated")
    annotated_species(model_sbml)
    sbml_path = write_sbml(tmp_path / "annotated.xml", model_sbml)
    cellml_path = tmp_path / "annotated.cellml"
    model = convert_sbml2cellml(sbml_path, cellml_path)
    assert model.component(0).variable("S1").id() == "S1"
    assert cellml_path.with_suffix(".rdf").is_file()
    with pytest.raises(SBML2CellMLConversionError, match="metadata"):
        convert_sbml2cellml(sbml_path, cellml_path, engine="rust")


def test_the_rust_engine_converts_an_annotated_model_without_the_metadata(
    tmp_path: Path,
) -> None:
    model_sbml = simple_model("annotated")
    annotated_species(model_sbml)
    sbml_path = write_sbml(tmp_path / "annotated.xml", model_sbml)
    cellml_path = tmp_path / "annotated.cellml"
    model = convert_sbml2cellml(sbml_path, cellml_path, metadata=False, engine="rust")
    assert model.component(0).variable("S1").id() == ""
    assert not cellml_path.with_suffix(".rdf").is_file()


def test_a_delay_is_refused_by_the_rust_engine_and_converted_by_python(
    tmp_path: Path,
) -> None:
    """The rust converter refuses a delay, `auto` falls back to python."""
    model_sbml = simple_model("delayed")
    law: libsbml.KineticLaw = model_sbml.getReaction("r1").getKineticLaw()
    law.setMath(libsbml.parseL3Formula("k1 * delay(S1, 1)"))
    sbml_path = write_sbml(tmp_path / "delayed.xml", model_sbml)
    with pytest.raises(SBML2CellMLConversionError, match="rust engine"):
        convert_sbml2cellml(sbml_path, engine="rust", validate=False)
    model = convert_sbml2cellml(sbml_path, validate=False)
    assert model.component(0).variable("S1") is not None


def test_the_rust_engine_flattens_the_submodels_with_libsbml() -> None:
    """A hierarchical model is flattened before the rust converter reads it."""
    model = convert_sbml2cellml(
        MODELS_DIR / "glimepiride_body_flat.xml", metadata=False, engine="rust"
    )
    assert model.component(0).variableCount() > 0
